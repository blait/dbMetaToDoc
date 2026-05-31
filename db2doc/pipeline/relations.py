"""Relationship recovery (engine-injected, dialect-agnostic).

Extracted from recover/keys.py.  The scoring formulas and gates are PURE
functions copied verbatim (no behavior change).  Only the inclusion-dependency
query is rewritten from PG `= ANY(%s)` to dialect-agnostic `col.in_(values)`
via targets/stats.
"""
from ..targets import stats as S

PK_THRESHOLD = 70
FK_THRESHOLD = 60
INT_TYPES = {"integer", "bigint", "smallint"}
INCLUSION_SAMPLE = 200


def _is_int(data_type):
    dt = (data_type or "").lower()
    return any(t in dt for t in INT_TYPES)


# --------------------------------------------------------------- PK scoring
def pk_score(table, col, ncols):
    s = col["stats"]
    f_u = 1.0 if s.get("unique_in_sample") else (s.get("distinct_ratio") or 0)
    name = col["name"].lower()
    if name == f"{table}_id":
        n = 1.0
    elif name.endswith("_id") or name == "id":
        n = 0.6
    else:
        n = 0.0
    d = 1.0 if _is_int(col["data_type"]) else 0.3
    pos = col["position"]
    p = max(0.55, 1.0 - 0.15 * (pos - 1))
    return 50 * f_u + 20 * n + 15 * d + 15 * p


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
    if ppk and ppk.replace("_id", "") in c:
        return 0.6
    return 0.0


def inclusion_ratio(conn, tbl_cache, child_table, child_col, parent_table, parent_col):
    """Fraction of sampled non-null child values present in parent column.

    Dialect-agnostic: uses reflected Tables + col.in_() (vs PG `= ANY`).
    `tbl_cache` maps table name -> reflected Table (reflected once).
    """
    try:
        ctbl = tbl_cache[child_table]
        ptbl = tbl_cache[parent_table]
        child_vals = S.sample_values(conn, ctbl, child_col, INCLUSION_SAMPLE)
        if not child_vals:
            return None, 0
        present = S.present_values(conn, ptbl, parent_col, list(child_vals))
        hit = sum(1 for v in child_vals if v in present)
        return hit / len(child_vals), len(child_vals)
    except Exception:
        return None, 0


def detect_fks(engine, schema, profile, pks):
    fks = []
    tables = profile["tables"]
    parents = {t: info["column"] for t, info in pks.items()}
    tbl_cache = {}

    def get_tbl(name):
        if name not in tbl_cache:
            tbl_cache[name] = S.reflect_table(engine, schema, name)
        return tbl_cache[name]

    with engine.connect() as conn:
        for ct, tinfo in tables.items():
            ct_pk = pks.get(ct, {}).get("column")
            for col in tinfo["columns"]:
                cname = col["name"]
                if cname == ct_pk:
                    continue
                if not (cname.lower().endswith("_id") or cname.lower() == "id"):
                    continue
                if not _is_int(col["data_type"]):
                    continue
                for pt, ppk in parents.items():
                    if pt == ct:
                        continue
                    sim = name_similarity(cname, pt, ppk)
                    if sim < 0.5:               # G1: require a name signal
                        continue
                    get_tbl(ct); get_tbl(pt)
                    v, tested = inclusion_ratio(conn, tbl_cache, ct, cname, pt, ppk)
                    if v is None:
                        continue
                    r = 1.0
                    k = 1.0
                    nu = 1.0 if col["nullable"] else 0.8
                    score = 40 * v + 20 * sim + 15 * r + 15 * k + 10 * nu
                    if v < 0.5:                 # G2: weak inclusion
                        continue
                    if score < FK_THRESHOLD:    # G3
                        continue
                    fks.append({
                        "child_table": ct, "child_column": cname,
                        "parent_table": pt, "parent_column": ppk,
                        "inclusion": round(v, 3), "name_sim": sim,
                        "score": round(score, 1), "tested": tested,
                    })
    # G4: best parent per child column
    best = {}
    for fk in fks:
        key = (fk["child_table"], fk["child_column"])
        if key not in best or fk["score"] > best[key]["score"]:
            best[key] = fk
    return list(best.values())


def recover_relations(engine, schema, profile, progress=None):
    """Return {"primary_keys": {...}, "foreign_keys": [...]}."""
    pks = detect_pks(profile)
    if progress:
        progress("pk", len(pks))
    fks = detect_fks(engine, schema, profile, pks)
    if progress:
        progress("fk", len(fks))
    return {"primary_keys": pks, "foreign_keys": fks}
