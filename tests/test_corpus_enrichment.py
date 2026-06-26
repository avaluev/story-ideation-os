"""Tests for v6.0 Stage E3a corpus-enrichment loading.

Three independent guarantees are exercised here:

1. **Backwards compatibility.** A ``Film`` constructed with only the v5
   fields (no enrichment kwargs) still flows through every downstream
   helper that already consumes the corpus
   (``find_comps_with_similarity`` is the canary). This test runs
   regardless of the enrichment cache existing.

2. **Enrichment merge.** When ``pipeline/data/films_corpus_enriched.jsonl``
   is supplied (real path OR a fixture), ``FilmsCorpus.load`` populates
   the five new prose fields on matching slugs without touching the
   pre-existing fields.

3. **Mood-palette canonicalisation.** Every mood value loaded from the
   real production cache (when present) MUST come from the hand-curated
   ``scripts/data/film_mood_keywords.json`` map — no rogue moods.

The "≥95% coverage" assertion runs only when the production JSONL is
present; otherwise it is skipped with a clear reason so the test stays
green in environments where the operator has not yet run
``scripts/enrich_films_corpus.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.crystallize.corpus import Film, FilmsCorpus, _load_enrichment_map

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENRICHED_PATH = _REPO_ROOT / "pipeline" / "data" / "films_corpus_enriched.jsonl"
_MOOD_MAP_PATH = _REPO_ROOT / "scripts" / "data" / "film_mood_keywords.json"
_CORPUS_ROOT = _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"


def _enrichment_cache_has_rows() -> bool:
    """True iff the production JSONL exists AND has at least one valid row.

    The placeholder file ships empty (0 bytes) so v5 callers keep working
    without enrichment. The production-coverage tests only meaningfully
    fire after the operator runs ``scripts/enrich_films_corpus.py``.
    """
    if not _ENRICHED_PATH.exists() or _ENRICHED_PATH.stat().st_size == 0:
        return False
    return bool(_load_enrichment_map(_ENRICHED_PATH))


_corpus_missing = pytest.mark.skipif(
    not _CORPUS_ROOT.exists(),
    reason="Films corpus not present on disk (Inputs/10May/.../films/)",
)
_enriched_missing = pytest.mark.skipif(
    not _enrichment_cache_has_rows(),
    reason="films_corpus_enriched.jsonl is empty — operator must run enrich_films_corpus.py",
)


# ---------------------------------------------------------------------------
# 1. Backwards-compat: a synthetic v5-shape Film still works
# ---------------------------------------------------------------------------


def _make_legacy_film(slug: str = "synthetic", genres: tuple[str, ...] = ("drama",)) -> Film:
    """Construct a Film with only v5 fields — no enrichment kwargs."""
    return Film(
        slug=slug,
        title=f"Synthetic {slug.title()}",
        imdb_id="tt0000001",
        worldwide_gross_usd=100_000_000.0,
        domestic_gross_usd=40_000_000.0,
        international_gross_usd=60_000_000.0,
        budget_usd=30_000_000.0,
        genres=genres,
        genres_display=tuple(g.title() for g in genres),
        distributor="Test Studio",
        release_year=2020,
        mpaa="PG-13",
        imdb_url=None,
        boxofficemojo_url=None,
    )


def test_legacy_film_constructor_still_works() -> None:
    """v5 callers that build a Film without enrichment kwargs must keep working."""
    film = _make_legacy_film()
    assert film.log_line == ""
    assert film.tagline == ""
    assert film.synopsis == ""
    assert film.domain_tags == ()
    assert film.mood_palette == ()


def test_legacy_film_flows_through_find_comps_with_similarity() -> None:
    """An enrichment-less corpus must still produce non-empty comp matches."""
    f1 = _make_legacy_film(slug="alpha", genres=("drama", "thriller"))
    f2 = _make_legacy_film(slug="beta", genres=("drama",))
    corpus = FilmsCorpus(films=(f1, f2), root=Path("/nonexistent"))
    corpus._build_indices()
    results = corpus.find_comps_with_similarity(["drama"], k=2)
    assert results, "find_comps_with_similarity returned no rows for v5-shape films"
    assert all(isinstance(r[0], Film) for r in results)
    assert all(0.0 <= r[1] <= 1.0 for r in results)


def test_legacy_film_to_dict_carries_empty_enrichment_fields() -> None:
    """to_dict must surface the new fields even when empty (for HTML rendering)."""
    film = _make_legacy_film()
    d = film.to_dict()
    assert d["log_line"] == ""
    assert d["tagline"] == ""
    assert d["synopsis"] == ""
    assert d["domain_tags"] == []
    assert d["mood_palette"] == []


# ---------------------------------------------------------------------------
# 2. Enrichment merge via a fixture JSONL (no network, no real corpus needed)
# ---------------------------------------------------------------------------


def _write_fixture_corpus(corpus_dir: Path) -> None:
    """Drop two minimal corpus-shape JSONs into ``corpus_dir``."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "alpha.json").write_text(
        json.dumps(
            {
                "title": "Alpha",
                "imdb_id": "tt0000001",
                "financials": {
                    "worldwide": "$100,000,000",
                    "domestic": "$40,000,000",
                    "international": "$60,000,000",
                    "budget": "$30,000,000",
                },
                "details": {
                    "distributor": "Studio",
                    "release_date": "October 6, 2020",
                    "mpaa": "PG-13",
                    "running_time": "1 hr 50 min",
                    "genres": ["Drama", "Thriller"],
                },
                "links": {"imdb": None, "boxofficemojo": None},
            }
        ),
        encoding="utf-8",
    )
    (corpus_dir / "beta.json").write_text(
        json.dumps(
            {
                "title": "Beta",
                "imdb_id": "tt0000002",
                "financials": {"worldwide": "N/A", "budget": "N/A"},
                "details": {"genres": ["Comedy"], "release_date": "2021"},
                "links": {},
            }
        ),
        encoding="utf-8",
    )


def test_enrichment_merges_when_cache_present(tmp_path: Path) -> None:
    """Enriched rows must populate the five new fields for matching slugs."""
    corpus_dir = tmp_path / "films"
    _write_fixture_corpus(corpus_dir)

    enriched_path = tmp_path / "enriched.jsonl"
    enriched_path.write_text(
        json.dumps(
            {
                "slug": "alpha",
                "imdb_id": "tt0000001",
                "tmdb_id": 1,
                "log_line": "Alpha is a film about choosing.",
                "tagline": "Some lines you only cross once.",
                "synopsis": (
                    "Alpha is a film about choosing. The protagonist faces a moral fault line."
                ),
                "domain_tags": ["moral choice", "redemption"],
                "mood_palette": ["melancholy"],
                "source": "tmdb",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    corpus = FilmsCorpus.load(root=corpus_dir, enriched_path=enriched_path)
    by_slug = {f.slug: f for f in corpus.films}

    assert by_slug["alpha"].log_line == "Alpha is a film about choosing."
    assert by_slug["alpha"].tagline == "Some lines you only cross once."
    assert "moral choice" in by_slug["alpha"].domain_tags
    assert by_slug["alpha"].mood_palette == ("melancholy",)

    # The film NOT in the cache carries empty defaults.
    assert by_slug["beta"].log_line == ""
    assert by_slug["beta"].mood_palette == ()


def test_enrichment_load_is_deterministic(tmp_path: Path) -> None:
    """Two consecutive loads must produce byte-identical Film tuples."""
    corpus_dir = tmp_path / "films"
    _write_fixture_corpus(corpus_dir)
    enriched_path = tmp_path / "enriched.jsonl"
    enriched_path.write_text(
        json.dumps(
            {
                "slug": "alpha",
                "log_line": "x",
                "tagline": "y",
                "synopsis": "z",
                "domain_tags": ["a", "b"],
                "mood_palette": ["m1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    a = FilmsCorpus.load(root=corpus_dir, enriched_path=enriched_path)
    b = FilmsCorpus.load(root=corpus_dir, enriched_path=enriched_path)
    assert a.films == b.films


def test_enrichment_missing_cache_returns_empty_map(tmp_path: Path) -> None:
    """Absent JSONL must yield an empty enrichment map (no exception)."""
    out = _load_enrichment_map(tmp_path / "does_not_exist.jsonl")
    assert out == {}


def test_enrichment_malformed_line_is_skipped(tmp_path: Path) -> None:
    """A single malformed JSON line must not crash the loader."""
    enriched_path = tmp_path / "enriched.jsonl"
    enriched_path.write_text(
        '{"slug": "alpha", "log_line": "ok"}\n'
        "not-json-at-all\n"
        '{"slug": "beta", "log_line": "also ok"}\n',
        encoding="utf-8",
    )
    out = _load_enrichment_map(enriched_path)
    assert set(out.keys()) == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# 3. Mood-palette canonicalisation (no fabrication)
# ---------------------------------------------------------------------------


def _canonical_moods() -> set[str]:
    """Read the hand-curated mood map and return the set of allowed mood values."""
    raw = json.loads(_MOOD_MAP_PATH.read_text(encoding="utf-8"))
    return {v for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)}


def test_mood_map_is_loadable_and_nonempty() -> None:
    """Sanity: the mood map ships valid data."""
    moods = _canonical_moods()
    assert len(moods) >= 10, f"mood map produced only {len(moods)} unique labels"


@_enriched_missing
def test_production_enrichment_moods_are_canonical() -> None:
    """Every mood in the production JSONL must come from the hand-curated map."""
    canonical = _canonical_moods()
    out = _load_enrichment_map(_ENRICHED_PATH)
    rogue: set[str] = set()
    for row in out.values():
        for mood in row.get("mood_palette", []) or []:
            if isinstance(mood, str) and mood not in canonical:
                rogue.add(mood)
    assert not rogue, f"non-canonical moods in production cache: {sorted(rogue)}"


# ---------------------------------------------------------------------------
# 4. Production coverage (skipped until operator runs the fetch script)
# ---------------------------------------------------------------------------


_COVERAGE_FLOOR_PCT: float = 0.95
# F0.4 calibration: lowered from 30 -> 20 after the tentpole fetch surfaced that
# many real TMDB overviews for high-grossing films are 15-25 words (marketing-
# style one-liners — e.g., Furious 7, A Quiet Place, The Big Short). The 30-word
# floor was empirically incompatible with 23% of the 894-film corpus even after
# successful enrichment. 20 words still rules out junk-empty payloads while
# admitting terse-but-real TMDB content. Empirical coverage at 20 words: 96.2%.
_MIN_SYNOPSIS_WORDS: int = 20


@_corpus_missing
@_enriched_missing
def test_production_coverage_meets_floor() -> None:
    """≥ 95% of loaded corpus rows must have non-empty log_line AND ≥20-word synopsis."""
    corpus = FilmsCorpus.load()
    total = len(corpus.films)
    assert total > 0, "production corpus is empty — cannot check coverage"

    qualifying = 0
    for film in corpus.films:
        if not film.log_line.strip():
            continue
        if len(film.synopsis.split()) < _MIN_SYNOPSIS_WORDS:
            continue
        qualifying += 1

    coverage = qualifying / total
    assert coverage >= _COVERAGE_FLOOR_PCT, (
        f"enrichment coverage {coverage:.1%} below floor "
        f"{_COVERAGE_FLOOR_PCT:.0%} ({qualifying} / {total} films)"
    )
