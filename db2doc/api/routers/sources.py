"""Source CRUD + connection test."""
from fastapi import APIRouter, Depends, HTTPException
from ..deps import get_session
from ..schemas import SourceIn, SourcePatch, SourceOut
from ...store import repo
from ...targets import engine as TE

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("")
def list_sources(s=Depends(get_session)):
    return [SourceOut.of(x) for x in repo.list_sources(s)]


@router.post("")
def create_source(body: SourceIn, s=Depends(get_session)):
    src = repo.create_source(
        s, name=body.name, dialect=body.dialect, host=body.host,
        port=body.port or (5432 if body.dialect == "postgresql" else 3306),
        database_name=body.database_name, db_schema=body.db_schema,
        username=body.username, password=body.password,
        connect_options=body.connect_options)
    return SourceOut.of(src)


@router.get("/{source_id}")
def get_source(source_id: int, s=Depends(get_session)):
    src = repo.get_source(s, source_id)
    if not src:
        raise HTTPException(404, "source not found")
    return SourceOut.of(src)


@router.patch("/{source_id}")
def patch_source(source_id: int, body: SourcePatch, s=Depends(get_session)):
    kw = {k: v for k, v in body.model_dump().items() if v is not None}
    src = repo.update_source(s, source_id, **kw)
    if not src:
        raise HTTPException(404, "source not found")
    return SourceOut.of(src)


@router.delete("/{source_id}")
def delete_source(source_id: int, s=Depends(get_session)):
    repo.delete_source(s, source_id)
    return {"ok": True}


@router.post("/{source_id}/test-connection")
def test_connection(source_id: int, s=Depends(get_session)):
    src = repo.get_source(s, source_id)
    if not src:
        raise HTTPException(404, "source not found")
    eng = TE.build_engine(src.dialect, src.host, src.port, src.database_name,
                          src.username, repo.source_password(src),
                          src.connect_options or {})
    ok, msg = TE.test_connection(eng)
    return {"ok": ok, "message": msg}
