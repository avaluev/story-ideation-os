"""EVAL-07 — Score floor gate: published concepts meet the run's configured floor.

Reads data/05_critiques.jsonl (output of _run_critic() which appends overall_score dict).
Every row must have a valid overall_score dict.
Published concepts (those in out/concepts/) must have final >= the floor that was
configured for the run that published them.

Floor resolution (in priority order):
  1. ANOMALY_FLOOR env var if set (explicit override; useful for CI)
  2. format_floor from latest entry in data/metrics/timeline.jsonl
  3. Default 85.0 (production target for Claude Sonnet/Opus)

This auto-tracks the run policy: --format-floor 60 in run.py persists 60.0 in
the metrics snapshot, and the eval picks it up. No more eval/policy mismatch.
Skips gracefully when data/05_critiques.jsonl is absent (fresh clone / CI).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_CONCEPTS_LOG = Path("data/05_critiques.jsonl")
_TIMELINE_LOG = Path("data/metrics/timeline.jsonl")
_PROD_FLOOR: float = 85.0


def _floor_from_timeline() -> float | None:
    """Return format_floor from the latest timeline entry, or None if unavailable."""
    if not _TIMELINE_LOG.exists():
        return None
    last: dict[str, object] | None = None
    for line in _TIMELINE_LOG.read_text().splitlines():
        if not line.strip():
            continue
        last = json.loads(line)
    if last is None:
        return None
    val = last.get("format_floor")
    if isinstance(val, int | float):
        return float(val)
    return None


def _configured_floor() -> float:
    """Return the floor to enforce.

    Priority: ANOMALY_FLOOR env var → latest run's format_floor → 85.0 default.
    """
    raw = os.environ.get("ANOMALY_FLOOR", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    timeline_floor = _floor_from_timeline()
    if timeline_floor is not None:
        return timeline_floor
    return _PROD_FLOOR


def test_score_floor_all_pass_concepts() -> None:
    """Every concept in data/05_critiques.jsonl must have a valid overall_score dict (EVAL-07).

    Published concepts (in out/concepts/) must meet the configured floor.
    Production floor is 85; demo runs may relax via ANOMALY_FLOOR env var.
    """
    if not _CONCEPTS_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")
    lines = [ln for ln in _CONCEPTS_LOG.read_text().splitlines() if ln.strip()]
    if not lines:
        pytest.skip("No pipeline output found — run the pipeline first.")
    _REQUIRED_KEYS = {"upstream", "critic", "base", "final", "passes_85_floor"}
    structural_failures: list[str] = []
    published_ids: set[str] = set()
    floor = _configured_floor()

    # Identify published concept IDs from out/concepts/
    out_dir = Path("out") / "concepts"
    if out_dir.exists():
        for md_file in out_dir.glob("*.md"):
            published_ids.add(md_file.stem)

    for line in lines:
        row = json.loads(line)
        concept_id = row.get("concept_id", "unknown")
        score_dict = row.get("overall_score", {})

        # Rule 1: overall_score must be a dict with required keys
        if not isinstance(score_dict, dict) or not _REQUIRED_KEYS.issubset(score_dict.keys()):
            structural_failures.append(
                f"{concept_id}: overall_score missing or lacks required keys "
                f"(has: {set(score_dict.keys()) if isinstance(score_dict, dict) else 'N/A'})"
            )
            continue

        # Rule 2: any concept published to out/concepts/ must meet the configured floor
        if str(concept_id) in published_ids:
            final = float(score_dict.get("final", 0))
            if final < floor:
                structural_failures.append(
                    f"{concept_id}: published to out/concepts/ but"
                    f" final={final} < configured floor={floor}"
                )

    assert not structural_failures, (
        f"Score floor gate failures (floor={floor}, {len(structural_failures)}):\n"
        + "\n".join(structural_failures)
    )
