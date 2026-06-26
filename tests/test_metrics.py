"""Unit tests for pipeline/metrics.py — pure-Python metrics scaffold (Workstream D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.metrics import (
    compute_run_metrics,
    emit_metrics,
    regenerate_progression_md,
)


@pytest.fixture
def tmp_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp working directory with the data/, out/ structure metrics expects."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "metrics").mkdir()
    (tmp_path / "out" / "concepts").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    return tmp_path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_compute_run_metrics_empty_returns_zero_volumes(tmp_workdir: Path) -> None:
    """No phase outputs at all → all counts are 0, no crash."""
    snap = compute_run_metrics(run_id="abc", theme="X", model="sonnet")

    assert snap["asset_count"] == 0
    assert snap["concept_count"] == 0
    assert snap["concept_published_count"] == 0
    assert snap["concept_final_score_p50"] == 0
    assert snap["concept_final_score_max"] == 0
    assert snap["asset_domain_distribution"] == {}
    assert snap["stabilization_patterns_queued"] == 0


def test_compute_run_metrics_counts_phase_outputs(tmp_workdir: Path) -> None:
    """Counts assets, JTBD, audience, concepts, critiques from existing JSONLs."""

    _write_jsonl(
        tmp_workdir / "data" / "01_assets.jsonl",
        [
            {"asset_id": "A-x-001"},
            {"asset_id": "A-x-002"},
            {"asset_id": "B-y-001"},
            {"asset_id": "C-z-001"},
        ],
    )
    _write_jsonl(
        tmp_workdir / "data" / "02_jtbd.jsonl",
        [{"asset_id": f"X-{i:03d}"} for i in range(3)],
    )
    snap = compute_run_metrics(run_id="r1", theme="t", model="m")

    assert snap["asset_count"] == 4
    assert snap["jtbd_count"] == 3
    assert snap["asset_domain_distribution"] == {"A": 2, "B": 1, "C": 1}
    assert snap["asset_domain_count"] == 3


def test_compute_run_metrics_extracts_final_scores(tmp_workdir: Path) -> None:
    """Final scores come from overall_score.final in critic rows."""

    _write_jsonl(
        tmp_workdir / "data" / "05_critiques.jsonl",
        [
            {"concept_id": "a", "overall_score": {"final": 50}},
            {"concept_id": "b", "overall_score": {"final": 70}},
            {"concept_id": "c", "overall_score": {"final": 90}},
        ],
    )
    snap = compute_run_metrics(run_id="r1", theme="t", model="m")

    assert snap["critique_count"] == 3
    assert snap["concept_final_score_p50"] == 70
    assert snap["concept_final_score_max"] == 90
    assert snap["concept_final_score_mean"] == 70.0
    assert snap["concepts_passing_85_pure_critic_count"] == 1


def test_compute_run_metrics_counts_published(tmp_workdir: Path) -> None:
    """concept_published_count counts *.md files in out/concepts/."""

    (tmp_workdir / "out" / "concepts" / "a.md").write_text("x")
    (tmp_workdir / "out" / "concepts" / "b.md").write_text("x")
    (tmp_workdir / "out" / "concepts" / "c.md").write_text("x")
    snap = compute_run_metrics(run_id="r1", theme="t", model="m")

    assert snap["concept_published_count"] == 3


def test_compute_run_metrics_filters_run_log_by_session(tmp_workdir: Path) -> None:
    """Wall time + key rotations + stab queued are scoped to the given session_id."""

    log = tmp_workdir / "data" / "run_log.jsonl"
    _write_jsonl(
        log,
        [
            {
                "event": "START",
                "phase": "miner",
                "ts": "2026-01-01T00:00:00+00:00",
                "session_id": "sX",
            },
            {
                "event": "DONE",
                "phase": "miner",
                "ts": "2026-01-01T00:00:30+00:00",
                "session_id": "sX",
            },
            {"event": "STABILIZATION_QUEUED", "phase": "critic", "session_id": "sX"},
            {
                "event": "STABILIZATION_QUEUED",
                "phase": "critic",
                "session_id": "sY",
            },  # different session
            {"event": "BUDGET_EXCEEDED", "phase": "mapper", "session_id": "sX"},
        ],
    )
    snap = compute_run_metrics(run_id="sX", theme="t", model="m")

    assert snap["wall_time_per_phase_s"]["miner"] == 30.0
    assert snap["stabilization_patterns_queued"] == 1
    assert snap["key_rotation_count"] == 1


def test_emit_metrics_writes_snapshot_and_appends_timeline(tmp_workdir: Path) -> None:
    """emit_metrics() writes a per-run JSON file and appends to the timeline JSONL."""

    snap = compute_run_metrics(run_id="r1", theme="t", model="m")
    emit_metrics(snap)

    snapshot_path = tmp_workdir / "data" / "metrics" / "r1.json"
    timeline = tmp_workdir / "data" / "metrics" / "timeline.jsonl"
    assert snapshot_path.exists()
    assert timeline.exists()
    assert json.loads(snapshot_path.read_text())["run_id"] == "r1"
    assert json.loads(timeline.read_text().strip().splitlines()[0])["run_id"] == "r1"


def test_emit_metrics_appends_multiple_runs_to_same_timeline(tmp_workdir: Path) -> None:
    """Two emit_metrics calls append two rows to timeline.jsonl."""

    emit_metrics(compute_run_metrics(run_id="r1", theme="t", model="m"))
    emit_metrics(compute_run_metrics(run_id="r2", theme="t", model="m"))

    timeline = tmp_workdir / "data" / "metrics" / "timeline.jsonl"
    rows = [json.loads(ln) for ln in timeline.read_text().splitlines() if ln.strip()]
    assert [r["run_id"] for r in rows] == ["r1", "r2"]


def test_regenerate_progression_md_no_runs(tmp_workdir: Path) -> None:
    """No timeline → progression report still generates with 0-runs message."""

    md = regenerate_progression_md()
    progression = tmp_workdir / "docs" / "PROGRESSION.md"
    assert progression.exists()
    assert "Total runs: **0**" in md
    assert "No runs recorded yet" in md


def test_regenerate_progression_md_with_runs_and_delta(tmp_workdir: Path) -> None:
    """Two runs in timeline → progression shows table + delta block."""

    emit_metrics(compute_run_metrics(run_id="r1", theme="t1", model="m"))
    emit_metrics(compute_run_metrics(run_id="r2", theme="t2", model="m"))

    md = regenerate_progression_md()
    assert "Total runs: **2**" in md
    assert "Last 10 Runs" in md
    assert "Delta vs Previous Run" in md
    assert "r1" not in md  # row IDs not shown; theme is shown
    assert "t2" in md
