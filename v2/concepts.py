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
    "about — core entities, the events/transactions they participate in, and "
    "the reference/lookup data they rely on — organized in a small IS-A "
    "hierarchy. Derive concepts ONLY from the given table descriptions; do "
    "not assume any particular product, schema, or industry.\n"
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


def extract_concepts(catalog):
    """LLM concept extraction from a catalog dict; returns concepts dict."""
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
    return {"concepts": concepts, "dropped_references": dropped,
            "usage": usage}


# --------------------------------------------------------- concept relations
RELATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Relation verb in English "
                                            "UPPER_SNAKE_CASE (e.g. "
                                            "PRESCRIBED_BY, BELONGS_TO, "
                                            "RECORDED_DURING)."},
                    "src": {"type": "string",
                            "description": "Source concept name (the side "
                                           "holding the FK / the 'many' side)."},
                    "dst": {"type": "string",
                            "description": "Target concept name (the "
                                           "referenced side)."},
                    "via": {"type": "string",
                            "description": "The foreign key this relation is "
                                           "grounded in, exactly as given in "
                                           "the input: 'child_table.column'."},
                    "description": {"type": "string",
                                    "description": "One sentence in Korean: "
                                                   "what this relation means "
                                                   "in the business domain."},
                    "confidence": {"type": "number",
                                   "description": "0-1: how clearly the FK "
                                                  "and names support this "
                                                  "relation."},
                },
                "required": ["name", "src", "dst", "via", "description",
                             "confidence"],
            },
        }
    },
    "required": ["relations"],
}

REL_SYSTEM = (
    "You are building the semantic relation layer of a data-catalog ontology. "
    "Given the business concepts of one database (each mapped to physical "
    "tables) and the recovered foreign keys between tables, name the "
    "MEANINGFUL BUSINESS RELATIONS between concepts. Derive relations ONLY "
    "from the given concepts and foreign keys; do not assume any particular "
    "product, schema, or industry.\n"
    "Rules:\n"
    "- Every relation must be grounded in exactly ONE foreign key from the "
    "input, referenced verbatim in `via` as 'child_table.column'.\n"
    "- `src` is the concept mapped to the FK's CHILD table; `dst` is the "
    "concept mapped to the PARENT table. Use ONLY concept names from the "
    "input.\n"
    "- `name` is an English verb phrase in UPPER_SNAKE_CASE that reads "
    "naturally as (src)-[NAME]->(dst), e.g. PRESCRIBED_BY, OCCURRED_DURING, "
    "BELONGS_TO, MEASURED_FOR.\n"
    "- Do NOT emit taxonomy relations (IS_A) — those already exist. Do NOT "
    "use vague names like RELATED_TO, HAS, LINKED_TO.\n"
    "- Skip FKs that are purely technical (audit/metadata plumbing) or where "
    "either side has no mapped concept.\n"
    "- One FK may support at most one relation; if several FKs express the "
    "same business relation between the same concept pair, emit one relation "
    "per FK (they differ in `via`).\n"
    "- Write `description` in natural Korean (identifiers stay as-is)."
)


def _fk_index(catalog):
    """{'child.col': fk-dict} for every recovered FK in the catalog."""
    idx = {}
    for t in catalog["tables"]:
        for f in t.get("foreign_keys", []):
            idx[f'{t["name"]}.{f["column"]}'] = {
                "child_table": t["name"], "column": f["column"],
                "ref": f["ref"], "source": f.get("source"),
                "confidence": f.get("confidence")}
    return idx


def _fk_cardinality(catalog, via):
    """Data-derived cardinality of the FK 'child.col': 1:1 if the child
    column is (near-)unique, else N:1. Never trusts the LLM for this."""
    child_table, col = via.split(".", 1)
    for t in catalog["tables"]:
        if t["name"] != child_table:
            continue
        for c in t["columns"]:
            if c["name"] == col:
                dr = (c.get("stats") or {}).get("distinct_ratio")
                return "1:1" if (dr or 0) >= 0.99 else "N:1"
    return "N:1"


def validate_relations(obj, concepts, catalog):
    """Ground every relation: src/dst must be known concepts, via must be a
    real recovered FK, and src's concept must map the FK's child table.
    Violations are dropped and reported (same policy as validate())."""
    by_name = {c["name"]: c for c in concepts}
    fks = _fk_index(catalog)
    kept, dropped = [], []
    seen = set()
    for r in obj.get("relations", []):
        why = None
        src, dst, via = r.get("src"), r.get("dst"), r.get("via")
        fk = fks.get(via)
        if src not in by_name or dst not in by_name:
            why = "unknown concept"
        elif fk is None:
            why = "unknown FK (via)"
        elif fk["child_table"] not in (by_name[src].get("tables") or []):
            why = "src concept does not map the FK child table"
        elif src == dst and fk["ref"].split(".", 1)[0] != fk["child_table"]:
            # self relation is legit only for a true self-FK (parent==child
            # table, e.g. preceding_visit_occurrence_id)
            why = "self relation without self-FK"
        elif (src, dst, via) in seen:
            why = "duplicate"
        if why:
            dropped.append({"relation": r.get("name"), "src": src,
                            "dst": dst, "via": via, "reason": why})
            continue
        seen.add((src, dst, via))
        kept.append({
            "name": r["name"], "src": src, "dst": dst,
            "via": f'{via} -> {fk["ref"]}',
            "cardinality": _fk_cardinality(catalog, via),   # data-derived
            "description": r.get("description"),
            "confidence": r.get("confidence"),
        })
    return kept, dropped


def extract_concept_relations(catalog, concepts):
    """LLM relation naming over recovered FKs; returns {relations, dropped}.

    Cardinality comes from column uniqueness statistics, not the LLM."""
    concept_of = {}   # table -> [concept names]
    for c in concepts:
        for t in (c.get("tables") or []):
            concept_of.setdefault(t, []).append(c["name"])
    fk_rows = []
    for via, fk in _fk_index(catalog).items():
        parent = fk["ref"].split(".", 1)[0]
        fk_rows.append({
            "fk": via, "references": fk["ref"],
            "child_concepts": concept_of.get(fk["child_table"], []),
            "parent_concepts": concept_of.get(parent, []),
        })
    payload = {
        "concepts": [{"name": c["name"], "name_ko": c.get("name_ko"),
                      "tables": c.get("tables") or []} for c in concepts],
        "foreign_keys": fk_rows,
    }
    obj, usage = claude_json(
        "Name the business relations between these concepts, grounded in "
        "the given foreign keys.\n\n" + json.dumps(payload, ensure_ascii=False),
        RELATIONS_SCHEMA, system=REL_SYSTEM, max_tokens=8192)
    relations, dropped = validate_relations(obj, concepts, catalog)
    return {"relations": relations, "dropped": dropped, "usage": usage}


def cmd_extract():
    catalog = load_json(out_path("catalog.json"))
    result = extract_concepts(catalog)
    dump_json(result, out_path("concepts.json"))
    roots = [c["name"] for c in concepts if not c["is_a"]]
    print(f">> {len(concepts)} concepts ({len(roots)} roots: {roots})")
    if dropped:
        print(f"   dropped unknown references on {len(dropped)} concepts")
    print(f">> wrote {out_path('concepts.json')}")


def load_concepts_to_graph(run_key, gid, concepts, relations=None):
    """Load a concepts list (+semantic relations) into run_key's graph."""
    _load(gid, run_key, concepts, relations)


def cmd_load():
    import graph as G
    gid = G.graph_id(type("A", (), {"graph_id": None})())  # this run's graph
    if not gid:
        raise SystemExit("no graph for this run — run `graph.py load` first")
    run = G.current_run_id()
    data = load_json(out_path("concepts.json"))
    _load(gid, run, data["concepts"])


def _load(gid, run, concepts, relations=None):
    import graph as G

    # clear this run's concept nodes before reloading (idempotent)
    G.run_query(gid, "MATCH (c:Concept {run: $run}) DETACH DELETE c",
                {"run": run})

    rows = [{"name": c["name"], "name_ko": c["name_ko"],
             "description": c["description"],
             "synonyms": ", ".join(c["synonyms"]),
             "confidence": float(c.get("confidence") or 0), "run": run}
            for c in concepts]
    for batch in G.chunks(rows, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MERGE (c:Concept {name: r.name, run: r.run})
            SET c.name_ko = r.name_ko, c.description = r.description,
                c.synonyms = r.synonyms, c.confidence = r.confidence
        """, {"rows": batch})

    isa = [{"child": c["name"], "parent": c["is_a"], "run": run}
           for c in concepts if c.get("is_a")]
    if isa:
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Concept {name: r.child, run: r.run}),
                  (b:Concept {name: r.parent, run: r.run})
            MERGE (a)-[:IS_A]->(b)
        """, {"rows": isa})

    t_maps = [{"concept": c["name"], "table": t, "run": run,
               "confidence": float(c.get("confidence") or 0)}
              for c in concepts for t in c["tables"]]
    for batch in G.chunks(t_maps, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (c:Concept {name: r.concept, run: r.run}),
                  (t:Table {name: r.table, run: r.run})
            MERGE (c)-[e:MAPPED_TO]->(t)
            SET e.confidence = r.confidence
        """, {"rows": batch})

    c_maps = [{"concept": c["name"], "col": k, "run": run,
               "confidence": float(c.get("confidence") or 0)}
              for c in concepts for k in c["key_columns"]]
    for batch in G.chunks(c_maps, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (c:Concept {name: r.concept, run: r.run}),
                  (col:Column {id: r.col, run: r.run})
            MERGE (c)-[e:MAPPED_TO]->(col)
            SET e.confidence = r.confidence
        """, {"rows": batch})

    # semantic relations between concepts (generic :REL edge — Neptune
    # openCypher cannot parametrize edge labels; the verb lives in r.name)
    rel_rows = [{"src": r["src"], "dst": r["dst"], "name": r["name"],
                 "cardinality": r.get("cardinality") or "",
                 "via": r.get("via") or "",
                 "confidence": float(r.get("confidence") or 0), "run": run}
                for r in (relations or [])]
    for batch in G.chunks(rel_rows, 50):
        G.run_query(gid, """
            UNWIND $rows AS r
            MATCH (a:Concept {name: r.src, run: r.run}),
                  (b:Concept {name: r.dst, run: r.run})
            MERGE (a)-[e:REL {name: r.name, via: r.via}]->(b)
            SET e.cardinality = r.cardinality, e.confidence = r.confidence
        """, {"rows": batch})

    out = G.run_query(gid, """
        MATCH (c:Concept {run: $run})
        OPTIONAL MATCH (c)-[m:MAPPED_TO]->()
        OPTIONAL MATCH (:Concept {run: $run})-[rel:REL]->(:Concept {run: $run})
        RETURN count(DISTINCT c) AS concepts, count(DISTINCT m) AS mappings,
               count(DISTINCT rel) AS relations
    """, {"run": run})
    print(">> loaded:", json.dumps(out.get("results")))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("extract", "all"):
        cmd_extract()
    if cmd in ("load", "all"):
        cmd_load()


if __name__ == "__main__":
    main()
