"""FastAPI dependencies."""
from ..store import db


def get_session():
    s = db.Session()
    try:
        yield s
    finally:
        s.close()
