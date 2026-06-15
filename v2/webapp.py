#!/usr/bin/env python3
"""db2doc v2 web app — run list home page + new-DB connection + detail pages.

    ../.venv/bin/uvicorn webapp:app --port 8200
    open http://localhost:8200

Pages
  /                  home: past runs (click into results) + "connect new DB"
  /runs/{run_id}     detail: tree catalog + similarity view (ui.py template)

API
  GET  /api/runs                      run list with status + headline scores
  POST /api/runs                      create a run (DB connection params) and
                                      launch the pipeline in the background
  POST /api/test-connection           validate connection params
  GET  /api/runs/{id}                 run status + log tail
  GET  /api/runs/{id}/artifact/{name} catalog.json / score.json / ...
  DELETE /api/runs/{id}               remove a run directory

Each run executes run.py with V2_OUT_DIR=runs/<id> and PG* env overrides, so
artifacts stay per-run. Scoring (stage 5) only runs for OMOP-truth runs —
arbitrary customer DBs have no ground truth, so they get catalog-only runs.
"""
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config  # noqa: F401  (loads .env)
from ui import render_fetching
from graph_ui import render_graph_page
from home_ui import HOME

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

ARTIFACTS = {"catalog.json", "score.json", "score_details.json",
             "profile.json", "relations.json", "descriptions.json"}

app = FastAPI(title="db2doc v2")


# ------------------------------------------------------------------ models
class ConnectionIn(BaseModel):
    name: str = ""
    host: str
    port: int = 5432
    dbname: str
    user: str
    password: str
    schema_name: str = "public"
    with_truth: bool = False     # OMOP ground-truth scoring (eval runs only)
    no_judge: bool = False


# ------------------------------------------------------------------ helpers
def run_dir(run_id):
    if not re.fullmatch(r"[a-z0-9\-]+", run_id):
        raise HTTPException(400, "bad run id")
    return os.path.join(RUNS_DIR, run_id)


def read_meta(rid):
    p = os.path.join(run_dir(rid), "meta.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def write_meta(rid, meta):
    with open(os.path.join(run_dir(rid), "meta.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def headline(rid):
    """Pull headline numbers from a finished run's artifacts."""
    d = run_dir(rid)
    out = {}
    sp = os.path.join(d, "score.json")
    if os.path.exists(sp):
        with open(sp) as f:
            s = json.load(f)
        dm = s.get("description_match", {})
        out["col_judge"] = dm.get("column", {}).get("judge_accuracy")
        out["tbl_judge"] = dm.get("table", {}).get("judge_accuracy")
        out["pk_f1"] = s.get("relations", {}).get("primary_key_f1", {}).get("f1")
        out["fk_f1"] = s.get("relations", {}).get("foreign_key_f1", {}).get("f1")
        out["s_overall"] = s.get("Soverall")
        out["judge_model"] = (s.get("scoring_methods", {})
                              .get("judge_accuracy", {}).get("model"))
    cp = os.path.join(d, "catalog.json")
    if os.path.exists(cp):
        with open(cp) as f:
            c = json.load(f)
        out["tables"] = len(c.get("tables", []))
        out["columns"] = sum(len(t["columns"]) for t in c.get("tables", []))
        out["domain"] = c.get("database", {}).get("domain")
        out["gen_model"] = c.get("model")
    return out


def launch_pipeline(rid, conn: ConnectionIn):
    """Run run.py as a subprocess with per-run env; track status in meta."""
    d = run_dir(rid)
    env = dict(os.environ)
    env.update({
        "V2_OUT_DIR": d,
        "PGHOST": conn.host, "PGPORT": str(conn.port),
        "PGDATABASE": conn.dbname, "PGUSER": conn.user,
        "PGPASSWORD": conn.password, "PGSCHEMA": conn.schema_name,
    })
    cmd = [sys.executable, os.path.join(HERE, "run.py")]
    if not conn.with_truth:
        cmd.append("--skip-score")
    elif conn.no_judge:
        cmd.append("--no-judge")
    log_path = os.path.join(d, "pipeline.log")

    def worker():
        meta = read_meta(rid)
        with open(log_path, "w") as log:
            p = subprocess.run(cmd, cwd=HERE, env=env,
                               stdout=log, stderr=subprocess.STDOUT)
        meta["status"] = "done" if p.returncode == 0 else "failed"
        meta["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_meta(rid, meta)

    threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ api
@app.post("/api/test-connection")
def test_connection(conn: ConnectionIn):
    import psycopg2
    try:
        c = psycopg2.connect(host=conn.host, port=conn.port,
                             dbname=conn.dbname, user=conn.user,
                             password=conn.password, connect_timeout=8)
        with c.cursor() as cur:
            cur.execute(
                """SELECT count(*) FROM information_schema.tables
                   WHERE table_schema=%s AND table_type='BASE TABLE'""",
                (conn.schema_name,))
            n = cur.fetchone()[0]
        c.close()
        return {"ok": True, "tables": n}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/runs")
def create_run(conn: ConnectionIn):
    rid = (datetime.now().strftime("%Y%m%d-%H%M%S") + "-"
           + uuid.uuid4().hex[:6])
    d = os.path.join(RUNS_DIR, rid)
    os.makedirs(d)
    write_meta(rid, {
        "id": rid,
        "name": conn.name or f"{conn.dbname}@{conn.host}",
        "host": conn.host, "port": conn.port, "dbname": conn.dbname,
        "schema": conn.schema_name, "user": conn.user,
        "with_truth": conn.with_truth,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    launch_pipeline(rid, conn)
    return {"id": rid}


@app.get("/api/runs")
def list_runs():
    runs = []
    for rid in sorted(os.listdir(RUNS_DIR), reverse=True):
        meta = read_meta(rid)
        if meta:
            meta["headline"] = headline(rid)
            meta.pop("password", None)
            runs.append(meta)
    return {"runs": runs}


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    meta = read_meta(rid)
    if not meta:
        raise HTTPException(404)
    meta["headline"] = headline(rid)
    log_path = os.path.join(run_dir(rid), "pipeline.log")
    if os.path.exists(log_path):
        with open(log_path) as f:
            meta["log_tail"] = f.readlines()[-30:]
    return meta


@app.get("/api/runs/{rid}/artifact/{name}")
def get_artifact(rid: str, name: str):
    if name not in ARTIFACTS:
        raise HTTPException(404)
    p = os.path.join(run_dir(rid), name)
    if not os.path.exists(p):
        raise HTTPException(404)
    with open(p) as f:
        return json.load(f)


@app.delete("/api/runs/{rid}")
def delete_run(rid: str):
    import shutil
    d = run_dir(rid)
    if not os.path.exists(d):
        raise HTTPException(404)
    shutil.rmtree(d)
    return {"ok": True}


# ------------------------------------------------------------------ graph
def load_catalog(rid):
    p = os.path.join(run_dir(rid), "catalog.json")
    if not os.path.exists(p):
        raise HTTPException(404, "catalog.json not ready")
    with open(p) as f:
        return json.load(f)


def graph_payload_from_catalog(catalog):
    """tables + join edges (same shape graph.py loads into Neptune)."""
    tables, joins = [], []
    for t in catalog["tables"]:
        pk = (t.get("primary_key") or {}).get("columns", [])
        tables.append({"name": t["name"], "rowcount": t.get("rowcount", 0),
                       "n_columns": len(t["columns"]),
                       "pk": ", ".join(pk),
                       "description": t.get("description", "")})
        for f in t.get("foreign_keys", []):
            parent = f["ref"].split(".", 1)[0]
            joins.append({"from": t["name"], "to": parent,
                          "via": f'{t["name"]}.{f["column"]} = {f["ref"]}',
                          "source": f.get("source", ""),
                          "confidence": f.get("confidence")})
    return tables, joins


def neptune_gid():
    return os.environ.get("NEPTUNE_GRAPH_ID")


def neptune_query(query, parameters=None):
    import graph as G
    return G.run_query(neptune_gid(), query, parameters)


@app.get("/api/runs/{rid}/graph")
def get_graph(rid: str):
    """Graph for visualization. Prefers Neptune; falls back to catalog."""
    gid = neptune_gid()
    if gid:
        try:
            t = neptune_query("""
                MATCH (t:Table) RETURN t.name AS name, t.rowcount AS rowcount,
                       t.n_columns AS n_columns, t.pk AS pk,
                       t.description AS description ORDER BY name""")
            j = neptune_query("""
                MATCH (a:Table)-[e:JOINS_TO]->(b:Table)
                RETURN a.name AS frm, b.name AS to, e.via AS via,
                       e.source AS source, e.confidence AS confidence""")
            return {"source": "neptune", "graph_id": gid,
                    "tables": t["results"],
                    "joins": [{"from": x["frm"], "to": x["to"],
                               "via": x["via"], "source": x["source"],
                               "confidence": x["confidence"]}
                              for x in j["results"]]}
        except Exception:
            pass  # fall through to local
    tables, joins = graph_payload_from_catalog(load_catalog(rid))
    return {"source": "catalog", "graph_id": None,
            "tables": tables, "joins": joins}


@app.get("/api/runs/{rid}/graph/table/{name}")
def get_graph_table(rid: str, name: str):
    catalog = load_catalog(rid)
    t = next((x for x in catalog["tables"] if x["name"] == name), None)
    if not t:
        raise HTTPException(404)
    return {
        "name": name, "description": t.get("description", ""),
        "columns": [{"name": c["name"], "type": c["type"],
                     "is_pk": c["is_pk"], "description": c["description"]}
                    for c in t["columns"]],
        "fks": [{"via": f'{name}.{f["column"]} = {f["ref"]}',
                 "source": f.get("source", "")}
                for f in t.get("foreign_keys", [])],
    }


@app.get("/api/runs/{rid}/graph/paths")
def get_join_paths(rid: str, frm: str, to: str, max_hops: int = 5, k: int = 3):
    """K shortest join paths between two tables — the text2sql planning
    primitive. Neptune openCypher when configured, local BFS fallback.
    Returns paths as alternating [{table},{via},...] lists."""
    gid = neptune_gid()
    if gid:
        try:
            # Neptune Analytics openCypher: no shortestPath()/reduce()-dedup,
            # so over-fetch ordered by length and keep simple paths here.
            res = neptune_query(f"""
                MATCH p = (a:Table {{name: $frm}})-[:JOINS_TO*1..{max_hops}]-(b:Table {{name: $to}})
                RETURN [n IN nodes(p) | n.name] AS names,
                       [e IN relationships(p) | e.via] AS vias
                ORDER BY size(vias) ASC LIMIT 40
            """, {"frm": frm, "to": to})
            paths = []
            for row in res["results"]:
                if len(set(row["names"])) != len(row["names"]):
                    continue  # drop paths revisiting a table
                seq = []
                for i, n in enumerate(row["names"]):
                    seq.append({"table": n})
                    if i < len(row["vias"]):
                        seq.append({"via": row["vias"][i]})
                paths.append(seq)
                if len(paths) >= k:
                    break
            return {"source": "neptune", "paths": paths}
        except Exception:
            pass
    # local BFS over the undirected join graph (k shortest, simple paths)
    tables, joins = graph_payload_from_catalog(load_catalog(rid))
    adj = {}
    for e in joins:
        adj.setdefault(e["from"], []).append((e["to"], e["via"]))
        adj.setdefault(e["to"], []).append((e["from"], e["via"]))
    from collections import deque
    found, q = [], deque([[{"table": frm}]])
    while q and len(found) < k:
        path = q.popleft()
        last = path[-1]["table"]
        if last == to and len(path) > 1:
            found.append(path)
            continue
        if (len(path) - 1) / 2 >= max_hops:
            continue
        seen = {p["table"] for p in path if "table" in p}
        for nxt, via in adj.get(last, []):
            if nxt in seen:
                continue
            q.append(path + [{"via": via}, {"table": nxt}])
    return {"source": "local", "paths": found}


@app.get("/api/runs/{rid}/graph/concepts")
def get_concepts(rid: str):
    """Concept (ontology) layer: prefers Neptune, falls back to the run's
    concepts.json. Returns concepts + IS_A edges + table mappings."""
    gid = neptune_gid()
    if gid:
        try:
            c = neptune_query("""
                MATCH (c:Concept) RETURN c.name AS name, c.name_ko AS name_ko,
                       c.description AS description, c.synonyms AS synonyms,
                       c.confidence AS confidence ORDER BY name""")
            if c["results"]:
                isa = neptune_query("""
                    MATCH (a:Concept)-[:IS_A]->(b:Concept)
                    RETURN a.name AS child, b.name AS parent""")
                maps = neptune_query("""
                    MATCH (c:Concept)-[m:MAPPED_TO]->(t:Table)
                    RETURN c.name AS concept, t.name AS tbl,
                           m.confidence AS confidence""")
                colmaps = neptune_query("""
                    MATCH (c:Concept)-[:MAPPED_TO]->(col:Column)
                    RETURN c.name AS concept, col.id AS col""")
                cols_by = {}
                for x in colmaps["results"]:
                    cols_by.setdefault(x["concept"], []).append(x["col"])
                for r in c["results"]:
                    r["key_columns"] = cols_by.get(r["name"], [])
                return {"source": "neptune",
                        "concepts": c["results"],
                        "is_a": isa["results"],
                        "mappings": [{"concept": m["concept"],
                                      "table": m["tbl"],
                                      "confidence": m["confidence"]}
                                     for m in maps["results"]]}
        except Exception:
            pass
    p = os.path.join(run_dir(rid), "concepts.json")
    if not os.path.exists(p):
        return {"source": "none", "concepts": [], "is_a": [], "mappings": []}
    with open(p) as f:
        data = json.load(f)
    concepts, isa, maps = [], [], []
    for c in data["concepts"]:
        concepts.append({"name": c["name"], "name_ko": c["name_ko"],
                         "description": c["description"],
                         "synonyms": ", ".join(c["synonyms"]),
                         "confidence": c.get("confidence"),
                         "key_columns": c.get("key_columns", [])})
        if c.get("is_a"):
            isa.append({"child": c["name"], "parent": c["is_a"]})
        for t in c["tables"]:
            maps.append({"concept": c["name"], "table": t,
                         "confidence": c.get("confidence")})
    return {"source": "local", "concepts": concepts, "is_a": isa,
            "mappings": maps}


# ------------------------------------------------------------------ pages
@app.get("/runs/{rid}", response_class=HTMLResponse)
def run_page(rid: str):
    if not read_meta(rid):
        raise HTTPException(404)
    return render_fetching(rid)


@app.get("/runs/{rid}/graph", response_class=HTMLResponse)
def graph_page(rid: str):
    if not read_meta(rid):
        raise HTTPException(404)
    return render_graph_page(rid)


@app.get("/", response_class=HTMLResponse)
def home():
    return HOME
