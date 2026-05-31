"""Dialect-agnostic column statistics via SQLAlchemy Core.

Replaces the raw PG SQL in profile.py (column_stats). Uses reflected Table
objects so identifier quoting and SQL are correct for any dialect.

Perf: callers pass an open Connection and a once-reflected Table so we don't
re-connect / re-reflect per column (that made profiling very slow over RDS).
"""
from sqlalchemy import (Table, MetaData, select, func, distinct, text)

TOPK = 10
SAMPLE_VALUES = 5


def reflect_table(engine, schema, table):
    md = MetaData()
    return Table(table, md, schema=schema, autoload_with=engine)


def table_rowcount(conn, tbl):
    return conn.execute(select(func.count()).select_from(tbl)).scalar_one()


def column_stats(conn, tbl, col_name, sample_rows):
    """Per-column profile over a bounded sample. Uses the given Connection."""
    col = tbl.c[col_name]
    sub = select(col).limit(sample_rows).subquery()
    sc = sub.c[col_name]
    stats = {}
    n, non_null, dist = conn.execute(
        select(func.count(), func.count(sc), func.count(distinct(sc)))
    ).one()
    stats["sampled"] = int(n)
    stats["null_ratio"] = round(1 - (non_null / n), 4) if n else None
    stats["distinct"] = int(dist)
    stats["distinct_ratio"] = round(dist / non_null, 4) if non_null else None
    stats["unique_in_sample"] = (dist == non_null and non_null > 0)

    try:
        mn, mx = conn.execute(select(func.min(sc), func.max(sc))).one()
        stats["min"] = None if mn is None else str(mn)
        stats["max"] = None if mx is None else str(mx)
    except Exception:
        stats["min"] = stats["max"] = None

    try:
        rows = conn.execute(
            select(sc, func.count().label("c"))
            .where(sc.isnot(None)).group_by(sc)
            .order_by(text("c DESC")).limit(TOPK)
        ).all()
        stats["top_values"] = [{"value": None if v is None else str(v),
                                "count": int(c)} for v, c in rows]
    except Exception:
        stats["top_values"] = []
    stats["examples"] = [tv["value"] for tv in stats["top_values"][:SAMPLE_VALUES]]
    return stats


def sample_values(conn, tbl, col_name, limit):
    """Non-null sampled values for inclusion-dependency tests."""
    col = tbl.c[col_name]
    return conn.execute(
        select(col).where(col.isnot(None)).limit(limit)
    ).scalars().all()


def present_values(conn, tbl, col_name, candidate_values):
    """Distinct candidate_values that exist in tbl.col_name (for inclusion)."""
    col = tbl.c[col_name]
    return set(conn.execute(
        select(distinct(col)).where(col.in_(candidate_values))
    ).scalars().all())
