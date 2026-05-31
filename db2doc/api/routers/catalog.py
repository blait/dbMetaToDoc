"""Catalog assembly — returns the DATA shape the frontend SPA expects.

Mirrors ui/build_ui.py build_dataset(), but sourced from the metastore and
including each description's id/status so the UI can edit/approve inline.
"""
from fastapi import APIRouter, Depends, HTTPException
from ..deps import get_session
from ...store import repo

router = APIRouter(prefix="/api/sources", tags=["catalog"])


def _assemble(s, source_id, scan_id):
    tables = repo.scan_tables(s, scan_id)
    rels = repo.scan_relations(s, scan_id)
    descs = repo.scan_descriptions(s, scan_id)

    pk_by_table = {r.child_table: r.child_column for r in rels if r.kind == "pk"}
    fk_by_child = {}
    for r in rels:
        if r.kind == "fk":
            fk_by_child.setdefault(r.child_table, []).append(r)

    # index descriptions by (level, table, column)
    d_db = None
    d_table = {}
    d_col = {}
    for d in descs:
        if d.level == "db":
            d_db = d
        elif d.level == "table":
            d_table[d.table_name] = d
        else:
            d_col[(d.table_name, d.column_name)] = d

    out_tables = []
    for t in tables:
        cols = []
        for c in sorted(t.columns, key=lambda x: x.position):
            st = c.stats or {}
            d = d_col.get((t.name, c.name))
            cols.append({
                "name": c.name,
                "description": d.current_text if d else "",
                "ai_text": d.ai_text if d else "",
                "confidence": (d.confidence if d else None),
                "status": (d.status if d else None),
                "description_id": (d.id if d else None),
                "type": c.data_type,
                "nullable": c.nullable,
                "evidence": {
                    "distinct_ratio": st.get("distinct_ratio"),
                    "null_ratio": st.get("null_ratio"),
                    "examples": st.get("examples", []),
                    "top_values": (st.get("top_values", []) or [])[:6],
                    "min": st.get("min"), "max": st.get("max"),
                },
                "truth": None,
            })
        td = d_table.get(t.name)
        out_tables.append({
            "name": t.name,
            "rowcount": t.row_count,
            "table_description": td.current_text if td else "",
            "table_description_id": td.id if td else None,
            "table_status": td.status if td else None,
            "table_truth": None,
            "pk": pk_by_table.get(t.name),
            "fks": [{"col": r.child_column, "ref_table": r.parent_table,
                     "ref_col": r.parent_column, "inclusion": r.inclusion}
                    for r in fk_by_child.get(t.name, [])],
            "columns": cols,
        })
    out_tables.sort(key=lambda t: (-t["rowcount"], t["name"]))

    src = repo.get_source(s, source_id)
    return {
        "source": {
            "id": source_id,
            "name": (d_db.current_text[:60] if d_db else src.name),
            "title": src.name,
            "dialect": src.dialect,
            "db_description": d_db.current_text if d_db else "",
            "model": repo.get_source(s, source_id) and "",
            "schema": src.db_schema,
            "usage": {},
        },
        "tables": out_tables,
        "score": {},
    }


@router.get("/{source_id}/catalog")
def catalog(source_id: int, s=Depends(get_session)):
    src = repo.get_source(s, source_id)
    if not src:
        raise HTTPException(404, "source not found")
    if not src.last_scan_id:
        # no scan yet: return empty shell so UI can still render + offer Scan
        return {"source": {"id": source_id, "name": src.name, "title": src.name,
                           "dialect": src.dialect, "db_description": "",
                           "schema": src.db_schema, "usage": {}},
                "tables": [], "score": {}}
    return _assemble(s, source_id, src.last_scan_id)
