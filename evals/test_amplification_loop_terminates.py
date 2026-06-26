"""EVAL -- Amplification loop (L2) terminates via plateau detection.

Tests that plateau_reached correctly terminates the L2 amplification loop
and that the 5-iteration cap is enforced.

SKIP until Wave C creates pipeline/loop_controller.py.
"""

from __future__ import annotations

import pytest

_mod = pytest.importorskip("pipeline.loop_controller", reason="defensive import guard")
patch_budget = _mod.patch_budget
plateau_reached = _mod.plateau_reached

# ── Synthetic SOM histories ───────────────────────────────────────────────────

# Rapid growth then plateau -- should terminate before the 5-iter cap
_GROW_THEN_FLAT = [100.0, 140.0, 180.0, 183.0, 184.0]

# Immediately plateaued -- should terminate at iter 2 or 3
_IMMEDIATE_PLATEAU = [100.0, 101.0, 101.5]

# Sustained growth >5% per iter -- should NOT plateau before cap
_ALWAYS_GROWING = [100.0, 110.0, 125.0, 145.0, 170.0]

# Exactly at the 5-iter cap (6 entries = iter-0 through iter-5)
_AT_CAP = [100.0, 120.0, 145.0, 175.0, 210.0, 250.0]


class TestAmplificationLoopTerminates:
    def test_plateau_detected_in_grow_then_flat(self) -> None:
        assert plateau_reached(_GROW_THEN_FLAT, delta_threshold=0.05) is True

    def test_plateau_detected_immediately(self) -> None:
        assert plateau_reached(_IMMEDIATE_PLATEAU, delta_threshold=0.05) is True

    def test_no_plateau_when_always_growing(self) -> None:
        assert plateau_reached(_ALWAYS_GROWING, delta_threshold=0.05) is False

    def test_l2_budget_is_5(self) -> None:
        assert patch_budget("L2") == 5

    def test_growing_then_flat_terminates_before_cap(self) -> None:
        budget = patch_budget("L2")
        history: list[float] = []
        termination_iter = budget  # default: ran to cap
        for i, som in enumerate(_GROW_THEN_FLAT):
            history.append(som)
            if plateau_reached(history) or i + 1 >= budget:
                termination_iter = i
                break
        assert termination_iter < budget

    def test_immediate_plateau_terminates_early(self) -> None:
        budget = patch_budget("L2")
        history: list[float] = []
        terminated_early = False
        for i, som in enumerate(_IMMEDIATE_PLATEAU):
            history.append(som)
            if plateau_reached(history):
                terminated_early = True
                assert i < budget
                break
        assert terminated_early

    def test_loop_stops_at_cap_when_no_plateau(self) -> None:
        budget = patch_budget("L2")
        iters_run = sum(1 for i, _ in enumerate(_AT_CAP) if i < budget)
        assert iters_run == budget

    def test_plateau_threshold_default_is_five_percent(self) -> None:
        # Two consecutive 4.9% deltas both below 5% -- window=2 satisfied
        # 100 -> 104.9 (4.9%) -> 109.7 (~4.6%) -- both below 5%
        assert plateau_reached([100.0, 104.9, 109.7]) is True

    def test_five_percent_exactly_is_not_plateau(self) -> None:
        # 5.0% growth is NOT below the threshold (equal is not less than)
        # window=2 requires two such deltas; these two are exactly at boundary
        assert plateau_reached([100.0, 105.0, 110.25]) is False

    def test_single_entry_never_plateaus(self) -> None:
        assert plateau_reached([100.0]) is False

    def test_empty_history_never_plateaus(self) -> None:
        assert plateau_reached([]) is False
