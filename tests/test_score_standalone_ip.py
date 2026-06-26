"""De-franchise facet (v5.1.0) — the 8th crystallization facet.

The operator's mandate: strong STANDALONE ideas, not franchise/sequel-
dependent ones. ``standalone_ip`` rewards concepts whose cash flow does not
lean on pre-existing IP. The module-level weight stays 0.0 (the v4 fallback
is byte-identical), but config/goal.json promotes it LIVE to 0.08 (funded by
derivative_distance 0.20 -> 0.12, so the 0.20 "originality budget" is
preserved, just split into corpus-novelty + franchise-independence).

Hermetic: pure scoring + regex; no network.
"""

from __future__ import annotations

import pytest

from pipeline.crystallize.score import (
    _STANDALONE_IP_FLOOR,
    _STANDALONE_IP_NEUTRAL,
    _standalone_ip_factor,
    _weights_from_goal,
    crystallization_score,
)
from pipeline.empirical_genius import detect_standalone_ip
from pipeline.goal import Goal

_BASE_SCORES = {
    "genius_score": 0.8,
    "goldilocks_score": 0.7,
    "cluster_coherence": 0.7,
    "emotional_universality_score": 4.0,
    "som_y1_usd": 300_000_000.0,
    "passes_500m_gate": True,
    "passes_genius_gate": True,
}


def test_standalone_ip_factor_values() -> None:
    assert _standalone_ip_factor(True) == 1.0
    assert _standalone_ip_factor(None) == _STANDALONE_IP_NEUTRAL == 0.5
    assert _standalone_ip_factor(False) == _STANDALONE_IP_FLOOR == 0.25


def test_default_fallback_is_byte_identical() -> None:
    """With no goal (v4 fallback, standalone_ip weight 0.0) the facet is inert:
    the flag must not move the score by even one ULP."""
    without = crystallization_score(dict(_BASE_SCORES))
    with_flag_true = crystallization_score({**_BASE_SCORES, "standalone_ip_flag": True})
    with_flag_false = crystallization_score({**_BASE_SCORES, "standalone_ip_flag": False})
    assert without == with_flag_true == with_flag_false


def test_live_goal_penalizes_franchise() -> None:
    """Under the live goal.json weights, a standalone concept scores strictly
    higher than an otherwise-identical franchise concept, and NEVER lower."""
    goal = Goal.load()  # config/goal.json — standalone_ip live at 0.08
    standalone = crystallization_score({**_BASE_SCORES, "standalone_ip_flag": True}, goal=goal)
    franchise = crystallization_score({**_BASE_SCORES, "standalone_ip_flag": False}, goal=goal)
    ambiguous = crystallization_score({**_BASE_SCORES, "standalone_ip_flag": None}, goal=goal)
    assert standalone > ambiguous > franchise


def test_eight_facet_weights_sum_to_one() -> None:
    """The effective exponent vector read through _weights_from_goal (all 8
    facets, incl operator_alignment 0.0 + standalone_ip) sums to 1.0."""
    goal = Goal.load()
    w = _weights_from_goal(goal)
    assert "standalone_ip" in w
    assert sum(w.values()) == pytest.approx(1.0)


def test_detect_standalone_ip() -> None:
    assert detect_standalone_ip("A sequel to the beloved space saga.", "") is False
    assert detect_standalone_ip("Set in the shared cinematic universe.", "") is False
    assert detect_standalone_ip("Based on the bestselling video game.", "") is False
    assert detect_standalone_ip("A remake of the 1970s thriller.", "") is False
    original = (
        "A grief counselor for AIs discovers her newest client is plotting a human extinction."
    )
    assert detect_standalone_ip(original, "") is True
    assert detect_standalone_ip("", "") is None  # no text -> ambiguous
