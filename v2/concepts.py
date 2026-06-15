#!/usr/bin/env python3
"""Stage 8 — Concept layer (ontology) on top of the schema graph.

Extracts BUSINESS CONCEPTS from the generated catalog with the LLM and
links them to the physical schema, ATHENA-style (VLDB 2016): natural-
language terms match concepts first, then resolve down to tables/columns.

  (:Concept {name, name_ko, description, synonyms})
  (:Concept)-[:IS_A]->(:Concept)                  # domain hierarchy
  (:Concept)-[:MAPPED_TO {confidence}]->(:Table)
  (:Concept)-[:MAPPED_TO {confidence}]->(:Column) # key columns only

Design constraint (same as the pipeline): concepts must be grounded in the
catalog — the LLM may only reference tables/columns that exist, and every
mapping is validated against the catalog before loading. Unknown references
are dropped and reported.

Usage:
  V2_OUT_DIR=runs/<id> python concepts.py extract   # LLM -> concepts.json
  V2_OUT_DIR=runs/<id> python concepts.py load      # concepts.json -> Neptune
  V2_OUT_DIR=runs/<id> python concepts.py all       # both
"""
import json
import sys

from config import out_path, load_json, dump_json, claude_json, cfg

CONCEPTS_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Canonical concept name in English, "
                                            "singular, Title Case (e.g. 'Patient')."},
                    "name_ko": {"type": "string",
                                "description": "Korean name (e.g. '환자')."},
                    "description": {"type": "string",
                                    "description": "1-2 sentences: what this "
                                                   "business concept means in this DB."},
                    "synonyms": {"type": "array", "items": {"type": "string"},
                                 "description": "Alternative terms a user might "
                                                "say, Korean and English."},
                    "is_a": {"type": ["string", "null"],
                             "description": "Parent concept name (must be another "
                                            "concept in this list), or null for roots."},
                    "tables": {"type": "array", "items": {"type": "string"},
                               "description": "Tables that store this concept."},
                    "key_columns": {"type": "array", "items": {"type": "string"},
                                    "description": "Most important columns as "
                                                   "'table.column' (ids, codes, names)."},
                    "confidence": {"type": "number",
                                   "description": "0-1: how clearly the schema "
                                                  "supports this concept."},
                },
                "required": ["name", "name_ko", "description", "synonyms",
                             "is_a", "tables", "key_columns", "confidence"],
            },
        }
    },
    "required": ["concepts"],
}

SYSTEM = (
    "You are building the concept layer (lightweight ontology) of a data "
    "catalog. Given the tables of one database with their inferred "
    "descriptions, extract the BUSINESS CONCEPTS a domain user would talk "
    "about (entities like Patient, events like Drug Exposure, reference "
    "data like Vocabulary), organized in a small IS-A hierarchy.\n"
    "Rules:\n"
    "- 15-35 concepts. Prefer concepts a user would actually name in a "
    "question; include 2-6 abstract parents (e.g. 'Clinical Event') to "
    "group them.\n"
    "- Every concept must map to >=1 existing table, EXCEPT abstract "
    "parents which may have empty tables.\n"
    "- Use ONLY table and column names that appear in the input.\n"
    "- is_a must reference another concept name from your own list.\n"
    "- Synonyms: include common Korean and English terms users would type.\n"
    "- Be faithful to the catalog descriptions; do not invent domain facts "
    "the schema does not support.\n"
    "- Write `description` in natural Korean (identifiers/acronyms stay "
    "as-is). `name` stays English Title Case; `name_ko` is the Korean name."
)


def compact_catalog(catalog):
    return [{
        "table": t["name"],
        "rows": t.get("rowcount", 0),
        "description": t.get("description", ""),
        "columns": [c["name"] for c in t["columns"]],
    } for t in catalog["tables"]]


def validate(obj, catalog):
    """Ground every reference in the catalog; drop and report unknowns."""
    tables = {t["name"] for t in catalog["tables"]}
    columns = {f'{t["name"]}.{c["name"]}'
               for t in catalog["tables"] for c in t["columns"]}
    names = {c["name"] for c in obj["concepts"]}
    dropped = []
    out = []
    for c in obj["concepts"]:
        bad_t = [t for t in c["tables"] if t not in tables]
        bad_c = [k for k in c["key_columns"] if k not in columns]
        if bad_t or bad_c:
            dropped.append({"concept": c["name"],
                            "unknown_tables": bad_t, "unknown_columns": bad_c})
        c["tables"] = [t for t in c["tables"] if t in tables]
        c["key_columns"] = [k for k in c["key_columns"] if k in columns]
        if c.get("is_a") and c["is_a"] not in names:
            c["is_a"] = None
        out.append(c)
    return out, dropped


def cmd_extract():
    catalog = load_json(out_path("catalog.json"))
    payload = {
        "database_domain": catalog.get("database", {}).get("domain", ""),
        "database_description": catalog.get("database", {}).get(
            "db_description", ""),
        "tables": compact_catalog(catalog),
    }
    obj, usage = claude_json(
        "Extract the business concept layer for this database.\n\n"
        + json.dumps(payload, ensure_ascii=False),
        CONCEPTS_SCHEMA, system=SYSTEM, max_tokens=16384)
    concepts, dropped = validate(obj, catalog)
    result = {"concepts": concepts, "dropped_references": dropped,
              "usage": usage}
    dump_json(result, out_path("concepts.json"))
    roots = [c["name"] for c in concepts if not c["is_a"]]
    print(f">> {len(concepts)} concepts ({len(roots)} roots: {roots})")
    if dropped:
        print(f"   dropped unknown references on {len(dropped)} concepts")
    print(f">> wrote {out_path('concepts.json')}")


def cmd_load():
    import graph as G
    gid = cfg("NEPTUNE_GRAPH_ID", required=True)
    data = load_json(out_path("concepts.json"))
    concepts = data["concepts"]

    rows = [{"name": c["name"], "name_ko": c["name_ko"],
             "description": c["description"],
             "synonyms": ", ".join(c["synonyms"]),
             "confidence": float(c.get("confidence") or 0)}
            for c in concepts]
    for batch in G.chunks(rows, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MERGE (c:Concept {name: r.name})
            SET c.name_ko = r.name_ko, c.description = r.description,
                c.synonyms = r.synonyms, c.confidence = r.confidence
        """, {"rows": batch})

    isa = [{"child": c["name"], "parent": c["is_a"]}
           for c in concepts if c.get("is_a")]
    if isa:
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Concept {name: r.child}), (b:Concept {name: r.parent})
            MERGE (a)-[:IS_A]->(b)
        """, {"rows": isa})

    t_maps = [{"concept": c["name"], "table": t,
               "confidence": float(c.get("confidence") or 0)}
              for c in concepts for t in c["tables"]]
    for batch in G.chunks(t_maps, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (c:Concept {name: r.concept}), (t:Table {name: r.table})
            MERGE (c)-[e:MAPPED_TO]->(t)
            SET e.confidence = r.confidence
        """, {"rows": batch})

    c_maps = [{"concept": c["name"], "col": k,
               "confidence": float(c.get("confidence") or 0)}
              for c in concepts for k in c["key_columns"]]
    for batch in G.chunks(c_maps, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (c:Concept {name: r.concept}), (col:Column {id: r.col})
            MERGE (c)-[e:MAPPED_TO]->(col)
            SET e.confidence = r.confidence
        """, {"rows": batch})

    out = G.run_query(gid, """
        MATCH (c:Concept)
        OPTIONAL MATCH (c)-[m:MAPPED_TO]->()
        RETURN count(DISTINCT c) AS concepts, count(m) AS mappings
    """)
    print(">> loaded:", json.dumps(out.get("results")))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("extract", "all"):
        cmd_extract()
    if cmd in ("load", "all"):
        cmd_load()


if __name__ == "__main__":
    main()
