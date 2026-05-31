"""Profiler — schema metadata + per-column stats + samples (engine-injected).

Extracted from profile/profile.py, made dialect-agnostic via targets/.
Output dict shape matches the PoC's profile.json so downstream code is unchanged.
Perf: one shared connection + reflect each table once.
"""
from ..targets import inspect as I, stats as S


def profile_schema(engine, schema, sample_rows=1000, progress=None):
    """Return {"schema", "tables": {name: {rowcount, columns:[...]}}}."""
    tables = I.list_tables(engine, schema)
    out = {"schema": schema, "tables": {}}
    n = len(tables)
    with engine.connect() as conn:
        for i, t in enumerate(tables, 1):
            cols = I.get_columns(engine, schema, t)
            tbl = S.reflect_table(engine, schema, t)
            rc = S.table_rowcount(conn, tbl)
            colprofiles = []
            for c in cols:
                st = S.column_stats(conn, tbl, c["name"], sample_rows)
                colprofiles.append({**c, "stats": st})
            out["tables"][t] = {"rowcount": rc, "columns": colprofiles}
            if progress:
                progress(i, n, t)
    return out
