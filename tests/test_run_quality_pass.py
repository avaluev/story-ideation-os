"""Tests for Phase 6 formatter quality pass filtering (PIPE-11).

Verifies that the formatter phase skips concepts where
overall_score['passes_85_floor'] is False and includes those where it is True.

These tests are RED until pipeline/run.py is implemented (Task 3).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipeline.run")

from pipeline.run import _should_format_concept


def test_quality_pass_filters_below_85() -> None:
    """Formatter must skip concept when passes_85_floor is False (score=80)."""
    result = _should_format_concept({"passes_85_floor": False, "final": 80})
    assert result is False


def test_quality_pass_includes_above_85() -> None:
    """Formatter must include concept when passes_85_floor is True (score=86)."""
    result = _should_format_concept({"passes_85_floor": True, "final": 86})
    assert result is True


def test_quality_pass_exact_85() -> None:
    """Concept with exact score of 85 passes the floor (>=, not >)."""
    result = _should_format_concept({"passes_85_floor": True, "final": 85})
    assert result is True


def test_quality_pass_zero_score() -> None:
    """Concept with score 0 is excluded by formatter."""
    result = _should_format_concept({"passes_85_floor": False, "final": 0})
    assert result is False
