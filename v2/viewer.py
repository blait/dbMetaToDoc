#!/usr/bin/env python3
"""Stage 6 — Viewer: static self-contained HTML (tree catalog + comparison).

The page template lives in ui.py (shared with the web app). This script
inlines the run's artifacts into out/viewer.html so it opens without a
server. For the multi-run home page + new-DB connections, use webapp.py.
"""
import json
import os

from config import out_path, load_json
from ui import render_inline


def main():
    catalog = load_json(out_path("catalog.json"))

    def opt(name):
        p = out_path(name)
        return json.dumps(load_json(p), ensure_ascii=False) \
            if os.path.exists(p) else None

    html = render_inline(
        json.dumps(catalog, ensure_ascii=False),
        opt("score.json"), opt("score_details.json"))
    path = out_path("viewer.html")
    with open(path, "w") as f:
        f.write(html)
    print(f">> wrote {path}  (open in a browser)")


if __name__ == "__main__":
    main()
