"""CRUD / sync helpers over the metastore.

  upsert_run(run_key, catalog, concepts, meta) — load a finished run into DB
  load_run(run_key)  — reconstruct the catalog dict the UI expects
  list_runs()        — run summaries for the home page
  edit_description(run_key, table, column, text, actor) — human review + audit
  delete_run(run_key)
"""
from datetime import datetime, timezone

from .db import Session
from .models import (Run, Table, Column, Description, Revision, Concept,
                     ConceptRelation, T2SQLHistory, VerifiedQuery,
                     RunArtifact)


# ------------------------------------------------------------------ write
def upsert_run(run_key, catalog, concepts=None, meta=None):
    """Replace a run's catalog in the metastore (idempotent by run_key).

    AI descriptions are stored as `ai_text`; if a Description row already
    has human edits (edited=True), the edit is preserved across re-syncs."""
    meta = meta or {}
    db = catalog.get("database", {})
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        # preserve prior human edits before wiping the catalog rows
        prior_edits = {}
        if run:
            for d in s.query(Description).filter_by(run_id=run.id):
                if d.edited:
                    prior_edits[(d.level, d.table_name, d.column_name)] = d
            # clear old catalog rows (tables cascade to columns)
            for t in list(run.tables):
                s.delete(t)
            s.query(Description).filter_by(run_id=run.id).delete()
            s.query(Concept).filter_by(run_id=run.id).delete()
            s.query(ConceptRelation).filter_by(run_id=run.id).delete()
        else:
            run = Run(run_key=run_key)
            s.add(run)

        run.name = meta.get("name", run_key)
        run.host = meta.get("host")
        run.port = meta.get("port")
        run.dbname = meta.get("dbname")
        run.schema_name = catalog.get("schema") or meta.get("schema")
        run.domain = db.get("domain")
        run.error = meta.get("error")
        run.model = catalog.get("model")
        run.status = meta.get("status", "done")
        run.with_truth = bool(meta.get("with_truth"))
        run.graph_id = meta.get("graph_id")
        run.table_count = len(catalog.get("tables", []))
        run.column_count = sum(len(t["columns"])
                               for t in catalog.get("tables", []))
        run.score = meta.get("score")
        # DB-level description (AI + reviewed)
        run.ai_db_description = db.get("ai_db_description") or db.get(
            "db_description")
        run.db_description = db.get("db_description")
        s.flush()

        def _desc(level, tname, cname, text, ai_text, conf, edited):
            key = (level, tname, cname)
            prev = prior_edits.get(key)
            d = Description(run_id=run.id, level=level, table_name=tname,
                            column_name=cname,
                            ai_text=ai_text, current_text=text,
                            confidence=conf, edited=edited)
            if prev:  # keep the human edit
                d.current_text = prev.current_text
                d.edited = True
                d.reviewed_by = prev.reviewed_by
                d.reviewed_at = prev.reviewed_at
            s.add(d)

        _desc("db", None, None, run.db_description, run.ai_db_description,
              None, bool(db.get("edited")))

        for t in catalog.get("tables", []):
            pk = t.get("primary_key") or {}
            tbl = Table(run_id=run.id, name=t["name"],
                        row_count=t.get("rowcount", 0),
                        pk_columns=", ".join(pk.get("columns", []) or []),
                        pk_source=pk.get("source"),
                        original_comment=t.get("original_comment"))
            run.tables.append(tbl)
            s.flush()
            _desc("table", t["name"], None, t.get("description", ""),
                  t.get("ai_description") or t.get("description", ""),
                  None, bool(t.get("edited")))
            fk_conf = {f["column"]: f.get("confidence")
                       for f in t.get("foreign_keys", [])}
            for c in t["columns"]:
                c = {**c, "fk_confidence": fk_conf.get(c["name"])}
                tbl.columns.append(Column(
                    name=c["name"], data_type=c.get("type", ""),
                    nullable=bool(c.get("nullable")),
                    is_pk=bool(c.get("is_pk")),
                    fk_ref=c.get("fk"), fk_source=c.get("fk_source"),
                    fk_confidence=c.get("fk_confidence"),
                    original_comment=c.get("original_comment"),
                    data_unverified=bool(c.get("data_unverified")),
                    stats=c.get("stats"), evidence=c.get("evidence")))
                _desc("column", t["name"], c["name"],
                      c.get("description", ""),
                      c.get("ai_description") or c.get("description", ""),
                      c.get("confidence"), bool(c.get("edited")))

        if concepts:
            for c in concepts.get("concepts", []):
                s.add(Concept(
                    run_id=run.id, name=c["name"], name_ko=c.get("name_ko"),
                    description=c.get("description"),
                    synonyms=", ".join(c.get("synonyms", []))
                    if isinstance(c.get("synonyms"), list) else c.get("synonyms"),
                    is_a=c.get("is_a"), confidence=c.get("confidence"),
                    mapped_tables=c.get("tables"),
                    key_columns=c.get("key_columns")))
            for r in concepts.get("relations", []):
                s.add(ConceptRelation(
                    run_id=run.id, name=r["name"],
                    src_concept=r["src"], dst_concept=r["dst"],
                    cardinality=r.get("cardinality"), via=r.get("via"),
                    description=r.get("description"),
                    confidence=r.get("confidence")))
        s.commit()
        return run.run_key


# --------------------------------------------------------------- lifecycle
def create_run(run_key, meta):
    """Insert a placeholder run (status=running) before analysis begins, so
    the home page can show it immediately. Idempotent on run_key."""
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            run = Run(run_key=run_key)
            s.add(run)
        run.name = meta.get("name", run_key)
        run.host = meta.get("host")
        run.port = meta.get("port")
        run.dbname = meta.get("dbname")
        run.schema_name = meta.get("schema")
        run.with_truth = bool(meta.get("with_truth"))
        run.status = meta.get("status", "running")
        s.commit()
        return run.run_key


def set_status(run_key, status, error=None, graph_id=None):
    """Update a run's status/error/graph_id without touching the catalog."""
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            return False
        run.status = status
        if error is not None:
            run.error = error
        if graph_id is not None:
            run.graph_id = graph_id
        s.commit()
        return True


# ------------------------------------------------------------------ read
def _run_summary(r):
    return {
        "id": r.run_key, "name": r.name, "schema": r.schema_name,
        "host": r.host, "port": r.port, "dbname": r.dbname,
        "with_truth": r.with_truth, "status": r.status, "error": r.error,
        "graph_id": r.graph_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "headline": {"tables": r.table_count, "columns": r.column_count,
                     "domain": r.domain, "gen_model": r.model,
                     **(r.score or {})},
    }


def list_runs():
    with Session() as s:
        return [_run_summary(r)
                for r in s.query(Run).order_by(Run.created_at.desc())]


def get_run(run_key):
    with Session() as s:
        r = s.query(Run).filter_by(run_key=run_key).one_or_none()
        return _run_summary(r) if r else None


def run_graph_id(run_key):
    with Session() as s:
        r = s.query(Run).filter_by(run_key=run_key).one_or_none()
        return r.graph_id if r else None


def load_run(run_key):
    """Rebuild the catalog dict the viewer expects (with edits applied).

    Eager-loads tables→columns in one round trip (selectinload) — lazy loading
    fires one SELECT per table, which is slow over a high-latency link."""
    from sqlalchemy.orm import selectinload
    with Session() as s:
        run = (s.query(Run).filter_by(run_key=run_key)
               .options(selectinload(Run.tables).selectinload(Table.columns))
               .one_or_none())
        if not run:
            return None
        descs = {}
        for d in s.query(Description).filter_by(run_id=run.id):
            descs[(d.level, d.table_name, d.column_name)] = d
        tables = []
        for t in sorted(run.tables, key=lambda x: x.name):
            td = descs.get(("table", t.name, None))
            cols = []
            for c in t.columns:
                cd = descs.get(("column", t.name, c.name))
                cols.append({
                    "name": c.name, "type": c.data_type,
                    "nullable": c.nullable, "is_pk": c.is_pk,
                    "fk": c.fk_ref, "fk_source": c.fk_source,
                    "description": cd.current_text if cd else "",
                    "ai_description": cd.ai_text if cd else "",
                    "edited": cd.edited if cd else False,
                    "confidence": cd.confidence if cd else None,
                    "original_comment": c.original_comment,
                    "has_original": bool(c.original_comment),
                    "data_unverified": c.data_unverified,
                    "evidence": c.evidence, "stats": c.stats or {},
                })
            tables.append({
                "name": t.name, "rowcount": t.row_count,
                "description": td.current_text if td else "",
                "ai_description": td.ai_text if td else "",
                "edited": td.edited if td else False,
                "original_comment": t.original_comment,
                "has_original": bool(t.original_comment),
                "primary_key": ({"columns": t.pk_columns.split(", "),
                                 "source": t.pk_source} if t.pk_columns else None),
                "foreign_keys": [
                    {"column": c.name, "ref": c.fk_ref,
                     "source": c.fk_source, "confidence": c.fk_confidence}
                    for c in t.columns if c.fk_ref],
                "columns": cols,
            })
        dbd = descs.get(("db", None, None))
        return {
            "schema": run.schema_name, "model": run.model,
            "database": {"domain": run.domain,
                         "db_description": dbd.current_text if dbd else run.db_description,
                         "ai_db_description": run.ai_db_description,
                         "edited": dbd.edited if dbd else False},
            "tables": tables,
        }


def load_concepts(run_key):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            return None
        rows = s.query(Concept).filter_by(run_id=run.id).all()
        concepts, isa, maps = [], [], []
        for c in rows:
            concepts.append({"name": c.name, "name_ko": c.name_ko,
                             "description": c.description,
                             "synonyms": c.synonyms,
                             "is_a": c.is_a,
                             "confidence": c.confidence,
                             "tables": c.mapped_tables or [],
                             "key_columns": c.key_columns or []})
            if c.is_a:
                isa.append({"child": c.name, "parent": c.is_a})
            for t in (c.mapped_tables or []):
                maps.append({"concept": c.name, "table": t,
                             "confidence": c.confidence})
        rels = [{"name": r.name, "src": r.src_concept, "dst": r.dst_concept,
                 "cardinality": r.cardinality, "via": r.via,
                 "description": r.description, "confidence": r.confidence}
                for r in s.query(ConceptRelation).filter_by(run_id=run.id)]
        return {"concepts": concepts, "is_a": isa, "mappings": maps,
                "relations": rels}


def replace_concept_relations(run_key, relations):
    """Replace this run's concept relations (backfill / re-extraction)."""
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            raise KeyError(run_key)
        s.query(ConceptRelation).filter_by(run_id=run.id).delete()
        for r in relations:
            s.add(ConceptRelation(
                run_id=run.id, name=r["name"],
                src_concept=r["src"], dst_concept=r["dst"],
                cardinality=r.get("cardinality"), via=r.get("via"),
                description=r.get("description"),
                confidence=r.get("confidence")))
        s.commit()
        return len(relations)


# ------------------------------------------------------------- artifacts
def save_artifact(run_key, name, payload):
    """Upsert a named JSON artifact (score report / details) for a run."""
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            raise KeyError(run_key)
        row = (s.query(RunArtifact)
               .filter_by(run_id=run.id, name=name).one_or_none())
        if row:
            row.payload = payload
        else:
            s.add(RunArtifact(run_id=run.id, name=name, payload=payload))
        s.commit()


def get_artifact(run_key, name):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            return None
        row = (s.query(RunArtifact)
               .filter_by(run_id=run.id, name=name).one_or_none())
        return row.payload if row else None


# ------------------------------------------------------------ verified qs
def add_verified_query(run_key, entry):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            raise KeyError(run_key)
        s.add(VerifiedQuery(
            run_id=run.id, question=entry.get("question", ""),
            sql=entry.get("sql"), rowcount=entry.get("rowcount"),
            ok=bool(entry.get("ok"))))
        s.commit()


def get_verified_queries(run_key, ok_only=True):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            return []
        q = s.query(VerifiedQuery).filter_by(run_id=run.id)
        if ok_only:
            q = q.filter_by(ok=True)
        return [{"question": v.question, "sql": v.sql,
                 "rowcount": v.rowcount, "ok": v.ok,
                 "created_at": v.created_at.isoformat() if v.created_at else None}
                for v in q.order_by(VerifiedQuery.id.asc())]


def clear_verified_queries(run_key):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if run:
            s.query(VerifiedQuery).filter_by(run_id=run.id).delete()
            s.commit()


# ------------------------------------------------------------------ edit
def edit_description(run_key, table, column, text, actor="reviewer"):
    """Human review: update current_text, keep ai_text, append a revision."""
    level = ("db" if table == "__db__"
             else "column" if column else "table")
    tname = None if table == "__db__" else table
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            raise KeyError(run_key)
        d = s.query(Description).filter_by(
            run_id=run.id, level=level, table_name=tname,
            column_name=column).one_or_none()
        before = d.current_text if d else None
        if not d:
            d = Description(run_id=run.id, level=level, table_name=tname,
                            column_name=column, ai_text=text)
            s.add(d)
        d.current_text = text
        d.edited = True
        d.reviewed_by = actor
        d.reviewed_at = datetime.now(timezone.utc)
        if level == "db":
            run.db_description = text
        s.add(Revision(run_id=run.id, level=level, table_name=tname,
                       column_name=column, before_text=before,
                       after_text=text, actor=actor))
        s.commit()
        return {"ok": True}


def delete_run(run_key):
    """Bulk-delete a run and all its rows (FK-safe order, no ORM cascade —
    396 per-row DELETEs over a flaky link deadlock; set-based DELETEs don't)."""
    from sqlalchemy import delete as sa_delete
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            return False
        rid = run.id
        col_ids = s.query(Column.id).join(
            Table, Column.table_id == Table.id).filter(Table.run_id == rid)
        s.execute(sa_delete(Column).where(Column.id.in_(col_ids.subquery())))
        s.execute(sa_delete(Table).where(Table.run_id == rid))
        for model in (Description, Concept, ConceptRelation, Revision,
                      T2SQLHistory, VerifiedQuery, RunArtifact):
            s.execute(sa_delete(model).where(model.run_id == rid))
        s.execute(sa_delete(Run).where(Run.id == rid))
        s.commit()
        return True


# --------------------------------------------------------- text2sql history
def add_t2sql_history(run_key, entry):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            raise KeyError(run_key)
        s.add(T2SQLHistory(
            run_id=run.id, question=entry.get("question", ""),
            ok=bool(entry.get("ok")), rowcount=entry.get("rowcount"),
            attempts=entry.get("attempts"), sql=entry.get("sql"),
            steps=entry.get("steps")))
        # cap history at 100 newest per run
        ids = [h.id for h in s.query(T2SQLHistory.id)
               .filter_by(run_id=run.id)
               .order_by(T2SQLHistory.created_at.desc()).all()]
        for old in ids[100:]:
            s.query(T2SQLHistory).filter_by(id=old).delete()
        s.commit()


def get_t2sql_history(run_key):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if not run:
            return []
        rows = (s.query(T2SQLHistory).filter_by(run_id=run.id)
                .order_by(T2SQLHistory.created_at.desc()).all())
        return [{"ts": h.created_at.isoformat() if h.created_at else None,
                 "question": h.question, "ok": h.ok, "rowcount": h.rowcount,
                 "attempts": h.attempts, "sql": h.sql, "steps": h.steps}
                for h in rows]


def clear_t2sql_history(run_key):
    with Session() as s:
        run = s.query(Run).filter_by(run_key=run_key).one_or_none()
        if run:
            s.query(T2SQLHistory).filter_by(run_id=run.id).delete()
            s.commit()
