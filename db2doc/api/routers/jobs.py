"""Job polling."""
from fastapi import APIRouter, Depends, HTTPException
from ..deps import get_session
from ..schemas import JobOut
from ...store import repo

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/{job_id}")
def get_job(job_id: int, s=Depends(get_session)):
    j = repo.get_job(s, job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return JobOut.of(j)


@router.get("/sources/{source_id}/jobs")
def list_jobs(source_id: int, s=Depends(get_session)):
    return [JobOut.of(j) for j in repo.list_jobs(s, source_id)]
