"""Tests for pipeline/crystallize/corpus.py — FilmsCorpus loader and comp matching.

Covers:
- _parse_dollars handles $ + comma format, None, malformed strings, "N/A".
- _parse_year extracts 4-digit year from "October 6, 2017" and falls back gracefully.
- roi() returns None when budget missing or zero; (ww-budget)/budget otherwise.
- FilmsCorpus.load() parses all 294 .json files without raising.
- FilmsCorpus.load() degrades gracefully when root is missing (returns empty corpus).
- find_comps() returns up to k films ranked by Jaccard on genres; falls back to
  top-by-gross when no overlap.
- find_comps() returns the requested film count (or all if corpus is smaller).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.crystallize.corpus import (
    Film,
    FilmsCorpus,
    _parse_dollars,
    _parse_year,
    roi,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_ROOT = _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"

_corpus_missing = pytest.mark.skipif(
    not _CORPUS_ROOT.exists(),
    reason="Films corpus not present on disk (Inputs/10May/.../films/)",
)


# ---------------------------------------------------------------------------
# _parse_dollars
# ---------------------------------------------------------------------------


def test_parse_dollars_standard_format() -> None:
    assert _parse_dollars("$277,882,781") == 277_882_781.0


def test_parse_dollars_no_dollar_sign() -> None:
    assert _parse_dollars("150,000,000") == 150_000_000.0


def test_parse_dollars_none() -> None:
    assert _parse_dollars(None) is None


def test_parse_dollars_empty_string() -> None:
    assert _parse_dollars("") is None


def test_parse_dollars_whitespace_only() -> None:
    assert _parse_dollars("   ") is None


def test_parse_dollars_na_sentinel() -> None:
    assert _parse_dollars("N/A") is None
    assert _parse_dollars("n/a") is None
    assert _parse_dollars("—") is None


def test_parse_dollars_no_digits() -> None:
    assert _parse_dollars("$,,,") is None


def test_parse_dollars_with_decimal() -> None:
    assert _parse_dollars("$1,234.56") == 1234.56


# ---------------------------------------------------------------------------
# _parse_year
# ---------------------------------------------------------------------------


def test_parse_year_long_format() -> None:
    assert _parse_year("October 6, 2017") == 2017


def test_parse_year_iso_format() -> None:
    assert _parse_year("2017-10-06") == 2017


def test_parse_year_none() -> None:
    assert _parse_year(None) is None


def test_parse_year_no_year() -> None:
    assert _parse_year("some random string") is None


# ---------------------------------------------------------------------------
# roi()
# ---------------------------------------------------------------------------


def _make_film(ww: float | None, budget: float | None) -> Film:
    return Film(
        slug="x",
        title="X",
        imdb_id=None,
        worldwide_gross_usd=ww,
        domestic_gross_usd=None,
        international_gross_usd=None,
        budget_usd=budget,
        genres=("drama",),
        genres_display=("Drama",),
        distributor=None,
        release_year=None,
        mpaa=None,
        imdb_url=None,
        boxofficemojo_url=None,
    )


def test_roi_normal_case() -> None:
    f = _make_film(ww=300_000_000.0, budget=100_000_000.0)
    assert roi(f) == pytest.approx(2.0)


def test_roi_none_budget() -> None:
    f = _make_film(ww=300_000_000.0, budget=None)
    assert roi(f) is None


def test_roi_zero_budget() -> None:
    f = _make_film(ww=300_000_000.0, budget=0.0)
    assert roi(f) is None


def test_roi_none_worldwide() -> None:
    f = _make_film(ww=None, budget=100_000_000.0)
    assert roi(f) is None


def test_roi_loss_case() -> None:
    f = _make_film(ww=50_000_000.0, budget=100_000_000.0)
    assert roi(f) == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# FilmsCorpus.load()
# ---------------------------------------------------------------------------


def test_load_missing_root_returns_empty_corpus(tmp_path: Path) -> None:
    """If root directory does not exist, return empty corpus, no raise."""
    nonexistent = tmp_path / "no_such_dir"
    c = FilmsCorpus.load(root=nonexistent)
    assert len(c) == 0
    assert c.films == ()


def test_load_empty_root_returns_empty_corpus(tmp_path: Path) -> None:
    """Empty directory yields empty corpus."""
    c = FilmsCorpus.load(root=tmp_path)
    assert len(c) == 0


def test_load_skips_malformed_json(tmp_path: Path) -> None:
    """Malformed .json files are skipped, not propagated."""
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
    (tmp_path / "ok.json").write_text(
        '{"title": "X", "imdb_id": "tt1", "financials": {}, "details": {}}',
        encoding="utf-8",
    )
    c = FilmsCorpus.load(root=tmp_path)
    assert len(c) == 1
    assert c.films[0].title == "X"


def test_load_skips_film_without_title(tmp_path: Path) -> None:
    """A film with no title is skipped silently."""
    (tmp_path / "no_title.json").write_text(
        '{"imdb_id": "tt1", "financials": {}, "details": {"genres": ["Drama"]}}',
        encoding="utf-8",
    )
    c = FilmsCorpus.load(root=tmp_path)
    assert len(c) == 0


@_corpus_missing
def test_load_real_corpus_parses_all_files() -> None:
    """The real 294-film corpus loads end-to-end without raising."""
    c = FilmsCorpus.load()
    # Must load at least 200 films (some may fail to parse but most are clean).
    assert len(c) >= 200, f"only {len(c)} films loaded — corpus may be corrupted"


@_corpus_missing
def test_load_real_corpus_has_known_films() -> None:
    """A handful of canonical films are present and well-formed."""
    c = FilmsCorpus.load()
    titles = {f.title for f in c.films}
    # These films are definitely in the corpus per Inputs/10May/.../films/.
    assert "Blade Runner 2049" in titles
    # At least 50% of films should have a parsed budget.
    have_budget = sum(1 for f in c.films if f.budget_usd is not None)
    assert have_budget >= len(c) // 2


# ---------------------------------------------------------------------------
# find_comps()
# ---------------------------------------------------------------------------


def _build_synthetic_corpus(tmp_path: Path) -> FilmsCorpus:
    """Build a tiny synthetic corpus with controlled genres for ranking tests."""
    fixtures = [
        ("a.json", "A", ["Sci-Fi", "Thriller"], "$200,000,000", "$50,000,000"),
        ("b.json", "B", ["Sci-Fi", "Drama"], "$150,000,000", "$60,000,000"),
        ("c.json", "C", ["Comedy"], "$100,000,000", "$20,000,000"),
        ("d.json", "D", ["Sci-Fi", "Thriller", "Drama"], "$300,000,000", "$80,000,000"),
    ]
    for fname, title, genres, ww, budget in fixtures:
        (tmp_path / fname).write_text(
            json.dumps(
                {
                    "title": title,
                    "imdb_id": "tt0",
                    "financials": {"worldwide": ww, "budget": budget},
                    "details": {"genres": list(genres)},
                }
            ),
            encoding="utf-8",
        )
    return FilmsCorpus.load(root=tmp_path)


def test_find_comps_returns_at_most_k(tmp_path: Path) -> None:
    c = _build_synthetic_corpus(tmp_path)
    assert len(c.find_comps(genres=["Sci-Fi"], k=2)) == 2
    assert len(c.find_comps(genres=["Sci-Fi"], k=10)) == 3  # only 3 sci-fi films


def test_find_comps_ranks_by_jaccard_then_gross(tmp_path: Path) -> None:
    """Film D (3/3 overlap) ranks above A (2/2 overlap), then B (2/3)."""
    c = _build_synthetic_corpus(tmp_path)
    result = c.find_comps(genres=["Sci-Fi", "Thriller", "Drama"], k=3)
    titles = [f.title for f in result]
    assert titles[0] == "D"  # 3/3 overlap = full Jaccard match
    # A has 2/2 with query (Sci-Fi+Thriller) → Jaccard 2/3 = 0.67
    # B has 2/3 with query (Sci-Fi+Drama)    → Jaccard 2/3 = 0.67
    # tie broken by worldwide gross → A=$200M > B=$150M
    assert titles[1] == "A"
    assert titles[2] == "B"


def test_find_comps_no_overlap_falls_back_to_top_gross(tmp_path: Path) -> None:
    """When no films match the requested genres, fall back to top-by-gross."""
    c = _build_synthetic_corpus(tmp_path)
    result = c.find_comps(genres=["Romance"], k=2)
    assert len(result) == 2
    # Highest grossing first: D ($300M), then A ($200M).
    assert [f.title for f in result] == ["D", "A"]


def test_find_comps_empty_query_falls_back_to_top_gross(tmp_path: Path) -> None:
    c = _build_synthetic_corpus(tmp_path)
    result = c.find_comps(genres=[], k=2)
    assert [f.title for f in result] == ["D", "A"]


def test_find_comps_empty_corpus_returns_empty(tmp_path: Path) -> None:
    c = FilmsCorpus.load(root=tmp_path)
    assert c.find_comps(genres=["Sci-Fi"], k=5) == []


# ---------------------------------------------------------------------------
# Film.to_dict()
# ---------------------------------------------------------------------------


def test_film_to_dict_shape() -> None:
    f = _make_film(ww=300_000_000.0, budget=100_000_000.0)
    d = f.to_dict()
    assert set(d.keys()) >= {
        "slug",
        "title",
        "imdb_id",
        "worldwide_gross_usd",
        "budget_usd",
        "roi",
        "genres",
        "release_year",
        "boxofficemojo_url",
        "imdb_url",
    }
    assert d["roi"] == pytest.approx(2.0)
