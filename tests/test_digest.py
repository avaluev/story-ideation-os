"""Tests for pipeline.digest -- 5-KPI dashboard.

WEDGE Step 8 of the plan (final move). Pins five contracts:

  1. throughput_last_week counts only rated-positive rows inside the 7d window.
  2. diversity_floor returns max single (axis, value_id) frequency over
     the last N runs.
  3. goal_bumps_last_week counts goal_history.jsonl rows within the
     cutoff.
  4. taste_convergence returns None when fewer than 3 paired
     (rating, score) samples can be assembled.
  5. collect_kpis + render produce a single non-empty terminal block
     end-to-end against a tmp data dir.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline import digest, labels


@pytest.fixture
def tmp_labels_path(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "labels.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def tmp_freq_path(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "axis_frequency.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def tmp_goal_history(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "goal_history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class TestThroughput:
    def test_counts_positive_ratings_in_window(self, tmp_labels_path: Path) -> None:
        now = datetime(2026, 5, 27, tzinfo=UTC)
        # 3 inside the 7d window, 2 outside.
        ts_inside = (now - timedelta(days=3)).isoformat()
        ts_outside = (now - timedelta(days=14)).isoformat()
        labels.append("a", 2, path=tmp_labels_path, ts=ts_inside)
        labels.append("b", 1, path=tmp_labels_path, ts=ts_inside)
        labels.append("c", -1, path=tmp_labels_path, ts=ts_inside)  # negative -> not counted
        labels.append("d", 2, path=tmp_labels_path, ts=ts_inside)
        labels.append("e", 2, path=tmp_labels_path, ts=ts_outside)
        labels.append("f", 1, path=tmp_labels_path, ts=ts_outside)

        assert digest.throughput_last_week(tmp_labels_path, now=now) == 3

    def test_empty_log_returns_zero(self, tmp_path: Path) -> None:
        assert digest.throughput_last_week(tmp_path / "nope.jsonl") == 0


class TestDiversityFloor:
    def test_max_axis_value_freq_over_window(self, tmp_freq_path: Path) -> None:
        # 3 runs; world_texture WT_X dominates (4 of 6 events = 0.667).
        rows = [
            {"run_id": "r1", "axis": "world_texture", "value_id": "WT_X"},
            {"run_id": "r1", "axis": "sdt_wound", "value_id": "SW_01"},
            {"run_id": "r2", "axis": "world_texture", "value_id": "WT_X"},
            {"run_id": "r2", "axis": "sdt_wound", "value_id": "SW_02"},
            {"run_id": "r3", "axis": "world_texture", "value_id": "WT_X"},
            {"run_id": "r3", "axis": "world_texture", "value_id": "WT_X"},
        ]
        tmp_freq_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        result = digest.diversity_floor(tmp_freq_path, window_runs=20)
        assert result == pytest.approx(4 / 6)

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert digest.diversity_floor(tmp_path / "nope.jsonl") is None

    def test_window_trims_old_runs(self, tmp_freq_path: Path) -> None:
        # 5 runs; window=2 should keep only the last 2 -> WT_X = 1/2 = 0.5
        rows = [
            {"run_id": "r1", "axis": "world_texture", "value_id": "WT_X"},
            {"run_id": "r2", "axis": "world_texture", "value_id": "WT_X"},
            {"run_id": "r3", "axis": "world_texture", "value_id": "WT_X"},
            {"run_id": "r4", "axis": "sdt_wound", "value_id": "SW_01"},
            {"run_id": "r5", "axis": "world_texture", "value_id": "WT_X"},
        ]
        tmp_freq_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        result = digest.diversity_floor(tmp_freq_path, window_runs=2)
        # r4+r5: 1 sdt + 1 world = max 0.5
        assert result == pytest.approx(0.5)


class TestGoalBumps:
    def test_counts_recent_saves(self, tmp_goal_history: Path) -> None:
        now = datetime(2026, 5, 27, tzinfo=UTC)
        rows = [
            {"ts": (now - timedelta(days=1)).isoformat(), "goal_id": "v1"},
            {"ts": (now - timedelta(days=3)).isoformat(), "goal_id": "v2"},
            {"ts": (now - timedelta(days=14)).isoformat(), "goal_id": "v0"},
        ]
        tmp_goal_history.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        assert digest.goal_bumps_last_week(tmp_goal_history, now=now) == 2

    def test_missing_file_returns_zero(self, tmp_path: Path) -> None:
        assert digest.goal_bumps_last_week(tmp_path / "nope.jsonl") == 0


class TestTasteConvergence:
    def test_returns_none_when_no_winners_sidecars(
        self, tmp_labels_path: Path, tmp_path: Path
    ) -> None:
        # Ratings exist but no winners.json sidecars in runs_root.
        for i in range(5):
            labels.append(f"r{i}", 2, path=tmp_labels_path)
        result = digest.taste_convergence(tmp_labels_path, runs_root=tmp_path / "runs")
        assert result is None

    def test_positive_correlation_when_score_tracks_rating(
        self, tmp_labels_path: Path, tmp_path: Path
    ) -> None:
        runs_root = tmp_path / "runs"
        # 5 rows: high rating <-> high facet values (perfect positive Spearman).
        for i, (rating, base) in enumerate([(2, 0.9), (2, 0.85), (1, 0.7), (-1, 0.3), (-1, 0.15)]):
            rid = f"r{i}"
            labels.append(rid, rating, path=tmp_labels_path)
            sidecar = runs_root / rid / "evolve" / "gen0" / "winners.json"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text(
                json.dumps(
                    {
                        "winners": [
                            {
                                "derivative_distance": base,
                                "scores": {
                                    "genius_score": base,
                                    "goldilocks_score": base,
                                    "cluster_coherence": base,
                                    "emotional_universality_score": base * 5,
                                    "som_y1_usd": base * 200_000_000,
                                },
                            }
                        ]
                    }
                )
            )
        result = digest.taste_convergence(tmp_labels_path, runs_root=runs_root)
        assert result is not None
        assert result > 0.9  # near-perfect rank agreement


class TestNoveltyLast20:
    def test_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        assert digest.novelty_last_20(tmp_path / "nope.jsonl") is None

    def test_returns_none_when_no_row_has_field(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        rows = [
            {"ts": "2026-05-27T10:00:00+00:00", "run_id": "r1", "top_score": 0.8},
            {"ts": "2026-05-27T11:00:00+00:00", "run_id": "r2", "top_score": 0.85},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        assert digest.novelty_last_20(p) is None

    def test_returns_latest_value_when_present(self, tmp_path: Path) -> None:
        p = tmp_path / "loop_history.jsonl"
        rows = [
            {"ts": "2026-05-27T10:00:00+00:00", "run_id": "r1", "mean_novelty_last_20": 0.42},
            {"ts": "2026-05-27T11:00:00+00:00", "run_id": "r2", "mean_novelty_last_20": 0.58},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        assert digest.novelty_last_20(p) == 0.58

    def test_tolerates_null_field(self, tmp_path: Path) -> None:
        """The Step-4 schema slot writes mean_novelty_last_20: null until
        the FAISS index lands. The reader must treat null as "no signal"."""
        p = tmp_path / "loop_history.jsonl"
        rows = [
            {"ts": "2026-05-27T10:00:00+00:00", "run_id": "r1", "mean_novelty_last_20": None},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        assert digest.novelty_last_20(p) is None


class TestCollectAndRender:
    def test_collect_kpis_returns_all_six(
        self,
        tmp_labels_path: Path,
        tmp_freq_path: Path,
        tmp_goal_history: Path,
        tmp_path: Path,
    ) -> None:
        # Touch nothing -- just verify the dashboard works against an empty
        # data dir without crashing.
        kpis = digest.collect_kpis(
            labels_path=tmp_labels_path,
            freq_path=tmp_freq_path,
            history_path=tmp_goal_history,
            loop_history_path=tmp_path / "loop_history.jsonl",
            runs_root=tmp_path / "runs",
        )
        assert len(kpis) == 6
        names = {k.name for k in kpis}
        assert names == {
            "loop_throughput",
            "taste_convergence",
            "diversity_floor",
            "subscription_burn",
            "novelty_last_20",
            "goal_stability",
        }
        # Every KPI has a non-empty value + target.
        for k in kpis:
            assert k.value
            assert k.target
            assert k.status in {"ok", "warn", "alert"}

    def test_render_produces_ascii_table(self) -> None:
        kpis = [
            digest.KPI("loop_throughput", "0 rated >=+1", ">= 3/week", "warn"),
            digest.KPI("taste_convergence", "(none)", ">= 0.5", "warn"),
            digest.KPI("diversity_floor", "9.0%", "<= 15%", "ok"),
            digest.KPI("subscription_burn", "12.0%", "< 70%", "ok"),
            digest.KPI("novelty_last_20", "(pending)", ">= 0.55", "warn"),
            digest.KPI("goal_stability", "1 bumps in last 7d", "1-2 per week", "ok"),
        ]
        out = digest.render(kpis)
        assert "Big Idea Generator" in out
        for k in kpis:
            assert k.name in out
            assert k.value in out
        # All lines have the same width (sanity check that the box renders).
        lines = [line for line in out.splitlines() if line.startswith("|") or line.startswith("+")]
        widths = {len(line) for line in lines}
        assert len(widths) == 1, f"render produced unequal line widths: {widths}"
