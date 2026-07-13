#!/usr/bin/env python3
"""text2sql over the generated catalog — LangGraph pipeline.

The whole point: show that the ontology / graph-RAG / metadata this solution
produced is enough to answer natural-language questions in SQL. The graph
wires our three retrieval substrates together:

  retrieve  — OpenSearch vector search over column/table descriptions
              (metadata RAG; finds relevant schema elements semantically,
              works even when wording isn't in the concept synonyms, and
              scales to thousands of tables where the full schema can't fit
              a context window)
  expand    — Neptune openCypher: from the retrieved tables, pull PK/FK and
              shortest JOIN paths (the ontology/graph gives join structure
              the vector search alone can't)
  generate  — LLM writes PostgreSQL using ONLY the retrieved+expanded schema
              context (table/column descriptions, keys, join conditions)
  execute   — run read-only on RDS (SELECT only, auto-LIMIT), preview rows
  repair    — on SQL error, feed the message back and regenerate (bounded
              self-correction; the loop is gated on a real DB error, not on
              free-form self-review)

run_text2sql(question, rid) yields step dicts for the UI; the final dict has
the answer. CLI: `python text2sql.py "환자별 처방 의사 목록"`
"""
import json
import os
import re
import sys

from config import claude_json, connect, PGSCHEMA, qident, cfg

MAX_REPAIRS = 2
ROW_LIMIT = 50


# --------------------------------------------------------------- run context
def _gid(rid):
    """This run's dedicated Neptune graph id, from the metastore."""
    try:
        from store import db as sdb, repo as srepo
        if sdb.enabled():
            return srepo.run_graph_id(rid)
    except Exception:
        pass
    return cfg("NEPTUNE_GRAPH_ID")   # legacy fallback


# ------------------------------------------------------------- concept layer
def match_concepts(question, rid):
    """Ontology path: match question terms to Concept nodes (by name/Korean
    name/synonym), expand IS_A children, and return the tables they MAP_TO.

    This is the structural counterpart to vector search: it catches abstract
    parent terms (e.g. '임상 이벤트' → all of condition/drug/measurement/...)
    that semantic search over individual columns would miss, and it uses the
    curated synonyms. Returns {} (no-op) if Neptune/concepts are unavailable.
    """
    gid = _gid(rid)
    if not gid:
        return {"matched": [], "tables": []}
    import graph as G
    run = rid
    try:
        rows = G.run_query(gid, """
            MATCH (c:Concept {run: $run})
            RETURN c.name AS name, c.name_ko AS name_ko,
                   c.synonyms AS synonyms
        """, {"run": run})["results"]
    except Exception:
        return {"matched": [], "tables": []}

    q = question.lower()
    matched = []
    for c in rows:
        terms = [c.get("name") or "", c.get("name_ko") or ""]
        terms += [s.strip() for s in (c.get("synonyms") or "").split(",")]
        for t in terms:
            t = t.strip()
            if len(t) >= 2 and t.lower() in q:
                matched.append(c["name"])
                break
    if not matched:
        return {"matched": [], "tables": []}

    # expand to descendants via IS_A (abstract parent -> concrete children)
    # and collect tables mapped to matched + descendant concepts
    try:
        res = G.run_query(gid, """
            UNWIND $names AS cn
            MATCH (c:Concept {name: cn, run: $run})
            OPTIONAL MATCH (d:Concept {run: $run})-[:IS_A*1..3]->(c)
            WITH collect(DISTINCT c) + collect(DISTINCT d) AS cs
            UNWIND cs AS cc
            MATCH (cc)-[:MAPPED_TO]->(t:Table {run: $run})
            RETURN DISTINCT cc.name AS concept, t.name AS tbl
        """, {"names": matched, "run": run})["results"]
    except Exception:
        return {"matched": matched, "tables": []}
    tables, seen = [], set()
    pairs = []
    for r in res:
        pairs.append({"concept": r["concept"], "table": r["tbl"]})
        if r["tbl"] not in seen:
            seen.add(r["tbl"])
            tables.append(r["tbl"])
    return {"matched": matched, "tables": tables, "mappings": pairs}


# ----------------------------------------------------------------- retrieve
def retrieve(question, rid, k=14):
    """Hybrid metadata RAG: semantic vector search (OpenSearch) UNION
    ontology concept matching (Neptune). Vector search finds columns by
    meaning; the concept layer adds tables reachable through matched
    business terms and their IS_A hierarchy. Vector hits lead (ranked),
    concept-only tables are appended."""
    import metasearch
    hits = metasearch.search(question, k=k, rid=rid)
    tables, seen = [], set()
    for h in hits:
        t = h["table"]
        if t and t not in seen:
            seen.add(t)
            tables.append(t)

    concepts = match_concepts(question, rid)
    concept_added = []
    for t in concepts.get("tables", []):
        if t not in seen:
            seen.add(t)
            tables.append(t)
            concept_added.append(t)

    return {"hits": hits, "tables": tables,
            "concepts": {"matched": concepts.get("matched", []),
                         "mappings": concepts.get("mappings", []),
                         "added_tables": concept_added}}


# ----------------------------------------------------------------- expand
def expand(tables, rid):
    """Graph RAG: pull keys, FK edges, and pairwise shortest join paths from
    Neptune for the retrieved tables. Falls back to the metastore catalog if
    Neptune is unset."""
    gid = _gid(rid)
    if gid and tables:
        try:
            return _expand_neptune(gid, tables, rid)
        except Exception:
            pass
    return _expand_catalog(tables, rid)


def _expand_neptune(gid, tables, run):
    import graph as G
    tl = list(tables)
    cols = G.run_query(gid, """
        UNWIND $tbls AS tn
        MATCH (t:Table {name: tn, run: $run})-[:HAS_COLUMN]->(c:Column {run: $run})
        RETURN t.name AS tbl, c.name AS col, c.type AS type,
               c.is_pk AS is_pk, c.description AS description
        ORDER BY tbl, col
    """, {"tbls": tl, "run": run})
    if not cols["results"]:
        raise RuntimeError("run not loaded in Neptune")  # → catalog fallback
    fks = G.run_query(gid, """
        UNWIND $tbls AS tn
        MATCH (a:Table {name: tn, run: $run})-[e:JOINS_TO]->(b:Table {run: $run})
        RETURN a.name AS frm, b.name AS to, e.via AS via,
               e.source AS source, e.confidence AS confidence
    """, {"tbls": tl, "run": run})
    # shortest join paths between each retrieved table pair
    paths = []
    for i in range(len(tl)):
        for j in range(i + 1, len(tl)):
            p = G.run_query(gid, """
                MATCH p = (a:Table {name:$a, run:$run})
                          -[:JOINS_TO*1..4]-(b:Table {name:$b, run:$run})
                RETURN [n IN nodes(p) | n.name] AS names,
                       [e IN relationships(p) | e.via] AS vias
                ORDER BY size(vias) ASC LIMIT 6
            """, {"a": tl[i], "b": tl[j], "run": run})
            for row in p["results"]:
                if len(set(row["names"])) == len(row["names"]):
                    paths.append({"tables": row["names"], "vias": row["vias"]})
                    break
    return {"columns": cols["results"],
            "fks": [{"from": f["frm"], "to": f["to"], "via": f["via"],
                     "source": f["source"], "confidence": f["confidence"]}
                    for f in fks["results"]],
            "paths": paths, "source": "neptune"}


def _expand_catalog(tables, rid):
    from store import repo as srepo
    cat = srepo.load_run(rid)
    if not cat:
        return {"columns": [], "fks": [], "paths": [], "source": "none"}
    tset = set(tables)
    cols, fks = [], []
    for t in cat["tables"]:
        if t["name"] not in tset:
            continue
        for c in t["columns"]:
            cols.append({"tbl": t["name"], "col": c["name"], "type": c["type"],
                         "is_pk": c["is_pk"], "description": c["description"]})
        for f in t.get("foreign_keys", []):
            fks.append({"from": t["name"], "to": f["ref"].split(".")[0],
                        "via": f'{t["name"]}.{f["column"]} = {f["ref"]}',
                        "source": f["source"], "confidence": f.get("confidence")})
    return {"columns": cols, "fks": fks, "paths": [], "source": "catalog"}


# ----------------------------------------------------------------- generate
SQL_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string",
                      "description": "어떤 테이블/컬럼/조인을 왜 골랐는지 한국어로 간단히."},
        "sql": {"type": "string",
                "description": "PostgreSQL 쿼리 (스키마 접두사 cdm. 포함, 단일 SELECT)."},
    },
    "required": ["reasoning", "sql"],
}

GEN_SYSTEM = (
    "You are a PostgreSQL expert generating a query for an OMOP CDM database. "
    "Use ONLY the tables/columns given in the schema context — never invent "
    "names. Schema is '{schema}'; qualify tables as {schema}.<table>. "
    "Prefer the provided join paths for multi-table queries. Output a single "
    "read-only SELECT (no DDL/DML). If the question implies a limit, respect "
    "it; otherwise the system appends a LIMIT. Put a short Korean reasoning "
    "in `reasoning`. If `verified_examples` is present, they are question→SQL "
    "pairs already EXECUTED successfully on this very database — follow their "
    "table/join conventions."
)


def _fewshot(rid, k=3):
    """Top-k verified queries for THIS run (rid-scoped; no cross-run leak).
    Returns [] when the metastore is unset or the run has none."""
    try:
        from store import db as sdb, repo as srepo
        if not sdb.enabled():
            return []
        vq = srepo.get_verified_queries(rid, ok_only=True)
        return [{"question": v["question"], "sql": v["sql"]}
                for v in vq[:k]]
    except Exception:
        return []


def _schema_context(retrieved, expanded):
    cols_by_t = {}
    for c in expanded["columns"]:
        cols_by_t.setdefault(c["tbl"], []).append(c)
    tables = []
    for t in retrieved["tables"]:
        cols = cols_by_t.get(t, [])
        tables.append({
            "table": t,
            "columns": [{"name": c["col"], "type": c["type"],
                         "pk": c["is_pk"],
                         "desc": (c["description"] or "")[:120]}
                        for c in cols],
        })
    return {
        "tables": tables,
        "join_paths": [" → ".join(p["tables"]) + "  ON  " + "; ".join(p["vias"])
                       for p in expanded["paths"]],
        "foreign_keys": [f["via"] for f in expanded["fks"]],
    }


def run_schema(rid):
    """This run's actual schema — from the metastore, NOT the global PGSCHEMA
    env (which defaults to 'cdm' and would mis-qualify other runs)."""
    try:
        from store import repo as srepo
        cat = srepo.load_run(rid)
        if cat and cat.get("schema"):
            return cat["schema"]
    except Exception:
        pass
    return PGSCHEMA


def generate(question, retrieved, expanded, rid, prior_error=None,
             prior_sql=None, examples=None):
    ctx = _schema_context(retrieved, expanded)
    payload = {"question": question, "schema_context": ctx}
    if examples:
        payload["verified_examples"] = examples
    if prior_error:
        payload["previous_sql"] = prior_sql
        payload["previous_error"] = prior_error
        payload["instruction"] = ("이전 SQL이 아래 오류로 실패했습니다. "
                                  "오류를 고쳐 다시 작성하세요.")
    obj, _ = claude_json(
        "다음 질문에 답하는 SQL을 작성하세요.\n\n"
        + json.dumps(payload, ensure_ascii=False),
        SQL_SCHEMA, system=GEN_SYSTEM.format(schema=run_schema(rid)),
        max_tokens=2048)
    return obj


# ----------------------------------------------------------------- execute
_WRITE = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|"
                    r"grant|revoke|copy|merge)\b", re.I)


def _guard_and_limit(sql):
    s = sql.strip().rstrip(";")
    if _WRITE.search(s):
        raise ValueError("쓰기/DDL 구문은 허용되지 않습니다 (읽기 전용).")
    if not re.match(r"(?is)^\s*(with|select)\b", s):
        raise ValueError("SELECT 쿼리만 허용됩니다.")
    if not re.search(r"(?is)\blimit\s+\d+\s*$", s):
        s += f" LIMIT {ROW_LIMIT}"
    return s


def execute(sql):
    safe = _guard_and_limit(sql)
    conn = connect()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 15000")  # 15s
            cur.execute(safe)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return {"ok": True, "executed_sql": safe, "columns": cols,
                "rows": [[_cell(v) for v in r] for r in rows],
                "rowcount": len(rows)}
    except Exception as e:
        return {"ok": False, "executed_sql": safe, "error": str(e).strip()}
    finally:
        conn.close()


def _cell(v):
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


# ----------------------------------------------------------------- graph
def build_graph():
    """LangGraph StateGraph: retrieve → expand → generate → execute
    → (repair → execute)*."""
    from langgraph.graph import StateGraph, END
    from typing import TypedDict, Any

    class S(TypedDict, total=False):
        question: str
        rid: str
        retrieved: Any
        expanded: Any
        gen: Any
        result: Any
        attempts: int
        steps: list
        fewshot: Any          # verified-query examples, fetched once

    def n_retrieve(s):
        r = retrieve(s["question"], s["rid"])
        hits = r["hits"]
        # sub-stage breakdown for the UI
        vec_tables, vseen = [], set()
        for h in hits:
            if h["table"] and h["table"] not in vseen:
                vseen.add(h["table"])
                vec_tables.append(h["table"])
        r["substages"] = {
            "vector": {
                "engine": "OpenSearch Serverless (벡터)",
                "n_hits": len(hits),
                "n_table_hits": sum(1 for h in hits if h["kind"] == "table"),
                "n_column_hits": sum(1 for h in hits if h["kind"] == "column"),
                "tables_from_vector": vec_tables,
            },
            "concept": {
                "engine": "Neptune 개념 레이어 (온톨로지)",
                "matched": r["concepts"]["matched"],
                "added_tables": r["concepts"]["added_tables"],
            },
            "merge": {
                "final_tables": r["tables"],
                "n_final": len(r["tables"]),
            },
        }
        return {"retrieved": r,
                "steps": s.get("steps", []) + [{"step": "retrieve", "data": r}]}

    def n_expand(s):
        e = expand(s["retrieved"]["tables"], s["rid"])
        # per-table column counts so the UI can show what was pulled
        cols_by_t = {}
        for c in e["columns"]:
            cols_by_t.setdefault(c["tbl"], 0)
            cols_by_t[c["tbl"]] += 1
        return {"expanded": e,
                "steps": s["steps"] + [{"step": "expand", "data": {
                    "tables": s["retrieved"]["tables"],
                    "source": e["source"],
                    "n_columns": len(e["columns"]),
                    "columns_per_table": cols_by_t,
                    "fk_count": len(e["fks"]),
                    "fks": e["fks"][:30],
                    "join_paths": e["paths"]}}]}

    def n_generate(s):
        prior = s.get("result") or {}
        # fetch few-shot once per question; repair re-entries reuse the same
        # set so the examples don't shift between attempts
        fewshot = s.get("fewshot")
        if fewshot is None:
            fewshot = _fewshot(s["rid"])
        gen = generate(s["question"], s["retrieved"], s["expanded"], s["rid"],
                       prior_error=prior.get("error"),
                       prior_sql=prior.get("executed_sql"),
                       examples=fewshot or None)
        return {"gen": gen, "fewshot": fewshot,
                "steps": s["steps"] + [{"step": "generate", "data": gen,
                    "repair": s.get("attempts", 0) > 0,
                    "fewshot_used": len(fewshot or [])}]}

    def n_execute(s):
        res = execute(s["gen"]["sql"])
        return {"result": res, "attempts": s.get("attempts", 0) + 1,
                "steps": s["steps"] + [{"step": "execute", "data": res}]}

    def route(s):
        if s["result"]["ok"] or s["attempts"] > MAX_REPAIRS:
            return END
        return "generate"

    g = StateGraph(S)
    for name, fn in [("retrieve", n_retrieve), ("expand", n_expand),
                     ("generate", n_generate), ("execute", n_execute)]:
        g.add_node(name, fn)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "expand")
    g.add_edge("expand", "generate")
    g.add_edge("generate", "execute")
    g.add_conditional_edges("execute", route, {END: END, "generate": "generate"})
    return g.compile()


_GRAPH = None


def run_text2sql(question, rid=None):
    """Run the pipeline; return the final state dict (steps + result)."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    out = _GRAPH.invoke(
        {"question": question, "rid": rid or "default",
         "steps": [], "attempts": 0},
        {"recursion_limit": 25})
    return {"question": question, "steps": out["steps"],
            "result": out.get("result"), "sql": out.get("gen", {}).get("sql"),
            "reasoning": out.get("gen", {}).get("reasoning"),
            "attempts": out.get("attempts", 0)}


def main():
    # usage: text2sql.py [--rid RUN_KEY] "<question>"
    args = sys.argv[1:]
    rid = None
    if "--rid" in args:
        i = args.index("--rid")
        rid = args[i + 1]
        del args[i:i + 2]
    q = " ".join(args) or "각 환자가 받은 처방 약물 수를 환자별로 세기"
    out = run_text2sql(q, rid=rid)
    for st in out["steps"]:
        print(f"\n=== {st['step']} ===")
        d = st["data"]
        if st["step"] == "retrieve":
            print("  tables:", d["tables"])
        elif st["step"] == "expand":
            print("  join_paths:", d["join_paths"][:3])
        elif st["step"] == "generate":
            print("  sql:", d["sql"])
        elif st["step"] == "execute":
            if d["ok"]:
                print("  OK rows:", d["rowcount"], "| cols:", d["columns"])
                for r in d["rows"][:5]:
                    print("   ", r)
            else:
                print("  ERROR:", d["error"][:200])
    print(f"\n>> attempts: {out['attempts']}, final ok:",
          out["result"]["ok"] if out["result"] else None)


if __name__ == "__main__":
    main()
