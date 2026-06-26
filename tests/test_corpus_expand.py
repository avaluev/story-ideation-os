"""Tests for scripts/corpus/expand_from_tmdb.py — transform + dedupe + round-trip.

The expansion loop is tested without HTTP via a ``DummyClient`` that
returns canned ``movie_full`` payloads. A final round-trip test loads
a generated file via ``pipeline.crystallize.corpus.FilmsCorpus`` to
prove the on-disk shape is loader-compatible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.crystallize.corpus import FilmsCorpus
from pipeline.tmdb_client import TMDBError
from scripts.corpus.expand_from_tmdb import (
    _existing_tmdb_ids,
    _format_dollars,
    _format_runtime,
    _genre_names,
    _mpaa_from_release_dates,
    expand,
    make_slug,
    slug_for_tmdb_film,
    to_corpus_row,
)

# ── pure helpers ────────────────────────────────────────────────────────────


def test_make_slug_basic() -> None:
    assert make_slug("The Matrix") == "the-matrix"


def test_make_slug_strips_special_chars() -> None:
    assert make_slug("Spider-Man: No Way Home (2021)!") == "spider-man-no-way-home-2021"


def test_make_slug_empty_falls_back_to_untitled() -> None:
    assert make_slug("") == "untitled"
    assert make_slug("***") == "untitled"


def test_make_slug_truncated() -> None:
    long = "a" * 200
    assert len(make_slug(long)) <= 60


def test_slug_namespaces_tmdb_id() -> None:
    assert slug_for_tmdb_film(603, "The Matrix") == "tmdb-603-the-matrix"


def test_format_dollars_integer() -> None:
    assert _format_dollars(132_963_417) == "$132,963,417"


def test_format_dollars_zero_is_na() -> None:
    assert _format_dollars(0) == "N/A"


def test_format_dollars_negative_is_na() -> None:
    assert _format_dollars(-1) == "N/A"


def test_format_dollars_none_is_na() -> None:
    assert _format_dollars(None) == "N/A"


def test_format_dollars_string_is_na() -> None:
    # TMDB occasionally returns strings for missing values.
    assert _format_dollars("not-a-number") == "N/A"


def test_format_runtime() -> None:
    assert _format_runtime(104) == "1 hr 44 min"
    assert _format_runtime(60) == "1 hr 0 min"
    assert _format_runtime(45) == "45 min"
    assert _format_runtime(0) == "N/A"
    assert _format_runtime(None) == "N/A"


def test_genre_names_filters_malformed() -> None:
    assert _genre_names(
        [
            {"id": 1, "name": "Drama"},
            {"name": "Action"},
            "not a dict",
            {"id": 99},  # missing name
            {"name": "  "},
        ]
    ) == ["Drama", "Action"]


def test_genre_names_handles_non_list() -> None:
    assert _genre_names(None) == []
    assert _genre_names("not a list") == []


def test_mpaa_from_release_dates_picks_us_cert() -> None:
    payload = {
        "results": [
            {
                "iso_3166_1": "GB",
                "release_dates": [{"certification": "15"}],
            },
            {
                "iso_3166_1": "US",
                "release_dates": [{"certification": "PG-13"}],
            },
        ]
    }
    assert _mpaa_from_release_dates(payload) == "PG-13"


def test_mpaa_from_release_dates_missing_is_na() -> None:
    assert _mpaa_from_release_dates({}) == "N/A"
    assert _mpaa_from_release_dates(None) == "N/A"


# ── to_corpus_row ───────────────────────────────────────────────────────────


def _sample_detail(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 603,
        "title": "The Matrix",
        "release_date": "1999-03-30",
        "runtime": 136,
        "budget": 63_000_000,
        "revenue": 467_222_824,
        "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Sci-Fi"}],
        "production_companies": [
            {"id": 1, "name": "Warner Bros."},
            {"id": 2, "name": "Village Roadshow"},
        ],
        "credits": {
            "cast": [
                {"id": 6384, "name": "Keanu Reeves", "character": "Neo"},
                {"id": 2975, "name": "Laurence Fishburne", "character": "Morpheus"},
            ],
            "crew": [
                {"id": 9339, "name": "Lana Wachowski", "job": "Director"},
                {"id": 9340, "name": "Lilly Wachowski", "job": "Director"},
                {"id": 9341, "name": "Don Davis", "job": "Original Music Composer"},
                # Noise — not in WANTED_CREW_JOBS.
                {"id": 9342, "name": "Random Person", "job": "Best Boy"},
            ],
        },
        "external_ids": {"imdb_id": "tt0133093"},
        "release_dates": {
            "results": [
                {"iso_3166_1": "US", "release_dates": [{"certification": "R"}]},
            ]
        },
    }
    base.update(overrides)
    return base


def test_to_corpus_row_shape_matches_existing_loader() -> None:
    row = to_corpus_row(_sample_detail())
    assert row["title"] == "The Matrix (1999)"
    assert row["imdb_id"] == "tt0133093"
    assert row["financials"]["worldwide"] == "$467,222,824"
    assert row["financials"]["budget"] == "$63,000,000"
    assert row["financials"]["domestic"] == "N/A"
    assert row["details"]["distributor"] == "Warner Bros."
    assert row["details"]["mpaa"] == "R"
    assert row["details"]["running_time"] == "2 hr 16 min"
    assert row["details"]["genres"] == ["Action", "Sci-Fi"]
    assert row["links"]["imdb"] == "https://www.imdb.com/title/tt0133093/"
    assert row["links"]["boxofficemojo"] == "https://www.boxofficemojo.com/title/tt0133093/"
    assert row["links"]["tmdb"] == "https://www.themoviedb.org/movie/603"
    assert row["source"] == "tmdb"
    assert row["source_tmdb_id"] == 603


def test_to_corpus_row_handles_missing_financials() -> None:
    detail = _sample_detail(budget=0, revenue=0)
    row = to_corpus_row(detail)
    assert row["financials"]["worldwide"] == "N/A"
    assert row["financials"]["budget"] == "N/A"


def test_to_corpus_row_handles_missing_external_ids() -> None:
    detail = _sample_detail(external_ids={})
    row = to_corpus_row(detail)
    assert row["imdb_id"] is None
    assert row["links"]["imdb"] is None
    assert row["links"]["boxofficemojo"] is None


def test_to_corpus_row_crew_only_keeps_wanted_jobs() -> None:
    row = to_corpus_row(_sample_detail())
    jobs = {entry["role"] for entry in row["personnel"]["crew"]}
    assert jobs == {"Director", "Original Music Composer"}
    # Director appears twice (one per Wachowski), Composer once.
    assert len(row["personnel"]["crew"]) == 3


# ── _existing_tmdb_ids ──────────────────────────────────────────────────────


def test_existing_tmdb_ids_scans_tmdb_prefix(tmp_path: Path) -> None:
    (tmp_path / "tmdb-1-foo.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tmdb-42-bar.json").write_text("{}", encoding="utf-8")
    (tmp_path / "1408.json").write_text("{}", encoding="utf-8")  # existing BOM row
    (tmp_path / "tmdb-malformed.json").write_text("{}", encoding="utf-8")  # bad id
    ids = _existing_tmdb_ids(tmp_path)
    assert ids == {1, 42}


def test_existing_tmdb_ids_returns_empty_when_missing(tmp_path: Path) -> None:
    assert _existing_tmdb_ids(tmp_path / "no_such_dir") == set()


# ── expand() with a stub client ─────────────────────────────────────────────


class _DummyClient:
    """Minimal stand-in for TMDBClient — only what expand() touches."""

    def __init__(self, ids: list[int], details: dict[int, dict[str, Any]]) -> None:
        self._ids = ids
        self._details = details
        self.movie_calls: list[int] = []

    def auth_summary(self) -> dict[str, Any]:
        return {"v4_bearer": None, "v3_keys": [], "rotation_pool_size": 0}

    def iter_movie_ids(
        self, endpoint: str, *, target: int, extra_params: dict[str, Any] | None = None
    ):
        # All sources return the same id list — the dedupe path handles repeats.
        yield from self._ids[:target]

    def movie_full(self, movie_id: int) -> dict[str, Any]:
        self.movie_calls.append(movie_id)
        if movie_id not in self._details:
            raise TMDBError(f"no fixture for id={movie_id}")
        return self._details[movie_id]

    def close(self) -> None:  # context manager parity (unused by tests)
        pass


def test_expand_writes_files_dedupes_across_sources(tmp_path: Path) -> None:
    client = _DummyClient(
        ids=[100, 101, 102],
        details={
            100: _sample_detail(id=100, title="Film A", external_ids={"imdb_id": "tt0000100"}),
            101: _sample_detail(id=101, title="Film B", external_ids={"imdb_id": "tt0000101"}),
            102: _sample_detail(id=102, title="Film C", external_ids={"imdb_id": "tt0000102"}),
        },
    )

    stats = expand(
        out_dir=tmp_path,
        target=10,
        sources=["top_rated", "popular"],  # both yield same ids; expect dedupe
        dry_run=False,
        client=client,  # type: ignore[arg-type]
        progress_log=None,
    )

    assert stats["written"] == 3
    assert stats["fetched"] == 3
    written_files = sorted(p.name for p in tmp_path.glob("tmdb-*.json"))
    assert written_files == [
        "tmdb-100-film-a-1999.json",
        "tmdb-101-film-b-1999.json",
        "tmdb-102-film-c-1999.json",
    ]
    # Every id fetched exactly once thanks to cross-source dedupe.
    assert client.movie_calls.count(100) == 1
    assert client.movie_calls.count(101) == 1
    assert client.movie_calls.count(102) == 1


def test_expand_skips_already_written_ids(tmp_path: Path) -> None:
    # Pre-seed one row as if from an earlier run.
    (tmp_path / "tmdb-200-already.json").write_text("{}", encoding="utf-8")

    client = _DummyClient(
        ids=[200, 201],
        details={
            200: _sample_detail(id=200, title="Already"),
            201: _sample_detail(id=201, title="Fresh"),
        },
    )

    stats = expand(
        out_dir=tmp_path,
        target=10,
        sources=["top_rated"],
        client=client,  # type: ignore[arg-type]
    )

    assert stats["skipped_existing"] == 1
    assert stats["written"] == 1
    # The pre-seeded file must not have been touched (still empty JSON).
    assert (tmp_path / "tmdb-200-already.json").read_text(encoding="utf-8") == "{}"
    assert client.movie_calls == [201]  # 200 never fetched


def test_expand_dry_run_writes_nothing(tmp_path: Path) -> None:
    client = _DummyClient(
        ids=[300, 301],
        details={
            300: _sample_detail(id=300, title="Dry A"),
            301: _sample_detail(id=301, title="Dry B"),
        },
    )

    stats = expand(
        out_dir=tmp_path,
        target=10,
        sources=["top_rated"],
        dry_run=True,
        client=client,  # type: ignore[arg-type]
    )

    assert stats["written"] == 0
    assert stats["fetched"] >= 1
    assert list(tmp_path.glob("*.json")) == []


def test_expand_records_errors(tmp_path: Path) -> None:
    client = _DummyClient(
        ids=[400, 401],
        details={400: _sample_detail(id=400, title="Good")},  # 401 missing → TMDBError
    )

    stats = expand(
        out_dir=tmp_path,
        target=10,
        sources=["top_rated"],
        client=client,  # type: ignore[arg-type]
    )

    assert stats["written"] == 1
    assert stats["errors"] == 1


def test_expand_progress_log_written(tmp_path: Path) -> None:
    log_path = tmp_path / "_progress.jsonl"
    client = _DummyClient(
        ids=[500],
        details={500: _sample_detail(id=500, title="Logged")},
    )

    expand(
        out_dir=tmp_path,
        target=10,
        sources=["top_rated"],
        client=client,  # type: ignore[arg-type]
        progress_log=log_path,
    )

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tmdb_id"] == 500
    assert record["status"] == "written"
    assert record["slug"].startswith("tmdb-500-")


# ── round-trip: expand → FilmsCorpus.load ───────────────────────────────────


def test_round_trip_generated_row_loads_via_films_corpus(tmp_path: Path) -> None:
    """A row written by expand() loads cleanly through the production loader."""
    client = _DummyClient(
        ids=[700],
        details={700: _sample_detail(id=700, title="Round Trip")},
    )

    expand(
        out_dir=tmp_path,
        target=1,
        sources=["top_rated"],
        client=client,  # type: ignore[arg-type]
    )

    corpus = FilmsCorpus.load(root=tmp_path)
    assert len(corpus) == 1
    film = corpus.films[0]
    assert film.title == "Round Trip (1999)"
    assert film.imdb_id == "tt0133093"
    assert film.budget_usd == pytest.approx(63_000_000.0)
    assert film.worldwide_gross_usd == pytest.approx(467_222_824.0)
    assert film.release_year == 1999
    # Genres normalized to lowercase, display preserved.
    assert "action" in film.genres
    assert "sci-fi" in film.genres
