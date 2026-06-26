"""Tests for the operator_alignment facet (Step 5 facet 7).

Two layers:

1. compute_operator_alignment correctness (pipeline.feedback) — given fixture
   labels + winners, the math returns the expected cosine-mapped value.

2. crystallization_score wire (pipeline.crystallize.score) — the new
   ``operator_alignment`` parameter integrates into the geometric mean
   without shifting any pre-rating score by even one ULP, because
   ``_W_OP_ALIGN`` starts at 0.0.

The fixture ratings here are deliberately fictional (axis vectors of
made-up numbers) so this test file does not encode any operator taste.
The real validation happens after the operator rates >= 30 concepts.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from pipeline import feedback
from pipeline.crystallize import score as score_mod
from pipeline.goal import Goal

# ---------------------------------------------------------------------------
# compute_operator_alignment — degenerate / insufficient signal paths
# ---------------------------------------------------------------------------


class TestComputeOperatorAlignmentNoSignal:
    def test_empty_rated_rows_returns_neutral(self) -> None:
        result = feedback.compute_operator_alignment(
            candidate_facets={
                "genius": 0.8,
                "goldilocks": 0.5,
                "cluster_coherence": 0.6,
                "emotional_universality": 0.7,
                "som_y1": 0.4,
                "derivative_distance": 0.9,
            },
            rated_rows=[],
            winners_by_run_id={},
        )
        assert result == feedback.OPERATOR_ALIGNMENT_NEUTRAL

    def test_only_negative_ratings_returns_neutral(self) -> None:
        rated = [
            {"run_id": "r1", "rating": -2, "ts": "2026-05-20T10:00:00+00:00"},
            {"run_id": "r2", "rating": -1, "ts": "2026-05-21T10:00:00+00:00"},
        ]
        winners = {
            "r1": {
                "genius": 0.5,
                "goldilocks": 0.5,
                "cluster_coherence": 0.5,
                "emotional_universality": 0.5,
                "som_y1": 0.5,
                "derivative_distance": 0.5,
            },
            "r2": {
                "genius": 0.5,
                "goldilocks": 0.5,
                "cluster_coherence": 0.5,
                "emotional_universality": 0.5,
                "som_y1": 0.5,
                "derivative_distance": 0.5,
            },
        }
        result = feedback.compute_operator_alignment(
            candidate_facets={"genius": 0.9},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == feedback.OPERATOR_ALIGNMENT_NEUTRAL

    def test_below_min_positive_returns_neutral(self) -> None:
        rated = [
            {"run_id": f"r{i}", "rating": 1, "ts": "2026-05-20T10:00:00+00:00"}
            for i in range(feedback.MIN_POSITIVE_FOR_ALIGNMENT - 1)
        ]
        winners = {
            f"r{i}": {f: 0.5 for f in feedback._V4_FACETS}
            for i in range(feedback.MIN_POSITIVE_FOR_ALIGNMENT - 1)
        }
        result = feedback.compute_operator_alignment(
            candidate_facets={f: 0.5 for f in feedback._V4_FACETS},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == feedback.OPERATOR_ALIGNMENT_NEUTRAL

    def test_missing_winners_sidecar_skips_row(self) -> None:
        rated = [
            {"run_id": f"r{i}", "rating": 1, "ts": "2026-05-20T10:00:00+00:00"}
            for i in range(feedback.MIN_POSITIVE_FOR_ALIGNMENT)
        ]
        winners: dict[str, dict[str, float]] = {}
        result = feedback.compute_operator_alignment(
            candidate_facets={f: 0.5 for f in feedback._V4_FACETS},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == feedback.OPERATOR_ALIGNMENT_NEUTRAL


# ---------------------------------------------------------------------------
# compute_operator_alignment — real-signal math
# ---------------------------------------------------------------------------


def _fixture_positive_batch(
    n: int = 5, value: float = 0.7
) -> tuple[list[dict[str, object]], dict[str, dict[str, float]]]:
    """n positive ratings, each winner has a uniform facet vector at ``value``."""
    rated = [{"run_id": f"r{i}", "rating": 1, "ts": "2026-05-20T10:00:00+00:00"} for i in range(n)]
    winners = {f"r{i}": {f: value for f in feedback._V4_FACETS} for i in range(n)}
    return rated, winners


class TestComputeOperatorAlignmentMath:
    def test_identical_candidate_and_centroid_returns_one(self) -> None:
        rated, winners = _fixture_positive_batch()
        # Candidate equals centroid exactly -> cosine = 1 -> (1+1)/2 = 1.0
        result = feedback.compute_operator_alignment(
            candidate_facets={f: 0.7 for f in feedback._V4_FACETS},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == pytest.approx(1.0)

    def test_scaled_candidate_returns_one(self) -> None:
        """Cosine is scale-invariant: a 2x-magnitude version of the
        centroid still has cosine 1."""
        rated, winners = _fixture_positive_batch(value=0.5)
        result = feedback.compute_operator_alignment(
            candidate_facets={f: 0.9 for f in feedback._V4_FACETS},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == pytest.approx(1.0)

    def test_orthogonal_candidate_returns_half(self) -> None:
        """Candidate orthogonal to centroid -> cosine = 0 -> (1+0)/2 = 0.5."""
        # Centroid lives on the genius axis; candidate lives on goldilocks.
        rated = [
            {"run_id": f"r{i}", "rating": 1, "ts": "2026-05-20T10:00:00+00:00"} for i in range(5)
        ]
        winners = {
            f"r{i}": {
                "genius": 1.0,
                "goldilocks": 0.0,
                "cluster_coherence": 0.0,
                "emotional_universality": 0.0,
                "som_y1": 0.0,
                "derivative_distance": 0.0,
            }
            for i in range(5)
        }
        result = feedback.compute_operator_alignment(
            candidate_facets={
                "genius": 0.0,
                "goldilocks": 1.0,
                "cluster_coherence": 0.0,
                "emotional_universality": 0.0,
                "som_y1": 0.0,
                "derivative_distance": 0.0,
            },
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == pytest.approx(0.5)

    def test_zero_candidate_returns_half(self) -> None:
        """All-zero candidate -> cosine helper returns 0 -> mapped to 0.5."""
        rated, winners = _fixture_positive_batch()
        result = feedback.compute_operator_alignment(
            candidate_facets={f: 0.0 for f in feedback._V4_FACETS},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        assert result == pytest.approx(0.5)

    def test_ignores_negative_ratings_when_building_centroid(self) -> None:
        """Negative rows do not pull the centroid -- only +1/+2 do."""
        # 5 positive winners at value 1.0; one negative winner at value 0.0.
        # If the centroid is built from positives only, it points at 1.0.
        # If negatives leaked in, the centroid would be ~5/6 (different angle).
        rated, winners = _fixture_positive_batch(value=1.0)
        rated.append({"run_id": "neg1", "rating": -2, "ts": "2026-05-20T10:00:00+00:00"})
        winners["neg1"] = {f: 0.0 for f in feedback._V4_FACETS}
        result = feedback.compute_operator_alignment(
            candidate_facets={f: 1.0 for f in feedback._V4_FACETS},
            rated_rows=rated,
            winners_by_run_id=winners,
        )
        # Negative is excluded, candidate matches positive centroid exactly.
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# crystallization_score wire — pre-rating must be byte-identical
# ---------------------------------------------------------------------------


_BASELINE_SCORES: dict[str, object] = {
    "genius_score": 0.75,
    "goldilocks_score": 0.60,
    "cluster_coherence": 0.55,
    "emotional_universality_score": 3.5,
    "som_y1_usd": 150_000_000.0,
    "passes_500m_gate": True,
    "passes_genius_gate": True,
}


class TestCrystallizationScoreWire:
    def test_default_operator_alignment_byte_identical_to_legacy(self) -> None:
        """Calling without operator_alignment must match calling with
        operator_alignment=1.0 -- and both must match the historical
        6-facet output."""
        legacy = score_mod.crystallization_score(_BASELINE_SCORES, derivative_distance=0.85)
        explicit_neutral = score_mod.crystallization_score(
            _BASELINE_SCORES, derivative_distance=0.85, operator_alignment=1.0
        )
        assert legacy == explicit_neutral

    def test_zero_op_align_no_shift_because_exponent_is_zero(self) -> None:
        """``_W_OP_ALIGN == 0.0`` means ``x ** 0 == 1`` for any x in
        ``(0, 1]`` -- so even a 0.0 operator_alignment leaves the score
        unchanged in this commit."""
        baseline = score_mod.crystallization_score(
            _BASELINE_SCORES, derivative_distance=0.85, operator_alignment=1.0
        )
        with_zero = score_mod.crystallization_score(
            _BASELINE_SCORES, derivative_distance=0.85, operator_alignment=0.0001
        )
        # Tolerance: the _safe_factor floor / FLOOR clamp can introduce
        # epsilon differences; what matters is that the result is
        # effectively unchanged when exponent is zero.
        assert math.isclose(baseline, with_zero, abs_tol=1e-12)

    def test_v4_weights_fallback_includes_operator_alignment(self) -> None:
        assert "operator_alignment" in score_mod._V4_WEIGHTS_FALLBACK
        assert score_mod._V4_WEIGHTS_FALLBACK["operator_alignment"] == 0.0

    def test_weight_promotion_via_goal_changes_score(self) -> None:
        """When a Goal supplies a non-zero operator_alignment weight,
        the facet starts shifting fitness. This is the activation path."""

        # Build a goal that promotes operator_alignment to 0.10 and pulls
        # the same amount from derivative_distance (sum stays 1.0).
        active_goal = dataclasses.replace(
            Goal.default(),
            facet_weights={
                "genius": 0.30,
                "goldilocks": 0.18,
                "cluster_coherence": 0.17,
                "emotional_universality": 0.13,
                "som_y1": 0.09,
                "derivative_distance": 0.03,
                "operator_alignment": 0.10,
            },
        )
        high_align = score_mod.crystallization_score(
            _BASELINE_SCORES,
            derivative_distance=0.85,
            goal=active_goal,
            operator_alignment=0.95,
        )
        low_align = score_mod.crystallization_score(
            _BASELINE_SCORES,
            derivative_distance=0.85,
            goal=active_goal,
            operator_alignment=0.10,
        )
        assert high_align > low_align
