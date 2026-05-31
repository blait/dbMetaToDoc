"""CRUD / persistence helpers over the metastore ORM."""
from datetime import datetime
from sqlalchemy import select, delete
from . import crypto
from .models import (Source, Scan, Table, Column, Relation, Description,
                     Revision, Job)


# ----------------------------------------------------------------- sources
def create_source(s, **kw):
    pw = kw.pop("password", "")
    src = Source(secret_ref=crypto.encrypt(pw), **kw)
    s.add(src)
    s.commit()
    return src


def update_source(s, source_id, **kw):
    src = s.get(Source, source_id)
    if not src:
        return None
    if "password" in kw:
        pw = kw.pop("password")
        if pw:
            src.secret_ref = crypto.encrypt(pw)
    for k, v in kw.items():
        setattr(src, k, v)
    s.commit()
    return src


def get_source(s, source_id):
    return s.get(Source, source_id)


def list_sources(s):
    return list(s.scalars(select(Source).order_by(Source.id)))


def delete_source(s, source_id):
    s.execute(delete(Source).where(Source.id == source_id))
    s.commit()


def source_password(src):
    return crypto.decrypt(src.secret_ref)


# ----------------------------------------------------------------- scans
def create_scan(s, source_id, status="pending"):
    sc = Scan(source_id=source_id, status=status)
    s.add(sc)
    s.commit()
    return sc


def finish_scan(s, scan_id, **kw):
    sc = s.get(Scan, scan_id)
    for k, v in kw.items():
        setattr(sc, k, v)
    sc.finished_at = datetime.utcnow()
    s.commit()
    return sc


def save_profile_and_relations(s, scan_id, source_id, profile, relations):
    """Persist tables/columns + relations for a scan."""
    pks = relations.get("primary_keys", {})
    ncols = 0
    for tname, tinfo in profile["tables"].items():
        tbl = Table(scan_id=scan_id, source_id=source_id, name=tname,
                    row_count=tinfo["rowcount"],
                    recovered_pk=pks.get(tname, {}).get("column"))
        for c in tinfo["columns"]:
            tbl.columns.append(Column(
                name=c["name"], data_type=c["data_type"],
                nullable=c["nullable"], position=c["position"],
                stats=c["stats"]))
            ncols += 1
        s.add(tbl)
    for t, info in pks.items():
        s.add(Relation(scan_id=scan_id, kind="pk", child_table=t,
                       child_column=info["column"], score=info["score"]))
    for fk in relations.get("foreign_keys", []):
        s.add(Relation(scan_id=scan_id, kind="fk",
                       child_table=fk["child_table"], child_column=fk["child_column"],
                       parent_table=fk["parent_table"], parent_column=fk["parent_column"],
                       score=fk["score"], inclusion=fk.get("inclusion"),
                       name_sim=fk.get("name_sim")))
    sc = s.get(Scan, scan_id)
    sc.table_count = len(profile["tables"])
    sc.column_count = ncols
    s.commit()


def save_descriptions(s, scan_id, source_id, desc):
    """Persist db/table/column descriptions (status=draft)."""
    db = desc.get("db", {})
    s.add(Description(scan_id=scan_id, source_id=source_id, level="db",
                      ai_text=db.get("db_description", ""),
                      current_text=db.get("db_description", ""), confidence=None))
    for tname, td in desc["tables"].items():
        s.add(Description(scan_id=scan_id, source_id=source_id, level="table",
                          table_name=tname, ai_text=td["table_description"],
                          current_text=td["table_description"], confidence=None))
        for c in td["columns"]:
            s.add(Description(scan_id=scan_id, source_id=source_id, level="column",
                              table_name=tname, column_name=c["name"],
                              ai_text=c["description"], current_text=c["description"],
                              confidence=c.get("confidence")))
    sc = s.get(Scan, scan_id)
    sc.token_in = desc.get("usage", {}).get("input_tokens", 0)
    sc.token_out = desc.get("usage", {}).get("output_tokens", 0)
    sc.model = desc.get("model")
    s.commit()


# ----------------------------------------------------------------- catalog reads
def scan_tables(s, scan_id):
    return list(s.scalars(select(Table).where(Table.scan_id == scan_id)
                          .order_by(Table.row_count.desc(), Table.name)))


def scan_relations(s, scan_id):
    return list(s.scalars(select(Relation).where(Relation.scan_id == scan_id)))


def scan_descriptions(s, scan_id):
    return list(s.scalars(select(Description).where(Description.scan_id == scan_id)))


# ----------------------------------------------------------------- descriptions / review
def edit_description(s, desc_id, new_text, actor=None, note=None):
    d = s.get(Description, desc_id)
    if not d:
        return None
    s.add(Revision(description_id=desc_id, action="edit",
                   before_text=d.current_text, after_text=new_text,
                   actor=actor, note=note))
    d.current_text = new_text
    d.status = "edited"
    s.commit()
    return d


def review_description(s, desc_id, action, actor=None, note=None):
    d = s.get(Description, desc_id)
    if not d:
        return None
    s.add(Revision(description_id=desc_id, action=action,
                   before_text=d.current_text, after_text=d.current_text,
                   actor=actor, note=note))
    d.status = "approved" if action == "approve" else "rejected"
    d.reviewed_by = actor
    d.reviewed_at = datetime.utcnow()
    s.commit()
    return d


def list_revisions(s, desc_id):
    return list(s.scalars(select(Revision).where(Revision.description_id == desc_id)
                          .order_by(Revision.id)))


# ----------------------------------------------------------------- jobs
def create_job(s, source_id, kind, scan_id=None):
    j = Job(source_id=source_id, kind=kind, scan_id=scan_id, state="queued")
    s.add(j)
    s.commit()
    return j


def update_job(s, job_id, **kw):
    j = s.get(Job, job_id)
    for k, v in kw.items():
        setattr(j, k, v)
    s.commit()
    return j


def get_job(s, job_id):
    return s.get(Job, job_id)


def list_jobs(s, source_id):
    return list(s.scalars(select(Job).where(Job.source_id == source_id)
                          .order_by(Job.id.desc())))
