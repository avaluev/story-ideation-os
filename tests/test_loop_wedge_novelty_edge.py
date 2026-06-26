"""Edge-case tests for ``_rolling_mean_novelty`` (Step 4 KPI 6).

The happy-path test lives in ``tests/test_loop_wedge.py``; this file
exists to pin behaviour at the boundaries:

  - empty / missing history file
  - history with fewer rows than the window
  - history with rows missing the ``novelty_top`` field (pre-Step-11
    forward-compat path)
  - history rows where ``novelty_top`` is null
  - mixed-type ``novelty_top`` values (int vs float)

These boundaries are where the digest will silently lie if a code
change drops one of the guards in ``_rolling_mean_novelty``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.loop_wedge import _rolling_mean_novelty  # pyright: ignore[reportPrivateUsage]

NOVELTY_WINDOW = 20


def _write_history(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    p = tmp_path / "loop_history.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return p


class TestEmptyAndMissingHistory:
    def test_no_history_file_no_current_novelty_returns_none(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.jsonl"
        assert _rolling_mean_novelty(None, missing) is None

    def test_no_history_file_with_current_novelty_returns_current(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.jsonl"
        result = _rolling_mean_novelty(0.42, missing)
        assert result == pytest.approx(0.42)

    def test_empty_history_file_with_current_novelty_returns_current(self, tmp_path: Path) -> None:
        empty = _write_history(tmp_path, [])
        result = _rolling_mean_novelty(0.42, empty)
        assert result == pytest.approx(0.42)

    def test_empty_history_file_no_current_novelty_returns_none(self, tmp_path: Path) -> None:
        empty = _write_history(tmp_path, [])
        assert _rolling_mean_novelty(None, empty) is None


class TestPartialHistory:
    def test_one_past_row_plus_current_averages_two(self, tmp_path: Path) -> None:
        hist = _write_history(tmp_path, [{"novelty_top": 0.20}])
        result = _rolling_mean_novelty(0.60, hist)
        assert result == pytest.approx(0.40)  # (0.20 + 0.60) / 2

    def test_nineteen_past_rows_plus_current_uses_all_twenty(self, tmp_path: Path) -> None:
        rows: list[dict[str, object]] = [{"novelty_top": 0.5} for _ in range(NOVELTY_WINDOW - 1)]
        hist = _write_history(tmp_path, rows)
        result = _rolling_mean_novelty(0.5, hist)
        assert result == pytest.approx(0.5)

    def test_twenty_five_past_rows_keeps_last_nineteen_plus_current(self, tmp_path: Path) -> None:
        # First 6 rows are dummies (0.0); last 19 are 1.0. Plus current 1.0.
        # Expected window: 19 ones (the recent past) + 1 one (current) = 1.0.
        rows: list[dict[str, object]] = [{"novelty_top": 0.0} for _ in range(6)]
        rows.extend({"novelty_top": 1.0} for _ in range(19))
        hist = _write_history(tmp_path, rows)
        result = _rolling_mean_novelty(1.0, hist)
        assert result == pytest.approx(1.0)
        # And confirm the older 0.0 rows really are dropped: feeding 0.0
        # as the current iter to the same history yields 19 ones + 1 zero
        # = 19/20 = 0.95.
        result2 = _rolling_mean_novelty(0.0, hist)
        assert result2 == pytest.approx(19 / 20)


class TestForwardCompatibility:
    def test_rows_missing_novelty_top_are_silently_skipped(self, tmp_path: Path) -> None:
        # Pre-Step-11 rows have no novelty_top.
        rows: list[dict[str, object]] = [
            {"iteration_id": "x1", "score": 0.7},
            {"iteration_id": "x2", "score": 0.8},
            {"iteration_id": "x3", "score": 0.6, "novelty_top": 0.4},
        ]
        hist = _write_history(tmp_path, rows)
        result = _rolling_mean_novelty(0.6, hist)
        assert result == pytest.approx(0.5)  # (0.4 + 0.6) / 2

    def test_rows_with_null_novelty_top_are_silently_skipped(self, tmp_path: Path) -> None:
        rows: list[dict[str, object]] = [
            {"novelty_top": None},
            {"novelty_top": 0.3},
        ]
        hist = _write_history(tmp_path, rows)
        result = _rolling_mean_novelty(0.5, hist)
        assert result == pytest.approx(0.4)  # (0.3 + 0.5) / 2

    def test_int_novelty_top_is_treated_as_float(self, tmp_path: Path) -> None:
        rows: list[dict[str, object]] = [{"novelty_top": 1}, {"novelty_top": 0}]
        hist = _write_history(tmp_path, rows)
        result = _rolling_mean_novelty(0.5, hist)
        assert result == pytest.approx(0.5)


class TestMalformedHistory:
    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        p.write_text('\n\n{"novelty_top": 0.4}\n\n', encoding="utf-8")
        result = _rolling_mean_novelty(0.6, p)
        assert result == pytest.approx(0.5)

    def test_malformed_json_lines_are_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        p.write_text('not json\n{"novelty_top": 0.4}\n{"broken":\n', encoding="utf-8")
        result = _rolling_mean_novelty(0.6, p)
        assert result == pytest.approx(0.5)

    def test_non_dict_json_rows_are_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        p.write_text('[1,2,3]\n"string"\n{"novelty_top": 0.4}\n', encoding="utf-8")
        result = _rolling_mean_novelty(0.6, p)
        assert result == pytest.approx(0.5)
