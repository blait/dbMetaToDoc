#!/usr/bin/env python3
"""Run the whole v2 pipeline end-to-end (in-memory, DB-only).

    python run.py                      # analyze the PG* target → metastore
    python run.py --name "My DB"       # set a display name
    python run.py --run-key myrun      # explicit run key (default: from
                                       #   V2_OUT_DIR basename, else 'default')
    python run.py --with-truth         # OMOP eval run (blind: ignore comments)
    python run.py --no-concepts        # skip the ontology layer

The pipeline chains profile → relations → describe → catalog (→ concepts) in
memory and persists ONLY to MySQL (+ Neptune graph + OpenSearch index). No
runs/<id>/*.json artifacts are written — the metastore is the source of truth.

Ground-truth scoring (score.py) is a separate eval tool; see score.py --help.
"""
import argparse
import os

import pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-key", default=None,
                    help="run key (default: V2_OUT_DIR basename or 'default')")
    ap.add_argument("--name", default=None)
    ap.add_argument("--with-truth", action="store_true",
                    help="OMOP eval run — stay blind (ignore DB comments)")
    ap.add_argument("--no-concepts", action="store_true")
    ap.add_argument("--no-graph", action="store_true")
    ap.add_argument("--no-index", action="store_true")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip stage 8 (verified competency questions)")
    args = ap.parse_args()

    rk = args.run_key or pipeline._run_key()
    if args.with_truth:
        os.environ["V2_USE_COMMENTS"] = "0"
    pipeline.run_pipeline(
        rk, name=args.name or rk, with_truth=args.with_truth,
        do_concepts=not args.no_concepts, do_graph=not args.no_graph,
        do_index=not args.no_index, do_verify=not args.no_verify)
    print("\n>> pipeline complete (results in the metastore).")


if __name__ == "__main__":
    main()
