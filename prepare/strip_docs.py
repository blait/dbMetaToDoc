#!/usr/bin/env python3
"""Reproduce a "no documentation" DB state on the target schema.

run_ddl.sh already loads WITHOUT foreign keys, but this script makes the
no-docs state explicit and repeatable:
  - DROP every FOREIGN KEY constraint in the schema
  - remove every table/column COMMENT
  - (optional, --drop-pk) drop PRIMARY KEY constraints too, so key recovery
    is tested from scratch rather than read off the catalog

Idempotent.  Use --keep-pk (default) to leave PKs in place.
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import connect, PGSCHEMA  # noqa: E402


def drop_foreign_keys(cur):
    cur.execute(
        """SELECT conrelid::regclass::text, conname
           FROM pg_constraint c
           JOIN pg_namespace n ON n.oid = c.connamespace
           WHERE c.contype='f' AND n.nspname=%s""", (PGSCHEMA,))
    rows = cur.fetchall()
    for tbl, con in rows:
        cur.execute(f'ALTER TABLE {tbl} DROP CONSTRAINT "{con}"')
    return len(rows)


def drop_primary_keys(cur):
    cur.execute(
        """SELECT conrelid::regclass::text, conname
           FROM pg_constraint c
           JOIN pg_namespace n ON n.oid = c.connamespace
           WHERE c.contype='p' AND n.nspname=%s""", (PGSCHEMA,))
    rows = cur.fetchall()
    for tbl, con in rows:
        cur.execute(f'ALTER TABLE {tbl} DROP CONSTRAINT "{con}"')
    return len(rows)


def strip_comments(cur):
    # tables
    cur.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema=%s AND table_type='BASE TABLE'""", (PGSCHEMA,))
    tables = [r[0] for r in cur.fetchall()]
    n = 0
    for t in tables:
        cur.execute(f'COMMENT ON TABLE "{PGSCHEMA}"."{t}" IS NULL')
        n += 1
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema=%s AND table_name=%s""", (PGSCHEMA, t))
        for (col,) in cur.fetchall():
            cur.execute(f'COMMENT ON COLUMN "{PGSCHEMA}"."{t}"."{col}" IS NULL')
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop-pk", action="store_true",
                    help="also drop PRIMARY KEY constraints")
    args = ap.parse_args()

    conn = connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        nfk = drop_foreign_keys(cur)
        nc = strip_comments(cur)
        print(f">> dropped {nfk} FK constraints, cleared {nc} comments")
        if args.drop_pk:
            npk = drop_primary_keys(cur)
            print(f">> dropped {npk} PK constraints")
    conn.close()
    print(">> schema is now in 'no documentation' state")


if __name__ == "__main__":
    main()
