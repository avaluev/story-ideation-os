"""scripts.rate -- operator-facing taste-rating CLI.

WEDGE Step 4 of the plan. Takes ~90 seconds per concept; the operator
opens a NARRATOR.md, decides +2 / +1 / -1 / -2, and runs::

    python -m scripts.rate evolve-20260524T034415Z +2 "Loved the protagonist tension"

The rating appends to ``data/labels.jsonl`` via :mod:`pipeline.labels`.
Step 5's :mod:`pipeline.feedback` reads the same log to refit fitness
weights every N ratings.

Rating scale (operator-stated):
  +2  "I would absolutely write this"
  +1  "Interesting, would consider"
  -1  "Derivative or weak"
  -2  "Veto -- never sample anything like this again"

Why this is a script not a slash command (for now): slash commands
require a SKILL.md round-trip which the operator already complained
about. ``python -m scripts.rate ...`` is one shell command with zero
context overhead. A ``/rate`` skill wraps this later (Step 6).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline import labels
from pipeline.goal import Goal


def _parse_rating(raw: str) -> int:
    """Accept '+2', '2', '-1', etc. Reject anything outside VALID_RATINGS."""
    cleaned = raw.strip().lstrip("+")
    try:
        n = int(cleaned)
    except ValueError as exc:
        raise SystemExit(f"rating must be one of +2/+1/-1/-2, got {raw!r}") from exc
    if n not in labels.VALID_RATINGS:
        raise SystemExit(f"rating must be one of {sorted(labels.VALID_RATINGS)}, got {n}")
    return n


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.rate",
        description="Append an operator taste-rating to data/labels.jsonl",
    )
    p.add_argument(
        "run_id",
        help="Run identifier from the leaderboard (e.g. evolve-20260524T034415Z)",
    )
    p.add_argument("rating", help="Rating: +2 / +1 / -1 / -2")
    p.add_argument("note", nargs="?", default="", help="Optional free-text justification")
    p.add_argument(
        "--labels-path",
        type=Path,
        default=labels.DEFAULT_LABELS_PATH,
        help=f"Override labels.jsonl path (default: {labels.DEFAULT_LABELS_PATH})",
    )
    p.add_argument(
        "--goal-path",
        type=Path,
        default=None,
        help="Override config/goal.json path (default: read goal sha from active goal)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    rating = _parse_rating(args.rating)
    goal = Goal.load(args.goal_path) if args.goal_path else Goal.load()
    row = labels.append(
        run_id=args.run_id,
        rating=rating,
        note=args.note,
        goal_sha=goal.sha,
        path=args.labels_path,
    )
    sys.stdout.write(
        f"rated {row['run_id']} {row['rating']:+d}"
        f" goal={goal.goal_id} ({goal.sha[:8]})"
        f"{' note=' + repr(row['note']) if row['note'] else ''}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised via subprocess in tests
    sys.exit(main())
