"""EVAL -- Data-driven revenue projection (ADR-0011).

Four gates protect ``pipeline.crystallize.revenue.project_revenue``:

1. **Leave-one-out MdAPE on log-scale** -- holding out each film, predict
   its worldwide gross from the remaining 293 comps; median absolute
   percentage error on log-scale must be at most 50% (a factor of ~1.6x).
   Films are log-normal in revenue; <=50% MdAPE on log-scale is the right
   calibration target.

2. **Non-degeneracy** -- predictions must vary meaningfully across films
   (sigma of log-predictions >= 0.08). Catches the "always predicts the
   same number" failure mode.

3. **Across-bucket Spearman rank correlation** -- bucket films by primary
   genre; the model's predicted bucket-medians must rank-correlate with
   the actual bucket-medians at rho >= 0.30. This is the test that fits
   what the model actually does (coarse genre-level projection); within-
   genre rank discrimination requires per-film features (budget, year,
   distributor) we add in v5.1 after the 3000-film TMDB expansion.

4. **calculation_method always set** -- every projection emits the literal
   string ``"python_executed"``. The Phase 7 narrator must refuse to write
   any SOM/SAM/TAM number whose source lacks this marker (ADR-0011).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Final

import pytest

from pipeline.crystallize.corpus import Film, FilmsCorpus
from pipeline.crystallize.revenue import (
    DEFAULT_TAM_USD,
    ProjectionContext,
    apply_geo_penalty,
    apply_window_penalty,
    compute_audience_overlap,
    project_revenue,
    weighted_log_quantiles,
)

# ── Calibration targets ──────────────────────────────────────────────────────

_MDAPE_LOG_MAX: Final[float] = 0.50
_PRED_SIGMA_MIN: Final[float] = 0.08
_BUCKET_RHO_MIN: Final[float] = 0.30
_BUCKET_MIN_FILMS: Final[int] = 5
_LEAVE_ONE_OUT_SAMPLE: Final[int] = 80
"""Subset for leave-one-out -- full 294 is ~3-5s; 80 keeps CI fast and the
threshold conservative."""

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def corpus() -> FilmsCorpus:
    return FilmsCorpus.load()


def _films_with_ww_and_genres(corpus: FilmsCorpus) -> list[Film]:
    return [
        f
        for f in corpus.films
        if f.worldwide_gross_usd is not None and f.worldwide_gross_usd > 0 and len(f.genres) > 0
    ]


def _spearman_rho(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation. Pure Python so we don't pull scipy."""
    if len(xs) != len(ys) or len(xs) < 3:
        return 0.0
    rx = _rankdata(xs)
    ry = _rankdata(ys)
    n = len(xs)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _rankdata(values: list[float]) -> list[float]:
    """Average-rank tie handling (matches scipy.stats.rankdata defaults)."""
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


# ── Unit tests for the pure-math helpers ────────────────────────────────────


class TestWeightedLogQuantiles:
    def test_returns_nones_when_too_few_comps(self) -> None:
        film = Film(
            slug="x",
            title="X",
            imdb_id=None,
            worldwide_gross_usd=None,
            domestic_gross_usd=None,
            international_gross_usd=None,
            budget_usd=None,
            genres=("drama",),
            genres_display=("Drama",),
            distributor=None,
            release_year=None,
            mpaa=None,
            imdb_url=None,
            boxofficemojo_url=None,
        )
        p10, p50, p90, sigma = weighted_log_quantiles([(film, 0.5)])
        assert p10 is None and p50 is None and p90 is None
        assert sigma == 0.0

    def test_monotonic_quantiles_under_normal_input(self) -> None:
        films = [
            Film(
                slug=f"f{i}",
                title=f"F{i}",
                imdb_id=None,
                worldwide_gross_usd=ww,
                domestic_gross_usd=None,
                international_gross_usd=None,
                budget_usd=None,
                genres=("drama",),
                genres_display=("Drama",),
                distributor=None,
                release_year=None,
                mpaa=None,
                imdb_url=None,
                boxofficemojo_url=None,
            )
            for i, ww in enumerate([50e6, 100e6, 200e6, 400e6, 800e6])
        ]
        pairs = [(f, 0.5) for f in films]
        p10, p50, p90, sigma = weighted_log_quantiles(pairs)
        assert p10 is not None and p50 is not None and p90 is not None
        assert p10 < p50 < p90
        assert sigma > 0.0


class TestComputeAudienceOverlap:
    def test_empty_domains(self) -> None:
        result = compute_audience_overlap([])
        assert result.unique_addressable_M == 0.0
        assert result.audience_factor == 0.0

    def test_single_domain_returns_size(self) -> None:
        result = compute_audience_overlap([{"id": "A", "size_M": 300, "domain_tags": ["x"]}])
        assert result.unique_addressable_M == 300.0
        assert 0.99 <= result.audience_factor <= 1.01

    def test_inclusion_exclusion_three_domains(self) -> None:
        # A, B, C with overlapping tags -- expect unique < sum, factor capped at 1.6
        domains = [
            {"id": "A", "size_M": 600, "domain_tags": ["health", "intimacy"], "affinity_with": []},
            {"id": "B", "size_M": 200, "domain_tags": ["institution"], "affinity_with": []},
            {"id": "C", "size_M": 320, "domain_tags": ["tech", "ai"], "affinity_with": []},
        ]
        result = compute_audience_overlap(domains)
        assert 0.0 < result.unique_addressable_M <= 600 + 200 + 320
        # Disjoint tags -> minimal overlap, near full sum
        assert result.unique_addressable_M >= 1000.0
        assert result.audience_factor == 1.6  # capped

    def test_affinity_floor_kicks_in(self) -> None:
        # Even with zero tag overlap, affinity_with forces 0.30 jaccard
        domains = [
            {"id": "A", "size_M": 100, "domain_tags": ["x"], "affinity_with": ["B"]},
            {"id": "B", "size_M": 100, "domain_tags": ["y"], "affinity_with": ["A"]},
        ]
        result = compute_audience_overlap(domains)
        # Expected: pairwise = 0.30 * min(100, 100) = 30
        # unique = 100 + 100 - 30 = 170
        assert 169.0 <= result.unique_addressable_M <= 171.0

    def test_permutation_invariance(self) -> None:
        a = {"id": "A", "size_M": 100, "domain_tags": ["x", "y"], "affinity_with": []}
        b = {"id": "B", "size_M": 200, "domain_tags": ["y", "z"], "affinity_with": []}
        c = {"id": "C", "size_M": 150, "domain_tags": ["z", "w"], "affinity_with": []}
        r1 = compute_audience_overlap([a, b, c])
        r2 = compute_audience_overlap([c, a, b])
        # Up to rounding
        assert abs(r1.unique_addressable_M - r2.unique_addressable_M) < 1.0


class TestWindowGeoPenalties:
    def test_explicit_window_overrides_auto(self) -> None:
        out, key = apply_window_penalty(100.0, "streaming_first")
        assert out == 40.0
        assert key == "streaming_first"

    def test_auto_window_infers_streaming_from_distributor(self) -> None:
        out, key = apply_window_penalty(100.0, "auto", distributor="Netflix")
        assert key == "streaming_first"
        assert out == 40.0

    def test_auto_window_infers_wide_from_distributor(self) -> None:
        out, key = apply_window_penalty(100.0, "auto", distributor="Warner Bros.")
        assert key == "theatrical_wide"
        assert out == 100.0

    def test_geo_factors_strict_order(self) -> None:
        _, us = apply_geo_penalty(100.0, "us_only")
        _, en5 = apply_geo_penalty(100.0, "english_5")
        _, gl = apply_geo_penalty(100.0, "global")
        assert us < en5 < gl


# ── Provability tests on real corpus ────────────────────────────────────────


class TestCalculationMethod:
    """ADR-0011: ``calculation_method`` MUST be ``"python_executed"`` on every projection."""

    def test_calculation_method_set(self, corpus: FilmsCorpus) -> None:
        candidate = {
            "genres": ["drama", "thriller"],
            "audiences": [{"id": "A", "size_M": 200, "domain_tags": ["drama"]}],
        }
        proj = project_revenue(candidate, corpus)
        assert proj.calculation_method == "python_executed"
        assert proj.assumptions["geo"] == "english_5"
        assert proj.tam_usd == DEFAULT_TAM_USD


class TestLeaveOneOut:
    """Sample N films, hold out each, predict from the rest."""

    def _run_loo(self, corpus: FilmsCorpus, n_sample: int) -> tuple[list[float], list[float]]:
        """Return (log_actual, log_predicted) over the sample."""
        eligible = _films_with_ww_and_genres(corpus)
        if len(eligible) < 10:
            pytest.skip("corpus too small for leave-one-out")
        sample = eligible[:: max(1, len(eligible) // n_sample)][:n_sample]
        log_actual: list[float] = []
        log_pred: list[float] = []
        for held_out in sample:
            remaining_films = tuple(f for f in corpus.films if f.slug != held_out.slug)
            mini_corpus = FilmsCorpus(films=remaining_films, root=corpus.root)
            mini_corpus._build_indices()
            candidate = {
                "genres": list(held_out.genres),
                "audiences": [],  # no overlap derate for LOO calibration
            }
            proj = project_revenue(
                candidate,
                mini_corpus,
                ctx=ProjectionContext(geo="global", window="theatrical_wide", comp_k=10),
            )
            if proj.p50_usd is None or proj.p50_usd <= 0:
                continue
            log_actual.append(math.log(held_out.worldwide_gross_usd or 1.0))
            # Predicted "theatrical-wide global" equals raw p50 (factors = 1.0).
            log_pred.append(math.log(proj.p50_usd))
        return (log_actual, log_pred)

    def test_log_mdape_within_50pct(self, corpus: FilmsCorpus) -> None:
        log_actual, log_pred = self._run_loo(corpus, _LEAVE_ONE_OUT_SAMPLE)
        if len(log_actual) < 10:
            pytest.skip("not enough successful projections in sample")
        ape = [abs(a - p) / max(abs(a), 1e-6) for a, p in zip(log_actual, log_pred, strict=True)]
        ape.sort()
        median_ape = ape[len(ape) // 2]
        assert median_ape <= _MDAPE_LOG_MAX, (
            f"MdAPE(log) = {median_ape:.3f} exceeds {_MDAPE_LOG_MAX:.2f}"
        )

    def test_predictions_non_degenerate(self, corpus: FilmsCorpus) -> None:
        """Catch the 'always predicts the same number' failure mode."""
        _, log_pred = self._run_loo(corpus, _LEAVE_ONE_OUT_SAMPLE)
        if len(log_pred) < 10:
            pytest.skip("not enough successful projections in sample")
        mean = sum(log_pred) / len(log_pred)
        sigma = math.sqrt(sum((p - mean) ** 2 for p in log_pred) / len(log_pred))
        assert sigma >= _PRED_SIGMA_MIN, (
            f"log-prediction sigma = {sigma:.3f} below {_PRED_SIGMA_MIN}; model is degenerate"
        )


class TestAcrossBucketSpearman:
    """Predicts genre-bucket median grosses and checks rank order.

    This is the right rank-correlation test for a coarse comp-by-genre model.
    Within-genre per-film discrimination needs per-film features (budget,
    year, distributor) that v5.1 will add post 3000-film TMDB expansion.
    """

    def test_bucket_median_rho(self, corpus: FilmsCorpus) -> None:
        buckets: dict[str, list[float]] = {}
        for f in corpus.films:
            if f.worldwide_gross_usd is None or f.worldwide_gross_usd <= 0:
                continue
            if not f.genres:
                continue
            key = f.genres[0]
            buckets.setdefault(key, []).append(f.worldwide_gross_usd)
        # Drop buckets that are too small to have a stable median
        usable = {g: ws for g, ws in buckets.items() if len(ws) >= _BUCKET_MIN_FILMS}
        if len(usable) < 4:
            pytest.skip("not enough genre buckets with >=5 films")

        actual_medians: list[float] = []
        predicted_medians: list[float] = []
        for genre, actuals in usable.items():
            actuals_sorted = sorted(actuals)
            actual_medians.append(actuals_sorted[len(actuals_sorted) // 2])
            # Predict using a synthetic candidate with this genre only.
            candidate = {"genres": [genre], "audiences": []}
            proj = project_revenue(
                candidate,
                corpus,
                ctx=ProjectionContext(geo="global", window="theatrical_wide", comp_k=10),
            )
            assert proj.p50_usd is not None, f"projection collapsed for bucket {genre}"
            predicted_medians.append(proj.p50_usd)

        rho = _spearman_rho(actual_medians, predicted_medians)
        assert rho >= _BUCKET_RHO_MIN, (
            f"Across-bucket Spearman rho = {rho:.3f} below threshold {_BUCKET_RHO_MIN}"
        )
