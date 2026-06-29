"""Metastore engine + Session factory + connection config.

Connection comes from env (see config.cfg):
  METASTORE_URL  — full SQLAlchemy URL, OR assembled from:
  METASTORE_HOST / METASTORE_PORT / METASTORE_DB / METASTORE_USER /
  METASTORE_PASSWORD  (MySQL, charset utf8mb4)

`enabled()` is False when no metastore is configured — callers then fall
back to file-based storage, so the DB is optional.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg  # noqa: E402

_engine = None
_Session = None


def metastore_url():
    url = cfg("METASTORE_URL")
    if url:
        return url
    host = cfg("METASTORE_HOST")
    if not host:
        return None
    port = cfg("METASTORE_PORT", "3306")
    db = cfg("METASTORE_DB", "db2doc")
    user = cfg("METASTORE_USER", "db2doc")
    pw = cfg("METASTORE_PASSWORD", "")
    return f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"


def enabled():
    return metastore_url() is not None


def engine():
    global _engine
    if _engine is None:
        url = metastore_url()
        if not url:
            raise RuntimeError("metastore not configured (set METASTORE_URL "
                               "or METASTORE_HOST/...)")
        from sqlalchemy import create_engine
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600,
                                future=True)
    return _engine


def Session():
    global _Session
    if _Session is None:
        from sqlalchemy.orm import sessionmaker
        _Session = sessionmaker(bind=engine(), expire_on_commit=False,
                                future=True)
    return _Session()


def init_db():
    """Create all metastore tables (idempotent)."""
    from .models import Base
    Base.metadata.create_all(engine())


def ddl_sql():
    """Return the CREATE TABLE DDL (for docs / manual provisioning)."""
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects import mysql
    from .models import Base
    out = []
    for t in Base.metadata.sorted_tables:
        out.append(str(CreateTable(t).compile(dialect=mysql.dialect()))
                   .strip() + ";")
    return "\n\n".join(out)
