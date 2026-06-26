"""pipeline.labels -- operator taste-rating log (data/labels.jsonl).

WEDGE Step 4 of the plan. Pre-Step-4, ``operator_rating`` in the
leaderboard CSV was a dead column with no writer (a comment in
``pipeline/leaderboard.py:500`` told the operator to hand-fill it in
Google Sheets). The closed loop the operator wanted -- "engine learns
my taste" -- could not start because there was no taste signal in the
system.

Post-Step-4, ``scripts/rate.py`` appends one row per rating to
``data/labels.jsonl``; ``pipeline.leaderboard`` mirrors the most recent
rating per run_id into the operator_rating + operator_notes columns of
the CSV; Step 5 (``pipeline.feedback``) reads the same log to refit the
fitness weights.

Schema for one row (ADR-0001 append-only)::

    {
        "ts": "2026-05-27T12:34:56+00:00",
        "run_id": "evolve-20260524T034415Z",
        "rating": +2,                          # +2 / +1 / -1 / -2
        "note": "Loved the protagonist tension",
        "goal_sha": "abc123def456",            # the goal that produced the score
    }

Rating scale (operator-stated):
  +2  "I would absolutely write this"
  +1  "Interesting, would consider"
  -1  "Derivative or weak"
  -2  "Veto -- never sample anything like this again"

Pure Python. No LLM. No external deps.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

DEFAULT_LABELS_PATH: Final[Path] = Path("data/labels.jsonl")

VALID_RATINGS: Final[frozenset[int]] = frozenset({-2, -1, 1, 2})


def append(
    run_id: str,
    rating: int,
    note: str = "",
    goal_sha: str = "",
    *,
    path: Path | str = DEFAULT_LABELS_PATH,
    ts: str | None = None,
) -> dict[str, object]:
    """Append one rating to the log. Returns the row that was written.

    Args:
        run_id: A run identifier from the leaderboard (e.g.
            "evolve-20260524T034415Z"). MUST be non-empty.
        rating: One of {+2, +1, -1, -2}. Other ints raise ValueError.
        note: Optional free-text justification (operator's words).
        goal_sha: The goal_id sha that produced the score; lets Step 5
            decay older ratings whose underlying goal has shifted.
        path: Override for testing.
        ts: Override timestamp (mostly for tests).

    Raises:
        ValueError: rating not in VALID_RATINGS, or run_id empty.
    """
    if not run_id:
        raise ValueError("run_id must be a non-empty string")
    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of {sorted(VALID_RATINGS)}, got {rating!r}")
    row: dict[str, object] = {
        "ts": ts or datetime.now(UTC).isoformat(),
        "run_id": str(run_id),
        "rating": int(rating),
        "note": str(note),
        "goal_sha": str(goal_sha),
    }
    append_jsonl(Path(path), row)
    return row


def read_all(path: Path | str = DEFAULT_LABELS_PATH) -> list[dict[str, object]]:
    """Read every row from the log. Empty list when the file does not exist.

    Malformed rows are silently skipped with a WARNING log -- the file
    can be hand-edited by the operator and we should not crash the
    feedback loop on one bad line.
    """
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, object]] = []
    with open(p, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                parsed: object = json.loads(line)
            except json.JSONDecodeError:
                _log.warning("labels.read_all: skipping malformed JSONL row")
                continue
            if not isinstance(parsed, dict):
                continue
            # parsed is dict[Unknown, Unknown] at this point; coerce keys to
            # str (JSON guarantees this anyway) and keep values opaque.
            narrowed: dict[str, object] = {}
            for key, value in parsed.items():  # type: ignore[reportUnknownVariableType]
                narrowed[str(key)] = value  # type: ignore[reportUnknownArgumentType]
            rows.append(narrowed)
    return rows


def read_since(
    cutoff: datetime,
    path: Path | str = DEFAULT_LABELS_PATH,
) -> list[dict[str, object]]:
    """Return rows with ``ts >= cutoff``. Used by Step 5 recalibration
    trigger ("every N new labels since the last refit")."""
    cutoff_iso = cutoff.isoformat()
    return [row for row in read_all(path) if str(row.get("ts", "")) >= cutoff_iso]


def latest_by_run_id(
    path: Path | str = DEFAULT_LABELS_PATH,
) -> dict[str, dict[str, object]]:
    """Return ``{run_id: most_recent_rating_row}``.

    Used by the leaderboard CSV mirror so the dead ``operator_rating``
    column lights up with the latest rating per run. If the operator
    rates the same run twice, the most recent rating wins (intent: a
    rerated concept reflects updated taste).
    """
    by_run: dict[str, dict[str, object]] = {}
    for row in read_all(path):
        rid = str(row.get("run_id", ""))
        if not rid:
            continue
        prev = by_run.get(rid)
        if prev is None or str(row.get("ts", "")) >= str(prev.get("ts", "")):
            by_run[rid] = row
    return by_run


__all__ = [
    "DEFAULT_LABELS_PATH",
    "VALID_RATINGS",
    "append",
    "latest_by_run_id",
    "read_all",
    "read_since",
]
