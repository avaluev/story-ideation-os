#!/usr/bin/env python3
"""PostToolUse(Task) hook — subagent transcript capture.

MEM-05: When a Task tool completes, capture the subagent's output into
a HandoffContract JSON file at .planning/state/handoffs/<from>_to_<to>_<ts>.json.

This enables cross-agent memory: the orchestrator reads the latest handoff
at the start of each session and knows what work the previous subagent did.

Exit codes:
  0 → always (PostToolUse never blocks)

See: MEM-05, ADR-0001.
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


def _write_handoff(handoff: dict) -> None:  # type: ignore[type-arg]
    """Write handoff dict to .planning/state/handoffs/.

    Tries pipeline.state.write_handoff first; falls back to stdlib on
    NotImplementedError (P0 stub raises; P3 fills the real body).
    # substrate stub raises until P3; fallback ships P0 functionality.
    """
    try:
        from pipeline.state import write_handoff  # noqa: PLC0415

        write_handoff(
            from_agent=handoff["from_agent"],
            to_agent=handoff["to_agent"],
            payload=handoff,
        )
    except NotImplementedError:
        # P0: pipeline.state stub raises NotImplementedError until P3.
        # Fallback: write directly via stdlib for P0 functionality.
        from_agent = handoff.get("from_agent", "subagent").replace("/", "-")
        to_agent = handoff.get("to_agent", "orchestrator").replace("/", "-")
        ts = handoff.get("handoff_ts", _iso_now()).replace(":", "").replace("-", "")
        filename = f"{from_agent}_to_{to_agent}_{ts}.json"

        handoffs_dir = Path(".planning/state/handoffs")
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        tmp = handoffs_dir / (filename + ".tmp")
        target = handoffs_dir / filename
        tmp.write_text(json.dumps(handoff, indent=2))
        os.replace(str(tmp), str(target))
    except Exception:  # noqa: S110
        # Never crash the agent context over a handoff write failure
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name: str = payload.get("tool_name", "") or ""

    # Only handle Task tool completions
    if tool_name != "Task":
        return 0

    subagent_output = payload.get("tool_output", {}) or {}
    session_id = (payload.get("session_id", "unknown") or "unknown")[:64]
    from_agent = (
        payload.get("tool_input", {}).get("subagent_type", "")
        or payload.get("tool_input", {}).get("description", "subagent")[:64]
        or "subagent"
    )

    # Truncate notes to respect HandoffContract._NOTES_MAX = 5000
    notes_raw = str(subagent_output)
    notes = notes_raw[:5000]

    handoff: dict = {  # type: ignore[type-arg]
        "schema_version": "1.0",
        "from_agent": from_agent,
        "to_agent": "orchestrator",
        "handoff_ts": _iso_now(),
        "session_id": session_id,
        "produced": [],
        "consumed": [],
        "next_action": "review subagent output",
        "assumptions_made": [],
        "open_decisions": [],
        "notes": notes,
    }

    _write_handoff(handoff)

    return 0


if __name__ == "__main__":
    sys.exit(main())
