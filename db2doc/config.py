"""Central settings for the metastore product (env-driven)."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _get(key, default=None, required=False):
    v = os.environ.get(key, default)
    if required and not v:
        raise RuntimeError(f"missing required env var: {key}")
    return v


# --- metastore (MySQL) connection ---
# Full SQLAlchemy URL, or assembled from parts below.
METASTORE_URL = _get("METASTORE_URL")
if not METASTORE_URL:
    host = _get("METASTORE_HOST", "127.0.0.1")
    port = _get("METASTORE_PORT", "3306")
    db = _get("METASTORE_DB", "db2doc")
    user = _get("METASTORE_USER", "root")
    pw = _get("METASTORE_PASSWORD", "")
    METASTORE_URL = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"

# --- secret encryption (target DB passwords) ---
# Fernet key (base64, 32 bytes). If absent, crypto.py can generate/persist one.
SECRET_KEY = _get("DB2DOC_SECRET_KEY")
SECRET_KEY_FILE = _get("DB2DOC_SECRET_KEY_FILE",
                       os.path.join(os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__))), "secrets", "master.key"))

# --- AWS / Bedrock (reused from common.py) ---
AWS_REGION = _get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = _get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-8")
BEDROCK_EMBED_MODEL_ID = _get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")

# --- job execution ---
JOB_WORKERS = int(_get("DB2DOC_JOB_WORKERS", "3"))
SAMPLE_ROWS = int(_get("DB2DOC_SAMPLE_ROWS", "1000"))
