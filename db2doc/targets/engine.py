"""Build SQLAlchemy engines for target databases (multi-DBMS)."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

DRIVERS = {
    "postgresql": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "mariadb": "mysql+pymysql",
}


def build_engine(dialect, host, port, database, username, password,
                 connect_options=None):
    """Create an Engine for a target DB. `dialect` in DRIVERS."""
    drivername = DRIVERS.get(dialect)
    if not drivername:
        raise ValueError(f"unsupported dialect: {dialect}")
    url = URL.create(
        drivername, username=username, password=password,
        host=host, port=int(port) if port else None, database=database,
        query=connect_options or {},
    )
    return create_engine(url, pool_pre_ping=True,
                         connect_args={"connect_timeout": 15})


def test_connection(engine):
    """Return (ok, message). Runs SELECT 1."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"
