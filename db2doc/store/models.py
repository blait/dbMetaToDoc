"""Metastore ORM (MySQL via SQLAlchemy 2.0)."""
from datetime import datetime
from sqlalchemy import (String, Integer, BigInteger, Float, Boolean, Text,
                        DateTime, ForeignKey, JSON, UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    dialect: Mapped[str] = mapped_column(String(32))          # postgresql|mysql|...
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database_name: Mapped[str] = mapped_column(String(255))
    db_schema: Mapped[str] = mapped_column(String(255))       # PG namespace / MySQL db
    username: Mapped[str] = mapped_column(String(255))
    secret_ref: Mapped[str] = mapped_column(Text)             # encrypted password
    connect_options: Mapped[dict] = mapped_column(JSON, default=dict)
    last_scan_id: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(),
                                                 onupdate=func.now())


class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    token_in: Mapped[int] = mapped_column(Integer, default=0)
    token_out: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)


class Table(Base):
    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("scan_id", "name", name="uq_scan_table"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    recovered_pk: Mapped[str] = mapped_column(String(255), nullable=True)
    columns: Mapped[list["Column"]] = relationship(
        back_populates="table", cascade="all, delete-orphan")


class Column(Base):
    __tablename__ = "columns"
    __table_args__ = (UniqueConstraint("table_id", "name", name="uq_table_col"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("tables.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[str] = mapped_column(String(128))
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    table: Mapped["Table"] = relationship(back_populates="columns")


class Relation(Base):
    __tablename__ = "relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))              # pk|fk
    child_table: Mapped[str] = mapped_column(String(255))
    child_column: Mapped[str] = mapped_column(String(255), nullable=True)
    parent_table: Mapped[str] = mapped_column(String(255), nullable=True)
    parent_column: Mapped[str] = mapped_column(String(255), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    inclusion: Mapped[float] = mapped_column(Float, nullable=True)
    name_sim: Mapped[float] = mapped_column(Float, nullable=True)


class Description(Base):
    __tablename__ = "descriptions"
    __table_args__ = (UniqueConstraint("scan_id", "level", "table_name",
                                       "column_name", name="uq_desc"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String(8))             # db|table|column
    table_name: Mapped[str] = mapped_column(String(255), nullable=True)
    column_name: Mapped[str] = mapped_column(String(255), nullable=True)
    ai_text: Mapped[str] = mapped_column(Text)               # immutable original
    current_text: Mapped[str] = mapped_column(Text)          # edited current
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|rejected|edited
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    description_id: Mapped[int] = mapped_column(ForeignKey("descriptions.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))          # edit|approve|reject
    before_text: Mapped[str] = mapped_column(Text, nullable=True)
    after_text: Mapped[str] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    scan_id: Mapped[int] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))            # scan|infer|full
    state: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    phase: Mapped[str] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
