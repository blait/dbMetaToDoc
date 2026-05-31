"""Pydantic DTOs for the API (never expose secrets)."""
from typing import Optional, Any
from pydantic import BaseModel


class SourceIn(BaseModel):
    name: str
    dialect: str                 # postgresql|mysql|mariadb
    host: str
    port: Optional[int] = None
    database_name: str
    db_schema: str
    username: str
    password: str = ""
    connect_options: dict = {}


class SourcePatch(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database_name: Optional[str] = None
    db_schema: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    connect_options: Optional[dict] = None


class SourceOut(BaseModel):
    id: int
    name: str
    dialect: str
    host: str
    port: Optional[int]
    database_name: str
    db_schema: str
    username: str
    last_scan_id: Optional[int]
    # NOTE: password / secret_ref intentionally omitted

    @classmethod
    def of(cls, src):
        return cls(id=src.id, name=src.name, dialect=src.dialect, host=src.host,
                   port=src.port, database_name=src.database_name,
                   db_schema=src.db_schema, username=src.username,
                   last_scan_id=src.last_scan_id)


class DescriptionPatch(BaseModel):
    current_text: str
    actor: Optional[str] = None
    note: Optional[str] = None


class ReviewIn(BaseModel):
    actor: Optional[str] = None
    note: Optional[str] = None


class JobOut(BaseModel):
    id: int
    kind: str
    state: str
    progress: float
    phase: Optional[str]
    message: Optional[str]
    error: Optional[str]
    scan_id: Optional[int]

    @classmethod
    def of(cls, j):
        return cls(id=j.id, kind=j.kind, state=j.state, progress=j.progress,
                   phase=j.phase, message=j.message, error=j.error, scan_id=j.scan_id)
