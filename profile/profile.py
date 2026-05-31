#!/usr/bin/env python3
"""Profiler: collect schema metadata + per-column statistics + sample rows.

Input  : the OMOP schema on RDS (after strip_docs removed FKs/comments).
Output : out/profile.json  — the only thing downstream stages read about the DB.

We deliberately read ONLY what a documentation-less DB would expose:
table/column names, data types, nullability, and the data itself.
We do NOT read comments or FK constraints here.
"""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import connect, PGSCHEMA, out_path, dump_json  # noqa: E402

SAMPLE_ROWS = 1000      # DBAutoDoc-style per-table sample cap
TOPK = 10               # most frequent values to keep per column
SAMPLE_VALUES = 5       # example distinct values to show per column


def fetch_tables(cur):
    cur.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema=%s AND table_type='BASE TABLE'
           ORDER BY table_name""", (PGSCHEMA,))
    return [r[0] for r in cur.fetchall()]


def fetch_columns(cur, table):
    cur.execute(
        """SELECT column_name, data_type, is_nullable, ordinal_position,
                  character_maximum_length, numeric_precision
           FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s
           ORDER BY ordinal_position""", (PGSCHEMA, table))
    return [dict(name=r[0], data_type=r[1], nullable=(r[2] == "YES"),
                 position=r[3], char_max_len=r[4], num_precision=r[5])
            for r in cur.fetchall()]


def table_rowcount(cur, table):
    cur.execute(f'SELECT count(*) FROM "{PGSCHEMA}"."{table}"')
    return cur.fetchone()[0]


def column_stats(cur, table, col, rowcount):
    """Per-column profile computed over a bounded sample for speed."""
    q = col["name"]
    # use a sampled subquery so large tables stay fast
    src = (f'(SELECT "{q}" FROM "{PGSCHEMA}"."{table}" '
           f'LIMIT {SAMPLE_ROWS}) s')
    stats = {}
    cur.execute(f'SELECT count(*), count("{q}"), count(DISTINCT "{q}") FROM {src}')
    n, non_null, distinct = cur.fetchone()
    stats["sampled"] = n
    stats["null_ratio"] = round(1 - (non_null / n), 4) if n else None
    stats["distinct"] = distinct
    stats["distinct_ratio"] = round(distinct / non_null, 4) if non_null else None
    stats["unique_in_sample"] = (distinct == non_null and non_null > 0)

    # min / max (works for numeric, date, text)
    try:
        cur.execute(f'SELECT min("{q}")::text, max("{q}")::text FROM {src}')
        mn, mx = cur.fetchone()
        stats["min"], stats["max"] = mn, mx
    except Exception:
        stats["min"] = stats["max"] = None

    # top-k frequent values
    try:
        cur.execute(
            f'SELECT "{q}"::text AS v, count(*) c FROM {src} '
            f'WHERE "{q}" IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT {TOPK}')
        stats["top_values"] = [{"value": v, "count": c} for v, c in cur.fetchall()]
    except Exception:
        stats["top_values"] = []

    # a few example distinct values (for the LLM to read)
    stats["examples"] = [tv["value"] for tv in stats["top_values"][:SAMPLE_VALUES]]
    return stats


def main():
    conn = connect()
    conn.autocommit = True
    profile = {"schema": PGSCHEMA, "tables": {}}
    with conn.cursor() as cur:
        tables = fetch_tables(cur)
        print(f">> {len(tables)} tables in schema {PGSCHEMA}")
        for t in tables:
            cols = fetch_columns(cur, t)
            rc = table_rowcount(cur, t)
            colprofiles = []
            for c in cols:
                s = column_stats(cur, t, c, rc)
                colprofiles.append({**c, "stats": s})
            profile["tables"][t] = {"rowcount": rc, "columns": colprofiles}
            print(f"   profiled {t:<26} rows={rc:<8} cols={len(cols)}")
    conn.close()
    path = dump_json(profile, out_path("profile.json"))
    print(f">> wrote {path}")


if __name__ == "__main__":
    main()
