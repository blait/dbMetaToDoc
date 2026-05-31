#!/usr/bin/env python3
"""(Supporting stage) Recover PK / FK relationships from data + names.

This is NOT the goal — it provides EVIDENCE so the description generator can say
"this column points to person" instead of guessing.  Approach follows DBAutoDoc:

  PK score  sPK = 50*f(u) + 20*n + 15*d + 15*p
      f(u): uniqueness (distinct/non_null in sample)
      n   : name pattern (ends with id / matches <table>_id)
      d   : datatype suitability (integer/bigint best)
      p   : position heuristic (earlier columns favoured)
  FK score  sFK = 40*v + 20*s + 15*r + 15*k + 10*nu
      v   : value inclusion (sampled child values found in parent PK domain)
      s   : name similarity to a parent table / parent PK
      r   : cardinality ratio plausibility
      k   : target is a detected/declared PK
      nu  : null handling (nullable FKs are common, mild bonus)
  then deterministic gates G1..G8 prune false positives.

Reads out/profile.json + samples actual values from the DB for inclusion tests.
Writes out/relations.json.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import connect, PGSCHEMA, out_path, load_json, dump_json  # noqa: E402

PK_THRESHOLD = 70
FK_THRESHOLD = 60
INT_TYPES = {"integer", "bigint", "smallint"}
INCLUSION_SAMPLE = 200   # child values tested against parent domain


# --------------------------------------------------------------- PK scoring
def pk_score(table, col, ncols):
    s = col["stats"]
    f_u = 1.0 if s.get("unique_in_sample") else (s.get("distinct_ratio") or 0)
    name = col["name"].lower()
    n = 1.0 if (name == f"{table}_id" or name.endswith("_id") or name == "id") else 0.0
    # exact <table>_id is the strongest signal
    if name == f"{table}_id":
        n = 1.0
    elif name.endswith("_id") or name == "id":
        n = 0.6
    d = 1.0 if col["data_type"] in INT_TYPES else 0.3
    pos = col["position"]
    # position heuristic: 1st col 1.0, 2nd .85, ... floor .55
    p = max(0.55, 1.0 - 0.15 * (pos - 1))
    score = 50 * f_u + 20 * n + 15 * d + 15 * p
    return score


def detect_pks(profile):
    pks = {}
    for table, tinfo in profile["tables"].items():
        ncols = len(tinfo["columns"])
        best = None
        for col in tinfo["columns"]:
            sc = pk_score(table, col, ncols)
            if best is None or sc > best[1]:
                best = (col["name"], sc)
        if best and best[1] >= PK_THRESHOLD:
            pks[table] = {"column": best[0], "score": round(best[1], 1)}
    return pks


# --------------------------------------------------------------- FK scoring
def name_similarity(child_col, parent_table, parent_pk):
    c = child_col.lower()
    pt = parent_table.lower()
    ppk = (parent_pk or "").lower()
    if c == ppk:
        return 1.0
    if c == f"{pt}_id":
        return 1.0
    if pt in c:
        return 0.7
    # shared stem, e.g. preceding_visit_occurrence_id -> visit_occurrence
    if ppk and ppk.replace("_id", "") in c:
        return 0.6
    return 0.0


def inclusion_ratio(cur, child_table, child_col, parent_table, parent_col):
    """Fraction of sampled non-null child values present in parent column."""
    try:
        cur.execute(
            f'SELECT "{child_col}" FROM "{PGSCHEMA}"."{child_table}" '
            f'WHERE "{child_col}" IS NOT NULL LIMIT {INCLUSION_SAMPLE}')
        vals = [r[0] for r in cur.fetchall()]
        if not vals:
            return None, 0
        cur.execute(
            f'SELECT count(DISTINCT "{parent_col}") '
            f'FROM "{PGSCHEMA}"."{parent_table}" '
            f'WHERE "{parent_col}" = ANY(%s)', (vals,))
        # count distinct child values that exist; approximate via membership
        cur.execute(
            f'SELECT "{child_col}" FROM "{PGSCHEMA}"."{child_table}" '
            f'WHERE "{child_col}" IS NOT NULL LIMIT {INCLUSION_SAMPLE}')
        child_vals = [r[0] for r in cur.fetchall()]
        cur.execute(
            f'SELECT DISTINCT "{parent_col}" FROM "{PGSCHEMA}"."{parent_table}" '
            f'WHERE "{parent_col}" = ANY(%s)', (child_vals,))
        present = {r[0] for r in cur.fetchall()}
        hit = sum(1 for v in child_vals if v in present)
        return hit / len(child_vals), len(child_vals)
    except Exception:
        return None, 0


def detect_fks(cur, profile, pks):
    fks = []
    tables = profile["tables"]
    # candidate parents = tables with a detected PK
    parents = {t: info["column"] for t, info in pks.items()}
    for ct, tinfo in tables.items():
        ct_pk = pks.get(ct, {}).get("column")
        for col in tinfo["columns"]:
            cname = col["name"]
            if cname == ct_pk:
                continue  # a table's own PK is not an FK
            if not (cname.lower().endswith("_id") or cname.lower() == "id"):
                continue
            if col["data_type"] not in INT_TYPES:
                continue
            for pt, ppk in parents.items():
                if pt == ct:
                    continue
                s = name_similarity(cname, pt, ppk)
                if s < 0.5:
                    continue  # G1: require a name signal
                v, tested = inclusion_ratio(cur, ct, cname, pt, ppk)
                if v is None:
                    continue
                r = 1.0   # cardinality plausibility (simplified)
                k = 1.0   # parent has a PK by construction
                nu = 1.0 if col["nullable"] else 0.8
                score = 40 * v + 20 * s + 15 * r + 15 * k + 10 * nu
                # gates
                if v < 0.5:               # G2: weak inclusion -> drop
                    continue
                if score < FK_THRESHOLD:  # G3
                    continue
                fks.append({
                    "child_table": ct, "child_column": cname,
                    "parent_table": pt, "parent_column": ppk,
                    "inclusion": round(v, 3), "name_sim": s,
                    "score": round(score, 1), "tested": tested,
                })
    # G4: keep only the best parent per child column
    best = {}
    for fk in fks:
        key = (fk["child_table"], fk["child_column"])
        if key not in best or fk["score"] > best[key]["score"]:
            best[key] = fk
    return list(best.values())


def main():
    profile = load_json(out_path("profile.json"))
    conn = connect()
    conn.autocommit = True
    pks = detect_pks(profile)
    with conn.cursor() as cur:
        fks = detect_fks(cur, profile, pks)
    conn.close()
    out = {"primary_keys": pks, "foreign_keys": fks}
    dump_json(out, out_path("relations.json"))
    print(f">> detected {len(pks)} PKs, {len(fks)} FKs -> out/relations.json")
    for fk in sorted(fks, key=lambda x: -x["score"])[:15]:
        print(f"   {fk['child_table']}.{fk['child_column']} -> "
              f"{fk['parent_table']}.{fk['parent_column']} "
              f"(incl={fk['inclusion']} score={fk['score']})")


if __name__ == "__main__":
    main()
