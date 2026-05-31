"""Re-export the Bedrock helpers from the PoC's common.py.

These (invoke_claude / claude_json / embed) are DB-agnostic, so we reuse them
verbatim rather than reimplementing.  Only the DB/file-coupled bits of common.py
(connect/PGSCHEMA/out_path) are intentionally NOT imported here.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import invoke_claude, claude_json, embed, MODEL_ID  # noqa: E402,F401

__all__ = ["invoke_claude", "claude_json", "embed", "MODEL_ID"]
