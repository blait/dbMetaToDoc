#!/usr/bin/env python3
"""Metadata RAG over OpenSearch Serverless (vector search).

Indexes the generated catalog's table/column descriptions as embeddings so
that a natural-language question can retrieve the semantically closest
schema elements — the part that concept-synonym matching and graph traversal
cannot do, and that becomes essential at large scale (thousands of tables
won't fit in an LLM context window; vector search narrows the candidates
first, then the graph expands join paths around them).

  python metasearch.py index    # V2_OUT_DIR's catalog.json -> OpenSearch
  python metasearch.py search "환자별 처방"   # ad-hoc top-k probe
  python metasearch.py status

Env: AOSS_ENDPOINT (collection endpoint, https://...), AWS_REGION,
     BEDROCK_EMBED_MODEL_ID. Each doc is a table or a column; embeddings are
     Titan v2 (multilingual, so Korean descriptions index/search natively).
"""
import json
import os
import sys

from config import REGION, cfg, embed, out_path, load_json

INDEX = "db2doc-meta"
EMBED_DIM = 1024          # Titan Embed Text v2 default dimension


def endpoint():
    ep = cfg("AOSS_ENDPOINT")
    if not ep:
        raise SystemExit("set AOSS_ENDPOINT (OpenSearch Serverless collection "
                         "endpoint, e.g. https://xxxx.us-east-1.aoss.amazonaws.com)")
    return ep


def client():
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth
    import boto3
    cred = boto3.Session().get_credentials()
    auth = AWS4Auth(cred.access_key, cred.secret_key, REGION, "aoss",
                    session_token=cred.token)
    host = endpoint().replace("https://", "")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth, use_ssl=True, verify_certs=True,
        connection_class=RequestsHttpConnection, timeout=60, pool_maxsize=20)


def ensure_index(os_client):
    if os_client.indices.exists(index=INDEX):
        return
    os_client.indices.create(index=INDEX, body={
        "settings": {"index": {"knn": True}},
        "mappings": {"properties": {
            "embedding": {"type": "knn_vector", "dimension": EMBED_DIM,
                          "method": {"name": "hnsw", "engine": "faiss",
                                     "space_type": "cosinesimil"}},
            "kind": {"type": "keyword"},      # 'table' | 'column'
            "table": {"type": "keyword"},
            "column": {"type": "keyword"},
            "name": {"type": "text"},
            "description": {"type": "text"},
            "rowcount": {"type": "long"},
            "is_pk": {"type": "boolean"},
            "fk_ref": {"type": "keyword"},
            "doc": {"type": "text"},          # the embedded text (for display)
        }}})
    print(f">> created index {INDEX}")


def catalog_docs(catalog):
    """One doc per table and per column. The embedded text combines name +
    description so both lexical and semantic signal are captured."""
    docs = []
    for t in catalog["tables"]:
        tdoc = f"테이블 {t['name']}: {t.get('description','')}"
        docs.append({"_id": f"t::{t['name']}", "kind": "table",
                     "table": t["name"], "column": None, "name": t["name"],
                     "description": t.get("description", ""),
                     "rowcount": t.get("rowcount", 0),
                     "doc": tdoc})
        for c in t["columns"]:
            cdoc = (f"컬럼 {t['name']}.{c['name']} ({c.get('type','')}): "
                    f"{c.get('description','')}")
            docs.append({"_id": f"c::{t['name']}.{c['name']}", "kind": "column",
                         "table": t["name"], "column": c["name"],
                         "name": c["name"], "description": c.get("description", ""),
                         "is_pk": bool(c.get("is_pk")),
                         "fk_ref": c.get("fk"), "doc": cdoc})
    return docs


def cmd_index():
    catalog = load_json(out_path("catalog.json"))
    docs = catalog_docs(catalog)
    os_client = client()
    # rebuild cleanly so re-indexing is idempotent
    if os_client.indices.exists(index=INDEX):
        os_client.indices.delete(index=INDEX)
    ensure_index(os_client)
    print(f">> embedding + indexing {len(docs)} docs (tables + columns)")
    from opensearchpy.helpers import bulk
    actions = []
    for i, d in enumerate(docs, 1):
        d.pop("_id", None)          # AOSS bulk rejects custom document IDs
        d["embedding"] = embed(d["doc"])
        actions.append({"_index": INDEX, "_source": d})
        if i % 50 == 0:
            print(f"   embedded {i}/{len(docs)}")
    ok, errs = bulk(os_client, actions, request_timeout=180, raise_on_error=False)
    if errs:
        print("   sample error:", json.dumps(errs[0])[:300])
    print(f">> indexed {ok} docs, {len(errs) if errs else 0} errors")


def search(question, k=12, kinds=None):
    """Return top-k schema elements semantically closest to the question."""
    os_client = client()
    qvec = embed(question)
    knn = {"embedding": {"vector": qvec, "k": k}}
    body = {"size": k, "query": {"knn": knn},
            "_source": ["kind", "table", "column", "name", "description",
                        "rowcount", "is_pk", "fk_ref", "doc"]}
    res = os_client.search(index=INDEX, body=body)
    hits = []
    for h in res["hits"]["hits"]:
        s = h["_source"]
        s["score"] = h["_score"]
        if kinds and s["kind"] not in kinds:
            continue
        hits.append(s)
    return hits


def cmd_search(question):
    for h in search(question, k=12):
        where = h["table"] + ("." + h["column"] if h["column"] else "")
        print(f"  [{h['score']:.3f}] {h['kind']:<6} {where:<40} "
              f"{(h['description'] or '')[:50]}")


def cmd_status():
    os_client = client()
    if not os_client.indices.exists(index=INDEX):
        print(">> index not created yet")
        return
    cnt = os_client.count(index=INDEX)["count"]
    print(f">> index {INDEX}: {cnt} docs")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "index":
        cmd_index()
    elif cmd == "search":
        cmd_search(" ".join(sys.argv[2:]))
    else:
        cmd_status()


if __name__ == "__main__":
    main()
