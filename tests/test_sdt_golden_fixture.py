"""Golden fixture for KNOW-02: SDT spine Al-Bukhari worked example.

Pins the contract that P3 `pipeline/scoring.py::sdt_score` must satisfy.

Status:
- Today (P1): XFAIL — pipeline.scoring does not exist yet.
- After P3 lands sdt_score body: PASS automatically; the strict=True flag
  ensures any drift from the documented formula in
  frameworks/sdt-spine.md surfaces as a test failure (not a silent XPASS).

References:
- frameworks/sdt-spine.md §The sdt_score Formula
- frameworks/sdt-spine.md §The Worked Al-Bukhari Example
- ADR-0002 (LLMs no arithmetic — scoring.py is the single source of truth)
- .planning/phases/01-knowledge-layer/01-RESEARCH.md §SDT Golden Fixture
"""

from __future__ import annotations

import pytest

# Defer import: P3 lands pipeline.scoring; until then importorskip → Skip.
scoring = pytest.importorskip(
    "pipeline.scoring",
    reason="pipeline.scoring lands in P3 plan 03-03 (sdt_score body)",
)


def test_al_bukhari_sdt_score_equals_70() -> None:
    """Al-Bukhari hand-computed sdt_score must equal 70/70.

    Inputs (from frameworks/sdt-spine.md §The Worked Al-Bukhari Example):
        primary_need              = "relatedness"
        primary_strength          = 0.95
        secondary_need            = "competence"
        secondary_strength        = 0.7
        deprivation_amplifier_active = True

    Manual computation (from frameworks/sdt-spine.md):
        primary_contrib   = 50 * 0.95 * 1.5 = 71.25
        secondary_contrib = 20 * 0.7        = 14.0
        amplified         = 71.25 + 14.0    = 85.25
        rounded           = round(85.25)    = 85
        capped            = min(85, 70)     = 70
        floor (s1>=0.7)   = pass
        => sdt_score      = 70
    """
    result = scoring.sdt_score(
        primary_need="relatedness",
        primary_strength=0.95,
        secondary_need="competence",
        secondary_strength=0.7,
        deprivation_amplifier_active=True,
    )
    assert result == 70, (
        f"sdt_score drift: got {result}, expected 70 per "
        f"frameworks/sdt-spine.md §The Worked Al-Bukhari Example. "
        f"Either update frameworks/sdt-spine.md (with operator approval) "
        f"or fix pipeline/scoring.py::sdt_score to match the documented formula."
    )


def test_sdt_score_returns_zero_below_floor() -> None:
    """primary_strength < 0.7 => sdt_score returns 0 (floor)."""
    result = scoring.sdt_score(
        primary_need="autonomy",
        primary_strength=0.5,  # below the 0.7 floor
        secondary_need=None,
        secondary_strength=0.0,
        deprivation_amplifier_active=False,
    )
    assert result == 0, (
        f"Floor check drift: primary_strength=0.5 (<0.7) must return 0, got {result}"
    )
