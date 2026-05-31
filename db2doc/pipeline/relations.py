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


def _has_data(tinfo):
    """True if at least one column has a measured sample (table not empty)."""
    for c in tinfo["columns"]:
        if c["stats"].get("sampled"):
            return True
    return False


def detect_pks(profile):
    """Detect a PK per table.

    - tables with data: statistical sPK score (>= threshold).
    - empty tables (no rows -> no stats): name-based fallback (`<table>_id` or
      a lone `*_id`/`id`), emitted with low confidence + source='name'.
    """
    pks = {}
    for table, tinfo in profile["tables"].items():
        ncols = len(tinfo["columns"])
        if _has_data(tinfo):
            best = None
            for col in tinfo["columns"]:
                sc = pk_score(table, col, ncols)
                if best is None or sc > best[1]:
                    best = (col["name"], sc)
            if best and best[1] >= PK_THRESHOLD:
                pks[table] = {"column": best[0], "score": round(best[1], 1),
                              "confidence": round(min(best[1] / 100, 0.99), 2),
                              "source": "stat"}
        else:
            # empty table: infer PK from naming only (low confidence)
            cand = None
            names = {c["name"].lower(): c for c in tinfo["columns"]}
            if f"{table.lower()}_id" in names:
                cand = names[f"{table.lower()}_id"]["name"]
            else:
                id_cols = [c["name"] for c in tinfo["columns"]
                           if c["name"].lower().endswith("_id")
                           or c["name"].lower() == "id"]
                if len(id_cols) == 1:
                    cand = id_cols[0]
            if cand:
                pks[table] = {"column": cand, "score": 0.0,
                              "confidence": 0.4, "source": "name"}
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


def name_based_fks(profile, pks):
    """FK candidates from naming only (no data needed).

    For any `*_id` column (not the table's own PK) whose stem matches a table
    that has a detected PK, emit a low-confidence FK. Used to recover FKs that
    value-overlap cannot see (empty tables, or values not loaded).
    """
    parents = {t: info["column"] for t, info in pks.items()}
    out = []
    for ct, tinfo in profile["tables"].items():
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
                if sim >= 1.0:   # only strong name matches (e.g. <parent>_id)
                    out.append({
                        "child_table": ct, "child_column": cname,
                        "parent_table": pt, "parent_column": ppk,
                        "inclusion": None, "name_sim": sim,
                        "score": round(20 * sim, 1), "tested": 0,
                        "confidence": 0.4, "source": "name"})
                    break
    return out


def recover_relations(engine, schema, profile, progress=None, use_declared=True):
    """Return {"primary_keys": {...}, "foreign_keys": [...]}.

    Order of trust: declared (from catalog) > statistical (value-verified) >
    name-based (low confidence, for empty/unloaded tables).
    """
    declared_pk, declared_fk = {}, []
    if use_declared:
        try:
            declared_pk, declared_fk = _declared_keys(engine, schema, profile)
        except Exception:
            declared_pk, declared_fk = {}, []

    pks = detect_pks(profile)
    # declared PK wins where present
    for t, col in declared_pk.items():
        pks[t] = {"column": col, "score": 100.0, "confidence": 1.0,
                  "source": "declared"}
    if progress:
        progress("pk", len(pks))

    fks = detect_fks(engine, schema, profile, pks)
    for fk in fks:
        fk.setdefault("confidence", round(min(fk["score"] / 100, 0.99), 2))
        fk.setdefault("source", "stat")

    # add name-based FK candidates for (child_table, child_column) not already found
    seen = {(f["child_table"], f["child_column"]) for f in fks}
    for nf in name_based_fks(profile, pks):
        if (nf["child_table"], nf["child_column"]) not in seen:
            fks.append(nf)
            seen.add((nf["child_table"], nf["child_column"]))

    # declared FK wins / adds (highest trust)
    for df in declared_fk:
        key = (df["child_table"], df["child_column"])
        fks = [f for f in fks if (f["child_table"], f["child_column"]) != key]
        df.update(confidence=1.0, source="declared", score=100.0)
        fks.append(df)

    if progress:
        progress("fk", len(fks))
    return {"primary_keys": pks, "foreign_keys": fks}


def _declared_keys(engine, schema, profile):
    """Read PK/FK already declared in the catalog (Inspector)."""
    from ..targets import inspect as I
    dpk, dfk = {}, []
    for table in profile["tables"].keys():
        pkcols = I.get_declared_pk(engine, schema, table)
        if len(pkcols) == 1:           # single-column PK
            dpk[table] = pkcols[0]
        for fk in I.get_declared_fks(engine, schema, table):
            cc = fk.get("child_columns") or []
            pc = fk.get("parent_columns") or []
            if len(cc) == 1 and fk.get("parent_table"):
                dfk.append({
                    "child_table": table, "child_column": cc[0],
                    "parent_table": fk["parent_table"],
                    "parent_column": pc[0] if pc else None,
                    "inclusion": None, "name_sim": None, "tested": 0})
    return dpk, dfk
