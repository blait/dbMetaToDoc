"""Shared helpers: env loading, RDS connection, Bedrock client.

Every stage imports from here so connection/model handling lives in one place.
"""
import os
import json
import functools

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass  # dotenv optional; env may be exported directly


# ---------------------------------------------------------------- config
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


# ---------------------------------------------------------------- database
def connect():
    """Open a psycopg2 connection to the target RDS PostgreSQL using PG* env vars."""
    import psycopg2
    return psycopg2.connect(
        host=cfg("PGHOST", required=True),
        port=cfg("PGPORT", "5432"),
        dbname=cfg("PGDATABASE", "omop"),
        user=cfg("PGUSER", required=True),
        password=cfg("PGPASSWORD", required=True),
        connect_timeout=15,
    )


# ---------------------------------------------------------------- bedrock
@functools.lru_cache(maxsize=1)
def _bedrock():
    import boto3
    return boto3.client("bedrock-runtime", region_name=REGION)


def invoke_claude(messages, system=None, max_tokens=4096, tools=None, tool_choice=None):
    """Invoke Claude Opus 4.8 on Bedrock.

    NOTE: Opus 4.8 rejects the `temperature` parameter, so we never send it.
    Returns the parsed response dict (anthropic messages format).
    """
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
    resp = _bedrock().invoke_model(modelId=MODEL_ID, body=json.dumps(body))
    return json.loads(resp["body"].read())


def claude_json(prompt, schema, system=None, max_tokens=4096):
    """Force a JSON object out of Claude via a single-tool tool_choice.

    `schema` is a JSON Schema for the object you want back. Returns the dict.
    """
    tool = {
        "name": "emit",
        "description": "Return the structured result.",
        "input_schema": schema,
    }
    out = invoke_claude(
        [{"role": "user", "content": prompt}],
        system=system,
        max_tokens=max_tokens,
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit"},
    )
    for block in out.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit":
            return block["input"], out.get("usage", {})
    raise RuntimeError(f"no tool_use block in response: {out}")


def embed(text):
    """Return the embedding vector for `text` using the Bedrock Titan embed model."""
    out = _bedrock().invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text}),
    )
    return json.loads(out["body"].read())["embedding"]


# ---------------------------------------------------------------- io
def out_path(name):
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(here, "out")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def dump_json(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return path
