#!/usr/bin/env python3
"""Metastore CLI.

  python -m store.sync init          # create tables (idempotent)
  python -m store.sync ddl           # print CREATE TABLE DDL (for docs)
  python -m store.sync list          # run summaries from DB

Analysis results are loaded by the pipeline itself (run.py / webapp) — there
is no file-based `push`; this build never writes catalog JSON to disk.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from store import db, repo  # noqa: E402


def cmd_init():
    db.init_db()
    print(">> metastore tables created at", db.metastore_url().split("@")[-1])


def cmd_ddl():
    print(db.ddl_sql())


def cmd_list():
    for r in repo.list_runs():
        h = r.get("headline", {})
        print(f"  {r['id']:<28} {r['name'][:30]:32} "
              f"{h.get('tables','?')}T/{h.get('columns','?')}C  {r['status']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    {"init": cmd_init, "ddl": cmd_ddl, "list": cmd_list}.get(cmd, cmd_init)()


if __name__ == "__main__":
    main()
