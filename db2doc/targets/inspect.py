"""Dialect-agnostic metadata reading via SQLAlchemy Inspector.

Replaces the PoC's direct information_schema queries (profile.py).
For MySQL, `schema` is the database name; for PostgreSQL it's the namespace.
Inspector handles both.
"""
from sqlalchemy import inspect as sa_inspect


def get_inspector(engine):
    return sa_inspect(engine)


def list_tables(engine, schema):
    insp = sa_inspect(engine)
    return sorted(insp.get_table_names(schema=schema))


def get_columns(engine, schema, table):
    """Return list of dicts: name, data_type, nullable, position."""
    insp = sa_inspect(engine)
    cols = []
    for i, c in enumerate(insp.get_columns(table, schema=schema), 1):
        cols.append({
            "name": c["name"],
            "data_type": str(c["type"]).lower(),
            "nullable": bool(c.get("nullable", True)),
            "position": i,
        })
    return cols


def get_declared_pk(engine, schema, table):
    """Declared primary key columns (may be empty if undocumented)."""
    insp = sa_inspect(engine)
    pk = insp.get_pk_constraint(table, schema=schema)
    return pk.get("constrained_columns", []) or []


def get_declared_fks(engine, schema, table):
    """Declared foreign keys, normalized to a simple shape."""
    insp = sa_inspect(engine)
    out = []
    for fk in insp.get_foreign_keys(table, schema=schema):
        cc = fk.get("constrained_columns", [])
        rc = fk.get("referred_columns", [])
        out.append({
            "child_columns": cc,
            "parent_table": fk.get("referred_table"),
            "parent_columns": rc,
        })
    return out
