"""Tests for pipeline/crystallize/score.py — crystallization_score scalar.

Covers:
- Output always in [0, 1].
- Geometric mean property: any near-zero factor collapses the total.
- Monotonic in genius_score (holding others constant).
- Gate multiplier halves the score when either gate fails.
- derivative_distance factor: 0.0 collapses, 1.0 no-op.
- emotional_universality_score / 5.0 rescaling.
- som_floor_M / 300.0 saturation.
- Exponents sum to 1.0 (geometric-mean invariant).
- None / NaN / non-numeric inputs handled gracefully.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline.crystallize import score as score_mod
from pipeline.crystallize.score import (
    _FLOOR,
    _GATE_FAILURE_PENALTY,
    crystallization_score,
)


def _full_scores(**overrides: Any) -> dict[str, Any]:
    """Return a CompoundScore-shaped dict with all-mid defaults, override as needed."""
    base: dict[str, Any] = {
        "genius_score": 0.7,
        "goldilocks_score": 0.7,
        "cluster_coherence": 0.7,
        "emotional_universality_score": 3.5,  # mid
        "som_floor_M": 200.0,  # mid
        "passes_500m_gate": True,
        "passes_genius_gate": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Range and bounds
# ---------------------------------------------------------------------------


def test_score_in_unit_interval() -> None:
    s = crystallization_score(_full_scores(), derivative_distance=0.5)
    assert 0.0 <= s <= 1.0


def test_score_all_maxed_approaches_one() -> None:
    s = crystallization_score(
        _full_scores(
            genius_score=1.0,
            goldilocks_score=1.0,
            cluster_coherence=1.0,
            emotional_universality_score=5.0,
            som_floor_M=400.0,
        ),
        derivative_distance=1.0,
    )
    assert s == pytest.approx(1.0)


def test_score_all_zero_does_not_crash() -> None:
    """Zero facets are floored to _FLOOR to avoid 0**0.13 = 1.0 surprises."""
    s = crystallization_score(
        _full_scores(
            genius_score=0.0,
            goldilocks_score=0.0,
            cluster_coherence=0.0,
            emotional_universality_score=0.0,
            som_floor_M=0.0,
        ),
        derivative_distance=0.0,
    )
    assert 0.0 <= s <= 1.0
    # At all-zero, every facet is _FLOOR (1e-6), so product is tiny.
    assert s < 1e-3


# ---------------------------------------------------------------------------
# Geometric mean property
# ---------------------------------------------------------------------------


def test_one_zero_factor_collapses_total() -> None:
    """If genius=0, the whole score must collapse (geometric not arithmetic)."""
    high_others = _full_scores(
        goldilocks_score=1.0,
        cluster_coherence=1.0,
        emotional_universality_score=5.0,
        som_floor_M=400.0,
    )
    arithmetic_high = crystallization_score(high_others, derivative_distance=1.0)
    collapsed = crystallization_score({**high_others, "genius_score": 0.0}, 1.0)
    # Collapsed score must be drastically smaller than the arithmetic-high baseline.
    assert collapsed < arithmetic_high * 0.05


def test_monotonic_in_genius_holding_others_constant() -> None:
    low = crystallization_score(_full_scores(genius_score=0.2), derivative_distance=1.0)
    mid = crystallization_score(_full_scores(genius_score=0.6), derivative_distance=1.0)
    high = crystallization_score(_full_scores(genius_score=1.0), derivative_distance=1.0)
    assert low < mid < high


# ---------------------------------------------------------------------------
# Gate multiplier
# ---------------------------------------------------------------------------


def test_gate_failure_halves_score() -> None:
    passing = crystallization_score(
        _full_scores(passes_500m_gate=True, passes_genius_gate=True),
        derivative_distance=1.0,
    )
    failing_500m = crystallization_score(
        _full_scores(passes_500m_gate=False, passes_genius_gate=True),
        derivative_distance=1.0,
    )
    failing_genius = crystallization_score(
        _full_scores(passes_500m_gate=True, passes_genius_gate=False),
        derivative_distance=1.0,
    )
    assert failing_500m == pytest.approx(passing * _GATE_FAILURE_PENALTY)
    assert failing_genius == pytest.approx(passing * _GATE_FAILURE_PENALTY)


def test_both_gates_failing_still_halves_once() -> None:
    """Penalty is multiplicative once, not squared, when both gates fail."""
    passing = crystallization_score(_full_scores(), derivative_distance=1.0)
    both_fail = crystallization_score(
        _full_scores(passes_500m_gate=False, passes_genius_gate=False),
        derivative_distance=1.0,
    )
    assert both_fail == pytest.approx(passing * _GATE_FAILURE_PENALTY)


# ---------------------------------------------------------------------------
# derivative_distance factor
# ---------------------------------------------------------------------------


def test_derivative_distance_one_is_noop() -> None:
    """derivative_distance=1.0 means no novelty penalty — score unchanged."""
    with_corpus = crystallization_score(_full_scores(), derivative_distance=1.0)
    no_corpus_default = crystallization_score(_full_scores())  # default 1.0
    assert with_corpus == pytest.approx(no_corpus_default)


def test_derivative_distance_zero_penalises() -> None:
    full_novel = crystallization_score(_full_scores(), derivative_distance=1.0)
    fully_derivative = crystallization_score(_full_scores(), derivative_distance=0.0)
    # _FLOOR ** 0.13 is much less than 1, so fully_derivative << full_novel.
    assert fully_derivative < full_novel * 0.5


def test_derivative_distance_monotonic() -> None:
    low = crystallization_score(_full_scores(), derivative_distance=0.1)
    mid = crystallization_score(_full_scores(), derivative_distance=0.5)
    high = crystallization_score(_full_scores(), derivative_distance=0.95)
    assert low < mid < high


# ---------------------------------------------------------------------------
# Sub-score rescaling
# ---------------------------------------------------------------------------


def test_emotional_universality_rescaled_by_five() -> None:
    """emo=5.0 saturates the factor at 1.0; emo=2.5 sits at 0.5."""
    saturated = crystallization_score(
        _full_scores(emotional_universality_score=5.0), derivative_distance=1.0
    )
    half = crystallization_score(
        _full_scores(emotional_universality_score=2.5), derivative_distance=1.0
    )
    assert saturated > half


def test_som_floor_saturates_at_300m() -> None:
    """som_floor_M >= 300 is treated identically (saturates)."""
    at_threshold = crystallization_score(_full_scores(som_floor_M=300.0), derivative_distance=1.0)
    above_threshold = crystallization_score(
        _full_scores(som_floor_M=600.0), derivative_distance=1.0
    )
    # Both clamp to factor 1.0 → same score.
    assert at_threshold == pytest.approx(above_threshold)


# ---------------------------------------------------------------------------
# Exponent invariant
# ---------------------------------------------------------------------------


def test_exponents_sum_to_one() -> None:
    """Geometric-mean exponents must sum to 1.0 so a homogeneous all-1 input
    produces exactly 1.0 (already covered by ``test_score_all_maxed_approaches_one``,
    but pin the sum explicitly so future tweaks can't violate it silently)."""
    total = (
        score_mod._W_GENIUS
        + score_mod._W_GOLDILOCKS
        + score_mod._W_CLUSTER_COHERENCE
        + score_mod._W_EMO
        + score_mod._W_SOM
        + score_mod._W_DERIV
        + score_mod._W_OP_ALIGN
    )
    assert total == pytest.approx(1.0)


def test_v4_fallback_cannot_diverge_from_goal_canonical() -> None:
    """score.py's v4 fallback is DERIVED from goal._V4_DEFAULT_WEIGHTS, and each
    documented _W_* exponent must equal the canonical goal value. This is the
    enforcer that closes the latent drift the audit flagged: edit a weight in one
    module without the other and this goes RED."""
    from pipeline.goal import _V4_DEFAULT_WEIGHTS  # noqa: PLC0415

    expected = {**_V4_DEFAULT_WEIGHTS, "operator_alignment": 0.0}
    assert expected == score_mod._V4_WEIGHTS_FALLBACK
    assert _V4_DEFAULT_WEIGHTS["genius"] == score_mod._W_GENIUS
    assert _V4_DEFAULT_WEIGHTS["goldilocks"] == score_mod._W_GOLDILOCKS
    assert _V4_DEFAULT_WEIGHTS["cluster_coherence"] == score_mod._W_CLUSTER_COHERENCE
    assert _V4_DEFAULT_WEIGHTS["emotional_universality"] == score_mod._W_EMO
    assert _V4_DEFAULT_WEIGHTS["som_y1"] == score_mod._W_SOM
    assert _V4_DEFAULT_WEIGHTS["derivative_distance"] == score_mod._W_DERIV
    assert _V4_DEFAULT_WEIGHTS["standalone_ip"] == score_mod._W_STANDALONE_IP


# ---------------------------------------------------------------------------
# Defensive parsing
# ---------------------------------------------------------------------------


def test_missing_field_does_not_crash() -> None:
    """Score handles incomplete scores dict gracefully (returns ~0)."""
    s = crystallization_score({}, derivative_distance=1.0)
    # All-missing → all floored to _FLOOR → product is _FLOOR ** 1.0 = _FLOOR.
    assert 0.0 <= s <= 0.001


def test_nan_field_treated_as_floor() -> None:
    s = crystallization_score(_full_scores(genius_score=float("nan")), derivative_distance=1.0)
    assert 0.0 <= s <= 1.0


def test_none_field_treated_as_floor() -> None:
    s = crystallization_score(
        _full_scores(emotional_universality_score=None), derivative_distance=1.0
    )
    assert 0.0 <= s <= 1.0
    # Score must be measurably lower than when emo is present.
    s_with_emo = crystallization_score(
        _full_scores(emotional_universality_score=4.0), derivative_distance=1.0
    )
    assert s < s_with_emo


def test_safe_factor_floor_constant_is_tiny() -> None:
    assert _FLOOR > 0.0
    assert _FLOOR < 1e-3
