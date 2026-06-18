#!/usr/bin/env python3
"""Stage 2 — Relationship recovery: PK / FK from data + names + LLM.

v2 design (the v1 ablation drove these choices):
  PK : declared > exact-unique candidate keys (from profiler, full-table
       verified) ranked by name/type/position > name-based fallback for
       empty tables.  Composite (2-col) PKs supported.
  FK : three candidate sources merged, each value-checked where possible —
       1. statistical: name signal + inclusion dependency (v1 mechanism)
       2. name-based : `<parent>_id` columns, for empty tables (low conf)
       3. LLM-proposed: the model reads the schema and proposes referential
          links statistics cannot see (DBAutoDoc: "LLM brings recall");
          every LLM proposal is then VERIFIED by value inclusion when the
          child has data, otherwise kept at low confidence.
  Gates: G1 name-or-LLM signal, G2 inclusion >= 0.5 when measurable,
       G3 score threshold, G4 best-parent-per-column, G5 fan-out penalty
       (a child column referencing implausibly many parents loses confidence),
       G6 PK-eligible target only.

Writes out/relations.json.
"""
import json
import sys

from config import (connect, PGSCHEMA, out_path, load_json, dump_json,
                    qident, claude_json)

PK_THRESHOLD = 70
FK_SCORE_THRESHOLD = 60
INT_TYPES = ("integer", "bigint", "smallint")
INCLUSION_SAMPLE = 200
GENERIC_ID_NAMES = {"id"}  # too generic to match a parent by name alone


def is_int(dt):
    return any(t in (dt or "").lower() for t in INT_TYPES)


def has_data(tinfo):
    return tinfo["rowcount"] > 0


# ------------------------------------------------------------------ PK
def pk_name_score(table, name):
    name = name.lower()
    if name == f"{table.lower()}_id":
        return 1.0
    if name.endswith("_id") or name in GENERIC_ID_NAMES:
        return 0.6
    return 0.0


def detect_pks(profile):
    pks = {}
    unique_keys = {}
    table_names = {t.lower() for t in profile["tables"]}
    for table, tinfo in profile["tables"].items():
        cols = tinfo["columns"]
        if has_data(tinfo):
            tiny = tinfo["rowcount"] < 25   # uniqueness is weak evidence
            best = None
            for col in cols:
                s = col["stats"]
                # uniqueness signal, full-table verified where possible.
                # tolerate dirty duplicates (>= 0.9 distinct) — demo loads
                # often contain duplicated rows; far-below-1 ratios mean the
                # column genuinely repeats and CANNOT be a key.
                full_dr = s.get("full_distinct_ratio")
                dr = full_dr if full_dr is not None else s.get("distinct_ratio")
                n = pk_name_score(table, col["name"])
                if dr == 1.0:
                    f_u = 1.0
                elif dr is not None and dr >= 0.9 and n == 1.0:
                    # dirty duplicates tolerated only for `<table>_id`
                    f_u = dr
                else:
                    f_u = 0.0
                if tiny and n < 1.0:
                    continue   # tiny table: only `<table>_id` is credible
                d = 1.0 if is_int(col["data_type"]) else 0.3
                p = max(0.55, 1.0 - 0.15 * (col["position"] - 1))
                score = 50 * f_u + 20 * n + 15 * d + 15 * p
                if f_u == 0.0:
                    continue   # proven non-unique: not PK-eligible
                if best is None or score > best[1]:
                    best = (col["name"], score)
            if best and best[1] >= PK_THRESHOLD:
                pks[table] = {"columns": [best[0]], "score": round(best[1], 1),
                              "confidence": round(min(best[1] / 100, 0.99), 2),
                              "source": "stat"}
                continue
            comp = tinfo.get("keys", {}).get("composite_candidates", [])
            # composite uniques are candidate keys, not declared-style PKs
            # (junction/history tables); surface them separately
            if comp and tinfo["rowcount"] >= 100:
                unique_keys[table] = {"columns": comp[0], "source": "composite",
                                      "confidence": 0.7}
            # table HAS data: statistics had their say — never fall back to
            # name-only guessing (it re-introduces disproven candidates)
            continue
        # empty table: name-based fallback, low confidence
        names = {c["name"].lower(): c["name"] for c in cols}
        cand = names.get(f"{table.lower()}_id")
        if not cand:
            # domain-agnostic: a *_id column whose stem names ANOTHER table is
            # a reference (FK), not this table's own PK — exclude it.
            id_cols = []
            for c in cols:
                cl = c["name"].lower()
                if not (cl.endswith("_id") or cl in GENERIC_ID_NAMES):
                    continue
                stem = norm_col(cl)[:-3]  # strip trailing _id
                if stem in table_names and stem != table.lower():
                    continue              # <other_table>_id -> FK, not PK
                id_cols.append(c["name"])
            if len(id_cols) == 1:
                cand = id_cols[0]
        if cand:
            pks[table] = {"columns": [cand], "score": 0.0,
                          "confidence": 0.4, "source": "name"}
    return pks, unique_keys


def declared_pks(cur, profile):
    cur.execute(
        """SELECT cl.relname, a.attname
           FROM pg_constraint c
           JOIN pg_class cl ON cl.oid = c.conrelid
           JOIN pg_namespace n ON n.oid = c.connamespace
           JOIN unnest(c.conkey) k(attnum) ON true
           JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = k.attnum
           WHERE c.contype='p' AND n.nspname=%s""", (PGSCHEMA,))
    out = {}
    for tbl, col in cur.fetchall():
        out.setdefault(tbl, []).append(col)
    return out


# ------------------------------------------------------------------ FK
import re

SELF_REF_MARKERS = ("preceding_", "_preceding", "parent_", "_parent",
                    "ancestor_", "_ancestor", "prior_", "_prior")


def norm_col(child_col):
    """domain_concept_id_1 -> domain_concept_id (positional suffix)."""
    return re.sub(r"_\d+$", "", child_col.lower())


def name_similarity(child_col, parent_table, parent_pk):
    c = norm_col(child_col)
    pt = parent_table.lower()
    ppk = (parent_pk or "").lower()
    if c == f"{pt}_id":
        return 1.0
    if c == ppk and c not in GENERIC_ID_NAMES:
        return 0.9
    # self/role references: visit_detail_parent_id, preceding_visit_occurrence_id
    stripped = c
    for m in SELF_REF_MARKERS:
        stripped = stripped.replace(m, "_" if m.startswith("_") and m.endswith("_") else "")
    stripped = re.sub(r"__+", "_", stripped).strip("_")
    if ppk and stripped == ppk:
        return 0.85
    if ppk and ppk not in GENERIC_ID_NAMES and c.endswith(ppk):
        return 0.8   # preceding_visit_occurrence_id -> visit_occurrence_id
    if pt in c:
        return 0.6
    return 0.0


def inclusion_ratio(cur, child_table, child_col, parent_table, parent_col):
    """Fraction of sampled non-null child values present in the parent col."""
    try:
        cur.execute(
            f"SELECT DISTINCT {qident(child_col)} "
            f"FROM {qident(PGSCHEMA)}.{qident(child_table)} "
            f"WHERE {qident(child_col)} IS NOT NULL LIMIT {INCLUSION_SAMPLE}")
        vals = [r[0] for r in cur.fetchall()]
        if not vals:
            return None, 0
        cur.execute(
            f"SELECT DISTINCT {qident(parent_col)} "
            f"FROM {qident(PGSCHEMA)}.{qident(parent_table)} "
            f"WHERE {qident(parent_col)} = ANY(%s)", (vals,))
        present = {r[0] for r in cur.fetchall()}
        hit = sum(1 for v in vals if v in present)
        return hit / len(vals), len(vals)
    except Exception:
        return None, 0


def single_pk(pks, table):
    info = pks.get(table)
    if info and len(info["columns"]) == 1:
        return info["columns"][0]
    return None


def stat_fk_candidates(cur, profile, pks):
    """Source 1: name-signal candidates verified by value inclusion."""
    fks = []
    parents = {t: single_pk(pks, t) for t in pks}
    parents = {t: c for t, c in parents.items() if c}
    for ct, tinfo in profile["tables"].items():
        ct_pk = set(pks.get(ct, {}).get("columns", []))
        for col in tinfo["columns"]:
            cname = col["name"]
            if cname in ct_pk and len(ct_pk) == 1:
                continue
            if not (norm_col(cname).endswith("_id")
                    or cname.lower() in GENERIC_ID_NAMES):
                continue
            for pt, ppk in parents.items():
                if pt == ct and cname == ppk:
                    continue                        # own PK is not a self-FK
                sim = name_similarity(cname, pt, ppk)
                # self-FK needs a strong name signal (preceding_*, parent_*)
                if pt == ct and sim < 0.8:
                    continue
                # non-integer columns can be FKs (varchar keys) but only
                # with a strong name match
                if not is_int(col["data_type"]) and sim < 0.8:
                    continue
                if sim < 0.5:                       # G1
                    continue
                v, tested = inclusion_ratio(cur, ct, cname, pt, ppk)
                if v is None:
                    continue
                nu = 1.0 if col["nullable"] else 0.8
                score = 40 * v + 20 * sim + 15 + 15 + 10 * nu
                if v < 0.5 or score < FK_SCORE_THRESHOLD:   # G2, G3
                    continue
                fks.append({"child_table": ct, "child_column": cname,
                            "parent_table": pt, "parent_column": ppk,
                            "inclusion": round(v, 3), "name_sim": sim,
                            "score": round(score, 1), "tested": tested,
                            "confidence": round(min(score / 100, 0.99), 2),
                            "source": "stat"})
    return fks


def name_fk_candidates(profile, pks):
    """Source 2: `<parent>_id` naming only — recovers FKs from empty tables."""
    parents = {t: single_pk(pks, t) for t in pks}
    parents = {t: c for t, c in parents.items() if c}
    out = []
    for ct, tinfo in profile["tables"].items():
        ct_pk = set(pks.get(ct, {}).get("columns", []))
        for col in tinfo["columns"]:
            cname = col["name"]
            if cname in ct_pk and len(ct_pk) == 1:
                continue
            if not norm_col(cname).endswith("_id"):
                continue
            best = None
            for pt, ppk in parents.items():
                if pt == ct and cname == ppk:
                    continue
                sim = name_similarity(cname, pt, ppk)
                if not is_int(col["data_type"]) and sim < 0.8:
                    continue
                if sim >= 0.8 and (best is None or sim > best[1]):
                    best = (pt, sim, ppk)
            if best:
                out.append({"child_table": ct, "child_column": cname,
                            "parent_table": best[0], "parent_column": best[2],
                            "inclusion": None, "name_sim": best[1],
                            "score": round(20 * best[1], 1), "tested": 0,
                            "confidence": 0.4, "source": "name"})
    return out


LLM_FK_SCHEMA = {
    "type": "object",
    "properties": {
        "foreign_keys": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "child_table": {"type": "string"},
                    "child_column": {"type": "string"},
                    "parent_table": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["child_table", "child_column", "parent_table"],
            },
        }
    },
    "required": ["foreign_keys"],
}

LLM_FK_SYSTEM = (
    "You are a database expert recovering foreign keys in an undocumented "
    "schema. You see every table with its columns and which columns are "
    "already covered by detected FKs. Propose ONLY missing referential links "
    "you are reasonably sure about from the names and schema structure "
    "(e.g. a column whose name encodes a parent table or a well-known "
    "domain convention). Use ONLY table/column names that appear in the "
    "input. Do not propose a table's own primary key as an FK to itself."
)


def llm_fk_candidates(profile, pks, covered):
    """Source 3: ask the LLM for referential links statistics cannot see.

    DBAutoDoc ablation: statistics-only recovers ~30% of FKs, LLM semantic
    proposals lift recall — every proposal is value-verified afterwards.
    """
    schema_view = {}
    for t, tinfo in profile["tables"].items():
        schema_view[t] = {
            "pk": pks.get(t, {}).get("columns"),
            "rowcount": tinfo["rowcount"],
            "columns": [c["name"] for c in tinfo["columns"]],
            "fk_covered_columns": sorted(
                c for (ct, c) in covered if ct == t),
        }
    obj, _ = claude_json(
        "Here is the full schema with already-detected FK coverage. Propose "
        "missing foreign keys.\n\n"
        + json.dumps(schema_view, ensure_ascii=False),
        LLM_FK_SCHEMA, system=LLM_FK_SYSTEM, max_tokens=8192)
    out = []
    tables = profile["tables"]
    for fk in obj.get("foreign_keys", []):
        ct, cc = fk.get("child_table"), fk.get("child_column")
        pt = fk.get("parent_table")
        if ct not in tables or pt not in tables or ct == pt:
            continue
        if cc not in {c["name"] for c in tables[ct]["columns"]}:
            continue
        ppk = single_pk(pks, pt)
        if not ppk:                                   # G6: PK-eligible target
            continue
        if (ct, cc) in covered:
            continue
        out.append({"child_table": ct, "child_column": cc,
                    "parent_table": pt, "parent_column": ppk,
                    "inclusion": None, "name_sim": None, "score": None,
                    "tested": 0, "confidence": 0.5, "source": "llm",
                    "reason": fk.get("reason")})
    return out


def verify_llm_candidates(cur, profile, cands):
    """Value-check LLM proposals where the child table has data."""
    kept = []
    for fk in cands:
        ct = fk["child_table"]
        if profile["tables"][ct]["rowcount"] > 0:
            v, tested = inclusion_ratio(cur, ct, fk["child_column"],
                                        fk["parent_table"], fk["parent_column"])
            if v is not None:
                if v < 0.5:        # measurable and failed -> reject
                    continue
                fk.update(inclusion=round(v, 3), tested=tested,
                          confidence=round(0.5 + 0.4 * v, 2),
                          source="llm+stat")
        kept.append(fk)
    return kept


def merge_best_parent(fks):
    """G4: one parent per (child_table, child_column); prefer source trust
    then score/inclusion."""
    trust = {"declared": 3, "stat": 2, "llm+stat": 2, "llm": 1, "name": 0}
    best = {}
    for fk in fks:
        key = (fk["child_table"], fk["child_column"])
        cur = best.get(key)
        if cur is None:
            best[key] = fk
            continue
        a = (trust.get(fk["source"], 0), fk.get("confidence") or 0)
        b = (trust.get(cur["source"], 0), cur.get("confidence") or 0)
        if a > b:
            best[key] = fk
    return list(best.values())


def fanout_penalty(fks):
    """G5: if one parent PK is referenced by very many child columns of the
    same name stem, that's normal (hub tables); but if a single CHILD column
    matched many parents pre-merge it was ambiguous — handled by G4. Here we
    de-rate sub-0.6-name-sim stat FKs to hub parents with huge fan-in."""
    fanin = {}
    for fk in fks:
        fanin[fk["parent_table"]] = fanin.get(fk["parent_table"], 0) + 1
    for fk in fks:
        if (fk["source"] == "stat" and (fk.get("name_sim") or 0) < 0.6
                and fanin[fk["parent_table"]] > 10):
            fk["confidence"] = round(fk["confidence"] * 0.8, 2)
            fk["fanout_derated"] = True
    return fks


def declared_fks(cur):
    cur.execute(
        """SELECT cl.relname, a.attname, fcl.relname, fa.attname
           FROM pg_constraint c
           JOIN pg_class cl ON cl.oid = c.conrelid
           JOIN pg_class fcl ON fcl.oid = c.confrelid
           JOIN pg_namespace n ON n.oid = c.connamespace
           JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ord) ON true
           JOIN unnest(c.confkey) WITH ORDINALITY fk(attnum, ord)
                ON fk.ord = k.ord
           JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = k.attnum
           JOIN pg_attribute fa ON fa.attrelid = fcl.oid
                AND fa.attnum = fk.attnum
           WHERE c.contype='f' AND n.nspname=%s""", (PGSCHEMA,))
    return [{"child_table": r[0], "child_column": r[1],
             "parent_table": r[2], "parent_column": r[3],
             "inclusion": None, "name_sim": None, "score": 100.0,
             "tested": 0, "confidence": 1.0, "source": "declared"}
            for r in cur.fetchall()]


def main():
    use_llm = "--no-llm" not in sys.argv
    profile = load_json(out_path("profile.json"))
    conn = connect()
    conn.autocommit = True

    with conn.cursor() as cur:
        # PKs: declared wins, then statistical/composite/name
        pks, unique_keys = detect_pks(profile)
        for t, cols in declared_pks(cur, profile).items():
            pks[t] = {"columns": cols, "score": 100.0, "confidence": 1.0,
                      "source": "declared"}
        print(f">> PKs: {len(pks)} "
              f"({sum(1 for p in pks.values() if p['source']=='stat')} stat, "
              f"{sum(1 for p in pks.values() if p['source']=='name')} name, "
              f"{sum(1 for p in pks.values() if p['source']=='declared')} declared)")

        # FKs: declared + statistical + name-based + LLM-proposed
        fks = declared_fks(cur)
        fks += stat_fk_candidates(cur, profile, pks)
        covered = {(f["child_table"], f["child_column"]) for f in fks}
        for nf in name_fk_candidates(profile, pks):
            if (nf["child_table"], nf["child_column"]) not in covered:
                fks.append(nf)
                covered.add((nf["child_table"], nf["child_column"]))
        n_before_llm = len(fks)
        if use_llm:
            cands = llm_fk_candidates(profile, pks, covered)
            cands = verify_llm_candidates(cur, profile, cands)
            fks += cands
            print(f">> LLM proposed {len(cands)} additional FK candidates "
                  f"(value-verified where measurable)")
        fks = merge_best_parent(fks)
        fks = fanout_penalty(fks)

    conn.close()
    out = {"primary_keys": pks, "unique_keys": unique_keys,
           "foreign_keys": fks}
    dump_json(out, out_path("relations.json"))
    by_src = {}
    for f in fks:
        by_src[f["source"]] = by_src.get(f["source"], 0) + 1
    print(f">> FKs: {len(fks)} by source {by_src} -> out/relations.json")


if __name__ == "__main__":
    main()
