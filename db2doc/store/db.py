"""Metastore engine + Session factory."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .. import config
from .models import Base

_engine = None
_Session = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(config.METASTORE_URL, pool_pre_ping=True,
                                pool_recycle=3600)
    return _engine


def Session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=engine(), expire_on_commit=False)
    return _Session()


def init_db():
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine())
