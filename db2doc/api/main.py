"""FastAPI app: metastore-backed schema documentation studio."""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from ..store import db
from .routers import sources, scans, jobs, catalog, descriptions, export

app = FastAPI(title="db2doc", version="0.1.0")


@app.on_event("startup")
def _startup():
    db.init_db()  # create_all (idempotent)


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(sources.router)
app.include_router(scans.router)
app.include_router(jobs.router)
app.include_router(catalog.router)
app.include_router(descriptions.router)
app.include_router(export.router)

# serve the SPA
_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_WEB):
    app.mount("/app", StaticFiles(directory=_WEB, html=True), name="web")


@app.get("/")
def root():
    return RedirectResponse("/app/")
