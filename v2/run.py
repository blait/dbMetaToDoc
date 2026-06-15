#!/usr/bin/env python3
"""Run the whole v2 pipeline end-to-end.

    python run.py            # all stages
    python run.py --from 3   # resume from stage 3 (descriptions)
    python run.py --no-judge # skip the LLM judge during scoring

Stages: 1 profile -> 2 relations -> 3 describe -> 4 catalog -> 5 score -> 6 viewer
"""
import argparse
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = [
    ("profiler.py", []),
    ("relations.py", []),
    ("describe.py", []),        # generates Korean descriptions natively
    ("catalog.py", []),
    ("score.py", []),           # scores against *_ko truth when present
    ("viewer.py", []),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=len(STAGES))
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--skip-score", action="store_true",
                    help="no ground truth available: run without stage 5")
    args = ap.parse_args()

    for i, (script, extra) in enumerate(STAGES, 1):
        if not (args.start <= i <= args.end):
            continue
        if script == "score.py" and args.skip_score:
            print(f"\n========== stage {i}: {script} (skipped) ==========")
            continue
        cmd = [sys.executable, os.path.join(HERE, script)] + extra
        if script == "score.py" and args.no_judge:
            cmd.append("--no-judge")
        print(f"\n========== stage {i}: {script} ==========")
        r = subprocess.run(cmd, cwd=HERE)
        if r.returncode != 0:
            sys.exit(f"stage {i} ({script}) failed with code {r.returncode}")
    print("\n>> pipeline complete.")


if __name__ == "__main__":
    main()
