# ruff: noqa: S311 -- test fixtures use random.Random for determinism, not crypto
"""Tests for the four Day-4 surgical wirings (v5.0 ADR-0011 + ADR-0012).

Each test pins one of the four wiring changes the v5.0 plan called out:

  1. _thematic_weighted_choice gains optional freq_table / axis_name kwargs.
     When supplied, weights are multiplied by diversity.penalty.
  2. _compute_audience_overlap delegates to revenue.compute_audience_overlap;
     signature preserved.
  3. crystallization_score's som factor reads som_y1_usd first (normalised
     vs $200M), falls back to som_floor_M (normalised vs $300M).
  4. single_idea.generate_seed_via_evolve writes seed.json + seed_candidates.jsonl
     from the v5 orchestrator's output.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, cast

import pytest

from pipeline.compound_seed import (
    _compute_audience_overlap,
    _thematic_weighted_choice,
)
from pipeline.crystallize.score import crystallization_score
from pipeline.evolve import one_shot
from pipeline.goal import Goal

# ─── Surgical wire #1: freq_table in _thematic_weighted_choice ──────────────


class TestFreqTableWiring:
    def _pool(self) -> list[dict[str, object]]:
        # 5 items, no thematic_cluster -> the v4 uniform-fallback path applies
        # unless we pass target_clusters.  We exercise both paths.
        return [{"id": f"X_{i:02d}", "thematic_cluster": ""} for i in range(5)]

    def test_no_freq_table_keeps_v4_behaviour(self) -> None:
        # No freq_table + empty target_clusters -> uniform choice (v4 path).
        rng = random.Random(0)
        chosen = _thematic_weighted_choice(
            rng, self._pool(), target_clusters=set(), penalty_weight=0.0
        )
        assert chosen["id"] in {f"X_{i:02d}" for i in range(5)}

    def test_freq_table_biases_against_over_sampled(self) -> None:
        # Heavily down-weight X_00 via freq_table; expect it to be picked
        # less than its uniform 1/5 share over many trials.
        freq_table: dict[tuple[str, str], int] = {("axis_test", "X_00"): 500}
        picks: list[str] = []
        for seed in range(500):
            rng = random.Random(seed)
            chosen = _thematic_weighted_choice(
                rng,
                self._pool(),
                target_clusters=set(),
                penalty_weight=0.0,
                freq_table=freq_table,
                axis_name="axis_test",
            )
            picks.append(str(chosen["id"]))
        x00_share = picks.count("X_00") / len(picks)
        # Uniform would be 0.20; penalty(500, alpha=0.3) ~= 0.155, so
        # X_00's expected share drops to ~0.155 / (4 + 0.155) ~= 3.7%.
        # Use a generous ceiling of 0.10 to keep the test stable.
        assert x00_share < 0.10, f"freq-table down-bias not respected ({x00_share=})"

    def test_freq_table_does_not_break_cluster_steering(self) -> None:
        # When target_clusters is non-empty, the cluster-steering path runs
        # AND folds the freq-table penalty into the same weight vector.
        pool: list[dict[str, object]] = [
            {"id": "A", "thematic_cluster": "institutional", "domain_tags": []},
            {"id": "B", "thematic_cluster": "emotional", "domain_tags": []},
            {"id": "C", "thematic_cluster": "technology", "domain_tags": []},
        ]
        # Target cluster = emotional (id=1); penalise the matching B heavily.
        freq_table = {("axis_test", "B"): 1000}
        picks: list[str] = []
        for seed in range(100):
            rng = random.Random(seed)
            chosen = _thematic_weighted_choice(
                rng,
                pool,
                target_clusters={1},
                penalty_weight=0.6,
                freq_table=freq_table,
                axis_name="axis_test",
            )
            picks.append(str(chosen["id"]))
        # B would have been favoured (cluster match) without the freq penalty;
        # with the penalty it should be a small minority.
        assert picks.count("B") < 30  # was ~85+ without the penalty


# ─── Surgical wire #2: audience overlap delegation ──────────────────────────


class TestAudienceOverlapWiring:
    def test_empty_audiences_returns_zero(self) -> None:
        assert _compute_audience_overlap([]) == 0.0

    def test_delegates_to_revenue_compute(self) -> None:
        # When delegating, the result MUST match revenue.compute_audience_overlap.
        from pipeline.crystallize.revenue import compute_audience_overlap  # noqa: PLC0415

        audiences: list[dict[str, object]] = [
            {
                "id": "AD_01",
                "name": "Gen Z",
                "size_M": 70.0,
                "domain_tags": ["youth", "social"],
                "affinity_with": ["AD_02"],
            },
            {
                "id": "AD_02",
                "name": "Millennials",
                "size_M": 80.0,
                "domain_tags": ["youth", "tech"],
                "affinity_with": ["AD_01"],
            },
        ]
        compound_overlap = _compute_audience_overlap(audiences)
        direct_overlap = compute_audience_overlap(audiences).unique_addressable_M
        assert compound_overlap == pytest.approx(direct_overlap)

    def test_returns_float(self) -> None:
        audiences: list[dict[str, object]] = [
            {
                "id": "AD_01",
                "name": "x",
                "size_M": 50.0,
                "domain_tags": ["t1"],
                "affinity_with": [],
            },
        ]
        result = _compute_audience_overlap(audiences)
        assert isinstance(result, float)
        assert result > 0


# ─── Surgical wire #3: som_y1_usd-aware score factor ────────────────────────


class TestSomY1ScoreFactor:
    def _base_scores(self) -> dict[str, object]:
        return {
            "genius_score": 0.8,
            "goldilocks_score": 0.7,
            "cluster_coherence": 0.7,
            "emotional_universality_score": 4.0,
            "passes_500m_gate": True,
            "passes_genius_gate": True,
        }

    def test_som_y1_usd_preferred_and_no_longer_saturates(self) -> None:
        # R5: som_y1_usd is log-scaled (no longer capped at $200M), so a
        # billion-dollar SOM scores strictly higher than a $200M one.
        big = {**self._base_scores(), "som_y1_usd": 1_200_000_000.0}
        small = {**self._base_scores(), "som_y1_usd": 200_000_000.0}
        assert crystallization_score(big) > crystallization_score(small)
        # And the som_y1_usd path is preferred over a legacy som_floor_M when both
        # are present (the v5 post-derate figure wins; som_floor_M is ignored).
        mixed = {**self._base_scores(), "som_y1_usd": 1_200_000_000.0, "som_floor_M": 50.0}
        assert crystallization_score(mixed) == pytest.approx(crystallization_score(big), rel=1e-6)

    def test_som_y1_usd_below_threshold_scales_down(self) -> None:
        # Log-scaled: a lower Y1 SOM yields a strictly lower score.
        high = {**self._base_scores(), "som_y1_usd": 400_000_000.0}
        low = {**self._base_scores(), "som_y1_usd": 100_000_000.0}
        assert crystallization_score(low) < crystallization_score(high)

    def test_falls_back_to_som_floor_M_when_y1_absent(self) -> None:
        # No som_y1_usd, only legacy som_floor_M -> the v4 path still works.
        scores = {**self._base_scores(), "som_floor_M": 150.0}
        result = crystallization_score(scores)
        assert 0.0 < result <= 1.0

    def test_som_y1_usd_zero_or_negative_floors_to_min(self) -> None:
        scores = {**self._base_scores(), "som_y1_usd": 0.0}
        # Score should still be in [0, 1].
        result = crystallization_score(scores)
        assert 0.0 <= result <= 1.0


class TestLiveScoringThreadsGoal:
    """R2/R4 regression pin: the live evolve path MUST pass goal= into
    crystallization_score and a tentpole-aware ProjectionContext (geo=global)
    into project_revenue. Both are one-liners a refactor can silently drop."""

    def test_score_population_threads_goal_and_global_geo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class _FakeScores:
            def to_dict(self) -> dict[str, object]:
                return {"som_floor_M": 250.0, "genius_score": 0.8}

        class _FakeCandidate:
            scores = _FakeScores()
            lineage: tuple[str, ...] = ()

            def to_dict(self) -> dict[str, object]:
                return {"id": "x"}

        class _FakeProj:
            som_y1_usd = 300_000_000.0

        def _fake_project_revenue(
            candidate: object, corpus: object, *, ctx: object = None
        ) -> object:
            captured["ctx_geo"] = getattr(ctx, "geo", None)
            captured["ctx_window"] = getattr(ctx, "window", None)
            return _FakeProj()

        def _fake_crystallization_score(
            scores: object,
            derivative_distance: float = 1.0,
            *,
            goal: object = None,
            operator_alignment: float = 1.0,
        ) -> float:
            captured["goal"] = goal
            return 0.5

        monkeypatch.setattr(one_shot, "project_revenue", _fake_project_revenue)
        monkeypatch.setattr(one_shot, "crystallization_score", _fake_crystallization_score)

        goal = Goal.load()
        candidates = cast("list[Any]", [_FakeCandidate()])
        result = one_shot._score_population(candidates, corpus=cast("Any", object()), goal=goal)

        assert len(result) == 1
        assert captured["goal"] is goal  # R2: operator goal threaded into scoring
        assert captured["ctx_geo"] == "global"  # R4: global geo applied
        # som_floor_M 250 -> prestige tier (>=200, <400)
        assert captured["ctx_window"] == "theatrical_prestige"


# ─── Surgical wire #4: generate_seed_via_evolve helper ──────────────────────


class TestSeedViaEvolveHelper:
    @pytest.mark.slow
    def test_writes_seed_json_and_candidates_jsonl(self, tmp_path: Path) -> None:
        """End-to-end: helper writes valid seed.json + seed_candidates.jsonl.

        Marked slow because it spins up the real engine + real corpus.
        """
        from pipeline.single_idea import generate_seed_via_evolve  # noqa: PLC0415

        seed = generate_seed_via_evolve(
            theme="legibility, agency",
            problem="the cost of being legible to algorithms",
            run_dir=tmp_path,
            n_base=3,  # keep it fast
            top_k=3,
            use_llm_operators=False,
        )
        # seed.json schema
        assert "candidate" in seed
        assert "revenue" in seed
        assert "crystallization_score" in seed
        assert "lineage" in seed
        # ADR-0011: every persisted revenue carries the python-executed marker.
        assert seed["revenue"]["calculation_method"] == "python_executed"
        # seed_candidates.jsonl shows top_k - 1 rows (top-1 is in seed.json).
        cands = tmp_path / "seed_candidates.jsonl"
        assert cands.exists()
        rows = [json.loads(line) for line in cands.read_text().splitlines() if line.strip()]
        assert len(rows) == 2
        for row in rows:
            assert "candidate" in row
            assert "crystallization_score" in row

    def test_rejects_empty_theme(self, tmp_path: Path) -> None:
        from pipeline.single_idea import generate_seed_via_evolve  # noqa: PLC0415

        with pytest.raises(ValueError, match="theme"):
            generate_seed_via_evolve(
                theme="   ,  ,  ",  # all whitespace
                problem="anything",
                run_dir=tmp_path,
            )

    def test_helper_imports(self) -> None:
        # Cheap import-only check so the suite catches accidental removal.
        from pipeline.single_idea import generate_seed_via_evolve  # noqa: PLC0415

        assert callable(generate_seed_via_evolve)
