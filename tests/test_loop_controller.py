"""Tests for pipeline.loop_controller -- plateau_reached + patch_budget.

SKIP until Wave C creates pipeline/loop_controller.py.
"""

from __future__ import annotations

import pytest

_mod = pytest.importorskip("pipeline.loop_controller", reason="defensive import guard")
patch_budget = _mod.patch_budget
plateau_reached = _mod.plateau_reached


class TestPlateauReached:
    def test_no_plateau_single_entry(self) -> None:
        assert plateau_reached([100.0]) is False

    def test_no_plateau_empty(self) -> None:
        assert plateau_reached([]) is False

    def test_no_plateau_when_growing(self) -> None:
        assert plateau_reached([100.0, 115.0, 135.0]) is False

    def test_plateau_when_delta_below_threshold_twice(self) -> None:
        # 100 -> 103 (3%) -> 104 (~0.97%) — two consecutive below 5%
        assert plateau_reached([100.0, 103.0, 104.0], delta_threshold=0.05) is True

    def test_no_plateau_only_one_below_threshold(self) -> None:
        # 100 -> 103 (3%) -> 115 (11.7%) — second is ABOVE threshold
        assert plateau_reached([100.0, 103.0, 115.0], delta_threshold=0.05) is False

    def test_plateau_two_consecutive_at_four_percent(self) -> None:
        # Both deltas 4% < 5%
        assert plateau_reached([100.0, 104.0, 108.16]) is True

    def test_exactly_at_threshold_not_plateau(self) -> None:
        # delta == 0.05 exactly is NOT below threshold
        assert plateau_reached([100.0, 105.0, 110.25], delta_threshold=0.05) is False

    def test_custom_window_three_required(self) -> None:
        # window=3: need 3 consecutive below-threshold deltas
        # deltas: 3%, ~1.9%, ~1.9% — all below 5%
        assert plateau_reached([100.0, 103.0, 105.0, 107.0], delta_threshold=0.05, window=3) is True

    def test_custom_window_three_not_met(self) -> None:
        # Only 2 below-threshold deltas when window=3
        assert (
            plateau_reached([100.0, 103.0, 104.0, 125.0], delta_threshold=0.05, window=3) is False
        )

    def test_returns_bool(self) -> None:
        assert isinstance(plateau_reached([100.0, 101.0, 101.5]), bool)


class TestPatchBudget:
    def test_l1_challenge_budget_is_3(self) -> None:
        assert patch_budget("L1") == 3

    def test_l2_amplification_budget_is_5(self) -> None:
        assert patch_budget("L2") == 5

    def test_l3_genius_budget_is_3(self) -> None:
        assert patch_budget("L3") == 3

    def test_l4_consistency_budget_is_3(self) -> None:
        assert patch_budget("L4") == 3

    def test_l5_narrator_budget_is_2(self) -> None:
        assert patch_budget("L5") == 2

    def test_unknown_loop_raises(self) -> None:
        with pytest.raises((KeyError, ValueError)):
            patch_budget("L99")

    def test_lowercase_accepted(self) -> None:
        assert patch_budget("l1") == patch_budget("L1")
        assert patch_budget("l2") == patch_budget("L2")
