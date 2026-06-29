#!/usr/bin/env python3
"""Stage 3 — Semantic inference: db / table / column descriptions via LLM.

v2 improvements over v1 (each traced to a measured v1 weakness):
  - code-value RESOLUTION: for a coded column with a recovered FK to a
    populated parent, JOIN the actual codes to their parent labels and put
    the code->label pairs in the prompt. The model then explains codes from
    data evidence instead of refusing to guess.  (v1 C3)
  - dependency-level batching: tables are described in FK topological order,
    with parent descriptions as context (kept from v1 — it worked).
  - evidence ledger: every description carries `evidence` (which signals
    were available) and confidence is CALIBRATED against it — empty-table
    columns are capped, sanity-flagged tables are derated.  (v1 C2)
  - self-verification loop: dependency-level sanity check; flagged tables
    get ONE re-analysis pass with the issue text in the prompt
    (generate -> verify -> regenerate; bounded, converges by construction).

Writes out/descriptions.json.
"""
import json
import sys

from config import (connect, PGSCHEMA, out_path, load_json, dump_json,
                    claude_json, qident, MODEL_ID, USAGE)

MAX_LABEL_LOOKUPS = 8     # codes resolved per column
RESOLVE_MAX_DISTINCT = 50  # only resolve labels for enum-ish columns

SYSTEM = (
    "You are a senior data analyst reverse-engineering an undocumented "
    "database. You see only physical schema (table/column names, types), "
    "data statistics, sample values, recovered keys, and — where available — "
    "code values RESOLVED to their labels via a recovered foreign key. "
    "Infer real-world meaning concisely and factually.\n"
    "Rules:\n"
    "- Describe what each column MEANS in the schema's domain — its intended "
    "real-world semantics — not the state of this particular dataset. Lead "
    "with the meaning. If the data shows a notable condition (all null, "
    "single value, unpopulated), append it as a secondary note like "
    "'(unpopulated in this dataset)', never as the definition itself.\n"
    "- For key columns, say what the identifier identifies (the entity / "
    "relationship type / event), not just 'primary key'.\n"
    "- When two columns clearly form a raw-vs-derived pair (e.g. a free-text "
    "or original-code column alongside a standardized/looked-up column for "
    "the same attribute, as suggested by their names and value shapes), "
    "describe the contrast between the original and the standardized value. "
    "Infer this ONLY from the given names and data, not from assumptions "
    "about any particular product or standard.\n"
    "- Use the evidence given: names, FK targets, sample values, cardinality, "
    "resolved code labels. An FK tells you what a column points to — say it.\n"
    "- If `resolved_codes` is present for a column, the code meanings ARE "
    "data-evidenced: state what the codes represent.\n"
    "- If `existing_comment` / `existing_table_comment` is present, it is a "
    "human-written comment already in the database — treat it as a strong "
    "hint and reconcile it with the data, but verify against the evidence "
    "rather than copying blindly (comments can be stale).\n"
    "- Low-cardinality columns are likely codes/enums; explain what they "
    "encode, but do NOT invent specific label mappings that are not given.\n"
    "- Never invent table or column names. Never state unsupported facts.\n"
    "- Confidence 0-1, conservative: < 0.7 when ambiguous or unverifiable "
    "(e.g. the table has no data). High confidence only with clear support. "
    "Sample values from a small demo dataset are weak evidence for UNIVERSAL "
    "claims (e.g. 'only value is X') — do not raise confidence for those.\n"
    "- WRITE ALL DESCRIPTIONS IN KOREAN (자연스러운 한국어). Keep table/"
    "column names, SQL identifiers, code values, units, and technical "
    "acronyms in their original form; the prose around them is Korean. "
    "Use declarative dictionary style (~다/~함)."
)

TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_description": {
            "type": "string",
            "description": "1-2 sentences: what entity/event this table records."},
        "reasoning": {
            "type": "string",
            "description": "Brief: which evidence led to this interpretation."},
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "Meaning; for coded columns, what the "
                                       "code holds (use resolved labels when given)."},
                    "confidence": {
                        "type": "number",
                        "description": "0..1, conservative."},
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
                   "description": "Short label, e.g. 'healthcare / clinical'."},
    },
    "required": ["db_description", "domain"],
}

SANITY_SCHEMA = {
    "type": "object",
    "properties": {
        "hasMaterialIssues": {"type": "boolean"},
        "tableIssues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "issueType": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": ["low", "medium", "high"]},
                    "description": {"type": "string"},
                },
                "required": ["table", "issueType", "severity", "description"],
            },
        },
    },
    "required": ["hasMaterialIssues", "tableIssues"],
}

SANITY_SYSTEM = (
    "You review related table/column descriptions for consistency: FK "
    "descriptions align parent<->child; no contradictions; consistent "
    "terminology; no misidentified table purpose. Report only MATERIAL "
    "issues — ignore style. Name the affected table per issue."
)


# ------------------------------------------------------------- code resolve
def find_label_column(profile, table):
    """Pick a human-readable label column in a (lookup) table: the first
    text column with reasonably high cardinality and a name that suggests
    a name/label/description."""
    tinfo = profile["tables"][table]
    texty = [c for c in tinfo["columns"]
             if c["data_type"] in ("character varying", "text", "character")]
    for pref in ("name", "label", "title", "description", "desc"):
        for c in texty:
            if pref in c["name"].lower():
                return c["name"]
    for c in texty:  # fallback: a distinctive text column
        if (c["stats"].get("distinct_ratio") or 0) > 0.5:
            return c["name"]
    return None


def resolve_codes(cur, profile, relations):
    """For each FK child column that is enum-ish, join its top codes to the
    parent's label column.  Returns {(table, column): [{code, label}]}.
    Data-evidenced: every pair comes from an actual JOIN on recovered keys."""
    resolved = {}
    tables = profile["tables"]
    for fk in relations.get("foreign_keys", []):
        ct, cc = fk["child_table"], fk["child_column"]
        pt, pc = fk["parent_table"], fk["parent_column"]
        if pt not in tables or tables[pt]["rowcount"] == 0:
            continue
        ctinfo = tables.get(ct)
        if not ctinfo or ctinfo["rowcount"] == 0:
            continue
        cstats = next((c["stats"] for c in ctinfo["columns"]
                       if c["name"] == cc), None)
        if not cstats or not cstats.get("top_values"):
            continue
        if (cstats.get("distinct") or 0) > RESOLVE_MAX_DISTINCT:
            continue
        label_col = find_label_column(profile, pt)
        if not label_col or not pc:
            continue
        codes = [tv["value"] for tv in cstats["top_values"][:MAX_LABEL_LOOKUPS]]
        try:
            cur.execute(
                f"SELECT {qident(pc)}::text, {qident(label_col)}::text "
                f"FROM {qident(PGSCHEMA)}.{qident(pt)} "
                f"WHERE {qident(pc)}::text = ANY(%s)", (codes,))
            pairs = [{"code": r[0], "label": r[1]} for r in cur.fetchall()]
            if pairs:
                resolved[(ct, cc)] = pairs
        except Exception:
            continue
    return resolved


# ------------------------------------------------------------- prompt build
def fk_order(profile, relations):
    fks = relations.get("foreign_keys", [])
    parents_of = {}
    for fk in fks:
        parents_of.setdefault(fk["child_table"], set()).add(fk["parent_table"])
    ordered, seen = [], set()

    def visit(t, stack):
        if t in seen or t in stack:
            return
        stack.add(t)
        for p in parents_of.get(t, ()):
            if p in profile["tables"]:
                visit(p, stack)
        stack.discard(t)
        seen.add(t)
        ordered.append(t)

    for t in profile["tables"]:
        visit(t, set())
    return ordered


def compact_columns(table, tinfo, resolved):
    out = []
    for c in tinfo["columns"]:
        s = c["stats"]
        item = {
            "name": c["name"], "type": c["data_type"], "nullable": c["nullable"],
            "distinct_ratio": s.get("distinct_ratio"),
            "null_ratio": s.get("null_ratio"),
            "examples": s.get("examples", []),
            "min": s.get("min"), "max": s.get("max"),
        }
        if s.get("is_enum_candidate"):
            item["enum_candidate"] = True
            item["value_distribution"] = s.get("top_values", [])
        rc = resolved.get((table, c["name"]))
        if rc:
            item["resolved_codes"] = rc
        if c.get("existing_comment"):
            item["existing_comment"] = c["existing_comment"]
        out.append(item)
    return out


def relations_for(table, relations):
    fks = [f'{fk["child_column"]} -> {fk["parent_table"]}.{fk["parent_column"]}'
           f' (confidence {fk.get("confidence")})'
           for fk in relations.get("foreign_keys", [])
           if fk["child_table"] == table]
    pk = relations.get("primary_keys", {}).get(table)
    return {"primary_key": pk["columns"] if pk else None, "foreign_keys": fks}


def describe_table(table, tinfo, relations, neighbours, resolved,
                   prior_issues=None):
    prompt = {
        "task": "Describe this table and each of its columns.",
        "table_name": table, "row_count": tinfo["rowcount"],
        "recovered_relations": relations_for(table, relations),
        "neighbour_table_descriptions": neighbours,
        "columns": compact_columns(table, tinfo, resolved),
    }
    if tinfo.get("table_comment"):
        prompt["existing_table_comment"] = tinfo["table_comment"]
    if prior_issues:
        prompt["consistency_issues_found_in_review"] = prior_issues
        prompt["task"] = ("Your previous descriptions of this table had the "
                          "consistency issues listed. Re-describe the table "
                          "and columns, fixing those issues.")
    return claude_json(
        "Analyze this table profile and return descriptions.\n\n"
        + json.dumps(prompt, ensure_ascii=False),
        TABLE_SCHEMA, system=SYSTEM, max_tokens=8192)


# ------------------------------------------------------------- calibration
def calibrate(table, tinfo, obj, resolved):
    """Evidence-based confidence: cap what the data cannot verify, and
    record the evidence ledger per column."""
    stats_by_col = {c["name"]: c["stats"] for c in tinfo["columns"]}
    empty = tinfo["rowcount"] == 0
    for c in obj.get("columns", []):
        st = stats_by_col.get(c["name"], {})
        ev = {
            "has_data": bool(st.get("sampled")),
            "has_distribution": bool(st.get("top_values")),
            "resolved_codes": (table, c["name"]) in resolved,
        }
        c["evidence"] = ev
        if (empty or not ev["has_data"]) and c.get("confidence") is not None:
            c["confidence"] = round(min(c["confidence"], 0.9) * 0.5, 2)
            c["data_unverified"] = True
        elif ev["resolved_codes"]:
            c["confidence"] = round(min(1.0, c["confidence"] + 0.05), 2)
    return obj


# ------------------------------------------------------------- sanity loop
def dependency_groups(relations, tables):
    """Group each parent with its children (dependency-level units)."""
    groups = []
    children = {}
    for fk in relations.get("foreign_keys", []):
        children.setdefault(fk["parent_table"], set()).add(fk["child_table"])
    seen = set()
    for p, cs in children.items():
        group = sorted(({p} | cs) & set(tables))
        key = tuple(group)
        if len(group) >= 2 and key not in seen:
            seen.add(key)
            groups.append(group)
    return groups


def sanity_check_group(group, table_descs, relations):
    payload = {"tables": []}
    fk_by_child = {}
    for f in relations.get("foreign_keys", []):
        fk_by_child.setdefault(f["child_table"], []).append(
            f'{f["child_column"]}->{f["parent_table"]}')
    for t in group:
        td = table_descs[t]
        payload["tables"].append({
            "name": t, "description": td["table_description"],
            "foreign_keys": fk_by_child.get(t, []),
            "columns": [{"name": c["name"], "description": c["description"]}
                        for c in td["columns"]],
        })
    obj, _ = claude_json(
        "Review these related table descriptions for material "
        "inconsistencies.\n\n" + json.dumps(payload, ensure_ascii=False),
        SANITY_SCHEMA, system=SANITY_SYSTEM, max_tokens=4096)
    return [i for i in obj.get("tableIssues", [])
            if i.get("severity") in ("medium", "high")]


def synthesize_db(table_descs):
    payload = {t: d["table_description"] for t, d in table_descs.items()}
    return claude_json(
        "Given these table descriptions from one database, describe the "
        "database as a whole.\n\n" + json.dumps(payload, ensure_ascii=False),
        DB_SCHEMA, system=SYSTEM, max_tokens=1024)


def build_descriptions(profile, relations, conn=None, limit=0):
    """Generate db/table/column descriptions and return the result dict."""
    own = conn is None
    if own:
        conn = connect()
        conn.autocommit = True
    with conn.cursor() as cur:
        resolved = resolve_codes(cur, profile, relations)
    if own:
        conn.close()
    print(f">> resolved code labels for {len(resolved)} coded columns "
          f"(via recovered FK joins)")

    order = fk_order(profile, relations)
    if limit:
        order = order[:limit]

    # forward pass: parents first, neighbours as context
    table_descs = {}
    for i, t in enumerate(order, 1):
        tinfo = profile["tables"][t]
        neighbours = {}
        for fk in relations.get("foreign_keys", []):
            if fk["child_table"] == t and fk["parent_table"] in table_descs:
                neighbours[fk["parent_table"]] = \
                    table_descs[fk["parent_table"]]["table_description"]
        obj, _ = describe_table(t, tinfo, relations, neighbours, resolved)
        table_descs[t] = calibrate(t, tinfo, obj, resolved)
        print(f"   [{i}/{len(order)}] {t}")

    # verification loop: dependency-level sanity -> one bounded re-pass
    groups = dependency_groups(relations, table_descs)
    issues_by_table = {}
    for g in groups:
        for issue in sanity_check_group(g, table_descs, relations):
            issues_by_table.setdefault(issue["table"], []).append(
                f'{issue["issueType"]}: {issue["description"]}')
    print(f">> sanity check: {len(issues_by_table)} tables flagged "
          f"across {len(groups)} dependency groups")
    for t, issues in issues_by_table.items():
        if t not in table_descs:
            continue
        tinfo = profile["tables"][t]
        neighbours = {}
        for fk in relations.get("foreign_keys", []):
            if fk["child_table"] == t and fk["parent_table"] in table_descs:
                neighbours[fk["parent_table"]] = \
                    table_descs[fk["parent_table"]]["table_description"]
        obj, _ = describe_table(t, tinfo, relations, neighbours, resolved,
                                prior_issues=issues)
        table_descs[t] = calibrate(t, tinfo, obj, resolved)
        table_descs[t]["sanity_revised"] = True
        print(f"   re-described {t} ({len(issues)} issues)")

    db_obj, _ = synthesize_db(table_descs)

    result = {
        "model": MODEL_ID, "db": db_obj, "tables": table_descs,
        "code_resolution": {f"{t}.{c}": v for (t, c), v in resolved.items()},
        "sanity_issues": issues_by_table,
        "usage": dict(USAGE),
    }
    print(f">> domain: {db_obj['domain']} | tokens in={USAGE['input_tokens']} "
          f"out={USAGE['output_tokens']} calls={USAGE['calls']}")
    return result


def main():
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    profile = load_json(out_path("profile.json"))
    relations = load_json(out_path("relations.json"))
    result = build_descriptions(profile, relations, limit=limit)
    dump_json(result, out_path("descriptions.json"))
    print(">> wrote out/descriptions.json")


if __name__ == "__main__":
    main()
