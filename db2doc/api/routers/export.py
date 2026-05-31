"""Export the current (edited) descriptions as SQL / MD / CSV / Mermaid."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from ..deps import get_session
from ...store import repo
from ...pipeline import render
from ...jobs import runner

router = APIRouter(prefix="/api/sources", tags=["export"])


def _desc_dict(s, scan_id):
    """Rebuild the descriptions dict (current_text) for the renderer."""
    descs = repo.scan_descriptions(s, scan_id)
    tables = {}
    db_text = ""
    for d in descs:
        if d.level == "db":
            db_text = d.current_text
        elif d.level == "table":
            tables.setdefault(d.table_name, {"table_description": "", "columns": []})
            tables[d.table_name]["table_description"] = d.current_text
        else:
            tables.setdefault(d.table_name, {"table_description": "", "columns": []})
            tables[d.table_name]["columns"].append(
                {"name": d.column_name, "description": d.current_text,
                 "confidence": d.confidence})
    return {"db": {"db_description": db_text, "domain": ""},
            "tables": tables, "model": "db2doc"}


@router.get("/{source_id}/export")
def export(source_id: int, format: str = "sql", s=Depends(get_session)):
    src = repo.get_source(s, source_id)
    if not src or not src.last_scan_id:
        raise HTTPException(404, "no scan to export")
    scan_id = src.last_scan_id
    desc = _desc_dict(s, scan_id)
    relations = runner._relations_from_store(s, scan_id)
    if format == "md":
        return PlainTextResponse(render.to_markdown(desc, relations, src.db_schema))
    if format == "sql":
        return PlainTextResponse(render.to_sql(desc, src.db_schema, src.dialect))
    if format == "csv":
        return PlainTextResponse(render.to_csv(desc), media_type="text/csv")
    if format == "mermaid":
        return PlainTextResponse(render.to_mermaid(desc, relations))
    raise HTTPException(400, "format must be sql|md|csv|mermaid")
