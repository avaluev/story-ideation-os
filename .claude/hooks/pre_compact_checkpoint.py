#!/usr/bin/env python3
"""PreCompact hook — session checkpoint before context compaction.

MEM-04: Before Claude Code compacts the context window, snapshot the current
session state to .planning/state/sessions/<session_id>/checkpoint.json.

This ensures that after compaction, the agent can read the checkpoint to
reconstruct what was happening before the compaction event.

Exit codes:
  0 → always (PreCompact never blocks)

See: MEM-04, ADR-0001.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_checkpoint(session_id: str, snapshot: dict) -> None:  # type: ignore[type-arg]
    """Write session checkpoint to .planning/state/sessions/<session_id>/checkpoint.json.

    Tries pipeline.state.write_checkpoint first; falls back to stdlib on
    NotImplementedError (P0 stub raises; P3 fills the real body).
    # substrate stub raises until P3; fallback ships P0 functionality.
    """
    try:
        from pipeline.state import write_checkpoint  # noqa: PLC0415

        write_checkpoint(session_id, snapshot)
    except NotImplementedError:
        # P0: pipeline.state stub raises NotImplementedError until P3.
        # Fallback: write directly via stdlib for P0 functionality.
        sessions_dir = Path(".planning/state/sessions") / session_id
        sessions_dir.mkdir(parents=True, exist_ok=True)
        tmp = sessions_dir / "checkpoint.json.tmp"
        target = sessions_dir / "checkpoint.json"
        tmp.write_text(json.dumps(snapshot, indent=2))
        os.replace(str(tmp), str(target))
    except Exception:  # noqa: S110
        # Never crash the agent context over a checkpoint write failure
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    session_id = (payload.get("session_id", "unknown") or "unknown")[:64]

    snapshot: dict = {  # type: ignore[type-arg]
        "schema_version": "1.0",
        "session_id": session_id,
        "started_at": "<unknown — full impl in P3>",
        "last_updated_at": _iso_now(),
        "current_phase": "P0",  # placeholder — full impl reads from STATE.md
        "current_plan": None,
        "pending_tasks": [],
        "open_questions": [],
        "last_artifact_path": None,
        "last_commit_sha": None,
        "files_edited_this_session": [],
        "handoffs_written": [],
        "notes": "PreCompact snapshot",
    }

    _write_checkpoint(session_id, snapshot)

    return 0


if __name__ == "__main__":
    sys.exit(main())
