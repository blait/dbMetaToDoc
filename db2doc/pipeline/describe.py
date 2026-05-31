"""Description generator (LLM) — extracted from document/refine.py.

No DB access, no file I/O: takes profile + relations, returns the descriptions
dict.  Reuses claude_json from bedrock.py (Opus 4.8, JSON-schema-forced).
"""
import json
from ..bedrock import claude_json, MODEL_ID

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
                    "confidence": {"type": "number",
                                   "description": "0..1 confidence."},
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
        "db_description": {"type": "string",
                           "description": "One paragraph: domain and purpose."},
        "domain": {"type": "string",
                   "description": "Short domain label, e.g. 'healthcare / clinical'."},
    },
    "required": ["db_description", "domain"],
}


def fk_order(profile, relations):
    """Parents (FK targets) before children."""
    fks = relations.get("foreign_keys", [])
    children = {}
    for fk in fks:
        children.setdefault(fk["child_table"], set()).add(fk["parent_table"])
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

    for t in profile["tables"].keys():
        visit(t, set())
    return ordered


def compact_columns(tinfo):
    out = []
    for c in tinfo["columns"]:
        s = c["stats"]
        out.append({
            "name": c["name"], "type": c["data_type"], "nullable": c["nullable"],
            "distinct_ratio": s.get("distinct_ratio"), "null_ratio": s.get("null_ratio"),
            "examples": s.get("examples", []), "min": s.get("min"), "max": s.get("max"),
        })
    return out


def relations_for(table, relations):
    out = [f'{fk["child_column"]} -> {fk["parent_table"]}.{fk["parent_column"]}'
           for fk in relations.get("foreign_keys", []) if fk["child_table"] == table]
    pk = relations.get("primary_keys", {}).get(table)
    return {"primary_key": pk["column"] if pk else None, "foreign_keys": out}


def describe_table(table, tinfo, relations, neighbour_desc):
    prompt = {
        "task": "Describe this table and each of its columns.",
        "table_name": table, "row_count": tinfo["rowcount"],
        "recovered_relations": relations_for(table, relations),
        "neighbour_table_descriptions": neighbour_desc,
        "columns": compact_columns(tinfo),
    }
    return claude_json(
        "Analyze this table profile and return descriptions.\n\n"
        + json.dumps(prompt, ensure_ascii=False, indent=2),
        TABLE_SCHEMA, system=SYSTEM, max_tokens=4096)


def synthesize_db(table_descs):
    payload = {t: d["table_description"] for t, d in table_descs.items()}
    return claude_json(
        "Given these table descriptions from one database, describe the database "
        "as a whole.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        DB_SCHEMA, system=SYSTEM, max_tokens=1024)


def describe(profile, relations, progress=None):
    """Return {"model", "db", "tables", "usage"} — same shape as PoC."""
    order = fk_order(profile, relations)
    table_descs, total_in, total_out = {}, 0, 0
    n = len(order)
    for i, t in enumerate(order, 1):
        tinfo = profile["tables"][t]
        neighbours = {}
        for fk in relations.get("foreign_keys", []):
            if fk["child_table"] == t and fk["parent_table"] in table_descs:
                neighbours[fk["parent_table"]] = \
                    table_descs[fk["parent_table"]]["table_description"]
        obj, usage = describe_table(t, tinfo, relations, neighbours)
        table_descs[t] = obj
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        if progress:
            progress(i, n, t)
    db_obj, usage = synthesize_db(table_descs)
    total_in += usage.get("input_tokens", 0)
    total_out += usage.get("output_tokens", 0)
    return {
        "model": MODEL_ID, "db": db_obj, "tables": table_descs,
        "usage": {"input_tokens": total_in, "output_tokens": total_out},
    }
