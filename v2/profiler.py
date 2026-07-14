#!/usr/bin/env python3
"""Stage 1 — Profiler: schema metadata + per-column statistics + samples.

v2 improvements over v1:
  - ONE aggregate query per table for all column stats (count / distinct /
    min / max) instead of 3 queries per column  -> far fewer round trips.
  - enum detection: low-cardinality columns get full value distributions.
  - candidate-key scan: exact uniqueness on the full table (not just a
    1000-row sample), plus 2-column composite-key candidates.

Reads ONLY what an undocumented DB exposes: names, types, and the data.
Writes out/profile.json.
"""
import sys

from config import connect, PGSCHEMA, out_path, dump_json, qident, cfg

SAMPLE_ROWS = 1000        # cap for value-level sampling
TOPK = 10                 # most frequent values kept per column
ENUM_MAX_DISTINCT = 50    # <= this many distinct values => treat as enum
MAX_COMPOSITE_COLS = 5    # leading columns considered for composite keys


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


def fetch_comments(cur, table):
    """Existing table/column COMMENTs (customer DBs often have them).

    Used as an EXTRA hint for description inference and surfaced with a
    'existing comment' provenance. Disabled in eval mode (V2_USE_COMMENTS=0)
    so the OMOP benchmark stays blind. Returns (table_comment, {col: comment}).
    """
    if cfg("V2_USE_COMMENTS", "1") not in ("1", "true", "True"):
        return None, {}
    rel = f"{PGSCHEMA}.{table}"
    tbl_comment = None
    col_comments = {}
    try:
        cur.execute("SELECT obj_description(%s::regclass, 'pg_class')", (rel,))
        row = cur.fetchone()
        tbl_comment = row[0] if row else None
        cur.execute(
            """SELECT a.attname, col_description(a.attrelid, a.attnum)
               FROM pg_attribute a
               WHERE a.attrelid = %s::regclass AND a.attnum > 0
                 AND NOT a.attisdropped""", (rel,))
        for name, comment in cur.fetchall():
            if comment:
                col_comments[name] = comment
    except Exception:
        return None, {}
    return tbl_comment, col_comments


# types with native min()/max() aggregates AND equality for DISTINCT;
# everything else (boolean, json, xml, geometric, ...) is cast to text
_AGG_OK = {"smallint", "integer", "bigint", "numeric", "real",
           "double precision", "money", "character varying", "character",
           "text", "date", "interval", "uuid", "inet", "name", "oid",
           "timestamp without time zone", "timestamp with time zone",
           "time without time zone", "time with time zone"}


def bulk_stats(cur, table, cols, rowcount):
    """All per-column aggregates in a single query over a bounded sample."""
    if rowcount == 0:
        return {c["name"]: {"sampled": 0, "null_ratio": None, "distinct": 0,
                            "distinct_ratio": None, "unique_in_sample": False,
                            "min": None, "max": None} for c in cols}
    parts = ["count(*) AS _n"]
    for i, c in enumerate(cols):
        q = qident(c["name"])
        agg = q if c["data_type"] in _AGG_OK else f"({q}::text)"
        parts.append(f"count({q}) AS nn_{i}")
        parts.append(f"count(DISTINCT {agg}) AS d_{i}")
        parts.append(f"min({agg})::text AS mn_{i}")
        parts.append(f"max({agg})::text AS mx_{i}")
    src = f"(SELECT * FROM {qident(PGSCHEMA)}.{qident(table)} LIMIT {SAMPLE_ROWS}) s"
    cur.execute(f"SELECT {', '.join(parts)} FROM {src}")
    row = cur.fetchone()
    n = row[0]
    stats = {}
    for i, c in enumerate(cols):
        nn, d, mn, mx = row[1 + i * 4: 5 + i * 4]
        stats[c["name"]] = {
            "sampled": n,
            "null_ratio": round(1 - nn / n, 4) if n else None,
            "distinct": d,
            "distinct_ratio": round(d / nn, 4) if nn else None,
            "unique_in_sample": (d == nn and nn > 0),
            "min": mn, "max": mx,
        }
    return stats


def top_values(cur, table, col):
    src = (f'(SELECT {qident(col)} AS v FROM {qident(PGSCHEMA)}.{qident(table)} '
           f'LIMIT {SAMPLE_ROWS}) s')
    try:
        cur.execute(
            f"SELECT v::text, count(*) c FROM {src} "
            f"WHERE v IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT {TOPK}")
        return [{"value": v, "count": c} for v, c in cur.fetchall()]
    except Exception:
        return []


def exact_distinct(cur, table, cols_expr):
    """Exact distinct count over the FULL table (not the sample)."""
    try:
        cur.execute(
            f"SELECT count(DISTINCT ({cols_expr})) "
            f"FROM {qident(PGSCHEMA)}.{qident(table)}")
        return cur.fetchone()[0]
    except Exception:
        return None


def candidate_keys(cur, table, cols, stats, rowcount):
    """Single-column unique keys (exact) + 2-column composite candidates.

    Also records full_distinct_ratio for near-unique columns so key
    detection can distinguish 'dirty duplicates' (ratio ~0.95) from
    genuinely repeating values (ratio far below 1)."""
    if rowcount == 0:
        return {"unique_columns": [], "composite_candidates": []}
    unique_cols = []
    for c in cols:
        st = stats[c["name"]]
        # verify exactly when the sample looks unique or near-unique
        if (st["distinct_ratio"] or 0) >= 0.95 and st["null_ratio"] == 0:
            if rowcount <= SAMPLE_ROWS:
                st["full_distinct_ratio"] = st["distinct_ratio"]
            else:
                d = exact_distinct(cur, table, qident(c["name"]))
                st["full_distinct_ratio"] = (round(d / rowcount, 4)
                                             if d is not None else None)
            if st["full_distinct_ratio"] == 1.0:
                unique_cols.append(c["name"])
    composites = []
    if not unique_cols:
        idish = [c["name"] for c in cols[:MAX_COMPOSITE_COLS]
                 if c["name"].lower().endswith("_id")]
        for i in range(len(idish)):
            for j in range(i + 1, len(idish)):
                expr = f"{qident(idish[i])}, {qident(idish[j])}"
                if exact_distinct(cur, table, expr) == rowcount:
                    composites.append([idish[i], idish[j]])
    return {"unique_columns": unique_cols, "composite_candidates": composites}


def build_profile(conn=None):
    """Profile the schema and return the profile dict (no file IO)."""
    own = conn is None
    if own:
        conn = connect()
        conn.autocommit = True
    profile = {"schema": PGSCHEMA, "tables": {}}
    with conn.cursor() as cur:
        tables = fetch_tables(cur)
        print(f">> {len(tables)} tables in schema {PGSCHEMA}")
        for t in tables:
            cols = fetch_columns(cur, t)
            cur.execute(f"SELECT count(*) FROM {qident(PGSCHEMA)}.{qident(t)}")
            rc = cur.fetchone()[0]
            stats = bulk_stats(cur, t, cols, rc)
            for c in cols:
                st = stats[c["name"]]
                # enums + likely-code columns get their value distribution
                if rc and 0 < st["distinct"] <= ENUM_MAX_DISTINCT:
                    st["top_values"] = top_values(cur, t, c["name"])
                    st["is_enum_candidate"] = True
                elif rc and st["distinct"] > 0:
                    st["top_values"] = top_values(cur, t, c["name"])[:5]
                    st["is_enum_candidate"] = False
                else:
                    st["top_values"] = []
                    st["is_enum_candidate"] = False
                st["examples"] = [tv["value"] for tv in st["top_values"][:5]]
            keys = candidate_keys(cur, t, cols, stats, rc)
            tbl_comment, col_comments = fetch_comments(cur, t)
            profile["tables"][t] = {
                "rowcount": rc,
                "table_comment": tbl_comment,
                "columns": [{**c, "stats": stats[c["name"]],
                             "existing_comment": col_comments.get(c["name"])}
                            for c in cols],
                "keys": keys,
            }
            print(f"   {t:<28} rows={rc:<8} cols={len(cols):<3} "
                  f"unique={keys['unique_columns']}")
    if own:
        conn.close()
    return profile


def main():
    profile = build_profile()
    path = dump_json(profile, out_path("profile.json"))
    print(f">> wrote {path}")


if __name__ == "__main__":
    main()
