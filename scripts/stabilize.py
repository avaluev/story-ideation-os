#!/usr/bin/env python3
"""scripts/stabilize.py — Stage queued anti-slop patterns for operator review (STAB-03/04).

STAB-02 bypass: writes prompts/anti_slop.md via open() NOT via Write/Edit tool.
Operator reviews staged diff, then: git commit (accept) or git checkout (reject).
After operator commits, run: make stabilize-commit (runs make test -k anti_slop).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

QUEUE_PATH = Path("data/stabilization_queue.jsonl")
ANTI_SLOP_PATH = Path("prompts/anti_slop.md")


def _read_queue_from(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _build_entry_line(row: dict) -> str:
    date_str = row["queued_at"][:10]  # YYYY-MM-DD
    concept_id = row["concept_id"]
    pattern = row["pattern"]
    return f"- {pattern}  # added {date_str}, triggered by {concept_id}"


def stage_patterns(
    queue_path: Path = QUEUE_PATH,
    anti_slop_path: Path = ANTI_SLOP_PATH,
) -> int:
    rows = _read_queue_from(queue_path)
    if not rows:
        print("No patterns queued.")
        return 0
    new_lines = [_build_entry_line(r) for r in rows]
    # STAB-02 bypass: write via open(), NOT via Write/Edit tool
    with open(anti_slop_path, "a", encoding="utf-8") as f:
        f.write("\n\n## Queued Stabilization Patterns\n\n")
        f.write("\n".join(new_lines) + "\n")
    subprocess.run(["git", "add", str(anti_slop_path)], check=True)  # noqa: S603,S607
    print(f"Staged {len(new_lines)} pattern(s) to {anti_slop_path}.")
    print("Review : git diff --staged")
    print("Accept : git commit -m 'fix(stab): add anti-slop patterns'")
    print("Reject : git checkout prompts/anti_slop.md")
    return 0


def main() -> int:
    return stage_patterns()


if __name__ == "__main__":
    sys.exit(main())
