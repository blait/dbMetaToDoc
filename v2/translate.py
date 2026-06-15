#!/usr/bin/env python3
"""Korean localization of catalog artifacts and the ground-truth dictionary.

Translates PROSE ONLY — table/column names, SQL identifiers, codes, units,
and domain acronyms (OMOP, CDM, FK, SNOMED, RxNorm, ...) stay as-is.

  python translate.py truth   # truth/*_ko.csv  (one-time, reused by score.py)
  python translate.py run     # V2_OUT_DIR's descriptions.json + concepts.json
                              # (idempotent: keeps *_en originals, skips done)

After `run`, rebuild downstream artifacts:
  catalog.py -> score.py -> viewer.py -> graph.py load -> concepts.py load
"""
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from config import out_path, load_json, dump_json, claude_json, REPO_DIR, OMOP_VERSION

TRUTH = os.path.join(REPO_DIR, "truth")
BATCH = 20
WORKERS = 4

TRANS_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
            },
        }
    },
    "required": ["translations"],
}

SYSTEM = (
    "You translate English data-catalog / data-dictionary descriptions into "
    "natural, professional Korean.\n"
    "Rules:\n"
    "- Keep table/column names, SQL identifiers, code values, units, and "
    "domain acronyms in their original form (OMOP, CDM, FK, PK, ETL, "
    "SNOMED, RxNorm, LOINC, concept_id, person_id, ...). Translate the "
    "prose around them.\n"
    "- Preserve meaning exactly: do not add, drop, or soften information.\n"
    "- Keep inline code/backticks and URLs unchanged.\n"
    "- Natural Korean word order; declarative endings (~다/~함) consistent "
    "with a technical dictionary.\n"
    "- Return exactly one translation per input id."
)


def translate_texts(texts):
    """texts: list[str] -> list[str] (parallel batched LLM translation)."""
    jobs = [(i, t) for i, t in enumerate(texts)]
    chunks = [jobs[i:i + BATCH] for i in range(0, len(jobs), BATCH)]
    out = {}

    def run(chunk):
        payload = [{"id": i, "text": t} for i, t in chunk]
        obj, _ = claude_json(
            "Translate each item's text to Korean.\n\n"
            + json.dumps(payload, ensure_ascii=False),
            TRANS_SCHEMA, system=SYSTEM, max_tokens=8192)
        got = {t["id"]: t["text"] for t in obj.get("translations", [])}
        # fall back to the original when the model skips an id
        return {i: got.get(i, t) for i, t in chunk}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for res in ex.map(run, chunks):
            out.update(res)
    print(f"   translated {len(out)}/{len(texts)}")
    return [out[i] for i in range(len(texts))]


def is_blank(text):
    return not text or text.strip().lower() in ("", "na", "n/a", "none")


# ------------------------------------------------------------------ truth
def cmd_truth():
    # Field-level: userGuidance
    src = os.path.join(TRUTH, f"OMOP_CDMv{OMOP_VERSION}_Field_Level.csv")
    dst = os.path.join(TRUTH, f"OMOP_CDMv{OMOP_VERSION}_Field_Level_ko.csv")
    with open(src, newline="", encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    idx = [i for i, r in enumerate(rows) if not is_blank(r.get("userGuidance"))]
    print(f">> field-level: translating {len(idx)} userGuidance texts")
    ko = translate_texts([rows[i]["userGuidance"] for i in idx])
    for j, i in enumerate(idx):
        rows[i]["userGuidance"] = ko[j]
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f">> wrote {dst}")

    # Table-level: tableDescription
    src = os.path.join(TRUTH, f"OMOP_CDMv{OMOP_VERSION}_Table_Level.csv")
    dst = os.path.join(TRUTH, f"OMOP_CDMv{OMOP_VERSION}_Table_Level_ko.csv")
    with open(src, newline="", encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    idx = [i for i, r in enumerate(rows)
           if not is_blank(r.get("tableDescription"))]
    print(f">> table-level: translating {len(idx)} descriptions")
    ko = translate_texts([rows[i]["tableDescription"] for i in idx])
    for j, i in enumerate(idx):
        rows[i]["tableDescription"] = ko[j]
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f">> wrote {dst}")


# ------------------------------------------------------------------ run
def cmd_run():
    # descriptions.json — translate db/table/column descriptions in place,
    # keeping the originals under *_en. Idempotent via the *_en marker.
    path = out_path("descriptions.json")
    desc = load_json(path)

    jobs = []   # (setter, original_text)
    def add(obj, key):
        if obj.get(key) and not obj.get(key + "_en"):
            jobs.append((obj, key, obj[key]))

    add(desc.get("db", {}), "db_description")
    for t, td in desc["tables"].items():
        add(td, "table_description")
        for c in td.get("columns", []):
            add(c, "description")

    if jobs:
        print(f">> descriptions.json: translating {len(jobs)} texts")
        ko = translate_texts([j[2] for j in jobs])
        for (obj, key, orig), k in zip(jobs, ko):
            obj[key + "_en"] = orig
            obj[key] = k
        dump_json(desc, path)
        print(f">> updated {path}")
    else:
        print(">> descriptions.json already translated — skipped")

    # concepts.json — concept descriptions
    cpath = out_path("concepts.json")
    if os.path.exists(cpath):
        data = load_json(cpath)
        cjobs = [c for c in data["concepts"]
                 if c.get("description") and not c.get("description_en")]
        if cjobs:
            print(f">> concepts.json: translating {len(cjobs)} descriptions")
            ko = translate_texts([c["description"] for c in cjobs])
            for c, k in zip(cjobs, ko):
                c["description_en"] = c["description"]
                c["description"] = k
            dump_json(data, cpath)
            print(f">> updated {cpath}")
        else:
            print(">> concepts.json already translated — skipped")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    if cmd == "truth":
        cmd_truth()
    elif cmd == "run":
        cmd_run()
    else:
        sys.exit("usage: translate.py truth|run")


if __name__ == "__main__":
    main()
