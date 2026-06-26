"""Regression: at ``_W_OP_ALIGN = 0.0`` the 7th facet must be a true no-op.

The Step 5 facet (operator_alignment) is wired structurally in
``pipeline.crystallize.score`` at weight zero. The math should produce
output equal (to floating-point tolerance) to the pre-Step-5 6-facet
score, regardless of what value the 7th-facet input takes.

If a future refactor accidentally promotes ``_W_OP_ALIGN`` to a
non-zero default, every comparison here flips red — a useful guard.

This file is sibling to ``test_operator_alignment.py``: that file tests
the *math* of ``compute_operator_alignment``; this file tests the
*wire* — specifically that the 7th factor disappears at weight zero.
"""

from __future__ import annotations

import pytest

from pipeline.crystallize import score as score_mod

# A synthetic candidate that exercises every facet (no edge-case zeros).
_BASE_SCORES: dict[str, float | bool] = {
    "genius_score": 0.83,
    "goldilocks_score": 0.62,
    "cluster_coherence": 0.71,
    "emotional_universality_score": 7.4,
    "som_y1_usd": 460_000_000.0,
    "passes_500m_gate": True,
    "passes_genius_gate": True,
}

# Three operator_alignment values that span the [0, 1] range. With the
# weight at 0.0, every value of x raised to 0.0 is 1.0, so all three
# inputs should produce *identical* output.
_OP_ALIGN_PROBES: list[float] = [0.0, 0.5, 1.0]


def test_w_op_align_is_zero_by_default() -> None:
    """Guard the constant itself: if a refactor changes the default the
    rest of this file would silently start exercising a different gate."""
    assert score_mod._W_OP_ALIGN == 0.0  # pyright: ignore[reportPrivateUsage]


def test_operator_alignment_default_is_neutral() -> None:
    """Default ``operator_alignment=1.0`` should produce the v4 score."""
    baseline = score_mod.crystallization_score(dict(_BASE_SCORES), derivative_distance=0.7)
    explicit_neutral = score_mod.crystallization_score(
        dict(_BASE_SCORES), derivative_distance=0.7, operator_alignment=1.0
    )
    assert baseline == pytest.approx(explicit_neutral)


@pytest.mark.parametrize("op_align", _OP_ALIGN_PROBES)
def test_op_align_value_does_not_shift_score_when_weight_is_zero(
    op_align: float,
) -> None:
    """The 7th factor is ``op_align ** _W_OP_ALIGN``. With the exponent
    at 0.0, output is identical for every ``op_align`` input."""
    baseline = score_mod.crystallization_score(
        dict(_BASE_SCORES), derivative_distance=0.7, operator_alignment=1.0
    )
    with_probe = score_mod.crystallization_score(
        dict(_BASE_SCORES), derivative_distance=0.7, operator_alignment=op_align
    )
    assert with_probe == pytest.approx(baseline, abs=1e-12)


def test_op_align_zero_special_case_does_not_collapse_score() -> None:
    """Edge case: ``0.0 ** 0.0`` in Python returns 1.0 (mathematical
    convention). So even an explicit zero alignment cannot zero the
    score while ``_W_OP_ALIGN`` is 0.0 — ``_safe_factor`` doesn't even
    have to kick in. This pins that behaviour."""
    baseline = score_mod.crystallization_score(
        dict(_BASE_SCORES), derivative_distance=0.7, operator_alignment=1.0
    )
    with_zero = score_mod.crystallization_score(
        dict(_BASE_SCORES), derivative_distance=0.7, operator_alignment=0.0
    )
    assert with_zero == pytest.approx(baseline, abs=1e-12)


def test_gate_failure_still_dominates_regardless_of_op_align() -> None:
    """The multiplicative gate penalty must remain the deciding factor —
    operator_alignment at weight 0.0 cannot rescue a failed gate."""
    failed_scores = dict(_BASE_SCORES)
    failed_scores["passes_500m_gate"] = False
    score_with_op_max = score_mod.crystallization_score(
        failed_scores, derivative_distance=0.7, operator_alignment=1.0
    )
    score_with_op_min = score_mod.crystallization_score(
        failed_scores, derivative_distance=0.7, operator_alignment=0.0
    )
    # Same penalised value either way.
    assert score_with_op_max == pytest.approx(score_with_op_min, abs=1e-12)
    # Penalised — must be strictly less than the all-passing baseline.
    passing = score_mod.crystallization_score(
        dict(_BASE_SCORES), derivative_distance=0.7, operator_alignment=1.0
    )
    assert score_with_op_max < passing
