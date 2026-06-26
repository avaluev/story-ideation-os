#!/usr/bin/env python3
"""PostToolUse(Task) hook — tasks.jsonl mirror.

MEM-10: Mirror TaskCreate/TaskUpdate/Task events to .planning/state/tasks.jsonl
so the full task history is available for cross-session replay and debugging.

This creates a durable audit trail of all task lifecycle events. Combined with
post_task_capture.py (handoff snapshots), this gives full observability of the
multi-agent pipeline execution history.

Exit codes:
  0 → always (PostToolUse never blocks)

See: MEM-10, ADR-0001.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _append_jsonl(path: Path, row: dict) -> None:  # type: ignore[type-arg]
    """Append row to a JSONL file.

    Tries pipeline.state.append_jsonl first; falls back to stdlib on
    NotImplementedError (P0 stub raises; P3 fills the real body).
    # substrate stub raises until P3; fallback ships P0 functionality.
    """
    try:
        from pipeline.state import append_jsonl  # noqa: PLC0415

        append_jsonl(path, row)
    except NotImplementedError:
        # P0: pipeline.state stub raises NotImplementedError until P3.
        # Fallback: direct O_APPEND write via stdlib for P0 functionality.
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:  # noqa: S110
        # Never crash the agent context over a log write failure
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name: str = payload.get("tool_name", "") or ""

    # Handle Task, TaskCreate, TaskUpdate events
    if tool_name not in ("Task", "TaskCreate", "TaskUpdate"):
        return 0

    row: dict = {  # type: ignore[type-arg]
        "ts": _iso_now(),
        "tool": tool_name,
        "input": payload.get("tool_input", {}),
        "output": payload.get("tool_output", {}),
        "session_id": payload.get("session_id"),
    }

    tasks_log = Path(".planning/state/tasks.jsonl")
    _append_jsonl(tasks_log, row)

    return 0


if __name__ == "__main__":
    sys.exit(main())
