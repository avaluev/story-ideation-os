"""Format-aware revenue projection (v5.1.0) — pipeline.crystallize.revenue.

Locks the load-bearing contract:
  * content_format None / "feature" / "animation_feature" -> the EXISTING
    theatrical math, byte-identical (regression lock; ADR-0011 preserved).
  * license formats (limited/returning/animation series) derive SOM from the
    cost-plus license fee, NOT the theatrical p50.
  * microdrama derives SOM from its share-of-serviceable-market model.
  * EVERY projection keeps calculation_method == "python_executed".
  * For EVERY format 0 < som_y1_usd < sam_usd < tam_usd (the credibility
    invariant — exercises limited_series + returning_series specifically,
    the SAM>TAM defect the red-team flagged).
  * The multi-window LIFETIME figure lives ONLY in assumptions, never folded
    into som_y1_usd (Year-1 SOM stays Year-1 — ADR-0011 semantics).

Hermetic: small in-memory corpus, no network.
"""

from __future__ import annotations

import pytest

from pipeline.crystallize import format_economics as fe
from pipeline.crystallize.corpus import Film, FilmsCorpus
from pipeline.crystallize.revenue import ProjectionContext, project_revenue
from pipeline.crystallize.score import _som_factor_y1


def _mk_film(slug: str, title: str, ww: float, genres: tuple[str, ...]) -> Film:
    return Film(
        slug=slug,
        title=title,
        imdb_id=None,
        worldwide_gross_usd=ww,
        domestic_gross_usd=ww * 0.4,
        international_gross_usd=ww * 0.6,
        budget_usd=ww * 0.25,
        genres=genres,
        genres_display=tuple(g.title() for g in genres),
        distributor="Universal",
        release_year=2022,
        mpaa="PG-13",
        imdb_url=None,
        boxofficemojo_url=None,
    )


@pytest.fixture
def corpus() -> FilmsCorpus:
    films = (
        _mk_film("a", "Alpha", 600_000_000, ("drama", "thriller")),
        _mk_film("b", "Beta", 250_000_000, ("drama", "mystery")),
        _mk_film("c", "Gamma", 900_000_000, ("action", "sci-fi")),
        _mk_film("d", "Delta", 400_000_000, ("drama", "crime")),
        _mk_film("e", "Eps", 150_000_000, ("comedy", "drama")),
    )
    c = FilmsCorpus(films=films, root=None)  # type: ignore[arg-type]
    c._build_indices()
    return c


def _candidate() -> dict[str, object]:
    return {
        "genres": ["drama", "thriller"],
        "audiences": [
            {"id": "AD_01", "size_M": 220, "domain_tags": ["drama"], "affinity_with": []},
            {"id": "AD_02", "size_M": 180, "domain_tags": ["thriller"], "affinity_with": []},
            {"id": "AD_03", "size_M": 140, "domain_tags": ["mystery"], "affinity_with": []},
        ],
    }


def test_none_and_feature_are_byte_identical(corpus: FilmsCorpus) -> None:
    base = project_revenue(_candidate(), corpus)  # content_format None
    feat = project_revenue(_candidate(), corpus, ctx=ProjectionContext(content_format="feature"))
    assert base.som_y1_usd == feat.som_y1_usd
    assert base.sam_usd == feat.sam_usd
    assert base.tam_usd == feat.tam_usd
    assert base.calculation_method == "python_executed"


def test_license_format_uses_cost_plus_not_theatrical(corpus: FilmsCorpus) -> None:
    proj = project_revenue(
        _candidate(), corpus, ctx=ProjectionContext(content_format="limited_series")
    )
    assert proj.assumptions.get("format_used") == "limited_series"
    assert proj.calculation_method == "python_executed"
    # SOM is the license fee (x audience factor), NOT the theatrical p50.
    profile = fe.FORMAT_PROFILES["limited_series"]
    base_fee = fe.license_fee_usd(profile)
    assert proj.som_y1_usd is not None
    # within the audience-factor band [floor, cap] of the base license fee
    assert 0.4 * base_fee <= proj.som_y1_usd <= 1.7 * base_fee


def test_microdrama_priced_as_microdrama_not_film(corpus: FilmsCorpus) -> None:
    proj = project_revenue(_candidate(), corpus, ctx=ProjectionContext(content_format="microdrama"))
    assert proj.assumptions.get("format_used") == "microdrama"
    assert proj.tam_usd == pytest.approx(fe.MICRODRAMA_TAM_GLOBAL_USD)
    assert proj.sam_usd == pytest.approx(fe.MICRODRAMA_TAM_EX_CHINA_USD)
    assert proj.som_y1_usd is not None
    assert proj.sam_usd is not None
    assert proj.som_y1_usd < proj.sam_usd


def test_score_som_scale_is_per_format() -> None:
    """A $40M Year-1 SOM is a strong MICRODRAMA but a weak feature: it must
    score materially higher on the microdrama scale than the theatrical one
    (the monoculture-via-selector fix). Feature scale (content_format None or
    'feature') stays byte-identical to the legacy theatrical bounds."""
    som = 40_000_000.0
    micro = _som_factor_y1(som, "microdrama")
    feature = _som_factor_y1(som, "feature")
    feature_none = _som_factor_y1(som, None)
    assert micro > 0.5, f"microdrama facet {micro} should reward a $40M micro SOM"
    assert feature < micro
    assert feature == feature_none  # 'feature' bounds == legacy default bounds


def test_som_lt_sam_lt_tam_every_format(corpus: FilmsCorpus) -> None:
    """The credibility invariant for EVERY format — includes the two
    streaming formats whose naive SAM=segment would have exceeded TAM."""
    for fmt in fe.VALID_FORMATS:
        proj = project_revenue(_candidate(), corpus, ctx=ProjectionContext(content_format=fmt))
        assert proj.calculation_method == "python_executed"
        assert proj.som_y1_usd is not None and proj.som_y1_usd > 0, fmt
        assert proj.sam_usd is not None and proj.tam_usd is not None, fmt
        assert proj.som_y1_usd < proj.sam_usd < proj.tam_usd, (
            f"{fmt}: SOM {proj.som_y1_usd:,.0f} < SAM {proj.sam_usd:,.0f} "
            f"< TAM {proj.tam_usd:,.0f} violated"
        )


def test_lifetime_only_in_assumptions(corpus: FilmsCorpus) -> None:
    for fmt in ("limited_series", "returning_series", "microdrama", "feature"):
        proj = project_revenue(_candidate(), corpus, ctx=ProjectionContext(content_format=fmt))
        lifetime = proj.assumptions.get("lifetime_som_y1_usd")
        assert lifetime is not None, fmt
        # Year-1 SOM is never the lifetime figure (lifetime >= Year-1).
        assert proj.som_y1_usd is not None
        assert proj.som_y1_usd <= float(lifetime) + 1.0, fmt
