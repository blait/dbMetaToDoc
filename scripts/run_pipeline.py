#!/usr/bin/env python3
"""Run the extracted pipeline against one source — no metastore, for regression.

Examples:
  # profile + relations only (no LLM), compare to PoC out/*.json
  python scripts/run_pipeline.py --dialect postgresql --host $PGHOST \
      --db $PGDATABASE --schema cdm --user $PGUSER --password $PGPASSWORD \
      --stages profile,relations --outdir /tmp/newrun

  # add describe (LLM) too
  ... --stages profile,relations,describe,render
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db2doc.targets import engine as E   # noqa: E402
from db2doc.pipeline import profiler, relations as rel, describe as desc_mod, render  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialect", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default=None)
    ap.add_argument("--db", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", default="")
    ap.add_argument("--stages", default="profile,relations")
    ap.add_argument("--outdir", default="/tmp/db2doc_run")
    ap.add_argument("--sample-rows", type=int, default=1000)
    args = ap.parse_args()
    stages = set(args.stages.split(","))
    os.makedirs(args.outdir, exist_ok=True)

    eng = E.build_engine(args.dialect, args.host, args.port, args.db,
                         args.user, args.password)
    ok, msg = E.test_connection(eng)
    print(f">> connect: {ok} {msg}")
    if not ok:
        sys.exit(1)

    def w(name, obj):
        p = os.path.join(args.outdir, name)
        with open(p, "w") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        print(f"   wrote {p}")

    profile = relations_out = None
    if "profile" in stages:
        profile = profiler.profile_schema(
            eng, args.schema, args.sample_rows,
            progress=lambda i, n, t: print(f"   profile {i}/{n} {t}"))
        w("profile.json", profile)
    if "relations" in stages:
        relations_out = rel.recover_relations(eng, args.schema, profile)
        w("relations.json", relations_out)
        print(f"   PKs={len(relations_out['primary_keys'])} "
              f"FKs={len(relations_out['foreign_keys'])}")
    if "describe" in stages:
        d = desc_mod.describe(
            profile, relations_out,
            progress=lambda i, n, t: print(f"   describe {i}/{n} {t}"))
        w("descriptions.json", d)
        print(f"   domain: {d['db']['domain']}  tokens={d['usage']}")
        if "render" in stages:
            with open(os.path.join(args.outdir, "data_dictionary.md"), "w") as f:
                f.write(render.to_markdown(d, relations_out, args.schema))
            with open(os.path.join(args.outdir, "comments.sql"), "w") as f:
                f.write(render.to_sql(d, args.schema, args.dialect))
            print("   wrote data_dictionary.md, comments.sql")


if __name__ == "__main__":
    main()
