"""Description generator (LLM) — extracted from document/refine.py.

No DB access, no file I/O: takes profile + relations, returns the descriptions
dict.  Reuses claude_json from bedrock.py (Opus 4.8, JSON-schema-forced).
"""
import json
from ..bedrock import claude_json, MODEL_ID

# Prompt guidance adapted from MemberJunction/MJ DBAutoDoc table-analysis.md (MIT).
SYSTEM = (
    "You are a senior data analyst reverse-engineering an undocumented database. "
    "You are given only physical schema (table/column names, types), data statistics, "
    "and sample values — no documentation. Infer the real-world meaning concisely and "
    "factually.\n"
    "Rules:\n"
    "- Use the evidence: column names, recovered FK relationships, sample values, and "
    "cardinality patterns. A FK reveals what a column points to — use it.\n"
    "- Low-cardinality columns (few distinct values) are likely codes/enums: use the "
    "actual sample values to explain what the code holds. If a coded column's concrete "
    "meaning is NOT evidenced by the data, say it is a code/enum and what it likely "
    "encodes, but do NOT invent specific label mappings.\n"
    "- Do NOT make up table or column names. Only refer to names given in the input.\n"
    "- Do not state facts the data does not support.\n"
    "- Confidence is 0-1 and must be conservative: use < 0.7 when the meaning is "
    "ambiguous or the table has little/no data to verify it. Reserve high confidence "
    "for cases the names + data clearly support."
)

TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_description": {
            "type": "string",
            "description": "1-2 sentences: what entity or event this table records.",
        },
        "reasoning": {
            "type": "string",
            "description": "Brief: which evidence (names, FKs, sample values, "
                           "cardinality) led to this table's interpretation.",
        },
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "What this column means; for coded/enum columns, "
                                       "what kind of code it holds (no invented mappings).",
                    },
                    "confidence": {"type": "number",
                                   "description": "0..1, conservative (<0.7 if ambiguous "
                                                  "or little data to verify)."},
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


def _calibrate(tinfo, obj):
    """Evidence-based confidence penalty.

    The model tends to be overconfident on empty tables (no data to verify).
    Penalize column confidence when the column has no measured sample / no
    distribution to back the claim. Flags such items as data-unverified.
    """
    stats_by_col = {c["name"]: c["stats"] for c in tinfo["columns"]}
    empty_table = not any(s.get("sampled") for s in stats_by_col.values())
    for c in obj.get("columns", []):
        st = stats_by_col.get(c["name"], {})
        unverified = empty_table or not st.get("sampled") or not st.get("top_values")
        if unverified and c.get("confidence") is not None:
            c["confidence"] = round(c["confidence"] * 0.5, 2)
            c["data_unverified"] = True
    return obj


# backpropagation pass — adapted from MemberJunction/MJ backpropagation.md (MIT)
REVISE_SCHEMA = {
    "type": "object",
    "properties": {
        "needsRevision": {"type": "boolean"},
        "revisedDescription": {"type": "string"},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["needsRevision"],
}

REVISE_SYSTEM = (
    "You may revise a parent table's description using insights from its child "
    "tables (tables that reference it). Revise ONLY if the children reveal the "
    "table serves a different purpose, clarify ambiguity, or change the meaning. "
    "Do NOT revise if children merely confirm the current description. Reference "
    "the insights explicitly in your reasoning."
)


def backpropagate(profile, relations, table_descs, progress=None):
    """One backward pass: for each parent (referenced by children), re-check its
    description against child descriptions; revise if warranted. Mutates
    table_descs. Returns (revised_count, usage)."""
    # children-of: parent -> [child descriptions]
    children = {}
    for fk in relations.get("foreign_keys", []):
        p, c = fk["parent_table"], fk["child_table"]
        if p in table_descs and c in table_descs and p != c:
            children.setdefault(p, set()).add(c)
    revised, tin, tout = 0, 0, 0
    parents = list(children.keys())
    for i, p in enumerate(parents, 1):
        insights = [{"child": c,
                     "description": table_descs[c]["table_description"]}
                    for c in sorted(children[p])]
        payload = {"table": p,
                   "current_description": table_descs[p]["table_description"],
                   "child_insights": insights}
        obj, usage = claude_json(
            "Reconsider this parent table's description given its children.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2),
            REVISE_SCHEMA, system=REVISE_SYSTEM, max_tokens=1024)
        tin += usage.get("input_tokens", 0)
        tout += usage.get("output_tokens", 0)
        if obj.get("needsRevision") and obj.get("revisedDescription"):
            table_descs[p]["table_description"] = obj["revisedDescription"]
            table_descs[p]["revised"] = True
            revised += 1
        if progress:
            progress(i, len(parents), p)
    return revised, {"input_tokens": tin, "output_tokens": tout}


def describe(profile, relations, progress=None, backprop_passes=0):
    """Return {"model", "db", "tables", "usage"} — same shape as PoC.

    backprop_passes: number of backward refinement passes after the forward
    pass (0 = none, like before; 1-2 = iterative refinement)."""
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
        table_descs[t] = _calibrate(tinfo, obj)
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        if progress:
            progress(i, n, t)

    # backward refinement passes (child insights -> parent descriptions)
    for p in range(backprop_passes):
        revised, usage = backpropagate(profile, relations, table_descs)
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        if progress:
            progress(n, n, f"backprop pass {p+1}: revised {revised}")
        if revised == 0:
            break  # converged

    db_obj, usage = synthesize_db(table_descs)
    total_in += usage.get("input_tokens", 0)
    total_out += usage.get("output_tokens", 0)
    return {
        "model": MODEL_ID, "db": db_obj, "tables": table_descs,
        "usage": {"input_tokens": total_in, "output_tokens": total_out},
    }
