"""Background job orchestration: scan (profile+relations) and infer (describe).

Each job runs in a worker thread with its OWN Session. Progress/phase are
committed in short transactions so the UI poll reflects them immediately.
"""
import traceback
from datetime import datetime
from ..store import db, repo
from ..targets import engine as TE
from ..pipeline import profiler, relations as rel, describe as desc_mod


def _engine_for(src):
    return TE.build_engine(src.dialect, src.host, src.port, src.database_name,
                          src.username, repo.source_password(src),
                          src.connect_options or {})


def submit_scan(source_id):
    """Create job+scan rows, return (job_id, scan_id) for immediate response."""
    s = db.Session()
    try:
        scan = repo.create_scan(s, source_id, status="pending")
        job = repo.create_job(s, source_id, "scan", scan_id=scan.id)
        return job.id, scan.id
    finally:
        s.close()


def submit_infer(source_id, scan_id):
    s = db.Session()
    try:
        job = repo.create_job(s, source_id, "infer", scan_id=scan_id)
        return job.id
    finally:
        s.close()


def run_scan(job_id, scan_id, source_id):
    """Profile + recover relations, persist to metastore. Worker thread."""
    s = db.Session()
    try:
        repo.update_job(s, job_id, state="running", phase="connecting",
                        started_at=datetime.utcnow())
        src = repo.get_source(s, source_id)
        eng = _engine_for(src)
        schema = src.db_schema

        def prog(i, n, t):
            repo.update_job(s, job_id, phase=f"profiling {i}/{n}",
                            progress=round(0.1 + 0.6 * i / n, 3), message=t)

        repo.update_job(s, job_id, phase="profiling", progress=0.1)
        profile = profiler.profile_schema(eng, schema, progress=prog)
        repo.update_job(s, job_id, phase="recovering relations", progress=0.75)
        relations = rel.recover_relations(eng, schema, profile)
        repo.save_profile_and_relations(s, scan_id, source_id, profile, relations)
        repo.finish_scan(s, scan_id, status="done")
        repo.update_source(s, source_id, last_scan_id=scan_id)
        repo.update_job(s, job_id, state="succeeded", progress=1.0,
                        phase="done", finished_at=datetime.utcnow())
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1500]}"
        repo.update_job(s, job_id, state="failed", error=err,
                        finished_at=datetime.utcnow())
        try:
            repo.finish_scan(s, scan_id, status="failed", error=str(e)[:500])
        except Exception:
            pass
    finally:
        s.close()


def run_infer(job_id, scan_id, source_id):
    """Generate descriptions from the scan's profile+relations, persist."""
    s = db.Session()
    try:
        repo.update_job(s, job_id, state="running", phase="loading scan",
                        started_at=datetime.utcnow(), progress=0.05)
        # rebuild profile/relations dicts from the metastore
        profile = _profile_from_store(s, scan_id)
        relations = _relations_from_store(s, scan_id)

        def prog(i, n, t):
            repo.update_job(s, job_id, phase=f"describing {i}/{n}",
                            progress=round(0.1 + 0.85 * i / n, 3), message=t)

        repo.update_job(s, job_id, phase="describing", progress=0.1)
        desc = desc_mod.describe(profile, relations, progress=prog)
        repo.save_descriptions(s, scan_id, source_id, desc)
        repo.update_job(s, job_id, state="succeeded", progress=1.0,
                        phase="done", finished_at=datetime.utcnow())
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1500]}"
        repo.update_job(s, job_id, state="failed", error=err,
                        finished_at=datetime.utcnow())
    finally:
        s.close()


def _profile_from_store(s, scan_id):
    tables = repo.scan_tables(s, scan_id)
    out = {"schema": "", "tables": {}}
    for t in tables:
        out["tables"][t.name] = {
            "rowcount": t.row_count,
            "columns": [{"name": c.name, "data_type": c.data_type,
                         "nullable": c.nullable, "position": c.position,
                         "stats": c.stats} for c in sorted(t.columns,
                                                           key=lambda x: x.position)],
        }
    return out


def _relations_from_store(s, scan_id):
    rels = repo.scan_relations(s, scan_id)
    pks, fks = {}, []
    for r in rels:
        if r.kind == "pk":
            pks[r.child_table] = {"column": r.child_column, "score": r.score}
        else:
            fks.append({"child_table": r.child_table, "child_column": r.child_column,
                        "parent_table": r.parent_table, "parent_column": r.parent_column,
                        "inclusion": r.inclusion, "name_sim": r.name_sim,
                        "score": r.score})
    return {"primary_keys": pks, "foreign_keys": fks}
