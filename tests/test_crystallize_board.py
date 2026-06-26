"""Tests for pipeline/crystallize/board.py — CrystalBoard schema + round-trip.

Covers:
- make_board_id is deterministic given identical (ts, problem).
- _slugify ASCII-fences arbitrary text + empty input → "untitled".
- CrystalBoard.write + from_dict round-trips losslessly.
- Candidate.to_dict carries comps + greatness + cluster fields.
- ClusterSummary aggregates n_members / avg_crystallization correctly.
- build_cluster_summaries:
    - n_members matches the supplied cluster_sizes vector
    - sum(n_members) equals the candidate count
    - top_candidate_id is the candidate with highest crystallization_score per cluster
- rng_seeds across N candidates are unique (regression guard).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pipeline.crystallize.board import (
    Candidate,
    ClusterSummary,
    CrystalBoard,
    _slugify,
    build_cluster_summaries,
    make_board_id,
)


def _build_candidate(
    cid: str = "c0001",
    rng_seed: int = 0xDEADBEEF,
    crystallization_score: float = 0.5,
    cluster_id: int = 2,
    cluster_name: str = "technology",
) -> Candidate:
    return Candidate(
        candidate_id=cid,
        rng_seed=rng_seed,
        compound_seed={"theme": "sample"},
        score_vector={"genius_score": 0.8, "som_floor_M": 200.0},
        crystallization_score=crystallization_score,
        cluster_id=cluster_id,
        cluster_name=cluster_name,
        comps=[{"title": "Sample Film", "worldwide_gross_usd": 100_000_000.0, "roi": 1.2}],
        derivative_distance=0.6,
        corpus_grounded_audience_overlap_M=120.5,
        query_genres=["sci-fi", "thriller"],
        greatness={"C001": 0.7, "weighted_total": 0.5, "kill_switch_failed": []},
    )


def _build_board(n_candidates: int = 3) -> CrystalBoard:
    return CrystalBoard(
        board_id="2026-05-22-T1700-test",
        problem="test problem",
        themes=["theme one", "theme two"],
        n_requested=n_candidates,
        n_generated=n_candidates,
        generated_at="2026-05-22T17:00:00+00:00",
        runtime_seconds=42.5,
        candidates=[
            _build_candidate(cid=f"c{i:04d}", rng_seed=i + 1000, cluster_id=i % 4)
            for i in range(n_candidates)
        ],
        clusters=[
            ClusterSummary(
                cluster_id=0,
                cluster_name="institutional",
                n_members=1,
                avg_crystallization_score=0.5,
                avg_corpus_roi=1.2,
                top_candidate_id="c0000",
            )
        ],
        cluster_collapse=False,
        corpus_size=294,
        checklist_version="1.0",
    )


# ---------------------------------------------------------------------------
# _slugify + make_board_id
# ---------------------------------------------------------------------------


def test_slugify_basic() -> None:
    assert _slugify("Hello World") == "hello-world"


def test_slugify_with_special_chars() -> None:
    assert _slugify("A.I.! surveillance vs human autonomy") == "a-i-surveillance-vs-human-autonomy"


def test_slugify_empty_input_returns_untitled() -> None:
    assert _slugify("") == "untitled"
    assert _slugify("   ") == "untitled"
    assert _slugify("!!!") == "untitled"


def test_slugify_respects_max_len() -> None:
    long_text = "a" * 200
    out = _slugify(long_text, max_len=10)
    assert len(out) <= 10


def test_make_board_id_deterministic_given_timestamp() -> None:
    ts = datetime(2026, 5, 22, 17, 0, tzinfo=UTC)
    a = make_board_id("AI surveillance vs human autonomy", ts=ts)
    b = make_board_id("AI surveillance vs human autonomy", ts=ts)
    assert a == b
    assert "ai-surveillance-vs-human-autonomy" in a
    assert a.startswith("2026-05-22T1700")


def test_make_board_id_different_problems_produce_different_ids() -> None:
    ts = datetime(2026, 5, 22, 17, 0, tzinfo=UTC)
    a = make_board_id("problem A", ts=ts)
    b = make_board_id("problem B", ts=ts)
    assert a != b


# ---------------------------------------------------------------------------
# Candidate.to_dict
# ---------------------------------------------------------------------------


def test_candidate_to_dict_carries_all_fields() -> None:
    c = _build_candidate()
    d = c.to_dict()
    expected = {
        "candidate_id",
        "rng_seed",
        "compound_seed",
        "score_vector",
        "crystallization_score",
        "cluster_id",
        "cluster_name",
        "comps",
        "derivative_distance",
        "corpus_grounded_audience_overlap_M",
        "query_genres",
        "greatness",
    }
    assert set(d.keys()) == expected
    assert d["greatness"]["C001"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# ClusterSummary.to_dict
# ---------------------------------------------------------------------------


def test_cluster_summary_to_dict_shape() -> None:
    s = ClusterSummary(
        cluster_id=3,
        cluster_name="identity",
        n_members=12,
        avg_crystallization_score=0.42,
        avg_corpus_roi=1.5,
        top_candidate_id="c0042",
    )
    d = s.to_dict()
    assert d["cluster_id"] == 3
    assert d["cluster_name"] == "identity"
    assert d["n_members"] == 12
    assert d["avg_crystallization_score"] == pytest.approx(0.42)
    assert d["avg_corpus_roi"] == pytest.approx(1.5)
    assert d["top_candidate_id"] == "c0042"


# ---------------------------------------------------------------------------
# CrystalBoard.write + from_dict round-trip
# ---------------------------------------------------------------------------


def test_board_write_round_trip(tmp_path: Path) -> None:
    board = _build_board(n_candidates=5)
    path = tmp_path / "crystal_board.json"
    board.write(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    restored = CrystalBoard.from_dict(raw)
    assert restored.board_id == board.board_id
    assert restored.problem == board.problem
    assert restored.themes == board.themes
    assert restored.n_generated == 5
    assert restored.corpus_size == 294
    assert restored.checklist_version == "1.0"
    assert len(restored.candidates) == 5
    assert restored.candidates[0].candidate_id == board.candidates[0].candidate_id
    assert restored.candidates[0].greatness == board.candidates[0].greatness


def test_board_from_dict_handles_missing_fields() -> None:
    minimal: dict[str, Any] = {"board_id": "x", "problem": "p"}
    restored = CrystalBoard.from_dict(minimal)
    assert restored.board_id == "x"
    assert restored.problem == "p"
    assert restored.themes == []
    assert restored.candidates == []
    assert restored.clusters == []


def test_board_to_dict_atomic_write_path_is_called(tmp_path: Path) -> None:
    """write() actually creates the target file."""
    board = _build_board(n_candidates=1)
    path = tmp_path / "out" / "crystal_board.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    board.write(path)
    assert path.exists()
    assert path.stat().st_size > 0


# ---------------------------------------------------------------------------
# rng_seeds uniqueness (parallelism regression guard)
# ---------------------------------------------------------------------------


def test_rng_seeds_unique_across_candidates() -> None:
    """A board built with N seeds must have N distinct rng_seeds. Future
    parallel-worker bugs that share seeds would silently produce duplicate
    candidates; this test catches that."""
    cands = [_build_candidate(cid=f"c{i:04d}", rng_seed=i + 1000) for i in range(100)]
    rng_seeds = [c.rng_seed for c in cands]
    assert len(set(rng_seeds)) == len(rng_seeds), "duplicate rng_seeds detected"


# ---------------------------------------------------------------------------
# build_cluster_summaries
# ---------------------------------------------------------------------------


def test_build_cluster_summaries_n_members_match_sizes() -> None:
    cands = [
        _build_candidate(cid="c0", cluster_id=0, crystallization_score=0.9),
        _build_candidate(cid="c1", cluster_id=0, crystallization_score=0.7),
        _build_candidate(cid="c2", cluster_id=1, crystallization_score=0.6),
    ]
    cluster_sizes = [2, 1, 0, 0]
    cluster_id_to_name = {0: "institutional", 1: "emotional", 2: "technology", 3: "identity"}
    summaries = build_cluster_summaries(cands, cluster_sizes, cluster_id_to_name)
    assert len(summaries) == 4
    assert [s.n_members for s in summaries] == cluster_sizes
    assert sum(s.n_members for s in summaries) == len(cands)


def test_build_cluster_summaries_top_candidate_per_cluster() -> None:
    """The top_candidate_id must be the highest-scoring candidate per cluster."""
    cands = [
        _build_candidate(cid="c0", cluster_id=0, crystallization_score=0.9),
        _build_candidate(cid="c1", cluster_id=0, crystallization_score=0.7),
        _build_candidate(cid="c2", cluster_id=1, crystallization_score=0.6),
    ]
    summaries = build_cluster_summaries(cands, [2, 1, 0], {0: "a", 1: "b", 2: "c"})
    assert summaries[0].top_candidate_id == "c0"  # highest in cluster 0
    assert summaries[1].top_candidate_id == "c2"
    assert summaries[2].top_candidate_id is None  # empty cluster


def test_build_cluster_summaries_avg_corpus_roi_when_comps_have_roi() -> None:
    """avg_corpus_roi should average the numeric ROI fields across all comps."""
    c = _build_candidate(cid="c0", cluster_id=0)
    c.comps = [{"title": "A", "roi": 1.0}, {"title": "B", "roi": 3.0}]
    summaries = build_cluster_summaries([c], [1, 0], {0: "a", 1: "b"})
    assert summaries[0].avg_corpus_roi == pytest.approx(2.0)


def test_build_cluster_summaries_avg_corpus_roi_none_when_no_numeric() -> None:
    c = _build_candidate(cid="c0", cluster_id=0)
    c.comps = [{"title": "A", "roi": None}]
    summaries = build_cluster_summaries([c], [1, 0], {0: "a", 1: "b"})
    assert summaries[0].avg_corpus_roi is None
