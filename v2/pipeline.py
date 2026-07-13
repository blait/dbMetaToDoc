#!/usr/bin/env python3
"""In-memory pipeline orchestrator — no intermediate files.

Chains profiler → relations → describe → catalog (→ concepts) as plain
function calls passing dicts, then loads the result into the MySQL
metastore, builds the per-run Neptune graph, and indexes the catalog into
OpenSearch. The DB is the single source of truth; nothing is written to
runs/<id>/*.json.

  run_pipeline(run_key, name, with_truth=False) -> catalog dict
      (reads PG* env for the target DB connection, like the rest of v2)

CLI:
  V2_OUT_DIR=runs/<id> python pipeline.py            # analyze + load to DB
"""
import os
import sys

from config import connect, PGSCHEMA, cfg
import profiler
import relations as rel
import describe as desc
import catalog as cat
import concepts as con
from store import db as sdb, repo as srepo


def run_pipeline(run_key, name=None, with_truth=False, do_concepts=True,
                 do_graph=True, do_index=True, do_verify=True,
                 meta_extra=None):
    """Full in-memory analysis → metastore (+ Neptune + OpenSearch).

    Returns the catalog dict. The DB is required — results live in MySQL,
    not files."""
    if not sdb.enabled():
        raise SystemExit("metastore not configured — set METASTORE_* in .env "
                         "(this build stores results in MySQL, not files)")
    name = name or run_key
    sdb.init_db()

    conn = connect()
    conn.autocommit = True
    try:
        print("== 1. profile ==")
        profile = profiler.build_profile(conn)
        print("== 2. relations ==")
        relations = rel.recover_relations(profile, conn)
        print("== 3. describe ==")
        descriptions = desc.build_descriptions(profile, relations, conn)
        print("== 4. catalog ==")
        catalog = cat.build_catalog(profile, relations, descriptions)
    finally:
        conn.close()

    concepts = None
    if do_concepts:
        print("== 5. concepts (ontology) ==")
        try:
            concepts = con.extract_concepts(catalog)
            print(f"   {len(concepts['concepts'])} concepts")
        except Exception as e:
            print(f"   concepts skipped: {e}")
        # semantic relations between concepts (grounded in recovered FKs;
        # cardinality is data-derived) — isolated from concept extraction
        if concepts:
            try:
                rel = con.extract_concept_relations(
                    catalog, concepts["concepts"])
                concepts["relations"] = rel["relations"]
                print(f"   {len(rel['relations'])} concept relations "
                      f"({len(rel['dropped'])} dropped)")
            except Exception as e:
                print(f"   concept relations skipped: {e}")

    # eval-only: score descriptions against OMOP ground truth (in-memory)
    score = None
    if with_truth:
        print("== 5b. score (OMOP ground truth) ==")
        try:
            import score as S
            report, _ = S.score_run(descriptions, relations)
            score = S.headline_from_report(report)
            print(f"   col_judge={score.get('col_judge')} "
                  f"fk_f1={score.get('fk_f1')} S={score.get('s_overall')}")
        except Exception as e:
            print(f"   scoring skipped: {e}")

    # primary load: the catalog + concepts into MySQL (source of truth)
    meta = {"name": name, "with_truth": with_truth, "status": "done",
            "schema": catalog.get("schema") or PGSCHEMA, "score": score}
    if meta_extra:
        meta.update(meta_extra)
    srepo.upsert_run(run_key, catalog, concepts, meta)
    ncols = sum(len(t["columns"]) for t in catalog["tables"])
    print(f">> loaded run '{run_key}' to metastore "
          f"({len(catalog['tables'])} tables / {ncols} columns)")

    # secondary: schema graph (Neptune) + metadata RAG index (OpenSearch),
    # both keyed by run_key. Best-effort: a missing service must not fail
    # the run — the catalog is already persisted.
    if do_graph:
        print("== 6. neptune graph ==")
        try:
            import graph as G
            gid = G.load_catalog_to_graph(
                run_key, catalog, srepo.run_graph_id(run_key))
            srepo.set_status(run_key, "done", graph_id=gid)
            if concepts:
                con.load_concepts_to_graph(
                    run_key, gid, concepts["concepts"],
                    concepts.get("relations"))
                print(f"   loaded {len(concepts['concepts'])} concepts to graph")
        except Exception as e:
            print(f"   graph skipped: {e}")

    if do_index:
        print("== 7. opensearch index ==")
        try:
            import metasearch
            metasearch.index_catalog(run_key, catalog)
        except Exception as e:
            print(f"   index skipped: {e}")

    # verified queries LAST — text2sql needs the graph + search index above
    if do_verify:
        print("== 8. verified queries (competency questions) ==")
        try:
            import verified
            verified.build_verified(run_key, catalog, concepts)
        except Exception as e:
            print(f"   verified queries skipped: {e}")

    return catalog


def _run_key():
    d = cfg("V2_OUT_DIR", "")
    return os.path.basename(os.path.normpath(d)) if d else "default"


def main():
    rk = _run_key()
    run_pipeline(rk, name=rk)


if __name__ == "__main__":
    main()
