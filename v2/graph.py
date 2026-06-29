#!/usr/bin/env python3
"""Stage 7 — Schema graph: load the generated catalog into AWS Neptune
Analytics as a property graph (openCypher), for text2sql schema linking
and join-path planning.

Graph model (RAT-SQL-style schema graph, property-graph flavored):
  (:Database {name, domain, description})
  (:Table    {name, description, rowcount, confidence})
  (:Column   {id: "table.column", name, type, nullable, is_pk,
              description, confidence, examples})
  (:Database)-[:HAS_TABLE]->(:Table)
  (:Table)-[:HAS_COLUMN]->(:Column)
  (:Column)-[:REFERENCES {source, confidence}]->(:Column)      # FK col->PK col
  (:Table)-[:JOINS_TO {via, source, confidence}]->(:Table)     # derived,
        # one edge per FK: the join-path planning layer for text2sql

Usage:
  python graph.py create            # create the Neptune Analytics graph
  python graph.py load              # upsert catalog -> graph (idempotent)
  python graph.py status            # node/edge counts
  python graph.py delete            # delete the AWS graph (stop billing)

Env: NEPTUNE_GRAPH_ID (or --graph-id), AWS_REGION. Reads catalog from the
run dir (V2_OUT_DIR or out/).
"""
import argparse
import json
import os
import sys
import time

import boto3

from config import REGION, out_path, load_json, cfg

GRAPH_NAME = "db2doc-schema-graph"


def client():
    from botocore.config import Config
    return boto3.client("neptune-graph", region_name=REGION,
                        config=Config(read_timeout=120,
                                      retries={"max_attempts": 6,
                                               "mode": "adaptive"}))


def meta_path():
    """meta.json of the current run (V2_OUT_DIR=runs/<id>)."""
    d = cfg("V2_OUT_DIR")
    return os.path.join(d, "meta.json") if d else None


def read_meta():
    p = meta_path()
    if p and os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def write_meta_graph_id(gid):
    p = meta_path()
    if not p or not os.path.exists(p):
        return
    with open(p) as f:
        meta = json.load(f)
    meta["graph_id"] = gid
    with open(p, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def graph_id(args):
    """Per-run graph id: explicit arg > this run's meta.json > env (legacy)."""
    gid = getattr(args, "graph_id", None)
    if gid:
        return gid
    gid = read_meta().get("graph_id")
    if gid:
        return gid
    return cfg("NEPTUNE_GRAPH_ID")  # legacy single-graph fallback


def ensure_run_graph():
    """Return this run's dedicated Neptune graph, creating it if absent.

    Each run gets its OWN graph (physical isolation). The id is persisted in
    the run's meta.json. NOTE: each graph is billed separately — run deletion
    must delete the graph (webapp does this)."""
    gid = read_meta().get("graph_id")
    c = client()
    if gid:
        try:
            if c.get_graph(graphIdentifier=gid)["status"] == "AVAILABLE":
                return gid
        except Exception:
            pass  # stale id -> recreate
    run = current_run_id()
    name = f"db2doc-{run}"[:63]
    g = c.create_graph(graphName=name, provisionedMemory=16,
                       publicConnectivity=True, replicaCount=0,
                       deletionProtection=False)
    gid = g["id"]
    print(f">> created dedicated graph {gid} ({name}) — waiting AVAILABLE")
    while True:
        st = c.get_graph(graphIdentifier=gid)["status"]
        if st == "AVAILABLE":
            break
        if st in ("FAILED", "DELETING"):
            raise SystemExit(f"graph creation failed: {st}")
        time.sleep(15)
    write_meta_graph_id(gid)
    return gid


def run_query(gid, query, parameters=None):
    kw = {"graphIdentifier": gid, "queryString": query,
          "language": "OPEN_CYPHER"}
    if parameters:
        kw["parameters"] = parameters
    resp = client().execute_query(**kw)
    return json.loads(resp["payload"].read())


# ------------------------------------------------------------------ create
def cmd_create(args):
    c = client()
    g = c.create_graph(graphName=GRAPH_NAME, provisionedMemory=16,
                       publicConnectivity=True, replicaCount=0,
                       deletionProtection=False)
    gid = g["id"]
    print(f">> creating {gid} ({g['endpoint']}) ...")
    while True:
        st = c.get_graph(graphIdentifier=gid)["status"]
        print("   status:", st)
        if st == "AVAILABLE":
            break
        if st in ("FAILED", "DELETING"):
            raise SystemExit(f"graph creation failed: {st}")
        time.sleep(20)
    print(f">> ready. export NEPTUNE_GRAPH_ID={gid}")


def cmd_delete(args):
    gid = graph_id(args)
    client().delete_graph(graphIdentifier=gid, skipSnapshot=True)
    print(f">> deleting {gid} (no snapshot)")


# ------------------------------------------------------------------ load
def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def build_payload(catalog):
    """Flatten catalog.json into node/edge dicts for batched UNWIND."""
    dbname = catalog.get("schema", "db")
    db = catalog.get("database", {})
    db_node = {"name": dbname,
               "domain": db.get("domain", ""),
               "description": db.get("db_description", "")}

    tables, columns, refs, joins = [], [], [], []
    for t in catalog["tables"]:
        pk_cols = set((t.get("primary_key") or {}).get("columns", []))
        tables.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "rowcount": t.get("rowcount", 0),
            "n_columns": len(t["columns"]),
            "pk": ", ".join(sorted(pk_cols)),
        })
        for c in t["columns"]:
            columns.append({
                "id": f'{t["name"]}.{c["name"]}',
                "table": t["name"],
                "name": c["name"],
                "type": c.get("type", ""),
                "nullable": bool(c.get("nullable")),
                "is_pk": c["name"] in pk_cols,
                "description": c.get("description", ""),
                "confidence": float(c.get("confidence") or 0),
                # Neptune openCypher properties are scalars: join examples
                "examples": ", ".join(map(str, (c.get("stats") or {})
                                          .get("examples", []))),
            })
        for f in t.get("foreign_keys", []):
            parent_table, parent_col = f["ref"].split(".", 1)
            refs.append({
                "from": f'{t["name"]}.{f["column"]}',
                "to": f["ref"],
                "source": f.get("source", ""),
                "confidence": float(f.get("confidence") or 0),
            })
            joins.append({
                "from": t["name"], "to": parent_table,
                "via": f'{t["name"]}.{f["column"]} = {f["ref"]}',
                "source": f.get("source", ""),
                "confidence": float(f.get("confidence") or 0),
            })
    return db_node, tables, columns, refs, joins


def current_run_id():
    """Derive the run id from V2_OUT_DIR (…/runs/<id>) so each run's graph is
    namespaced inside the single Neptune Analytics graph (per-graph billing
    makes one-graph-per-run impractical)."""
    d = cfg("V2_OUT_DIR") or ""
    rid = os.path.basename(os.path.normpath(d)) if d else ""
    return rid or "default"


def create_run_graph(run_key, existing_gid=None):
    """Return a dedicated Neptune graph for run_key, creating it if needed.

    DB-only variant of ensure_run_graph (no meta.json). Pass the run's stored
    graph_id as existing_gid to reuse it; returns the (possibly new) gid."""
    c = client()
    if existing_gid:
        try:
            if c.get_graph(graphIdentifier=existing_gid)["status"] == "AVAILABLE":
                return existing_gid
        except Exception:
            pass  # stale -> recreate
    name = f"db2doc-{run_key}"[:63]
    gid = c.create_graph(graphName=name, provisionedMemory=16,
                         publicConnectivity=True, replicaCount=0,
                         deletionProtection=False)["id"]
    print(f">> created dedicated graph {gid} ({name}) — waiting AVAILABLE")
    while True:
        st = c.get_graph(graphIdentifier=gid)["status"]
        if st == "AVAILABLE":
            break
        if st in ("FAILED", "DELETING"):
            raise SystemExit(f"graph creation failed: {st}")
        time.sleep(15)
    return gid


def load_catalog_to_graph(run_key, catalog, existing_gid=None):
    """Load a catalog DICT into run_key's dedicated graph (no files).

    Returns the graph id (create it if existing_gid is stale/None)."""
    gid = create_run_graph(run_key, existing_gid)
    db_node, tables, columns, refs, joins = build_payload(catalog)
    db_node["run"] = run_key
    for x in tables + columns + refs + joins:
        x["run"] = run_key
    print(f">> loading run '{run_key}' into {gid}: {len(tables)} tables, "
          f"{len(columns)} columns, {len(refs)} FK refs")
    delete_run_namespace(gid, run_key)

    run_query(gid, """
        MERGE (d:Database {name: $name, run: $run})
        SET d.domain = $domain, d.description = $description
    """, db_node)
    for batch in chunks(tables, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MERGE (t:Table {name: r.name, run: r.run})
            SET t.description = r.description, t.rowcount = r.rowcount,
                t.n_columns = r.n_columns, t.pk = r.pk
            WITH t, r
            MATCH (d:Database {name: $db, run: r.run})
            MERGE (d)-[:HAS_TABLE]->(t)
        """, {"rows": batch, "db": db_node["name"]})
    for batch in chunks(columns, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MERGE (c:Column {id: r.id, run: r.run})
            SET c.name = r.name, c.table = r.table, c.type = r.type,
                c.nullable = r.nullable, c.is_pk = r.is_pk,
                c.description = r.description, c.confidence = r.confidence,
                c.examples = r.examples
            WITH c, r
            MATCH (t:Table {name: r.table, run: r.run})
            MERGE (t)-[:HAS_COLUMN]->(c)
        """, {"rows": batch})
    for batch in chunks(refs, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Column {id: r.from, run: r.run}),
                  (b:Column {id: r.to, run: r.run})
            MERGE (a)-[e:REFERENCES]->(b)
            SET e.source = r.source, e.confidence = r.confidence
        """, {"rows": batch})
    for batch in chunks(joins, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Table {name: r.from, run: r.run}),
                  (b:Table {name: r.to, run: r.run})
            MERGE (a)-[e:JOINS_TO {via: r.via}]->(b)
            SET e.source = r.source, e.confidence = r.confidence
        """, {"rows": batch})
    print("   graph load done")
    return gid


def delete_run_namespace(gid, run):
    """Remove all nodes/edges of one run (idempotent reload)."""
    run_query(gid, "MATCH (n {run: $run}) DETACH DELETE n", {"run": run})


def cmd_load(args):
    gid = ensure_run_graph()          # this run's dedicated graph
    run = current_run_id()
    catalog = load_json(out_path("catalog.json"))
    db_node, tables, columns, refs, joins = build_payload(catalog)
    # every node carries `run`; keys are (run, name) so the same table name
    # in different runs are distinct nodes
    db_node["run"] = run
    for x in tables + columns:
        x["run"] = run
    for x in refs + joins:
        x["run"] = run
    print(f">> loading run '{run}' into {gid}: {len(tables)} tables, "
          f"{len(columns)} columns, {len(refs)} FK refs")

    delete_run_namespace(gid, run)
    print("   cleared previous nodes for this run")

    run_query(gid, """
        MERGE (d:Database {name: $name, run: $run})
        SET d.domain = $domain, d.description = $description
    """, db_node)

    for batch in chunks(tables, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MERGE (t:Table {name: r.name, run: r.run})
            SET t.description = r.description, t.rowcount = r.rowcount,
                t.n_columns = r.n_columns, t.pk = r.pk
            WITH t, r
            MATCH (d:Database {name: $db, run: r.run})
            MERGE (d)-[:HAS_TABLE]->(t)
        """, {"rows": batch, "db": db_node["name"]})
    print("   tables done")

    for batch in chunks(columns, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MERGE (c:Column {id: r.id, run: r.run})
            SET c.name = r.name, c.table = r.table, c.type = r.type,
                c.nullable = r.nullable, c.is_pk = r.is_pk,
                c.description = r.description, c.confidence = r.confidence,
                c.examples = r.examples
            WITH c, r
            MATCH (t:Table {name: r.table, run: r.run})
            MERGE (t)-[:HAS_COLUMN]->(c)
        """, {"rows": batch})
    print("   columns done")

    for batch in chunks(refs, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Column {id: r.from, run: r.run}),
                  (b:Column {id: r.to, run: r.run})
            MERGE (a)-[e:REFERENCES]->(b)
            SET e.source = r.source, e.confidence = r.confidence
        """, {"rows": batch})
    for batch in chunks(joins, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Table {name: r.from, run: r.run}),
                  (b:Table {name: r.to, run: r.run})
            MERGE (a)-[e:JOINS_TO {via: r.via}]->(b)
            SET e.source = r.source, e.confidence = r.confidence
        """, {"rows": batch})
    print("   relationships done")
    cmd_status(args)


def cmd_status(args):
    gid = graph_id(args)
    run = current_run_id()
    out = run_query(gid, """
        MATCH (n {run: $run}) WITH count(n) AS nodes
        OPTIONAL MATCH (:Table {run: $run})-[e]->({run: $run})
        RETURN nodes, count(e) AS edges
    """, {"run": run})
    print(f">> run '{run}':", json.dumps(out.get("results", out),
                                         ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "load", "status", "delete"])
    ap.add_argument("--graph-id", default=None)
    args = ap.parse_args()
    {"create": cmd_create, "load": cmd_load,
     "status": cmd_status, "delete": cmd_delete}[args.command](args)


if __name__ == "__main__":
    main()
