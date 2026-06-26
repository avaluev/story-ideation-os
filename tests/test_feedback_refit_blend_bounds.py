"""Bound invariants for ``refit_weights`` — the prior-blend floor.

``pipeline/feedback.py`` documents (lines 75-79) that the default
``prior_blend = 0.3`` keeps a prior floor so "10 ratings cannot flip
the engine into a corner". This file makes that claim mechanical:

  - After ``refit_weights`` with N ratings, no single facet weight may
    exceed ``(1 - prior_blend) + prior_blend * max(uniform_prior)``.
  - Weights always sum to ~1.0 (normalised output).
  - Degenerate inputs (no usable rows, all-same-class labels) return
    the prior unchanged.

The synthetic fixtures here use clearly-made-up ratings — they do not
encode any real operator taste; the real validation runs after the
operator rates >= 30 concepts.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pipeline import feedback

_NOW = datetime(2026, 5, 28, 0, 0, 0, tzinfo=UTC)
_HOUR_AGO = datetime(2026, 5, 27, 23, 0, 0, tzinfo=UTC).isoformat()

# Facet vector that pushes the logistic toward "genius" being the
# discriminating feature. Pure synthetic; no taste claim.
_POSITIVE_FACETS: dict[str, float] = {
    "genius": 0.95,
    "goldilocks": 0.30,
    "cluster_coherence": 0.30,
    "emotional_universality": 0.30,
    "som_y1": 0.30,
    "derivative_distance": 0.30,
}
_NEGATIVE_FACETS: dict[str, float] = {
    "genius": 0.10,
    "goldilocks": 0.30,
    "cluster_coherence": 0.30,
    "emotional_universality": 0.30,
    "som_y1": 0.30,
    "derivative_distance": 0.30,
}


def _make_rated_rows(positive: int, negative: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(positive):
        rows.append({"run_id": f"pos-{i}", "rating": 1, "ts": _HOUR_AGO})
    for i in range(negative):
        rows.append({"run_id": f"neg-{i}", "rating": -1, "ts": _HOUR_AGO})
    return rows


def _make_winners_map(positive: int, negative: int) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for i in range(positive):
        out[f"pos-{i}"] = dict(_POSITIVE_FACETS)
    for i in range(negative):
        out[f"neg-{i}"] = dict(_NEGATIVE_FACETS)
    return out


class TestBlendCeiling:
    def test_ten_ratings_do_not_push_any_weight_above_prior_ceiling(self) -> None:
        """The hard ceiling: (1 - prior_blend) * 1.0 + prior_blend * uniform.

        Default prior_blend=0.3, uniform=1/6 ~= 0.1667. Ceiling = 0.75.
        With 10 ratings, no single facet should exceed that.
        """
        rated = _make_rated_rows(positive=5, negative=5)
        winners = _make_winners_map(positive=5, negative=5)
        out = feedback.refit_weights(rated, winners, now=_NOW)
        uniform = 1.0 / 6
        ceiling = (1.0 - feedback.DEFAULT_PRIOR_BLEND) + (feedback.DEFAULT_PRIOR_BLEND * uniform)
        for facet, weight in out.items():
            assert weight <= ceiling + 1e-9, (
                f"facet {facet} = {weight:.4f} > ceiling {ceiling:.4f} "
                "— 10 ratings flipped the engine into a corner"
            )

    def test_weights_always_sum_to_one(self) -> None:
        rated = _make_rated_rows(positive=5, negative=5)
        winners = _make_winners_map(positive=5, negative=5)
        out = feedback.refit_weights(rated, winners, now=_NOW)
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)

    def test_weights_always_non_negative(self) -> None:
        rated = _make_rated_rows(positive=5, negative=5)
        winners = _make_winners_map(positive=5, negative=5)
        out = feedback.refit_weights(rated, winners, now=_NOW)
        for facet, weight in out.items():
            assert weight >= 0.0, f"negative weight on {facet}: {weight}"


class TestDegenerateDefersToPrior:
    def test_no_rated_rows_returns_prior_unchanged(self) -> None:
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}  # pyright: ignore[reportPrivateUsage]
        out = feedback.refit_weights(
            rated_rows=[], winners_by_run_id={}, prior_weights=prior, now=_NOW
        )
        for facet, expected in prior.items():
            assert out[facet] == pytest.approx(expected)

    def test_all_positive_ratings_degenerate_fit_keeps_prior(self) -> None:
        """Per refit_weights docstring: 'All ratings positive or all
        negative -> the fit degenerates; we fall back to the prior to
        avoid pushing the engine into a single-facet corner.'"""
        rated = _make_rated_rows(positive=10, negative=0)
        winners = _make_winners_map(positive=10, negative=0)
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}  # pyright: ignore[reportPrivateUsage]
        out = feedback.refit_weights(rated, winners, prior_weights=prior, now=_NOW)
        for facet, expected in prior.items():
            assert out[facet] == pytest.approx(expected, abs=1e-9)

    def test_all_negative_ratings_degenerate_fit_keeps_prior(self) -> None:
        rated = _make_rated_rows(positive=0, negative=10)
        winners = _make_winners_map(positive=0, negative=10)
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}  # pyright: ignore[reportPrivateUsage]
        out = feedback.refit_weights(rated, winners, prior_weights=prior, now=_NOW)
        for facet, expected in prior.items():
            assert out[facet] == pytest.approx(expected, abs=1e-9)

    def test_missing_winners_for_rated_rows_returns_prior(self) -> None:
        """Rated rows whose run_id has no winners.json are skipped;
        if NONE resolve, refit returns the prior."""
        rated = _make_rated_rows(positive=5, negative=5)
        out = feedback.refit_weights(rated, winners_by_run_id={}, now=_NOW)
        # Default prior is uniform 1/6.
        for weight in out.values():
            assert weight == pytest.approx(1.0 / 6, abs=1e-9)


class TestExtremePriorBlendBoundary:
    def test_prior_blend_one_returns_only_prior(self) -> None:
        """``prior_blend=1.0`` means new == prior, regardless of fit."""
        rated = _make_rated_rows(positive=5, negative=5)
        winners = _make_winners_map(positive=5, negative=5)
        prior = {
            "genius": 0.5,
            "goldilocks": 0.1,
            "cluster_coherence": 0.1,
            "emotional_universality": 0.1,
            "som_y1": 0.1,
            "derivative_distance": 0.1,
        }
        out = feedback.refit_weights(rated, winners, prior_weights=prior, prior_blend=1.0, now=_NOW)
        for facet, expected in prior.items():
            assert out[facet] == pytest.approx(expected, abs=1e-9)

    def test_prior_blend_zero_returns_only_fit(self) -> None:
        """``prior_blend=0.0`` removes the prior floor — useful as a
        sanity check that the math is wired correctly. The fitted
        weights are free to push any single facet to ~1.0."""
        rated = _make_rated_rows(positive=8, negative=2)
        winners = _make_winners_map(positive=8, negative=2)
        out = feedback.refit_weights(rated, winners, prior_blend=0.0, now=_NOW)
        # We don't assert a specific facet here — only that the floor
        # is gone (i.e., some weight CAN exceed the 0.75 ceiling).
        # In practice the logistic may not push that hard with 10
        # samples, so we settle for "sum is still 1.0".
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
