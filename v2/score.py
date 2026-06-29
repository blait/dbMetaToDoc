#!/usr/bin/env python3
"""Stage 5 — Similarity scoring against the OMOP official data dictionary.

Main metric: description semantic match per column/table —
  (a) embedding cosine similarity (Titan v2)
  (b) LLM judge: semantically equivalent? (0/1, with reason)

Supporting: PK/FK recovery F1, coverage, DBAutoDoc S_overall.
Everything is computed per-item and saved to out/score_details.json so the
viewer can show generated vs ground-truth side by side.

Usage: score.py [--no-judge] [--workers N] [--limit N]
"""
import csv
import json
import math
import os
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor

from config import (out_path, load_json, dump_json, embed, claude_json,
                    OMOP_VERSION, V2_DIR, REPO_DIR, MODEL_ID, EMBED_MODEL_ID)

TRUTH = os.path.join(REPO_DIR, "truth")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "equivalent": {"type": "boolean",
                       "description": "true if the generated description "
                                      "conveys the same core meaning."},
        "reason": {"type": "string"},
    },
    "required": ["equivalent", "reason"],
}

JUDGE_CONTEXT = (
    "You are judging a generated column/table description against an OMOP CDM "
    "reference. Texts may be in Korean and/or English — judge MEANING, not "
    "language or wording. The OMOP reference is often ETL guidance or usage "
    "notes rather than a clean definition, and may be longer or phrased "
    "differently. Mark `equivalent: true` if the generated description "
    "correctly captures what the field/table IS (its real-world meaning), "
    "even if more concise or with extra correct detail. Mark false only if "
    "wrong or contradictory.\n\n"
)


def is_blank(text):
    if not text:
        return True
    return text.strip().lower() in ("", "na", "n/a", "none")


# ---------------------------------------------------------------- truth
def _truth_path(name):
    """Prefer the Korean-localized truth CSV (translate.py truth) if present."""
    ko = os.path.join(TRUTH, name.replace(".csv", "_ko.csv"))
    if os.path.exists(ko):
        return ko, "utf-8"
    return os.path.join(TRUTH, name), "latin-1"


def load_field_truth():
    path, enc = _truth_path(f"OMOP_CDMv{OMOP_VERSION}_Field_Level.csv")
    rows = {}
    with open(path, newline="", encoding=enc) as f:
        for r in csv.DictReader(f):
            t = r["cdmTableName"].strip().lower()
            c = r["cdmFieldName"].strip().lower()
            rows[(t, c)] = r
    return rows


def load_table_truth():
    path, enc = _truth_path(f"OMOP_CDMv{OMOP_VERSION}_Table_Level.csv")
    out = {}
    with open(path, newline="", encoding=enc) as f:
        for r in csv.DictReader(f):
            desc = (r.get("tableDescription") or r.get("userGuidance")
                    or r.get("description") or "")
            out[r["cdmTableName"].strip().lower()] = desc
    return out


# ---------------------------------------------------------------- similarity
def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def sim_pair(gen, ref, use_judge):
    if not gen or is_blank(ref):
        return None
    cos = cosine(embed(gen), embed(ref))
    judge = reason = None
    if use_judge:
        obj, _ = claude_json(
            JUDGE_CONTEXT + f"Reference (OMOP):\n{ref}\n\nGenerated:\n{gen}\n\n"
            "Does the generated description correctly capture the meaning?",
            JUDGE_SCHEMA, max_tokens=300)
        judge = 1 if obj["equivalent"] else 0
        reason = obj.get("reason")
    return {"cosine": round(cos, 4), "judge": judge, "judge_reason": reason}


# ---------------------------------------------------------------- relations
def score_relations(relations, field_truth):
    truth_pk = {(t, c) for (t, c), r in field_truth.items()
                if r.get("isPrimaryKey", "").strip().lower() == "yes"}
    pred_pk = set()
    for t, info in relations.get("primary_keys", {}).items():
        for c in info["columns"]:
            pred_pk.add((t.lower(), c.lower()))
    pk = prf(pred_pk, truth_pk)

    truth_fk = set()
    for (t, c), r in field_truth.items():
        if r.get("isForeignKey", "").strip().lower() == "yes":
            truth_fk.add((t, c, r.get("fkTableName", "").strip().lower()))
    pred_fk = {(f["child_table"].lower(), f["child_column"].lower(),
                f["parent_table"].lower())
               for f in relations.get("foreign_keys", [])}
    fk = prf(pred_fk, truth_fk)
    fk["fn_items"] = sorted(".".join(x[:2]) + "->" + x[2]
                            for x in (truth_fk - pred_fk))[:200]
    fk["fp_items"] = sorted(".".join(x[:2]) + "->" + x[2]
                            for x in (pred_fk - truth_fk))[:200]
    return pk, fk


def prf(pred, truth):
    tp, fp, fn = len(pred & truth), len(pred - truth), len(truth - pred)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3),
            "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}


# ---------------------------------------------------------------- main
def score_run(desc, relations, use_judge=True, workers=8, limit=0):
    """Score description dicts against OMOP truth; returns (report, details).

    In-memory variant of main() — no file IO, for the DB-only pipeline."""
    field_truth = load_field_truth()
    table_truth = load_table_truth()

    tables = list(desc["tables"].items())
    if limit:
        tables = tables[:limit]

    jobs = []
    for table, tdesc in tables:
        tl = table.lower()
        ref_t = table_truth.get(tl)
        if not is_blank(ref_t):
            jobs.append(("table", table, None,
                         tdesc["table_description"], ref_t, None))
        conf_by_col = {c["name"]: c.get("confidence")
                       for c in tdesc["columns"]}
        for c in tdesc["columns"]:
            ref = field_truth.get((tl, c["name"].lower()))
            if not ref:
                continue
            ug = ref.get("userGuidance", "")
            if is_blank(ug):
                continue
            jobs.append(("column", table, c["name"], c["description"], ug,
                         conf_by_col.get(c["name"])))

    def run_job(job):
        level, table, col, gen, ref, conf = job
        s = sim_pair(gen, ref, use_judge)
        if s is None:
            return None
        return {"level": level, "table": table, "column": col,
                "generated": gen, "reference": ref, "confidence": conf,
                **s}

    details = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(run_job, jobs), 1):
            if res:
                details.append(res)
            if i % 25 == 0:
                print(f"   scored {i}/{len(jobs)}")
    print(f"   scored {len(jobs)}/{len(jobs)}")

    col_scores = [d for d in details if d["level"] == "column"]
    tbl_scores = [d for d in details if d["level"] == "table"]

    def agg(scores, key):
        vals = [s[key] for s in scores if s.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    pk, fk = score_relations(relations, field_truth)

    n_truth_cols = sum(1 for r in field_truth.values()
                       if not is_blank(r.get("userGuidance", "")))
    n_truth_tbls = sum(1 for v in table_truth.values() if not is_blank(v))
    c_col = round(len(col_scores) / n_truth_cols, 3) if n_truth_cols else 0
    c_table = round(len(tbl_scores) / n_truth_tbls, 3) if n_truth_tbls else 0
    s_overall = round(0.35 * fk["f1"] + 0.30 * pk["f1"]
                      + 0.20 * c_table + 0.15 * c_col, 4)

    # confidence calibration check: judge accuracy among high vs low confidence
    hi = [d for d in col_scores if (d.get("confidence") or 0) >= 0.7]
    lo = [d for d in col_scores if (d.get("confidence") or 0) < 0.7]

    report = {
        "version": "v2",
        # provenance: what produced each number
        "scoring_methods": {
            "judge_accuracy": {
                "method": "LLM-as-judge (reference-guided equivalence, "
                          "true/false per item)",
                "model": MODEL_ID if use_judge else None,
                "is_llm": True,
            },
            "mean_cosine": {
                "method": "embedding cosine similarity (generated vs truth)",
                "model": EMBED_MODEL_ID,
                "is_llm": False,
            },
            "pk_fk_f1": {
                "method": "deterministic set comparison against the official "
                          "OMOP data dictionary (exact match)",
                "model": None,
                "is_llm": False,
            },
            "Soverall": {
                "method": "DBAutoDoc formula: 0.35*F1_FK + 0.30*F1_PK "
                          "+ 0.20*C_table + 0.15*C_col",
                "model": None,
                "is_llm": False,
            },
        },
        "description_match": {
            "column": {"n": len(col_scores),
                       "mean_cosine": agg(col_scores, "cosine"),
                       "judge_accuracy": agg(col_scores, "judge")},
            "table": {"n": len(tbl_scores),
                      "mean_cosine": agg(tbl_scores, "cosine"),
                      "judge_accuracy": agg(tbl_scores, "judge")},
        },
        "calibration": {
            "high_conf_n": len(hi), "high_conf_judge": agg(hi, "judge"),
            "low_conf_n": len(lo), "low_conf_judge": agg(lo, "judge"),
        },
        "relations": {"primary_key_f1": pk,
                      "foreign_key_f1": {k: v for k, v in fk.items()
                                         if not k.endswith("_items")}},
        "coverage": {"column": c_col, "table": c_table},
        "Soverall": s_overall,
        "usage_doc": desc.get("usage"),
    }
    detail_doc = {"items": details,
                  "fk_errors": {"missed": fk.get("fn_items", []),
                                "extra": fk.get("fp_items", [])}}
    return report, detail_doc


def headline_from_report(report):
    """Compact headline metrics for the run row (matches the old webapp shape)."""
    dm = report.get("description_match", {})
    rel = report.get("relations", {})
    return {
        "col_judge": dm.get("column", {}).get("judge_accuracy"),
        "tbl_judge": dm.get("table", {}).get("judge_accuracy"),
        "pk_f1": rel.get("primary_key_f1", {}).get("f1"),
        "fk_f1": rel.get("foreign_key_f1", {}).get("f1"),
        "s_overall": report.get("Soverall"),
        "judge_model": (report.get("scoring_methods", {})
                        .get("judge_accuracy", {}).get("model")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    desc = load_json(out_path("descriptions.json"))
    relations = load_json(out_path("relations.json"))
    report, detail_doc = score_run(desc, relations, use_judge=not args.no_judge,
                                   workers=args.workers, limit=args.limit)
    dump_json(report, out_path("score.json"))
    dump_json(detail_doc, out_path("score_details.json"))
    print("\n==================  SCORE (v2)  ==================")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
