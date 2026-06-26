"""Regression: FilmsCorpus.find_comps uses MMR decorrelation.

WEDGE Step 2 of the plan. Before this change, ``find_comps`` was a greedy
top-K sort by Jaccard then worldwide gross. The audit traced the
leaderboard's "same reference movies" failure to this: A.I. Artificial
Intelligence (tagged drama + sci-fi + thriller) Jaccard-matched almost any
query and won 22 of 49 leaderboard slots because the greedy selector had
no reason to spread results across the corpus.

These tests pin the new contract:

  1. On a synthetic corpus where four films are exact genre clones of one
     "A.I.-like" film, greedy top-K returns 5 clones; MMR returns 1 clone
     + 4 diverse films.
  2. The first comp is unchanged (still the top scorer).
  3. ``find_comps_with_similarity`` mirrors the diversification AND
     preserves the ORIGINAL Jaccard score so revenue.py weighting is
     unaffected by the lambda penalty.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.crystallize.corpus import Film, FilmsCorpus


def _film(slug: str, title: str, genres: tuple[str, ...], ww: float) -> Film:
    return Film(
        slug=slug,
        title=title,
        imdb_id=None,
        worldwide_gross_usd=ww,
        domestic_gross_usd=ww * 0.45,
        international_gross_usd=ww * 0.55,
        budget_usd=ww / 4.0,
        genres=tuple(g.lower() for g in genres),
        genres_display=genres,
        distributor=None,
        release_year=2020,
        mpaa=None,
        imdb_url=None,
        boxofficemojo_url=None,
    )


def _ai_clone_corpus() -> FilmsCorpus:
    """Five A.I.-clones (all drama+sci-fi+thriller) plus six diverse films.

    Without MMR, a query of [drama, sci-fi, thriller] returns 5 clones
    sorted by gross. With MMR, the second slot prefers diversity.
    """
    films = [
        # The 5 A.I. clones — identical genres, varying gross.
        _film("ai-1", "A.I. Clone Alpha", ("Drama", "Sci-Fi", "Thriller"), 500e6),
        _film("ai-2", "A.I. Clone Beta", ("Drama", "Sci-Fi", "Thriller"), 480e6),
        _film("ai-3", "A.I. Clone Gamma", ("Drama", "Sci-Fi", "Thriller"), 460e6),
        _film("ai-4", "A.I. Clone Delta", ("Drama", "Sci-Fi", "Thriller"), 440e6),
        _film("ai-5", "A.I. Clone Epsilon", ("Drama", "Sci-Fi", "Thriller"), 420e6),
        # 6 diverse films — share at most 2 genres with the query.
        _film("div-1", "Pure Sci-Fi", ("Sci-Fi",), 400e6),
        _film("div-2", "Drama Romance", ("Drama", "Romance"), 380e6),
        _film("div-3", "Thriller Action", ("Thriller", "Action"), 360e6),
        _film("div-4", "Sci-Fi Adventure", ("Sci-Fi", "Adventure"), 340e6),
        _film("div-5", "Drama Mystery", ("Drama", "Mystery"), 320e6),
        _film("div-6", "Crime Thriller", ("Crime", "Thriller"), 300e6),
    ]
    return FilmsCorpus(films=tuple(films), root=Path("."))


class TestMMRFindComps:
    """The single regression that proves greedy top-K is dead."""

    def test_mmr_breaks_genre_clones_into_diverse_set(self) -> None:
        corpus = _ai_clone_corpus()
        results = corpus.find_comps(["drama", "sci-fi", "thriller"], k=5)

        assert len(results) == 5
        # Slot 1: pure greedy still picks the highest-Jaccard, highest-gross clone.
        assert results[0].slug == "ai-1"
        # Slots 2-5: MMR must NOT return 4 more clones. At least 2 of the
        # remaining 4 results should come from the diverse pool.
        ai_clone_slugs = {"ai-1", "ai-2", "ai-3", "ai-4", "ai-5"}
        clones_in_results = sum(1 for f in results if f.slug in ai_clone_slugs)
        assert clones_in_results <= 2, (
            f"MMR failed: {clones_in_results}/5 are A.I.-clones "
            f"(got slugs {[f.slug for f in results]})"
        )

    def test_first_comp_is_top_scorer_unchanged(self) -> None:
        """Slot 1 behaviour matches pre-WEDGE-Step-2: top Jaccard wins."""
        corpus = _ai_clone_corpus()
        results = corpus.find_comps(["drama", "sci-fi", "thriller"], k=3)
        assert results[0].slug == "ai-1"

    def test_mmr_with_similarity_preserves_original_jaccard(self) -> None:
        """find_comps_with_similarity must return ORIGINAL Jaccard (not
        the MMR-adjusted score) so revenue.py weighting math is unchanged."""
        corpus = _ai_clone_corpus()
        results = corpus.find_comps_with_similarity(["drama", "sci-fi", "thriller"], k=5)

        assert len(results) == 5
        # First result is full match — Jaccard should be 3/3 = 1.0.
        ai_first, sim_first = results[0]
        assert ai_first.slug == "ai-1"
        assert sim_first == 1.0
        # Diverse pool entries should report their TRUE Jaccard (1/3 or 2/3 etc.),
        # not the lambda-penalised value.
        for film, sim in results[1:]:
            actual_jaccard = len(set(film.genres) & {"drama", "sci-fi", "thriller"}) / len(
                set(film.genres) | {"drama", "sci-fi", "thriller"}
            )
            assert abs(sim - actual_jaccard) < 1e-9, (
                f"{film.slug} similarity {sim} != actual Jaccard {actual_jaccard}"
            )

    def test_k_larger_than_candidates_returns_all_available(self) -> None:
        """k > number of films with sim > 0 should not crash; returns all matches."""
        corpus = _ai_clone_corpus()
        # query that only the 5 clones + 4 diverse films overlap with
        results = corpus.find_comps(["drama", "sci-fi", "thriller"], k=100)
        # 5 clones + (div-1 sci-fi, div-2 drama, div-3 thriller, div-4 sci-fi,
        # div-5 drama, div-6 thriller) = 11 with sim > 0
        assert len(results) == 11

    def test_empty_query_fallback_unchanged(self) -> None:
        """Empty query still falls back to top-K by worldwide gross."""
        corpus = _ai_clone_corpus()
        results = corpus.find_comps([], k=3)
        assert len(results) == 3
        # Sorted by ww desc; ai-1 (500M) > ai-2 (480M) > ai-3 (460M)
        assert results[0].slug == "ai-1"
        assert results[1].slug == "ai-2"
        assert results[2].slug == "ai-3"
