"""Description editing + review (approve/reject) + revision history."""
from fastapi import APIRouter, Depends, HTTPException
from ..deps import get_session
from ..schemas import DescriptionPatch, ReviewIn
from ...store import repo

router = APIRouter(prefix="/api/descriptions", tags=["descriptions"])


def _out(d):
    return {"id": d.id, "level": d.level, "table_name": d.table_name,
            "column_name": d.column_name, "ai_text": d.ai_text,
            "current_text": d.current_text, "status": d.status,
            "confidence": d.confidence}


@router.patch("/{desc_id}")
def edit(desc_id: int, body: DescriptionPatch, s=Depends(get_session)):
    d = repo.edit_description(s, desc_id, body.current_text, body.actor, body.note)
    if not d:
        raise HTTPException(404, "description not found")
    return _out(d)


@router.post("/{desc_id}/approve")
def approve(desc_id: int, body: ReviewIn, s=Depends(get_session)):
    d = repo.review_description(s, desc_id, "approve", body.actor, body.note)
    if not d:
        raise HTTPException(404, "description not found")
    return _out(d)


@router.post("/{desc_id}/reject")
def reject(desc_id: int, body: ReviewIn, s=Depends(get_session)):
    d = repo.review_description(s, desc_id, "reject", body.actor, body.note)
    if not d:
        raise HTTPException(404, "description not found")
    return _out(d)


@router.get("/{desc_id}/revisions")
def revisions(desc_id: int, s=Depends(get_session)):
    return [{"id": r.id, "action": r.action, "before_text": r.before_text,
             "after_text": r.after_text, "actor": r.actor, "note": r.note,
             "created_at": str(r.created_at)} for r in repo.list_revisions(s, desc_id)]
