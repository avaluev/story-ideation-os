"""Unit tests for pipeline.select.diversity_select (ADR-0012 Module 5).

Covers:
    - Boundary behaviour: empty input, k<=0, k>=len, single candidate.
    - Greedy ranking: highest score wins when no duplicates.
    - Repeat-penalty: triples with duplicates lose to fresh triples.
    - Cluster-floor swap-in: fills missing clusters from qualifying anchors.
    - Quality threshold: weak anchors are never force-promoted.
    - Unsatisfiable floor: returns best feasible coverage, never raises.
    - SelectCandidate.triple correctness.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Final

import pytest

from pipeline.select.diversity_select import (
    DEFAULT_CLUSTER_FLOOR,
    DEFAULT_QUALITY_THRESHOLD,
    DEFAULT_REPEAT_PENALTY_ALPHA,
    DEFAULT_TOP_K,
    SelectCandidate,
    select_top_k,
)


def _cand(
    score: float,
    cluster: str = "institutional",
    archetype: str = "PA_01",
    texture: str = "WT_01",
    payload: object = None,
) -> SelectCandidate:
    return SelectCandidate(
        score=score,
        primary_cluster=cluster,
        archetype_id=archetype,
        world_texture_id=texture,
        payload=payload,
    )


_EIGHT_CLUSTERS: Final[tuple[str, ...]] = (
    "institutional",
    "emotional",
    "technology",
    "identity",
    "nature",
    "economic",
    "temporal",
    "civilizational",
)


# ─── SelectCandidate adapter ─────────────────────────────────────────────────


class TestSelectCandidate:
    def test_triple_is_tuple_of_three(self) -> None:
        c = _cand(0.9, cluster="X", archetype="Y", texture="Z")
        assert c.triple == ("X", "Y", "Z")

    def test_frozen_dataclass(self) -> None:
        c = _cand(0.9)
        with pytest.raises(FrozenInstanceError):
            c.score = 0.5  # type: ignore[misc]

    def test_payload_preserved(self) -> None:
        payload = {"id": "abc"}
        c = _cand(0.9, payload=payload)
        assert c.payload is payload


# ─── Boundary behaviour ──────────────────────────────────────────────────────


class TestBoundary:
    def test_empty_input_returns_empty(self) -> None:
        assert select_top_k([], k=5) == []

    def test_k_zero_returns_empty(self) -> None:
        assert select_top_k([_cand(0.9)], k=0) == []

    def test_k_negative_returns_empty(self) -> None:
        assert select_top_k([_cand(0.9)], k=-3) == []

    def test_single_candidate_returned(self) -> None:
        c = _cand(0.5)
        # cluster_floor=0 disables the floor check so a 1-cluster pool works.
        assert select_top_k([c], k=5, cluster_floor=0) == [c]

    def test_k_larger_than_pool(self) -> None:
        pool = [_cand(0.9, cluster=cl) for cl in _EIGHT_CLUSTERS]
        out = select_top_k(pool, k=20, cluster_floor=4)
        assert len(out) == len(pool)


# ─── Greedy ranking ──────────────────────────────────────────────────────────


class TestGreedyRanking:
    def test_picks_highest_score_first(self) -> None:
        pool = [
            _cand(0.3, cluster="A"),
            _cand(0.9, cluster="B"),
            _cand(0.6, cluster="C"),
        ]
        out = select_top_k(pool, k=1, cluster_floor=0)
        assert out[0].score == pytest.approx(0.9)

    def test_returns_top_k_by_score_when_all_unique_triples(self) -> None:
        pool = [
            _cand(score, cluster=cl, archetype=f"PA_{i}", texture=f"WT_{i}")
            for i, (score, cl) in enumerate(
                [(0.95, "A"), (0.85, "B"), (0.80, "C"), (0.50, "D"), (0.30, "E")]
            )
        ]
        out = select_top_k(pool, k=3, cluster_floor=0)
        assert [c.score for c in out] == pytest.approx([0.95, 0.85, 0.80])

    def test_returns_at_most_k(self) -> None:
        pool = [
            _cand(0.9 - i * 0.01, cluster=f"CL_{i}", archetype=f"PA_{i}", texture=f"WT_{i}")
            for i in range(20)
        ]
        out = select_top_k(pool, k=5, cluster_floor=0)
        assert len(out) == 5


# ─── Repeat-penalty ──────────────────────────────────────────────────────────


class TestRepeatPenalty:
    def test_duplicate_triples_demoted_after_first_pick(self) -> None:
        # All same triple: scores 0.9, 0.8, 0.7. Plus one unique triple at 0.6.
        # After the 0.9 pick, the 0.8 candidate's adjusted score becomes
        # 0.8 * 0.5 = 0.4 < 0.6 -> the unique triple wins slot #2.
        pool = [
            _cand(0.9, cluster="A", archetype="P", texture="T"),
            _cand(0.8, cluster="A", archetype="P", texture="T"),
            _cand(0.7, cluster="A", archetype="P", texture="T"),
            _cand(0.6, cluster="B", archetype="Q", texture="U"),
        ]
        out = select_top_k(pool, k=2, cluster_floor=0, repeat_penalty_alpha=0.5)
        assert out[0].score == pytest.approx(0.9)
        assert out[1].score == pytest.approx(0.6)

    def test_alpha_one_disables_penalty(self) -> None:
        pool = [
            _cand(0.9, cluster="A", archetype="P", texture="T"),
            _cand(0.8, cluster="A", archetype="P", texture="T"),
            _cand(0.6, cluster="B", archetype="Q", texture="U"),
        ]
        out = select_top_k(pool, k=2, cluster_floor=0, repeat_penalty_alpha=1.0)
        # No penalty -> raw ranking holds, duplicate stays at slot #2.
        assert [c.score for c in out] == pytest.approx([0.9, 0.8])

    def test_alpha_zero_bans_duplicates(self) -> None:
        # alpha=0 -> adjusted score of any duplicate triple is exactly 0.
        pool = [
            _cand(0.9, cluster="A", archetype="P", texture="T"),
            _cand(0.85, cluster="A", archetype="P", texture="T"),
            _cand(0.05, cluster="B", archetype="Q", texture="U"),
        ]
        out = select_top_k(pool, k=2, cluster_floor=0, repeat_penalty_alpha=0.0)
        assert out[0].score == pytest.approx(0.9)
        # The 0.05 candidate beats the discounted 0.85 duplicate (0.85 * 0 = 0).
        assert out[1].score == pytest.approx(0.05)

    def test_penalty_compounds_across_duplicates(self) -> None:
        # 4 duplicates of one triple + 1 unique candidate at 0.30.
        # Greedy trace with alpha=0.5:
        #   slot 0: 0.95 (dup=0 -> 0.95) wins
        #   slot 1: 0.90 (dup=1 -> 0.45) > 0.30 (adj 0.30) -> A wins
        #   slot 2: 0.88 (dup=2 -> 0.22) < 0.30 (adj 0.30) -> B wins
        #   slot 3: 0.88 (dup=2 -> 0.22) > 0.87 (adj ~0.2175) -> A wins
        pool = [
            _cand(0.95, cluster="A", archetype="P", texture="T"),
            _cand(0.90, cluster="A", archetype="P", texture="T"),
            _cand(0.88, cluster="A", archetype="P", texture="T"),
            _cand(0.87, cluster="A", archetype="P", texture="T"),
            _cand(0.30, cluster="B", archetype="Q", texture="U"),
        ]
        out = select_top_k(pool, k=4, cluster_floor=0, repeat_penalty_alpha=0.5)
        clusters = [c.primary_cluster for c in out]
        assert clusters == ["A", "A", "B", "A"]


# ─── Cluster-floor swap-in ───────────────────────────────────────────────────


class TestClusterFloor:
    def test_floor_fills_missing_clusters(self) -> None:
        # 4 high-score candidates all in cluster A (different triples to avoid
        # the repeat-penalty kicking in) + one strong anchor in B, C, D.
        pool = [
            _cand(0.95, cluster="A", archetype="P1", texture="T1"),
            _cand(0.93, cluster="A", archetype="P2", texture="T2"),
            _cand(0.91, cluster="A", archetype="P3", texture="T3"),
            _cand(0.89, cluster="A", archetype="P4", texture="T4"),
            _cand(0.70, cluster="B", archetype="P5", texture="T5"),
            _cand(0.65, cluster="C", archetype="P6", texture="T6"),
            _cand(0.60, cluster="D", archetype="P7", texture="T7"),
        ]
        out = select_top_k(pool, k=4, cluster_floor=4, quality_threshold=0.55)
        clusters = {c.primary_cluster for c in out}
        assert len(clusters) >= 4
        assert clusters == {"A", "B", "C", "D"}

    def test_quality_threshold_blocks_weak_anchors(self) -> None:
        # Strong A pool, only weak anchors elsewhere.
        pool = [
            _cand(0.95, cluster="A", archetype="P1", texture="T1"),
            _cand(0.93, cluster="A", archetype="P2", texture="T2"),
            _cand(0.30, cluster="B", archetype="P3", texture="T3"),  # below 0.55
            _cand(0.20, cluster="C", archetype="P4", texture="T4"),  # below 0.55
        ]
        out = select_top_k(pool, k=2, cluster_floor=4, quality_threshold=0.55)
        # B and C below threshold -> never force-promoted; we keep the A
        # winners.  Length stays at 2.
        assert len(out) == 2
        assert all(c.primary_cluster == "A" for c in out)

    def test_unsatisfiable_floor_returns_best_feasible(self) -> None:
        # Only 2 clusters total but floor=5: should not loop forever and
        # should return the greedy top-K.
        pool = [
            _cand(0.95, cluster="A", archetype="P1", texture="T1"),
            _cand(0.90, cluster="B", archetype="P2", texture="T2"),
            _cand(0.80, cluster="A", archetype="P3", texture="T3"),
            _cand(0.75, cluster="B", archetype="P4", texture="T4"),
        ]
        out = select_top_k(pool, k=4, cluster_floor=5, quality_threshold=0.0)
        assert len(out) == 4
        # Coverage stays at 2 (the universe of available clusters).
        assert {c.primary_cluster for c in out} == {"A", "B"}

    def test_empty_cluster_survivors_swapped_first(self) -> None:
        # One empty-cluster survivor with the highest score, plus anchors in
        # two distinct clusters.  Floor=2 should swap the empty out.
        pool = [
            _cand(0.95, cluster="", archetype="P1", texture="T1"),  # no cluster
            _cand(0.85, cluster="A", archetype="P2", texture="T2"),
            _cand(0.80, cluster="B", archetype="P3", texture="T3"),
        ]
        out = select_top_k(pool, k=2, cluster_floor=2, quality_threshold=0.55)
        clusters = {c.primary_cluster for c in out if c.primary_cluster}
        # Empty-cluster survivor should have been swapped out.
        assert "A" in clusters or "B" in clusters
        assert len(clusters) == 2

    def test_cluster_floor_zero_skips_enforcement(self) -> None:
        pool = [
            _cand(0.9, cluster="A"),
            _cand(0.8, cluster="A"),
            _cand(0.7, cluster="A"),
        ]
        out = select_top_k(pool, k=3, cluster_floor=0)
        # All from A -- selector did NOT try to enforce coverage.
        assert {c.primary_cluster for c in out} == {"A"}


# ─── Defaults / public surface ───────────────────────────────────────────────


class TestDefaults:
    def test_default_constants(self) -> None:
        assert DEFAULT_TOP_K == 10
        assert DEFAULT_CLUSTER_FLOOR == 4
        assert pytest.approx(0.55) == DEFAULT_QUALITY_THRESHOLD
        assert pytest.approx(0.5) == DEFAULT_REPEAT_PENALTY_ALPHA

    def test_defaults_used_when_kwargs_omitted(self) -> None:
        pool = [_cand(0.9, cluster=cl) for cl in _EIGHT_CLUSTERS]
        out = select_top_k(pool)
        assert len(out) <= DEFAULT_TOP_K
        assert len({c.primary_cluster for c in out}) >= DEFAULT_CLUSTER_FLOOR
