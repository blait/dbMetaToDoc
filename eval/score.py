#!/usr/bin/env python3
"""Quantitative scoring against the OMOP official data dictionary (ground truth).

MAIN metric — description semantic match:
  Compare each generated column/table description to the truth `userGuidance`
  using (a) embedding cosine similarity and (b) an LLM judge (semantically
  equivalent? 0/1).  Report coverage and mean scores.

SUPPORTING metric — relationship recovery:
  PK F1 and FK F1 vs the truth (isPrimaryKey / isForeignKey + fkTableName).

Also reports DBAutoDoc's Soverall = .35*F1_FK + .30*F1_PK + .20*C_table + .15*C_col.

Inputs:
  out/descriptions.json, out/relations.json
  truth/OMOP_CDMv<ver>_Field_Level.csv   (cdmTableName,cdmFieldName,userGuidance,
                                           isPrimaryKey,isForeignKey,fkTableName,fkFieldName)
  truth/OMOP_CDMv<ver>_Table_Level.csv    (cdmTableName, tableDescription)
"""
import os
import sys
import csv
import math
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import (out_path, load_json, dump_json, embed, claude_json,  # noqa: E402
                    OMOP_VERSION)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUTH = os.path.join(REPO, "truth")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "equivalent": {"type": "boolean",
                       "description": "true if the generated description conveys the "
                                      "same core meaning as the reference."},
        "reason": {"type": "string"},
    },
    "required": ["equivalent", "reason"],
}

JUDGE_CONTEXT = (
    "You are judging a generated column/table description against an OMOP CDM "
    "reference. NOTE: the OMOP reference text is often ETL guidance or usage notes "
    "(e.g. 'Compute age using year_of_birth') rather than a clean definition, and may "
    "be phrased differently or be longer. Mark `equivalent: true` if the generated "
    "description correctly captures what the field/table IS (its real-world meaning), "
    "even if it is more concise or adds correct detail. Mark false only if it is wrong "
    "or contradicts the reference.\n\n"
)


def is_blank_truth(text):
    """OMOP leaves many fields as 'NA' or empty — not scorable references."""
    if not text:
        return True
    t = text.strip().lower()
    return t in ("", "na", "n/a", "none")


# ---------------------------------------------------------------- truth load
def load_field_truth():
    path = os.path.join(TRUTH, f"OMOP_CDMv{OMOP_VERSION}_Field_Level.csv")
    rows = {}
    with open(path, newline="", encoding="latin-1") as f:
        for r in csv.DictReader(f):
            t = r["cdmTableName"].strip().lower()
            c = r["cdmFieldName"].strip().lower()
            rows[(t, c)] = r
    return rows


def load_table_truth():
    path = os.path.join(TRUTH, f"OMOP_CDMv{OMOP_VERSION}_Table_Level.csv")
    out = {}
    with open(path, newline="", encoding="latin-1") as f:
        for r in csv.DictReader(f):
            # column name for the description varies; try common keys
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
    if not gen or is_blank_truth(ref):
        return None  # nothing to score against
    cos = cosine(embed(gen), embed(ref))
    judge = None
    if use_judge:
        obj, _ = claude_json(
            JUDGE_CONTEXT
            + f"Reference (OMOP):\n{ref}\n\nGenerated:\n{gen}\n\n"
              "Does the generated description correctly capture the meaning?",
            JUDGE_SCHEMA, max_tokens=300)
        judge = 1 if obj["equivalent"] else 0
    return {"cosine": round(cos, 4), "judge": judge}


# ---------------------------------------------------------------- relation F1
def score_relations(relations, field_truth):
    # truth PKs
    truth_pk = {(t, c) for (t, c), r in field_truth.items()
                if r.get("isPrimaryKey", "").strip().lower() == "yes"}
    pred_pk = {(t.lower(), info["column"].lower())
               for t, info in relations.get("primary_keys", {}).items()}
    pk = prf(pred_pk, truth_pk)

    # truth FKs: (child_table, child_col) -> parent_table
    truth_fk = set()
    for (t, c), r in field_truth.items():
        if r.get("isForeignKey", "").strip().lower() == "yes":
            truth_fk.add((t, c, r.get("fkTableName", "").strip().lower()))
    pred_fk = {(f["child_table"].lower(), f["child_column"].lower(),
                f["parent_table"].lower())
               for f in relations.get("foreign_keys", [])}
    fk = prf(pred_fk, truth_fk)
    return pk, fk


def prf(pred, truth):
    tp = len(pred & truth)
    fp = len(pred - truth)
    fn = len(truth - pred)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3),
            "tp": tp, "fp": fp, "fn": fn}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true",
                    help="skip LLM judge (cosine only, cheaper)")
    ap.add_argument("--limit", type=int, default=0,
                    help="score only first N tables (debug)")
    args = ap.parse_args()
    use_judge = not args.no_judge

    desc = load_json(out_path("descriptions.json"))
    relations = load_json(out_path("relations.json"))
    field_truth = load_field_truth()
    table_truth = load_table_truth()

    col_scores, tbl_scores = [], []
    tables = list(desc["tables"].items())
    if args.limit:
        tables = tables[:args.limit]

    for table, tdesc in tables:
        tl = table.lower()
        # table-level
        ref_t = table_truth.get(tl)
        st = sim_pair(tdesc["table_description"], ref_t, use_judge)
        if st:
            tbl_scores.append(st)
        # column-level
        for c in tdesc["columns"]:
            ref = field_truth.get((tl, c["name"].lower()))
            if not ref:
                continue
            s = sim_pair(c["description"], ref.get("userGuidance", ""), use_judge)
            if s:
                col_scores.append(s)
        print(f"   scored {table:<26} cols={len(tdesc['columns'])}")

    def agg(scores, key):
        vals = [s[key] for s in scores if s.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    pk, fk = score_relations(relations, field_truth)

    # coverage = fraction of *scorable* truth columns/tables we described
    # (scorable = truth has a non-blank userGuidance/description)
    n_truth_cols = sum(1 for r in field_truth.values()
                       if not is_blank_truth(r.get("userGuidance", "")))
    n_truth_tbls = sum(1 for v in table_truth.values() if not is_blank_truth(v))
    c_col = round(len(col_scores) / n_truth_cols, 3) if n_truth_cols else 0
    c_table = round(len(tbl_scores) / n_truth_tbls, 3) if n_truth_tbls else 0
    s_overall = round(0.35 * fk["f1"] + 0.30 * pk["f1"]
                      + 0.20 * c_table + 0.15 * c_col, 4)

    report = {
        "description_match": {
            "column": {"n": len(col_scores),
                       "mean_cosine": agg(col_scores, "cosine"),
                       "judge_accuracy": agg(col_scores, "judge")},
            "table": {"n": len(tbl_scores),
                      "mean_cosine": agg(tbl_scores, "cosine"),
                      "judge_accuracy": agg(tbl_scores, "judge")},
        },
        "relations": {"primary_key_f1": pk, "foreign_key_f1": fk},
        "coverage": {"column": c_col, "table": c_table},
        "Soverall": s_overall,
        "usage_doc": desc.get("usage"),
    }
    dump_json(report, out_path("score.json"))
    print("\n==================  SCORE  ==================")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
