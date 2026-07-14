"""Metastore ORM (MySQL via SQLAlchemy 2.0) — v2.

Extends the v1 schema to cover everything v2 produces:
  - original DB comments (preserved verbatim, rule-based)
  - FK provenance (declared/stat/llm/name) + confidence
  - ontology concepts (IS_A hierarchy, MAPPED_TO)
  - per-run dedicated graph id, evidence ledger, data_unverified
  - human-review audit trail (AI original is immutable; edits tracked)
"""
from datetime import datetime
from sqlalchemy import (String, Integer, BigInteger, Float, Boolean, Text,
                        DateTime, ForeignKey, JSON, UniqueConstraint, func)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            relationship)


class Base(DeclarativeBase):
    pass


class Source(Base):
    """A connected database (one per distinct target)."""
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    dialect: Mapped[str] = mapped_column(String(32), default="postgresql")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database_name: Mapped[str] = mapped_column(String(255))
    db_schema: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=True)   # encrypted pw
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())


class Run(Base):
    """One analysis run (== a `runs/<id>` directory)."""
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"),
                                           nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    host: Mapped[str] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, nullable=True)
    dbname: Mapped[str] = mapped_column(String(255), nullable=True)
    schema_name: Mapped[str] = mapped_column(String(255), nullable=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    db_description: Mapped[str] = mapped_column(Text, nullable=True)
    ai_db_description: Mapped[str] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="done")
    with_truth: Mapped[bool] = mapped_column(Boolean, default=False)
    graph_id: Mapped[str] = mapped_column(String(64), nullable=True)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[dict] = mapped_column(JSON, nullable=True)   # headline metrics
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())
    tables: Mapped[list["Table"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")


class Table(Base):
    __tablename__ = "cat_tables"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_run_table"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    pk_columns: Mapped[str] = mapped_column(String(512), nullable=True)
    pk_source: Mapped[str] = mapped_column(String(32), nullable=True)
    original_comment: Mapped[str] = mapped_column(Text, nullable=True)
    run: Mapped["Run"] = relationship(back_populates="tables")
    columns: Mapped[list["Column"]] = relationship(
        back_populates="table", cascade="all, delete-orphan")


class Column(Base):
    __tablename__ = "cat_columns"
    __table_args__ = (UniqueConstraint("table_id", "name", name="uq_table_col"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("cat_tables.id"),
                                          index=True)
    name: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[str] = mapped_column(String(128))
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_pk: Mapped[bool] = mapped_column(Boolean, default=False)
    fk_ref: Mapped[str] = mapped_column(String(512), nullable=True)
    fk_source: Mapped[str] = mapped_column(String(32), nullable=True)
    fk_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    original_comment: Mapped[str] = mapped_column(Text, nullable=True)
    data_unverified: Mapped[bool] = mapped_column(Boolean, default=False)
    stats: Mapped[dict] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=True)
    table: Mapped["Table"] = relationship(back_populates="columns")


class Description(Base):
    """db/table/column description: AI original (immutable) + reviewed."""
    __tablename__ = "descriptions"
    __table_args__ = (UniqueConstraint("run_id", "level", "table_name",
                                       "column_name", name="uq_desc"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    level: Mapped[str] = mapped_column(String(8))            # db|table|column
    table_name: Mapped[str] = mapped_column(String(255), nullable=True)
    column_name: Mapped[str] = mapped_column(String(255), nullable=True)
    ai_text: Mapped[str] = mapped_column(Text, nullable=True)   # immutable
    current_text: Mapped[str] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Revision(Base):
    """Audit trail: every human edit/approve on a description."""
    __tablename__ = "revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String(8))
    table_name: Mapped[str] = mapped_column(String(255), nullable=True)
    column_name: Mapped[str] = mapped_column(String(255), nullable=True)
    before_text: Mapped[str] = mapped_column(Text, nullable=True)
    after_text: Mapped[str] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())


class T2SQLHistory(Base):
    """text2sql question history per run (replaces t2sql_history.json)."""
    __tablename__ = "t2sql_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    rowcount: Mapped[int] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=True)
    sql: Mapped[str] = mapped_column(Text, nullable=True)
    steps: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())


class Concept(Base):
    """Ontology concept (with IS_A parent + mapped tables/columns as JSON)."""
    __tablename__ = "concepts"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    name_ko: Mapped[str] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    synonyms: Mapped[str] = mapped_column(Text, nullable=True)
    is_a: Mapped[str] = mapped_column(String(255), nullable=True)   # parent
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    mapped_tables: Mapped[list] = mapped_column(JSON, nullable=True)
    key_columns: Mapped[list] = mapped_column(JSON, nullable=True)


class ConceptRelation(Base):
    """Semantic relation between two concepts, grounded in a recovered FK.

    e.g. (Prescription)-[PRESCRIBED_BY]->(Provider)
         via drug_exposure.provider_id -> provider.provider_id.
    Cardinality is DATA-derived (child column uniqueness), not LLM-guessed."""
    __tablename__ = "concept_relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))          # UPPER_SNAKE verb
    src_concept: Mapped[str] = mapped_column(String(255))
    dst_concept: Mapped[str] = mapped_column(String(255))
    cardinality: Mapped[str] = mapped_column(String(8), nullable=True)  # 1:1|N:1
    via: Mapped[str] = mapped_column(String(512), nullable=True)  # child.col -> parent.col
    description: Mapped[str] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())


class RunArtifact(Base):
    """Named JSON artifact for a run (e.g. score report / per-item details).

    Replaces the old runs/<id>/*.json files in the DB-only flow so the
    viewer can still show per-table/column ground-truth scoring."""
    __tablename__ = "run_artifacts"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_artifact"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())


class VerifiedQuery(Base):
    """Competency question verified by actually running text2sql on this run.

    Doubles as few-shot examples for later text2sql generations (rid-scoped)."""
    __tablename__ = "verified_queries"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text, nullable=True)
    rowcount: Mapped[int] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 server_default=func.now())
