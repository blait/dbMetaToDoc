"""LLM verification passes — adapted from MemberJunction/MJ DBAutoDoc (MIT).

Two passes:
  prune_relations(): an LLM keep/drop decision over low-confidence FK/PK
    candidates (the name-based ones we added). Restores precision that the
    cheap name-based recall boost costs. (fk-pruning-holistic.md)
  sanity_check(): per dependency-level consistency review of descriptions;
    flags contradictions / mismatched FK descriptions / terminology conflicts
    and lowers confidence on affected items. (dependency-level-sanity-check.md)
"""
import json
from ..bedrock import claude_json

# --------------------------------------------------------------- FK/PK pruning
PRUNE_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "action": {"type": "string", "enum": ["keep", "remove"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "action"],
            },
        }
    },
    "required": ["decisions"],
}

PRUNE_SYSTEM = (
    "You are reviewing proposed foreign-key relationships in a database holistically, "
    "considering the FULL relationship graph. Decide keep or remove for each candidate. "
    "Heuristics: reverse-direction FKs (parent->child) should almost always be removed; "
    "transitive hops (A->B when both independently reference C) should almost always be "
    "removed; keep candidates that form sensible references given the table meanings. "
    "Only judge the candidates given; do not invent tables."
)


def prune_relations(relations, table_descs=None, only_low_confidence=True):
    """LLM keep/remove over FK candidates. Mutates a copy of relations.

    `table_descs`: {table: description} to give the model context (optional).
    By default only reviews low-confidence/name-based FKs (the risky ones).
    """
    fks = relations.get("foreign_keys", [])
    review_idx = [i for i, f in enumerate(fks)
                  if (not only_low_confidence) or f.get("source") == "name"
                  or (f.get("confidence") or 0) < 0.6]
    if not review_idx:
        return relations, {"reviewed": 0, "removed": 0}

    cand = [{"index": i,
             "from": f'{fks[i]["child_table"]}.{fks[i]["child_column"]}',
             "to": f'{fks[i]["parent_table"]}.{fks[i]["parent_column"]}',
             "confidence": fks[i].get("confidence"),
             "source": fks[i].get("source")}
            for i in review_idx]
    ctx = {"candidates": cand}
    if table_descs:
        ctx["table_descriptions"] = table_descs
    obj, _ = claude_json(
        "Review these FK candidates and decide keep/remove for EACH.\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2),
        PRUNE_SCHEMA, system=PRUNE_SYSTEM, max_tokens=4096)

    remove = {d["index"] for d in obj.get("decisions", [])
              if d.get("action") == "remove"}
    kept = [f for i, f in enumerate(fks) if i not in remove]
    out = dict(relations)
    out["foreign_keys"] = kept
    return out, {"reviewed": len(review_idx), "removed": len(remove)}


# --------------------------------------------------------------- sanity check
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
    "You review a group of related table/column descriptions for consistency. Check: "
    "(1) FK descriptions align between parent and child; (2) descriptions make sense "
    "together; (3) consistent terminology; (4) logical contradictions in how tables "
    "relate or what they represent; (5) misidentified table purpose. Report only "
    "MATERIAL issues (contradictions, wrong purpose, cardinality errors, terminology "
    "conflicts) — ignore wording/style. Name the affected table for each issue."
)


def sanity_check(desc, relations):
    """Cross-table consistency review. Returns list of material issues and
    lowers confidence on flagged tables' columns."""
    payload = {"tables": []}
    fk_by_child = {}
    for f in relations.get("foreign_keys", []):
        fk_by_child.setdefault(f["child_table"], []).append(
            f'{f["child_column"]}->{f["parent_table"]}')
    for t, td in desc["tables"].items():
        payload["tables"].append({
            "name": t,
            "description": td["table_description"],
            "foreign_keys": fk_by_child.get(t, []),
            "columns": [{"name": c["name"], "description": c["description"]}
                        for c in td["columns"]],
        })
    obj, _ = claude_json(
        "Review these related table descriptions for material inconsistencies.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2),
        SANITY_SCHEMA, system=SANITY_SYSTEM, max_tokens=4096)

    issues = obj.get("tableIssues", [])
    flagged = {i["table"] for i in issues if i.get("severity") in ("medium", "high")}
    for t in flagged:
        if t in desc["tables"]:
            for c in desc["tables"][t]["columns"]:
                if c.get("confidence") is not None:
                    c["confidence"] = round(c["confidence"] * 0.8, 2)
                    c["sanity_flagged"] = True
    return {"hasMaterialIssues": obj.get("hasMaterialIssues", False),
            "issues": issues, "flagged_tables": sorted(flagged)}
