"""Trigger scan / infer / full jobs (background)."""
from fastapi import APIRouter, Depends, HTTPException
from ..deps import get_session
from ...store import repo
from ...jobs import runner
from ...jobs.executor import executor

router = APIRouter(prefix="/api/sources", tags=["jobs"])


@router.post("/{source_id}/scan")
def scan(source_id: int, s=Depends(get_session)):
    if not repo.get_source(s, source_id):
        raise HTTPException(404, "source not found")
    job_id, scan_id = runner.submit_scan(source_id)
    executor().submit(runner.run_scan, job_id, scan_id, source_id)
    return {"job_id": job_id, "scan_id": scan_id}


@router.post("/{source_id}/infer")
def infer(source_id: int, s=Depends(get_session)):
    src = repo.get_source(s, source_id)
    if not src:
        raise HTTPException(404, "source not found")
    if not src.last_scan_id:
        raise HTTPException(400, "no completed scan; run scan first")
    job_id = runner.submit_infer(source_id, src.last_scan_id)
    executor().submit(runner.run_infer, job_id, src.last_scan_id, source_id)
    return {"job_id": job_id, "scan_id": src.last_scan_id}


@router.post("/{source_id}/run")
def run_full(source_id: int, s=Depends(get_session)):
    """Scan then infer (chained in one worker)."""
    if not repo.get_source(s, source_id):
        raise HTTPException(404, "source not found")
    job_id, scan_id = runner.submit_scan(source_id)

    def chain():
        runner.run_scan(job_id, scan_id, source_id)
        # only infer if scan succeeded
        s2 = __import__("db2doc.store.db", fromlist=["Session"]).Session()
        try:
            job = repo.get_job(s2, job_id)
            if job and job.state == "succeeded":
                infer_job = runner.submit_infer(source_id, scan_id)
                runner.run_infer(infer_job, scan_id, source_id)
        finally:
            s2.close()

    executor().submit(chain)
    return {"job_id": job_id, "scan_id": scan_id}
