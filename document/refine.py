#!/usr/bin/env python3
"""★ Core stage: generate natural-language descriptions with Claude Opus 4.8.

Given ONLY profile.json (names, types, stats, sample values) + recovered
relations.json, produce semantic descriptions at three levels:

    column  -> what each column means (incl. code-value interpretation)
    table   -> what entity/event each table records
    db      -> what domain the whole database serves

Strategy (DBAutoDoc-inspired):
  - process tables in FK-dependency order (parents first as context)
  - for each table, describe its columns + the table in one structured call,
    seeing recovered FKs and a few neighbouring-table descriptions already made
  - a light second pass (refine) lets later/global context flow back; bounded
    iterations (default 1 refine pass = 2 total) for cost control
  - finally synthesize the DB-level description from table descriptions

Writes out/descriptions.json.
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import claude_json, out_path, load_json, dump_json, MODEL_ID  # noqa: E402

SYSTEM = (
    "You are a senior data analyst reverse-engineering an undocumented database. "
    "You are given only physical schema (table/column names, types), data statistics, "
    "and sample values — no documentation. Infer the real-world meaning concisely and "
    "factually. Do not invent facts the data does not support. Descriptions must be "
    "specific (mention units, what a code/id refers to, the entity a table records)."
)

TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_description": {
            "type": "string",
            "description": "1-2 sentences: what entity or event this table records.",
        },
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "What this column means; for *_concept_id / coded "
                                       "columns, what kind of code it holds.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0..1 confidence in this description.",
                    },
                },
                "required": ["name", "description", "confidence"],
            },
        },
    },
    "required": ["table_description", "columns"],
}

DB_SCHEMA = {
    "type": "object",
    "properties": {
        "db_description": {
            "type": "string",
            "description": "One paragraph: the domain and purpose of this database.",
        },
        "domain": {"type": "string", "description": "Short domain label, e.g. 'healthcare / clinical'."},
    },
    "required": ["db_description", "domain"],
}


def fk_order(profile, relations):
    """Topological-ish order: parents (FK targets) before children."""
    fks = relations.get("foreign_keys", [])
    children = {}
    for fk in fks:
        children.setdefault(fk["child_table"], set()).add(fk["parent_table"])
    tables = list(profile["tables"].keys())
    ordered, seen = [], set()

    def visit(t, stack):
        if t in seen or t in stack:
            return
        stack.add(t)
        for parent in children.get(t, ()):
            if parent in profile["tables"]:
                visit(parent, stack)
        stack.discard(t)
        seen.add(t)
        ordered.append(t)

    for t in tables:
        visit(t, set())
    return ordered


def compact_columns(tinfo):
    """Trim the profile to what's useful in a prompt (keep token cost down)."""
    out = []
    for c in tinfo["columns"]:
        s = c["stats"]
        out.append({
            "name": c["name"],
            "type": c["data_type"],
            "nullable": c["nullable"],
            "distinct_ratio": s.get("distinct_ratio"),
            "null_ratio": s.get("null_ratio"),
            "examples": s.get("examples", []),
            "min": s.get("min"), "max": s.get("max"),
        })
    return out


def relations_for(table, relations):
    out = []
    for fk in relations.get("foreign_keys", []):
        if fk["child_table"] == table:
            out.append(f'{fk["child_column"]} -> {fk["parent_table"]}.{fk["parent_column"]}')
    pk = relations.get("primary_keys", {}).get(table)
    return {"primary_key": pk["column"] if pk else None, "foreign_keys": out}


def describe_table(table, tinfo, relations, neighbour_desc):
    prompt = {
        "task": "Describe this table and each of its columns.",
        "table_name": table,
        "row_count": tinfo["rowcount"],
        "recovered_relations": relations_for(table, relations),
        "neighbour_table_descriptions": neighbour_desc,
        "columns": compact_columns(tinfo),
    }
    import json
    obj, usage = claude_json(
        "Analyze this table profile and return descriptions.\n\n"
        + json.dumps(prompt, ensure_ascii=False, indent=2),
        TABLE_SCHEMA, system=SYSTEM, max_tokens=4096)
    return obj, usage


def synthesize_db(table_descs):
    import json
    payload = {t: d["table_description"] for t, d in table_descs.items()}
    obj, usage = claude_json(
        "Given these table descriptions from one database, describe the database "
        "as a whole.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        DB_SCHEMA, system=SYSTEM, max_tokens=1024)
    return obj, usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="describe only first N tables (debug)")
    args = ap.parse_args()

    profile = load_json(out_path("profile.json"))
    relations = load_json(out_path("relations.json"))
    order = fk_order(profile, relations)
    if args.limit:
        order = order[:args.limit]

    table_descs = {}
    total_in = total_out = 0
    for i, t in enumerate(order, 1):
        tinfo = profile["tables"][t]
        # give the model up to 5 already-described neighbours as context
        neighbours = {}
        for fk in relations.get("foreign_keys", []):
            if fk["child_table"] == t and fk["parent_table"] in table_descs:
                neighbours[fk["parent_table"]] = table_descs[fk["parent_table"]]["table_description"]
        obj, usage = describe_table(t, tinfo, relations, neighbours)
        table_descs[t] = obj
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        print(f"   [{i}/{len(order)}] {t:<26} cols={len(obj['columns'])}")

    db_obj, usage = synthesize_db(table_descs)
    total_in += usage.get("input_tokens", 0)
    total_out += usage.get("output_tokens", 0)

    result = {
        "model": MODEL_ID,
        "db": db_obj,
        "tables": table_descs,
        "usage": {"input_tokens": total_in, "output_tokens": total_out},
    }
    dump_json(result, out_path("descriptions.json"))
    print(f">> wrote out/descriptions.json")
    print(f">> domain: {db_obj['domain']}")
    print(f">> tokens in={total_in} out={total_out}")


if __name__ == "__main__":
    main()
