#!/usr/bin/env python3
"""db2doc v2 web app — run list home page + new-DB connection + detail pages.

    ../.venv/bin/uvicorn webapp:app --port 8200
    open http://localhost:8200

Storage: the MySQL metastore is the single source of truth. The pipeline runs
in-process (a background thread, chaining stages in memory) and persists ONLY
to MySQL (catalog/descriptions/concepts) + Neptune (schema graph) + OpenSearch
(metadata RAG). No per-run JSON artifacts are written to disk.

Pages
  /                  home: past runs (click into results) + "connect new DB"
  /runs/{run_id}     detail: tree catalog + similarity view (ui.py template)

API
  GET  /api/runs                      run list with status + headline scores
  POST /api/runs                      create a run and launch the pipeline
  POST /api/test-connection           validate connection params
  GET  /api/runs/{id}                 run status
  GET  /api/runs/{id}/artifact/{name} catalog (from DB)
  DELETE /api/runs/{id}               remove a run (+ its Neptune graph)
"""
import os
import re
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
from t2sql_ui import render_t2sql_page
from store import db as sdb, repo as srepo

HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="db2doc v2")

# pipeline runs in-process; serialize so concurrent runs don't thrash Bedrock /
# the single target connection. Each run still gets its own metastore row.
_run_lock = threading.Lock()


def _require_store():
    if not sdb.enabled():
        raise HTTPException(503, "metastore not configured (set METASTORE_* "
                                 "in .env) — this build stores results in MySQL")
    sdb.init_db()


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


# ------------------------------------------------------------------ pipeline
def launch_pipeline(rid, conn: ConnectionIn):
    """Run the in-memory pipeline in a background thread with per-run env."""
    def worker():
        with _run_lock:
            env_keys = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER",
                        "PGPASSWORD", "PGSCHEMA", "V2_USE_COMMENTS")
            saved = {k: os.environ.get(k) for k in env_keys}
            os.environ.update({
                "PGHOST": conn.host, "PGPORT": str(conn.port),
                "PGDATABASE": conn.dbname, "PGUSER": conn.user,
                "PGPASSWORD": conn.password, "PGSCHEMA": conn.schema_name,
                # Customer mode (default): use existing COMMENTs as hints.
                # Eval mode (with_truth): stay blind so the OMOP benchmark
                # measures pure inference.
                "V2_USE_COMMENTS": "0" if conn.with_truth else "1",
            })
            try:
                import importlib
                import config as _cfg
                importlib.reload(_cfg)        # pick up the env override
                import pipeline
                importlib.reload(pipeline)
                pipeline.run_pipeline(
                    rid, name=conn.name or f"{conn.dbname}@{conn.host}",
                    with_truth=conn.with_truth,
                    meta_extra={"host": conn.host, "port": conn.port,
                                "dbname": conn.dbname})
            except Exception as e:
                srepo.set_status(rid, "failed", error=str(e)[:2000])
                print(f"[pipeline] run {rid} failed: {e}")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

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
    _require_store()
    rid = (datetime.now().strftime("%Y%m%d-%H%M%S") + "-"
           + uuid.uuid4().hex[:6])
    srepo.create_run(rid, {
        "name": conn.name or f"{conn.dbname}@{conn.host}",
        "host": conn.host, "port": conn.port, "dbname": conn.dbname,
        "schema": conn.schema_name, "with_truth": conn.with_truth,
        "status": "running",
    })
    launch_pipeline(rid, conn)
    return {"id": rid}


@app.get("/api/runs")
def list_runs():
    _require_store()
    return {"runs": srepo.list_runs()}


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    _require_store()
    meta = srepo.get_run(rid)
    if not meta:
        raise HTTPException(404)
    return meta


@app.get("/api/runs/{rid}/artifact/{name}")
def get_artifact(rid: str, name: str):
    """The viewer fetches 'catalog.json'; we serve it from the metastore.
    Score artifacts exist only for eval runs (with_truth) — null otherwise."""
    _require_store()
    if name == "catalog.json":
        cat = srepo.load_run(rid)
        if not cat:
            raise HTTPException(404)
        return cat
    if name in ("score.json", "score_details.json"):
        return JSONResponse(srepo.get_artifact(rid, name))
    raise HTTPException(404)


class DescEdit(BaseModel):
    table: str
    column: str | None = None          # None → table-level description
    description: str


@app.patch("/api/runs/{rid}/catalog/description")
def edit_description(rid: str, e: DescEdit):
    """Human review: overwrite a generated description, keep the AI original,
    and append an audit row — all in the metastore."""
    _require_store()
    if not srepo.get_run(rid):
        raise HTTPException(404)
    try:
        srepo.edit_description(rid, e.table, e.column, e.description)
    except KeyError:
        raise HTTPException(404)
    target = ("__db__" if e.table == "__db__"
              else f"{e.table}.{e.column}" if e.column else e.table)
    return {"ok": True, "target": target, "description": e.description}


@app.delete("/api/runs/{rid}")
def delete_run(rid: str):
    _require_store()
    meta = srepo.get_run(rid)
    if not meta:
        raise HTTPException(404)
    # delete this run's dedicated Neptune graph too (per-graph billing!)
    gid = meta.get("graph_id")
    graph_deleted = None
    if gid:
        try:
            import graph as G
            G.client().delete_graph(graphIdentifier=gid, skipSnapshot=True)
            graph_deleted = gid
        except Exception as e:
            graph_deleted = f"failed: {e}"
    srepo.delete_run(rid)
    return {"ok": True, "graph_deleted": graph_deleted}


# ------------------------------------------------------------------ graph
def load_catalog(rid):
    cat = srepo.load_run(rid)
    if not cat:
        raise HTTPException(404, "catalog not ready")
    return cat


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


def neptune_gid(rid):
    """This run's dedicated graph id (from the metastore)."""
    return srepo.run_graph_id(rid) or os.environ.get("NEPTUNE_GRAPH_ID")


def neptune_query(gid, query, parameters=None):
    import graph as G
    return G.run_query(gid, query, parameters)


@app.get("/api/runs/{rid}/graph")
def get_graph(rid: str):
    """Graph for visualization, scoped to THIS run. Prefers Neptune (run-
    namespaced nodes), falls back to the metastore catalog."""
    _require_store()
    gid = neptune_gid(rid)
    if gid:
        try:
            t = neptune_query(gid, """
                MATCH (t:Table {run: $rid})
                RETURN t.name AS name, t.rowcount AS rowcount,
                       t.n_columns AS n_columns, t.pk AS pk,
                       t.description AS description ORDER BY name""",
                {"rid": rid})
            if t["results"]:        # this run is loaded in Neptune
                j = neptune_query(gid, """
                    MATCH (a:Table {run: $rid})-[e:JOINS_TO]->(b:Table {run: $rid})
                    RETURN a.name AS frm, b.name AS to, e.via AS via,
                           e.source AS source, e.confidence AS confidence""",
                    {"rid": rid})
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
    _require_store()
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
    _require_store()
    gid = neptune_gid(rid)
    if gid:
        try:
            # Neptune Analytics openCypher: no shortestPath()/reduce()-dedup,
            # so over-fetch ordered by length and keep simple paths here.
            res = neptune_query(gid, f"""
                MATCH p = (a:Table {{name: $frm, run: $rid}})
                          -[:JOINS_TO*1..{max_hops}]-
                          (b:Table {{name: $to, run: $rid}})
                RETURN [n IN nodes(p) | n.name] AS names,
                       [e IN relationships(p) | e.via] AS vias
                ORDER BY size(vias) ASC LIMIT 40
            """, {"frm": frm, "to": to, "rid": rid})
            if res["results"]:
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
    """Concept (ontology) layer: prefers Neptune, falls back to the metastore.
    Returns concepts + IS_A edges + table mappings."""
    _require_store()
    gid = neptune_gid(rid)
    if gid:
        try:
            c = neptune_query(gid, """
                MATCH (c:Concept {run: $rid})
                RETURN c.name AS name, c.name_ko AS name_ko,
                       c.description AS description, c.synonyms AS synonyms,
                       c.confidence AS confidence ORDER BY name""", {"rid": rid})
            if c["results"]:
                isa = neptune_query(gid, """
                    MATCH (a:Concept {run: $rid})-[:IS_A]->(b:Concept {run: $rid})
                    RETURN a.name AS child, b.name AS parent""", {"rid": rid})
                maps = neptune_query(gid, """
                    MATCH (c:Concept {run: $rid})-[m:MAPPED_TO]->(t:Table {run: $rid})
                    RETURN c.name AS concept, t.name AS tbl,
                           m.confidence AS confidence""", {"rid": rid})
                colmaps = neptune_query(gid, """
                    MATCH (c:Concept {run: $rid})-[:MAPPED_TO]->(col:Column {run: $rid})
                    RETURN c.name AS concept, col.id AS col""", {"rid": rid})
                rels = neptune_query(gid, """
                    MATCH (a:Concept {run: $rid})-[r:REL]->(b:Concept {run: $rid})
                    RETURN a.name AS src, b.name AS dst, r.name AS name,
                           r.cardinality AS cardinality, r.via AS via,
                           r.confidence AS confidence""", {"rid": rid})
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
                                     for m in maps["results"]],
                        "relations": rels["results"]}
        except Exception:
            pass
    data = srepo.load_concepts(rid)
    if not data or not data["concepts"]:
        return {"source": "none", "concepts": [], "is_a": [],
                "mappings": [], "relations": []}
    return {"source": "metastore", **data}


# ------------------------------------------------------------------ pages
@app.get("/runs/{rid}", response_class=HTMLResponse)
def run_page(rid: str):
    if not srepo.get_run(rid):
        raise HTTPException(404)
    return render_fetching(rid)


@app.get("/runs/{rid}/graph", response_class=HTMLResponse)
def graph_page(rid: str):
    if not srepo.get_run(rid):
        raise HTTPException(404)
    return render_graph_page(rid)


@app.get("/runs/{rid}/text2sql", response_class=HTMLResponse)
def t2sql_page(rid: str):
    if not srepo.get_run(rid):
        raise HTTPException(404)
    return render_t2sql_page(rid)


class QuestionIn(BaseModel):
    question: str


@app.post("/api/runs/{rid}/text2sql")
def run_t2sql(rid: str, q: QuestionIn):
    _require_store()
    if not srepo.get_run(rid):
        raise HTTPException(404)
    import text2sql
    try:
        out = text2sql.run_text2sql(q.question, rid=rid)
    except Exception as e:
        raise HTTPException(500, f"text2sql failed: {e}")
    # persist a compact history entry (full steps kept for replay)
    res = out.get("result") or {}
    exec_step = next((s for s in reversed(out.get("steps", []))
                      if s["step"] == "execute"), None)
    ed = exec_step["data"] if exec_step else {}
    srepo.add_t2sql_history(rid, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": q.question,
        "ok": bool(res.get("ok")),
        "rowcount": ed.get("rowcount"),
        "attempts": out.get("attempts"),
        "sql": out.get("sql"),
        "steps": out.get("steps"),       # full detail for "이력에서 다시 보기"
    })
    return out


@app.get("/api/runs/{rid}/text2sql/verified")
def t2sql_verified(rid: str):
    """Competency questions verified by execution on this run's DB.
    The UI uses these as example questions (✓ 검증됨)."""
    _require_store()
    if not srepo.get_run(rid):
        raise HTTPException(404)
    return {"verified": srepo.get_verified_queries(rid, ok_only=True)}


@app.get("/api/runs/{rid}/text2sql/history")
def t2sql_history(rid: str):
    _require_store()
    if not srepo.get_run(rid):
        raise HTTPException(404)
    return {"history": srepo.get_t2sql_history(rid)}


@app.delete("/api/runs/{rid}/text2sql/history")
def t2sql_history_clear(rid: str):
    _require_store()
    if not srepo.get_run(rid):
        raise HTTPException(404)
    srepo.clear_t2sql_history(rid)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home():
    return HOME
