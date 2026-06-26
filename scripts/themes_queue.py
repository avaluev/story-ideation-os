"""scripts/themes_queue.py — OPS-09: Themes queue add/next CLI helpers.

Manages data/themes_queue.jsonl — a JSONL log of themes queued for future
pipeline runs.

JSONL entry format (locked by CONTEXT.md):
    {"theme": "...", "added_at": "2026-05-01T12:00:00+00:00", "status": "pending"}

Usage:
    make add-theme THEME="Cold War spy satellites"
    make next-theme

    python scripts/themes_queue.py add "Cold War spy satellites"
    python scripts/themes_queue.py next
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

# Path to the themes queue JSONL file (monkeypatched in tests)
QUEUE_PATH = Path("data/themes_queue.jsonl")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_pending() -> list[dict]:
    """Read all pending entries from QUEUE_PATH. Returns [] if file not found."""
    if not QUEUE_PATH.exists():
        return []
    rows: list[dict] = []
    for raw in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            _log.warning("Skipping malformed themes_queue line: %s", exc)
            continue
        if row.get("status") == "pending":
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_theme(theme: str) -> None:
    """Append a new pending theme to the queue.

    Args:
        theme: The theme string to enqueue. Must be non-empty and non-whitespace.

    Raises:
        SystemExit(1): If theme is empty or whitespace-only.

    Output (locked format):
        Added: {theme} (position N/N)
    """
    if not theme or not theme.strip():
        print("ERROR: theme must be a non-empty string.", file=sys.stderr)
        sys.exit(1)

    theme = theme.strip()
    # Count existing pending entries to compute position
    existing = _read_pending()
    n = len(existing) + 1

    entry: dict = {
        "theme": theme,
        "added_at": datetime.now(UTC).isoformat(),
        "status": "pending",
    }
    append_jsonl(QUEUE_PATH, entry)
    print(f"Added: {theme} (position {n}/{n})")


def next_theme() -> None:
    """Print the first pending entry in the queue (read-only).

    Output (locked format):
        [N/M] {theme} (added YYYY-MM-DD)
        or: Queue is empty.
    """
    pending = _read_pending()
    if not pending:
        print("Queue is empty.")
        return

    first = pending[0]
    total = len(pending)
    added_date = first.get("added_at", "")[:10]  # YYYY-MM-DD
    theme = first.get("theme", "")
    print(f"[1/{total}] {theme} (added {added_date})")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> int:
    """CLI dispatcher: argv[1] must be 'add' or 'next'."""
    if len(sys.argv) < 2 or sys.argv[1] not in {"add", "next"}:  # noqa: PLR2004
        print("Usage: themes_queue.py add <theme> | themes_queue.py next", file=sys.stderr)
        return 1

    cmd = sys.argv[1]
    if cmd == "add":
        if len(sys.argv) < 3:  # noqa: PLR2004
            print("ERROR: 'add' requires a theme argument.", file=sys.stderr)
            return 1
        add_theme(sys.argv[2])
    else:
        next_theme()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
