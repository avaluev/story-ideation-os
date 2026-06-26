"""Tests for pipeline.goal -- the operator's taste contract.

WEDGE Step 3 of the plan. Pins three contracts:

  1. Goal.load() falls back to v4 defaults when config/goal.json absent
     -- pipelines shipped before the operator creates a goal.json keep
     working unchanged (forward compatibility).
  2. Goal.save() bumps goal_id, appends to data/goal_history.jsonl,
     returns the bumped Goal. Round-trip load(save(g)).goal_id ==
     bumped_id.
  3. Goal.facet_weights inject into crystallization_score: editing the
     SOM weight from the v4 0.09 to 0.30 measurably changes the score
     for a candidate where SOM is the dominant factor. This is the
     entire point of Step 3 -- operator edits JSON -> top-K reshuffles.
"""

from __future__ import annotations

import json
from dataclasses import replace as _replace
from pathlib import Path

import pytest

from pipeline.crystallize.score import crystallization_score
from pipeline.goal import (
    DEFAULT_GOAL_HISTORY_PATH,
    DEFAULT_GOAL_PATH,
    Goal,
    VetoedAttractor,
)


@pytest.fixture
def tmp_goal_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Redirect Goal.load / Goal.save to a temp directory."""
    gp = tmp_path / "config" / "goal.json"
    hp = tmp_path / "data" / "goal_history.jsonl"
    gp.parent.mkdir(parents=True, exist_ok=True)
    hp.parent.mkdir(parents=True, exist_ok=True)
    return gp, hp


def _strong_v4_score() -> dict[str, float | bool]:
    """Score dict that is HIGH on the v4 heavy facets (genius / goldilocks /
    cluster_coherence / emo) but mid on SOM. Under v4 weights this beats
    a SOM-strong but v4-weak candidate; under SOM-heavy weights it loses."""
    return {
        "genius_score": 1.0,
        "goldilocks_score": 1.0,
        "cluster_coherence": 1.0,
        "emotional_universality_score": 5.0,  # = 1.0 after normalisation
        "som_y1_usd": 60_000_000,  # 0.3 after normalisation (200M floor)
        "passes_500m_gate": True,
        "passes_genius_gate": True,
    }


def _strong_som_score() -> dict[str, float | bool]:
    """Score dict that is HIGH on SOM but mid on v4 heavies. Inverse of
    _strong_v4_score -- under SOM-heavy weights it wins, under v4 weights
    it loses."""
    return {
        "genius_score": 0.6,
        "goldilocks_score": 0.6,
        "cluster_coherence": 0.6,
        "emotional_universality_score": 3.0,  # = 0.6 after normalisation
        "som_y1_usd": 200_000_000,  # = 1.0, exactly the normaliser saturation
        "passes_500m_gate": True,
        "passes_genius_gate": True,
    }


class TestGoalLoadSave:
    def test_load_missing_file_returns_default(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        g = Goal.load(missing)
        assert g.goal_id == "default_v4"
        # v4 weights mirror crystallize/score.py exactly.
        assert g.facet_weights["genius"] == pytest.approx(0.30)
        assert g.facet_weights["som_y1"] == pytest.approx(0.09)

    def test_load_real_config_file(self) -> None:
        """The shipped config/goal.json must parse with the new schema.

        Updated to investor_v2 (applied 2026-05-30 via the lineage-preserving
        `python -m pipeline.goal set` front door): som_y1 0.25->0.28,
        derivative_distance 0.12->0.16, genius 0.22->0.20, raised floors, and a
        175M SOM gate. The durable assertions are the lineage and the
        sum-to-1.0 invariant.
        """
        g = Goal.load(DEFAULT_GOAL_PATH)
        assert g.schema_version >= 1
        assert g.goal_id == "investor_v2"
        assert g.facet_weights["som_y1"] == pytest.approx(0.28)
        assert g.facet_weights["genius"] == pytest.approx(0.20)
        assert g.gates["som_y1_usd_min"] == 175_000_000
        # Sum to 1.0 (within tolerance).
        assert sum(g.facet_weights.values()) == pytest.approx(1.0)

    def test_save_bumps_goal_id_and_returns_bumped(self, tmp_goal_paths: tuple[Path, Path]) -> None:
        gp, hp = tmp_goal_paths
        original = Goal.default()
        bumped = original.save(path=gp, history_path=hp)
        assert bumped.goal_id != original.goal_id
        assert bumped.goal_id.endswith("_v2") or "_v" in bumped.goal_id
        # History row appended.
        assert hp.exists()
        history_rows = [json.loads(line) for line in hp.read_text().splitlines() if line.strip()]
        assert len(history_rows) == 1
        assert history_rows[0]["goal_id"] == bumped.goal_id
        assert history_rows[0]["sha"] == bumped.sha

    def test_round_trip_load_save_load(self, tmp_goal_paths: tuple[Path, Path]) -> None:
        gp, hp = tmp_goal_paths
        original = Goal.default()
        saved = original.save(path=gp, history_path=hp)
        reloaded = Goal.load(gp)
        assert reloaded.goal_id == saved.goal_id
        assert reloaded.facet_weights == saved.facet_weights
        assert reloaded.sha == saved.sha

    def test_load_normalises_weights_that_dont_sum_to_one(self, tmp_path: Path) -> None:
        """Forward-compat: if a Step-5-era goal.json adds operator_alignment
        and the human wrote weights that sum to ~1.05, we re-normalise rather
        than reject."""
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "goal_id": "experimental",
                    "facet_weights": {
                        "genius": 0.30,
                        "goldilocks": 0.20,
                        "cluster_coherence": 0.20,
                        "emotional_universality": 0.20,
                        "som_y1": 0.30,
                        "derivative_distance": 0.30,
                    },
                }
            )
        )
        g = Goal.load(bad)
        assert sum(g.facet_weights.values()) == pytest.approx(1.0)
        # Original ratio between genius and som_y1 (30:30) preserved.
        assert g.facet_weights["genius"] == pytest.approx(g.facet_weights["som_y1"])

    def test_load_rejects_negative_weights(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"goal_id": "broken", "facet_weights": {"genius": -0.5, "som_y1": 1.5}})
        )
        with pytest.raises(ValueError, match="negative"):
            Goal.load(bad)

    def test_vetoed_attractors_round_trip(self, tmp_goal_paths: tuple[Path, Path]) -> None:
        gp, hp = tmp_goal_paths

        g = _replace(
            Goal.default(),
            vetoed_attractors=(
                VetoedAttractor(
                    mf_id="MF_03", de_id="DE_06", sdt_id="SW_07", reason="Fifty Shades"
                ),
            ),
        )
        saved = g.save(path=gp, history_path=hp)
        reloaded = Goal.load(gp)
        assert len(reloaded.vetoed_attractors) == 1
        assert reloaded.vetoed_attractors[0].reason == "Fifty Shades"
        assert reloaded.vetoed_attractors[0].mf_id == "MF_03"
        assert reloaded.sha == saved.sha

    def test_sha_is_stable(self) -> None:
        """Same goal -> same sha (used as winners.json provenance)."""
        a = Goal.default()
        b = Goal.default()
        assert a.sha == b.sha

    def test_sha_changes_on_weight_change(self) -> None:

        a = Goal.default()
        b = _replace(a, facet_weights={**a.facet_weights, "som_y1": 0.25})
        assert a.sha != b.sha

    def test_with_overrides_returns_copy(self) -> None:
        a = Goal.default()
        b = a.with_overrides(target_score=0.95)
        assert a.target_score != 0.95
        assert b.target_score == 0.95
        # goal_id preserved -- the runtime override doesn't bump version.
        assert b.goal_id == a.goal_id


class TestGoalInjectsIntoCrystallizationScore:
    """The single regression that proves Step 3 actually steers scoring."""

    def test_no_goal_uses_v4_weights(self) -> None:
        """When goal is None, behaviour is byte-identical to pre-Step-3."""
        scores = _strong_som_score()
        result = crystallization_score(scores, derivative_distance=0.5)
        assert 0.0 <= result <= 1.0
        # Same call with default Goal should produce the same value
        # (default goal mirrors the v4 weights).
        default_goal = Goal.default()
        result_default = crystallization_score(scores, derivative_distance=0.5, goal=default_goal)
        assert result == pytest.approx(result_default)

    def test_som_heavy_goal_reshuffles_ranking(self) -> None:
        """The whole point of Step 3: editing the SOM weight reshuffles the
        ranking. Candidate A is strong on v4-heavy facets but mid-SOM;
        candidate B is mid on v4 heavies but saturated SOM. Under v4
        weights A wins. Under SOM-heavy weights B wins."""
        a_v4_strong = _strong_v4_score()
        b_som_strong = _strong_som_score()

        v4_goal = Goal.default()
        v4_a = crystallization_score(a_v4_strong, derivative_distance=1.0, goal=v4_goal)
        v4_b = crystallization_score(b_som_strong, derivative_distance=1.0, goal=v4_goal)
        assert v4_a > v4_b, (
            f"v4 weights should favour A (heavies-strong) over B (som-strong): "
            f"a={v4_a:.3f} b={v4_b:.3f}"
        )

        # SOM-heavy: SOM = 0.40, every other facet = 0.10 (sum to 1.0).
        som_heavy = _replace(
            v4_goal,
            facet_weights={
                "genius": 0.10,
                "goldilocks": 0.10,
                "cluster_coherence": 0.10,
                "emotional_universality": 0.10,
                "som_y1": 0.40,
                "derivative_distance": 0.20,
            },
        )
        s_a = crystallization_score(a_v4_strong, derivative_distance=1.0, goal=som_heavy)
        s_b = crystallization_score(b_som_strong, derivative_distance=1.0, goal=som_heavy)
        assert s_b > s_a, f"SOM-heavy goal failed to reshuffle: a={s_a:.3f} b={s_b:.3f}"

    def test_missing_facet_in_goal_falls_back_to_v4(self) -> None:
        """If a goal.json only sets one weight (e.g. operator hand-edits to
        bump SOM and forgets the others), the missing facets fall back to
        the v4 hardcoded values rather than zeroing out."""

        partial = _replace(Goal.default(), facet_weights={"som_y1": 0.25})
        result = crystallization_score(_strong_som_score(), derivative_distance=1.0, goal=partial)
        # Should not crash, not produce 0.0 (other facets still apply via v4 fallback).
        assert result > 0.0


def test_zero_sum_facet_weights_raises_valueerror(tmp_path: Path) -> None:
    """A goal.json whose facet_weights sum to zero raises a clear ValueError
    (regression: previously a ZeroDivisionError during auto-normalisation)."""
    gp = tmp_path / "goal.json"
    gp.write_text(
        json.dumps({"goal_id": "degenerate", "facet_weights": {"genius": 0.0, "som_y1": 0.0}})
    )
    with pytest.raises(ValueError, match="must be positive"):
        Goal.load(gp)


__all__ = ["DEFAULT_GOAL_HISTORY_PATH"]
