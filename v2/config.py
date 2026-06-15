"""v2 shared config: env, DB connection, Bedrock client, token accounting, IO.

v2 is self-contained under db2doc/v2/ and reads the repo-root .env so the
existing RDS/Bedrock settings keep working without duplication.
"""
import os
import json
import time
import threading
import functools

V2_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(V2_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_DIR, ".env"))
    load_dotenv(os.path.join(V2_DIR, ".env"), override=True)
except Exception:
    pass


def cfg(key, default=None, required=False):
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"missing required env var: {key}")
    return val


REGION = cfg("AWS_REGION", "us-east-1")
MODEL_ID = cfg("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-8")
EMBED_MODEL_ID = cfg("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
PGSCHEMA = cfg("PGSCHEMA", "cdm")
OMOP_VERSION = cfg("OMOP_VERSION", "5.3")

# resource guardrail (DBAutoDoc GUARDRAILS-style hard limits)
MAX_LLM_TOKENS = int(cfg("V2_MAX_LLM_TOKENS", "800000"))   # in+out, whole run
MAX_LLM_CALLS = int(cfg("V2_MAX_LLM_CALLS", "400"))


# ---------------------------------------------------------------- database
def connect():
    import psycopg2
    return psycopg2.connect(
        host=cfg("PGHOST", required=True),
        port=cfg("PGPORT", "5432"),
        dbname=cfg("PGDATABASE", "omop"),
        user=cfg("PGUSER", required=True),
        password=cfg("PGPASSWORD", required=True),
        connect_timeout=15,
    )


def qident(name):
    """Quote a SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------- bedrock
@functools.lru_cache(maxsize=1)
def _bedrock():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "bedrock-runtime", region_name=REGION,
        config=Config(read_timeout=300, retries={"max_attempts": 8,
                                                 "mode": "adaptive"}))


class Guardrail(Exception):
    """Raised when the run exceeds its token/call budget."""


_usage_lock = threading.Lock()
USAGE = {"input_tokens": 0, "output_tokens": 0, "calls": 0}


def _track(usage):
    with _usage_lock:
        USAGE["input_tokens"] += usage.get("input_tokens", 0)
        USAGE["output_tokens"] += usage.get("output_tokens", 0)
        USAGE["calls"] += 1
        total = USAGE["input_tokens"] + USAGE["output_tokens"]
        if total > MAX_LLM_TOKENS or USAGE["calls"] > MAX_LLM_CALLS:
            raise Guardrail(
                f"LLM budget exceeded: {total} tokens / {USAGE['calls']} calls "
                f"(limits {MAX_LLM_TOKENS} / {MAX_LLM_CALLS})")


def invoke_claude(messages, system=None, max_tokens=4096, tools=None,
                  tool_choice=None):
    """Invoke Claude on Bedrock. Opus 4.8 rejects `temperature` — never sent."""
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    last = None
    for attempt in range(5):
        try:
            resp = _bedrock().invoke_model(modelId=MODEL_ID, body=json.dumps(body))
            out = json.loads(resp["body"].read())
            _track(out.get("usage", {}))
            return out
        except Guardrail:
            raise
        except Exception as e:  # throttling / transient
            last = e
            if "Throttling" in str(type(e).__name__) or "throttl" in str(e).lower():
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise last


def claude_json(prompt, schema, system=None, max_tokens=4096):
    """Force a JSON object out of Claude via single-tool tool_choice."""
    tool = {"name": "emit", "description": "Return the structured result.",
            "input_schema": schema}
    out = invoke_claude(
        [{"role": "user", "content": prompt}], system=system,
        max_tokens=max_tokens, tools=[tool],
        tool_choice={"type": "tool", "name": "emit"})
    for block in out.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit":
            return block["input"], out.get("usage", {})
    raise RuntimeError(f"no tool_use block in response: {out}")


def embed(text):
    out = _bedrock().invoke_model(
        modelId=EMBED_MODEL_ID, body=json.dumps({"inputText": text}))
    return json.loads(out["body"].read())["embedding"]


# ---------------------------------------------------------------- io
def out_path(name):
    """Output dir for the current run.

    Defaults to v2/out; the web app sets V2_OUT_DIR=runs/<run_id> so each
    pipeline run keeps its own artifacts."""
    d = os.environ.get("V2_OUT_DIR") or os.path.join(V2_DIR, "out")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def dump_json(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return path
