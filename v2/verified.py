#!/usr/bin/env python3
"""Stage 8 — Verified queries (competency questions).

Generates representative business questions from the catalog + concept
layer, runs each through the full text2sql pipeline against the live DB,
and stores the ones that actually executed (ok=True) as VERIFIED queries.

Two payoffs:
  - proof: the ontology/catalog demonstrably answers real questions
    (OntoForge-style "this answer really comes from the graph")
  - accuracy: verified pairs become rid-scoped few-shot examples for later
    text2sql generations (text2sql._fewshot).

Self-reference is avoided by clearing this run's verified queries FIRST, so
the generation pass always runs with an empty few-shot set (deterministic).
"""
import json

from config import claude_json
from store import repo as srepo

N_QUESTIONS = 8

VQ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Representative business questions in Korean.",
        }
    },
    "required": ["questions"],
}

VQ_SYSTEM = (
    "You are validating a data catalog by asking it questions. Given the "
    "tables of one database (with descriptions and row counts) and its "
    "business-concept layer, write the questions a domain user would "
    "actually ask this data. Derive questions ONLY from the given catalog; "
    "do not assume any particular product, schema, or industry.\n"
    "Rules:\n"
    f"- Exactly {N_QUESTIONS} questions, in natural Korean.\n"
    "- Mix difficulty: a few single-table aggregations, several 2-table "
    "joins, one or two 3-table joins. Use the concept relations as join "
    "hints.\n"
    "- Every question must be answerable from the given tables/columns — "
    "no external knowledge, no data the schema cannot hold.\n"
    "- Prefer tables with rows > 0.\n"
    "- Questions must be self-contained (no '위 질문에 이어서')."
)


def _compact(catalog, concepts_dict):
    tables = [{"table": t["name"], "rows": t.get("rowcount", 0),
               "description": (t.get("description") or "")[:150]}
              for t in catalog["tables"]]
    concepts = [{"name": c["name"], "name_ko": c.get("name_ko"),
                 "tables": c.get("tables") or []}
                for c in (concepts_dict or {}).get("concepts", [])]
    relations = [{"src": r["src"], "name": r["name"], "dst": r["dst"],
                  "via": r.get("via")}
                 for r in (concepts_dict or {}).get("relations", [])]
    return {"tables": tables, "concepts": concepts,
            "concept_relations": relations}


def generate_questions(catalog, concepts_dict):
    payload = _compact(catalog, concepts_dict)
    obj, _ = claude_json(
        "Write the representative business questions for this database.\n\n"
        + json.dumps(payload, ensure_ascii=False),
        VQ_SCHEMA, system=VQ_SYSTEM, max_tokens=2048)
    return [q.strip() for q in obj.get("questions", []) if q.strip()]


def build_verified(rid, catalog, concepts_dict):
    """Generate → execute → store verified queries for one run.

    Returns (n_ok, n_total). Clears previous verified queries first so the
    generation pass never sees its own output as few-shot."""
    import text2sql

    srepo.clear_verified_queries(rid)   # deterministic empty few-shot
    questions = generate_questions(catalog, concepts_dict)
    print(f"   {len(questions)} candidate questions")

    n_ok = 0
    for i, q in enumerate(questions, 1):
        try:
            out = text2sql.run_text2sql(q, rid=rid)
            res = out.get("result") or {}
            ok = bool(res.get("ok"))
        except Exception as e:
            print(f"   [{i}/{len(questions)}] ERROR {e!s:.60} | {q[:40]}")
            continue
        if ok:
            srepo.add_verified_query(rid, {
                "question": q, "sql": out.get("sql"),
                "rowcount": res.get("rowcount"), "ok": True})
            n_ok += 1
        print(f"   [{i}/{len(questions)}] {'ok' if ok else 'FAIL'} "
              f"rows={res.get('rowcount')} | {q[:40]}")
    print(f">> verified {n_ok}/{len(questions)} queries")
    return n_ok, len(questions)
