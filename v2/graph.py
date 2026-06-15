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


def graph_id(args):
    gid = getattr(args, "graph_id", None) or cfg("NEPTUNE_GRAPH_ID")
    if not gid:
        # fall back to the first available graph with our name
        for g in client().list_graphs()["graphs"]:
            if g["name"] == GRAPH_NAME and g["status"] == "AVAILABLE":
                return g["id"]
        raise SystemExit("no graph: set NEPTUNE_GRAPH_ID or run "
                         "`graph.py create` first")
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


def cmd_load(args):
    gid = graph_id(args)
    catalog = load_json(out_path("catalog.json"))
    db_node, tables, columns, refs, joins = build_payload(catalog)
    print(f">> loading into {gid}: {len(tables)} tables, "
          f"{len(columns)} columns, {len(refs)} FK refs")

    run_query(gid, """
        MERGE (d:Database {name: $name})
        SET d.domain = $domain, d.description = $description
    """, db_node)

    for batch in chunks(tables, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MERGE (t:Table {name: r.name})
            SET t.description = r.description, t.rowcount = r.rowcount,
                t.n_columns = r.n_columns, t.pk = r.pk
            WITH t
            MATCH (d:Database {name: $db})
            MERGE (d)-[:HAS_TABLE]->(t)
        """, {"rows": batch, "db": db_node["name"]})
    print("   tables done")

    for batch in chunks(columns, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MERGE (c:Column {id: r.id})
            SET c.name = r.name, c.table = r.table, c.type = r.type,
                c.nullable = r.nullable, c.is_pk = r.is_pk,
                c.description = r.description, c.confidence = r.confidence,
                c.examples = r.examples
            WITH c, r
            MATCH (t:Table {name: r.table})
            MERGE (t)-[:HAS_COLUMN]->(c)
        """, {"rows": batch})
    print("   columns done")

    for batch in chunks(refs, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Column {id: r.from}), (b:Column {id: r.to})
            MERGE (a)-[e:REFERENCES]->(b)
            SET e.source = r.source, e.confidence = r.confidence
        """, {"rows": batch})
    for batch in chunks(joins, 50):
        run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Table {name: r.from}), (b:Table {name: r.to})
            MERGE (a)-[e:JOINS_TO {via: r.via}]->(b)
            SET e.source = r.source, e.confidence = r.confidence
        """, {"rows": batch})
    print("   relationships done")
    cmd_status(args)


def cmd_status(args):
    gid = graph_id(args)
    out = run_query(gid, """
        MATCH (n) WITH count(n) AS nodes
        MATCH ()-[e]->() RETURN nodes, count(e) AS edges
    """)
    print(">>", json.dumps(out.get("results", out), ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "load", "status", "delete"])
    ap.add_argument("--graph-id", default=None)
    args = ap.parse_args()
    {"create": cmd_create, "load": cmd_load,
     "status": cmd_status, "delete": cmd_delete}[args.command](args)


if __name__ == "__main__":
    main()
