"""Tests for pipeline.feedback -- logistic weight recalibration.

WEDGE Step 5 of the plan. Pins five contracts:

  1. Empty rated_rows -> returns the prior unchanged.
  2. All-positive or all-negative ratings -> degenerate fit -> return prior.
  3. Synthetic ratings that strongly favour high-SOM candidates over
     high-genius candidates produce a fitted weight vector with SOM
     weight > genius weight (the operator's stated taste shines through).
  4. Time-decay: a 90-day-old rating contributes less than a today
     rating; the weighted fit reflects this.
  5. read_winner_facets reads runs/<run_id>/evolve/gen0/winners.json
     correctly; missing sidecars are skipped silently.

Honest caveat: these tests use synthetic ratings designed to be
separable. Real operator ratings will be noisier. The Step 5
operator_alignment facet wire (cosine to rated-positive centroid in
axis space) is explicitly NOT in this commit -- it requires real
labels to validate, per the TODO at the bottom of pipeline/feedback.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline import feedback


def _rating(
    run_id: str, rating: int, age_days: int = 0, now: datetime | None = None
) -> dict[str, object]:
    """Build one rated_row as labels.append would produce it."""
    ts = (now or datetime(2026, 5, 27, tzinfo=UTC)) - timedelta(days=age_days)
    return {
        "ts": ts.isoformat(),
        "run_id": run_id,
        "rating": rating,
        "note": "",
        "goal_sha": "abc",
    }


def _winner_facets(
    genius: float = 0.5,
    goldilocks: float = 0.5,
    cluster_coherence: float = 0.5,
    emotional_universality: float = 0.5,
    som_y1: float = 0.5,
    derivative_distance: float = 0.5,
) -> dict[str, float]:
    """Build one row of winners_by_run_id (post-normalised facet values)."""
    return {
        "genius": genius,
        "goldilocks": goldilocks,
        "cluster_coherence": cluster_coherence,
        "emotional_universality": emotional_universality,
        "som_y1": som_y1,
        "derivative_distance": derivative_distance,
    }


class TestRefitDegenerateAndEdgeCases:
    def test_no_rated_rows_returns_prior(self) -> None:
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights([], {}, prior_weights=prior)
        # Float drift through _normalised() -- compare with tolerance.
        for f in feedback._V4_FACETS:
            assert result[f] == pytest.approx(prior[f], abs=1e-9)

    def test_all_positive_ratings_returns_prior(self) -> None:
        """Degenerate label distribution -> keep prior, don't push the
        engine into a single-facet corner."""
        rated = [_rating(f"r{i}", 2) for i in range(5)]
        winners = {f"r{i}": _winner_facets(som_y1=0.9) for i in range(5)}
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(rated, winners, prior_weights=prior)
        # Weights still sum to 1.0 and stay close to prior (within 5%).
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)
        for f in feedback._V4_FACETS:
            assert result[f] == pytest.approx(prior[f], abs=0.05)

    def test_all_negative_ratings_returns_prior(self) -> None:
        rated = [_rating(f"r{i}", -2) for i in range(5)]
        winners = {f"r{i}": _winner_facets(som_y1=0.9) for i in range(5)}
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(rated, winners, prior_weights=prior)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)

    def test_missing_winner_facets_skips_row(self) -> None:
        rated = [_rating("r1", 2), _rating("r2", -1)]
        # r2 has no winner facets -> only r1 contributes -> degenerate fit.
        winners = {"r1": _winner_facets(som_y1=0.9)}
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(rated, winners, prior_weights=prior)
        # Single sample is degenerate -> keep prior.
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)


class TestRefitConverges:
    def test_som_loving_operator_pushes_som_weight_up(self) -> None:
        """Construct synthetic ratings where the operator gives +2 to
        every high-SOM candidate and -2 to every low-SOM candidate
        (other facets held constant). The fit should produce SOM
        weight > genius weight."""
        rated: list[dict[str, object]] = []
        winners: dict[str, dict[str, float]] = {}
        # 8 positives: high SOM, mid everything else.
        for i in range(8):
            rid = f"pos-{i}"
            rated.append(_rating(rid, 2))
            winners[rid] = _winner_facets(som_y1=0.9, genius=0.5)
        # 8 negatives: low SOM, mid everything else.
        for i in range(8):
            rid = f"neg-{i}"
            rated.append(_rating(rid, -2))
            winners[rid] = _winner_facets(som_y1=0.1, genius=0.5)

        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(rated, winners, prior_weights=prior)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)
        assert result["som_y1"] > result["genius"], (
            f"SOM-loving operator failed to lift SOM weight: result={result}"
        )

    def test_genius_loving_operator_pushes_genius_weight_up(self) -> None:
        """Inverse: operator rewards genius, ignores SOM."""
        rated: list[dict[str, object]] = []
        winners: dict[str, dict[str, float]] = {}
        for i in range(8):
            rid = f"pos-{i}"
            rated.append(_rating(rid, 2))
            winners[rid] = _winner_facets(genius=0.9, som_y1=0.5)
        for i in range(8):
            rid = f"neg-{i}"
            rated.append(_rating(rid, -2))
            winners[rid] = _winner_facets(genius=0.1, som_y1=0.5)

        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(rated, winners, prior_weights=prior)
        assert result["genius"] > result["som_y1"], (
            f"genius-loving operator failed to lift genius weight: result={result}"
        )

    def test_time_decay_reduces_old_rating_influence(self) -> None:
        """An ancient rating (180 days old) should barely shift the fit;
        a today rating with the same signal should shift it noticeably.

        Setup: today there's a strong SOM signal (8 ratings); 180 days
        ago there was a CONFLICTING strong genius signal (8 ratings).
        Without decay, the two cancel. With decay (half-life=30d), the
        180-day signal contributes ~2% -- today's SOM wins.
        """
        now = datetime(2026, 5, 27, tzinfo=UTC)
        rated: list[dict[str, object]] = []
        winners: dict[str, dict[str, float]] = {}
        # Today: SOM loved.
        for i in range(8):
            rid = f"today-pos-{i}"
            rated.append(_rating(rid, 2, age_days=0, now=now))
            winners[rid] = _winner_facets(som_y1=0.9, genius=0.5)
        for i in range(8):
            rid = f"today-neg-{i}"
            rated.append(_rating(rid, -2, age_days=0, now=now))
            winners[rid] = _winner_facets(som_y1=0.1, genius=0.5)
        # 180 days ago: opposite preference (genius loved, SOM hated).
        for i in range(8):
            rid = f"ancient-pos-{i}"
            rated.append(_rating(rid, 2, age_days=180, now=now))
            winners[rid] = _winner_facets(genius=0.9, som_y1=0.5)
        for i in range(8):
            rid = f"ancient-neg-{i}"
            rated.append(_rating(rid, -2, age_days=180, now=now))
            winners[rid] = _winner_facets(genius=0.1, som_y1=0.5)

        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(
            rated, winners, prior_weights=prior, now=now, half_life_days=30.0
        )
        assert result["som_y1"] > result["genius"], (
            f"time-decay failed: ancient genius signal beat today's SOM signal: result={result}"
        )

    def test_prior_blend_preserves_weight_floor(self) -> None:
        """With prior_blend=0.5, even extreme operator signal should not
        push any single facet above ~75% (anti-overfit ceiling)."""
        rated: list[dict[str, object]] = []
        winners: dict[str, dict[str, float]] = {}
        for i in range(20):
            rid = f"pos-{i}"
            rated.append(_rating(rid, 2))
            winners[rid] = _winner_facets(som_y1=0.99, genius=0.01)
        for i in range(20):
            rid = f"neg-{i}"
            rated.append(_rating(rid, -2))
            winners[rid] = _winner_facets(som_y1=0.01, genius=0.99)
        prior = {f: 1.0 / 6 for f in feedback._V4_FACETS}
        result = feedback.refit_weights(rated, winners, prior_weights=prior, prior_blend=0.5)
        for f, w in result.items():
            assert w <= 0.80, f"prior_blend=0.5 failed -- {f}={w} exceeded 80% ceiling"


class TestReadWinnerFacets:
    def test_reads_sidecar_at_expected_path(self, tmp_path: Path) -> None:
        runs_root = tmp_path / "runs"
        run_id = "evolve-test-001"
        sidecar = runs_root / run_id / "evolve" / "gen0" / "winners.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text(
            json.dumps(
                {
                    "winners": [
                        {
                            "derivative_distance": 0.8,
                            "scores": {
                                "genius_score": 0.7,
                                "goldilocks_score": 0.6,
                                "cluster_coherence": 0.5,
                                "emotional_universality_score": 4.0,
                                "som_y1_usd": 150_000_000,
                            },
                        }
                    ]
                }
            )
        )
        rated = [_rating(run_id, 2)]
        out = feedback.read_winner_facets(rated, runs_root=runs_root)
        assert run_id in out
        assert out[run_id]["genius"] == pytest.approx(0.7)
        assert out[run_id]["emotional_universality"] == pytest.approx(4.0 / 5.0)
        assert out[run_id]["som_y1"] == pytest.approx(150_000_000 / 200_000_000)
        assert out[run_id]["derivative_distance"] == pytest.approx(0.8)

    def test_missing_sidecar_silently_skipped(self, tmp_path: Path) -> None:
        rated = [_rating("ghost-run", 2)]
        out = feedback.read_winner_facets(rated, runs_root=tmp_path / "runs")
        assert out == {}

    def test_malformed_sidecar_silently_skipped(self, tmp_path: Path) -> None:
        runs_root = tmp_path / "runs"
        sidecar = runs_root / "evolve-bad" / "evolve" / "gen0" / "winners.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("not json")
        out = feedback.read_winner_facets([_rating("evolve-bad", 1)], runs_root=runs_root)
        assert out == {}
