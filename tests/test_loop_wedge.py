"""Tests for pipeline.loop_wedge -- autonomous /loop-engine iteration body.

WEDGE Step 6 of the plan. Pins five contracts:

  1. Quota gate refusal -> iteration aborts, records halted_reason
     "opus_quota_exhausted", returns the goal unchanged.
  2. Goal-met halt -> iteration records halted_reason "goal_met", run_many
     stops early.
  3. Plateau without ratings -> strategy "plateau:no_new_ratings",
     goal unchanged.
  4. Plateau WITH >= DEFAULT_RECALIBRATION_TRIGGER fresh ratings -> calls
     feedback.refit_weights and bumps the goal_id.
  5. --dry-run CLI prints the planned configuration without burning quota.

End-to-end ``/evolve`` integration is exercised via the ``_evolve_fn``
injection seam, not the real ``one_shot.explore_and_select`` -- that
wire lives in the ``/loop-engine`` slash command per the honest
deferral in pipeline.loop_wedge._real_evolve_run docstring.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from pipeline import labels, loop_wedge
from pipeline.goal import Goal


class _StubExplore:
    """Mimics enough of ExploreResult for _extract_top."""

    def __init__(self, run_id: str, score: float, som_y1: float) -> None:
        self.run_id = run_id

        class _Proj:
            def __init__(self, som: float) -> None:
                self.som_y1_usd = som

        class _Winner:
            def __init__(self, score: float, som: float) -> None:
                self.crystallization_score = score
                self.projection = _Proj(som)

        self.top_k = [_Winner(score, som_y1)]


def _evolve_fn_factory(score: float, som_y1: float = 0.0) -> Any:
    """Build an injectable evolve stub that returns a fixed top score/SOM."""

    def _fn(*, n_base: int, goal: Goal, runs_root: Path) -> object:
        return _StubExplore(run_id=f"evolve-stub-{score:.2f}", score=score, som_y1=som_y1)

    return _fn


def _allow_quota() -> Any:
    def _fn(model: str, expected_tokens: int, floor: float) -> bool:
        return True

    return _fn


def _refuse_quota() -> Any:
    def _fn(model: str, expected_tokens: int, floor: float) -> bool:
        return False

    return _fn


@pytest.fixture
def tmp_history(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "loop_history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class TestQuotaGate:
    def test_quota_refusal_aborts_iteration(self, tmp_history: Path) -> None:
        goal = Goal.default()
        new_goal, result = loop_wedge.run_iteration(
            goal,
            history_path=tmp_history,
            _evolve_fn=_evolve_fn_factory(0.5, 100_000_000),
            _quota_gate_fn=_refuse_quota(),
        )
        assert new_goal is goal  # unchanged
        assert result is None
        # An abort row is still persisted (truth source for /digest KPIs).
        lines = tmp_history.read_text().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["halted_reason"] == "opus_quota_exhausted"
        assert row["strategy"] == "abort:quota"


class TestGoalMetHalt:
    def test_iteration_records_goal_met(self, tmp_history: Path) -> None:
        goal = Goal.default()  # target_score=0.75, revenue_floor_usd=200M
        evolve = _evolve_fn_factory(score=0.9, som_y1=250_000_000)
        _, result = loop_wedge.run_iteration(
            goal,
            history_path=tmp_history,
            _evolve_fn=evolve,
            _quota_gate_fn=_allow_quota(),
        )
        assert result is not None
        assert result.halted_reason == "goal_met"
        assert result.strategy == "halt:goal_met"

    def test_run_many_stops_early_on_goal_met(self, tmp_history: Path) -> None:
        results = loop_wedge.run_many(
            iterations=10,
            goal=Goal.default(),
            history_path=tmp_history,
            _evolve_fn=_evolve_fn_factory(score=0.9, som_y1=300_000_000),
            _quota_gate_fn=_allow_quota(),
        )
        assert len(results) == 1
        assert results[0].halted_reason == "goal_met"

    def test_run_many_below_target_runs_all_iterations(self, tmp_history: Path) -> None:
        # Score below target_score -> never halts on goal_met.
        results = loop_wedge.run_many(
            iterations=4,
            goal=Goal.default(),
            history_path=tmp_history,
            _evolve_fn=_evolve_fn_factory(score=0.5, som_y1=10_000_000),
            _quota_gate_fn=_allow_quota(),
        )
        assert len(results) == 4
        for r in results:
            assert r.halted_reason is None


class TestPlateauHandling:
    def test_plateau_without_ratings_keeps_goal(
        self, tmp_history: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plateau triggers strategy 'plateau:no_new_ratings' when no
        labels.jsonl rows have accumulated since the goal's created_at."""
        labels_path = tmp_path / "labels.jsonl"
        monkeypatch.setattr(labels, "DEFAULT_LABELS_PATH", labels_path)
        # No labels written -> read_since returns [].

        goal = Goal.default()
        # Provide a flat score history so the very first iteration triggers
        # plateau (window=3 means need 4 entries; we seed 3 prior + 1 from
        # this iteration). Use run_many with iterations=4 + flat evolve_fn.
        results = loop_wedge.run_many(
            iterations=4,
            goal=goal,
            history_path=tmp_history,
            _evolve_fn=_evolve_fn_factory(score=0.5, som_y1=10_000_000),
            _quota_gate_fn=_allow_quota(),
        )
        # By the 4th iteration, plateau should be detected.
        assert any(r.strategy == "plateau:no_new_ratings" for r in results), (
            f"expected plateau:no_new_ratings, got strategies={[r.strategy for r in results]}"
        )

    def test_plateau_with_enough_ratings_refits_goal(
        self,
        tmp_history: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Plateau + 10+ fresh ratings -> goal_id bumps, strategy 'plateau:refit'."""
        labels_path = tmp_path / "labels.jsonl"
        goal_path = tmp_path / "goal.json"
        runs_root = tmp_path / "runs"
        monkeypatch.setattr(labels, "DEFAULT_LABELS_PATH", labels_path)

        # Seed 16 ratings AFTER the (yet-to-be-created) goal's created_at.
        # We'll create the goal first, then write ratings with ts strictly
        # after goal.created_at.
        goal = Goal.default()
        ts_after_goal = (datetime.fromisoformat(goal.created_at) + timedelta(seconds=1)).isoformat()
        for i in range(8):
            labels.append(
                run_id=f"r-pos-{i}",
                rating=2,
                path=labels_path,
                ts=ts_after_goal,
            )
            # Create a winners.json sidecar so feedback.read_winner_facets
            # has something to read.
            sidecar = runs_root / f"r-pos-{i}" / "evolve" / "gen0" / "winners.json"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text(
                json.dumps(
                    {
                        "winners": [
                            {
                                "derivative_distance": 0.7,
                                "scores": {
                                    "genius_score": 0.5,
                                    "goldilocks_score": 0.5,
                                    "cluster_coherence": 0.5,
                                    "emotional_universality_score": 2.5,
                                    "som_y1_usd": 180_000_000,
                                },
                            }
                        ]
                    }
                )
            )
        for i in range(8):
            labels.append(
                run_id=f"r-neg-{i}",
                rating=-2,
                path=labels_path,
                ts=ts_after_goal,
            )
            sidecar = runs_root / f"r-neg-{i}" / "evolve" / "gen0" / "winners.json"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text(
                json.dumps(
                    {
                        "winners": [
                            {
                                "derivative_distance": 0.7,
                                "scores": {
                                    "genius_score": 0.5,
                                    "goldilocks_score": 0.5,
                                    "cluster_coherence": 0.5,
                                    "emotional_universality_score": 2.5,
                                    "som_y1_usd": 10_000_000,
                                },
                            }
                        ]
                    }
                )
            )

        results = loop_wedge.run_many(
            iterations=4,
            goal=goal,
            history_path=tmp_history,
            goal_path=goal_path,
            runs_root=runs_root,
            _evolve_fn=_evolve_fn_factory(score=0.5, som_y1=10_000_000),
            _quota_gate_fn=_allow_quota(),
        )
        assert any(r.strategy == "plateau:refit" for r in results), (
            f"expected plateau:refit; got {[r.strategy for r in results]}"
        )
        # Goal should have been saved at least once.
        assert goal_path.exists()
        new_goal = Goal.load(goal_path)
        assert new_goal.goal_id != goal.goal_id


class TestDryRunCLI:
    def test_dry_run_does_not_burn_quota_and_prints_plan(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "pipeline.loop_wedge", "--iterations", "3", "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert "dry-run" in result.stdout
        assert "3 iterations" in result.stdout

    def test_iterations_cap_enforced(self, tmp_history: Path) -> None:
        # Request 999 iterations; cap at DEFAULT_MAX_ITERATIONS=100.
        # Evolve always returns score above target so we halt after 1.
        results = loop_wedge.run_many(
            iterations=999,
            goal=Goal.default(),
            history_path=tmp_history,
            _evolve_fn=_evolve_fn_factory(score=0.99, som_y1=500_000_000),
            _quota_gate_fn=_allow_quota(),
        )
        assert len(results) == 1  # halted on goal_met after 1 iter


class TestIterationResultNoveltySlot:
    """Schema slot for the embedding-novelty term (Step 4 of
    what-can-you-do-glowing-trinket.md). The field is part of the
    serialised row so digest.novelty_last_20 can populate the dashboard
    once the FAISS index lands."""

    def _kwargs(self) -> dict[str, object]:
        return {
            "ts": "2026-05-27T20:00:00+00:00",
            "run_id": "r1",
            "top_score": 0.72,
            "top_som_y1": 250_000_000.0,
            "goal_sha": "abc1234",
            "strategy": "climbing",
            "halted_reason": None,
        }

    def test_default_is_none(self) -> None:
        ir = loop_wedge.IterationResult(**self._kwargs())  # type: ignore[arg-type]
        assert ir.mean_novelty_last_20 is None

    def test_to_dict_includes_field(self) -> None:
        ir = loop_wedge.IterationResult(**self._kwargs())  # type: ignore[arg-type]
        d = ir.to_dict()
        assert "mean_novelty_last_20" in d
        assert d["mean_novelty_last_20"] is None

    def test_explicit_value_round_trips(self) -> None:
        kwargs = self._kwargs()
        kwargs["mean_novelty_last_20"] = 0.61
        ir = loop_wedge.IterationResult(**kwargs)  # type: ignore[arg-type]
        assert ir.mean_novelty_last_20 == 0.61
        assert ir.to_dict()["mean_novelty_last_20"] == 0.61

    def test_novelty_top_round_trips(self) -> None:
        kwargs = self._kwargs()
        kwargs["novelty_top"] = 0.42
        ir = loop_wedge.IterationResult(**kwargs)  # type: ignore[arg-type]
        assert ir.novelty_top == 0.42
        assert ir.to_dict()["novelty_top"] == 0.42


# ── _candidate_text_for_novelty (Task 11) ────────────────────────────────────


class _StubCandidate:
    """Minimal duck-typed stand-in for ScoredCandidate.candidate."""

    def __init__(
        self,
        world_texture: dict[str, str] | None = None,
        hidden_attrs: dict[str, str] | None = None,
        themes: list[str] | None = None,
        problems: list[str] | None = None,
    ) -> None:
        self.world_texture = world_texture
        self.hidden_attrs = hidden_attrs
        self.themes = themes
        self.problems = problems


class TestCandidateTextForNovelty:
    def test_all_fields_concatenated(self) -> None:
        text = loop_wedge._candidate_text_for_novelty(
            _StubCandidate(
                world_texture={"name": "a desert outpost", "id": "WT_99"},
                hidden_attrs={"moral_wager": "Truth is heavier than survival"},
                themes=["legibility", "agency"],
                problems=["the cost of being legible"],
            )
        )
        assert "a desert outpost" in text
        assert "Truth is heavier than survival" in text
        assert "legibility" in text
        assert "the cost of being legible" in text

    def test_empty_candidate_returns_empty_string(self) -> None:
        text = loop_wedge._candidate_text_for_novelty(_StubCandidate())
        assert text == ""

    def test_only_world_texture(self) -> None:
        text = loop_wedge._candidate_text_for_novelty(
            _StubCandidate(world_texture={"name": "alone"})
        )
        assert text == "alone"

    def test_skips_empty_strings(self) -> None:
        text = loop_wedge._candidate_text_for_novelty(
            _StubCandidate(
                world_texture={"name": "   "},  # whitespace-only
                hidden_attrs={"moral_wager": "real wager"},
            )
        )
        assert text == "real wager"


# ── _rolling_mean_novelty (Task 11) ──────────────────────────────────────────


class TestRollingMeanNovelty:
    def test_no_history_no_iter_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        assert loop_wedge._rolling_mean_novelty(None, p) is None

    def test_no_history_with_iter_returns_iter_value(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        result = loop_wedge._rolling_mean_novelty(0.55, p)
        assert result == pytest.approx(0.55)

    def test_history_with_iter_averages(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        rows = [
            {"ts": "t1", "novelty_top": 0.10},
            {"ts": "t2", "novelty_top": 0.20},
            {"ts": "t3", "novelty_top": 0.30},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        # Past = [0.1, 0.2, 0.3]; this iter = 0.4; mean = 0.25
        result = loop_wedge._rolling_mean_novelty(0.40, p)
        assert result == pytest.approx(0.25)

    def test_caps_at_window(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        # 25 past rows; with window=20 only the last 19 are kept (+ this iter).
        rows = [{"ts": f"t{i}", "novelty_top": float(i) / 100.0} for i in range(25)]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        result = loop_wedge._rolling_mean_novelty(0.0, p, window=20)
        # Kept: rows 6..24 (last 19) -> values 0.06..0.24, plus 0.0 this iter.
        expected = (sum(range(6, 25)) / 100.0 + 0.0) / 20
        assert result == pytest.approx(expected)

    def test_skips_rows_without_field(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        rows = [
            {"ts": "t1"},  # no novelty_top -> skip
            {"ts": "t2", "novelty_top": None},  # null -> skip
            {"ts": "t3", "novelty_top": 0.50},  # kept
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        # Only 0.50 is past; this iter = 0.30; mean = 0.40
        result = loop_wedge._rolling_mean_novelty(0.30, p)
        assert result == pytest.approx(0.40)

    def test_tolerates_corrupt_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        p.write_text('{"ts": "t1", "novelty_top": 0.5}\nnot json\n')
        result = loop_wedge._rolling_mean_novelty(None, p)
        assert result == pytest.approx(0.5)
