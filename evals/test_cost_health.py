"""EVAL-08 — Rolling 30-day cost health: per-phase cost must stay within +-2 stdev.

Reads data/run_log.jsonl. Extracts cost_usd per phase per run (grouped by date).
Computes rolling 30-day mean and stdev per phase. Flags any day > mean + 2*stdev.
If fewer than 2 days of data, skips (insufficient history for statistics).
If fewer than 30 days, computes stdev on available data.
Skips gracefully when data/run_log.jsonl is absent or contains no cost_usd rows.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

_RUN_LOG = Path("data/run_log.jsonl")
_SIGMA_THRESHOLD = 2.0
_MIN_DATA_POINTS = 2


def test_cost_health_no_outlier_phases() -> None:
    """Rolling 30-day per-phase cost must stay within +-2 stdev of mean (EVAL-08)."""
    if not _RUN_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")

    # Group cost_usd by (phase, date_str)
    phase_day_costs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for raw_line in _RUN_LOG.read_text().splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        cost = row.get("cost_usd")
        if cost is None:
            continue
        try:
            cost_float = float(cost)
        except (TypeError, ValueError):
            continue

        phase = str(row.get("phase", "unknown"))
        ts_str = str(row.get("ts", ""))
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue

        phase_day_costs[phase][date_str] += cost_float

    if not phase_day_costs:
        pytest.skip("No cost_usd rows in run_log.jsonl — run the pipeline with --paid-ok first.")

    violations: list[str] = []

    for phase, day_costs in phase_day_costs.items():
        daily_values = list(day_costs.values())
        if len(daily_values) < _MIN_DATA_POINTS:
            continue  # insufficient history

        mean = statistics.mean(daily_values)
        stdev = statistics.stdev(daily_values)

        if stdev == 0:
            continue  # no variation — nothing to flag

        for date_str, cost in day_costs.items():
            z_score = abs(cost - mean) / stdev
            if z_score > _SIGMA_THRESHOLD:
                violations.append(
                    f"phase={phase} date={date_str}: "
                    f"cost=${cost:.4f} (mean=${mean:.4f}, stdev=${stdev:.4f}, z={z_score:.1f})"
                )

    assert not violations, f"Cost outliers beyond +-2 stdev ({len(violations)}):\n" + "\n".join(
        violations
    )
