"""Tests for pipeline.cc_dispatch — Pure-CC Task fan-out shim (ADR-0007)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pipeline.cc_dispatch as ccd
import pipeline.quota as q


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect cc_dispatch and quota roots into per-test tmp dirs."""
    monkeypatch.setattr(ccd, "DISPATCH_ROOT", tmp_path / "dispatch")
    monkeypatch.setattr(ccd, "CHUNKS_ROOT", tmp_path / "chunks")
    monkeypatch.setattr(q, "QUOTA_LOG", tmp_path / "quota.jsonl")
    monkeypatch.chdir(tmp_path)  # so run_log.jsonl lands in tmp


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _read_manifest(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_plan_with_input_creates_one_row_per_slice(tmp_path: Path) -> None:
    inp = tmp_path / "01_assets.jsonl"
    _write_jsonl(inp, [{"asset_id": f"a{i}"} for i in range(10)])

    manifest = ccd.plan(
        phase="mapper",
        run_id="run1",
        input_path=inp,
        slice_size=4,
        model_tier="sonnet",
        prompt_template_path="prompts/02-jtbd-mapper.md",
        expected_tokens_per_slice=4000,
    )
    rows = _read_manifest(manifest)
    assert len(rows) == 3  # 10 / 4 = 3 (4, 4, 2)
    assert [r["slice_id"] for r in rows] == [0, 1, 2]
    assert len(rows[0]["input_slice"]) == 4
    assert len(rows[2]["input_slice"]) == 2
    assert all(r["status"] == "PENDING" for r in rows)
    assert all(r["model_tier"] == "sonnet" for r in rows)


def test_plan_empty_input_emits_zero_row(tmp_path: Path) -> None:
    inp = tmp_path / "empty.jsonl"
    inp.write_text("", encoding="utf-8")
    manifest = ccd.plan(
        phase="miner",
        run_id="run2",
        input_path=inp,
        slice_size=5,
        model_tier="sonnet",
        prompt_template_path="prompts/01-asset-miner.md",
        expected_tokens_per_slice=6000,
    )
    rows = _read_manifest(manifest)
    assert len(rows) == 1
    assert rows[0]["slice_id"] == 0
    assert rows[0]["input_slice"] == []


def test_plan_missing_input_treated_as_empty(tmp_path: Path) -> None:
    manifest = ccd.plan(
        phase="miner",
        run_id="run3",
        input_path=tmp_path / "nonexistent.jsonl",
        slice_size=10,
        model_tier="sonnet",
        prompt_template_path="prompts/01-asset-miner.md",
        expected_tokens_per_slice=6000,
    )
    rows = _read_manifest(manifest)
    assert len(rows) == 1
    assert rows[0]["input_slice"] == []


def test_plan_validates_slice_size() -> None:
    with pytest.raises(ValueError, match="slice_size"):
        ccd.plan(
            phase="miner",
            run_id="r",
            input_path="x.jsonl",
            slice_size=0,
            model_tier="sonnet",
            prompt_template_path="p.md",
            expected_tokens_per_slice=100,
        )


def test_plan_validates_expected_tokens() -> None:
    with pytest.raises(ValueError, match="expected_tokens"):
        ccd.plan(
            phase="miner",
            run_id="r",
            input_path="x.jsonl",
            slice_size=1,
            model_tier="sonnet",
            prompt_template_path="p.md",
            expected_tokens_per_slice=-1,
        )


def test_plan_overwrites_existing_manifest(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, [{"asset_id": "a1"}])
    ccd.plan(
        phase="mapper",
        run_id="r",
        input_path=inp,
        slice_size=1,
        model_tier="sonnet",
        prompt_template_path="p.md",
        expected_tokens_per_slice=100,
    )
    _write_jsonl(inp, [{"asset_id": "a1"}, {"asset_id": "a2"}])
    manifest = ccd.plan(
        phase="mapper",
        run_id="r",
        input_path=inp,
        slice_size=1,
        model_tier="sonnet",
        prompt_template_path="p.md",
        expected_tokens_per_slice=100,
    )
    rows = _read_manifest(manifest)
    assert len(rows) == 2  # second plan overwrote first


def test_merge_concatenates_chunks_and_dedupes_by_concept_id(tmp_path: Path) -> None:
    chunks = ccd.CHUNKS_ROOT / "run4" / "forger"
    chunks.mkdir(parents=True)
    _write_jsonl(
        chunks / "slice_0000.jsonl", [{"concept_id": "c1", "v": 1}, {"concept_id": "c2", "v": 2}]
    )
    _write_jsonl(
        chunks / "slice_0001.jsonl", [{"concept_id": "c2", "v": 99}, {"concept_id": "c3", "v": 3}]
    )
    target = tmp_path / "data" / "04_concepts.jsonl"

    n = ccd.merge(phase="forger", run_id="run4", target_path=target)
    assert n == 3
    written = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    ids = [r["concept_id"] for r in written]
    assert ids == ["c1", "c2", "c3"]
    assert next(r for r in written if r["concept_id"] == "c2")["v"] == 2  # first wins


def test_merge_no_chunks_writes_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "data" / "04_concepts.jsonl"
    n = ccd.merge(phase="forger", run_id="run5", target_path=target)
    assert n == 0
    assert target.exists()
    assert target.read_text() == ""


def test_merge_skips_corrupt_lines(tmp_path: Path) -> None:
    chunks = ccd.CHUNKS_ROOT / "run6" / "miner"
    chunks.mkdir(parents=True)
    (chunks / "slice_0000.jsonl").write_text(
        '{"asset_id": "a1"}\nnot-json\n{"asset_id": "a2"}\n', encoding="utf-8"
    )
    target = tmp_path / "01_assets.jsonl"
    n = ccd.merge(phase="miner", run_id="run6", target_path=target)
    assert n == 2  # corrupt line skipped


def test_record_task_completion_updates_manifest_status(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, [{"asset_id": "a1"}, {"asset_id": "a2"}])
    ccd.plan(
        phase="mapper",
        run_id="run7",
        input_path=inp,
        slice_size=1,
        model_tier="sonnet",
        prompt_template_path="p.md",
        expected_tokens_per_slice=100,
    )
    ccd.record_task_completion(
        phase="mapper",
        run_id="run7",
        slice_id=0,
        tokens_in=300,
        tokens_out=80,
        model_tier="sonnet",
    )
    manifest = ccd._manifest_path("mapper", "run7")
    rows = _read_manifest(manifest)
    slice0 = next(r for r in rows if r["slice_id"] == 0)
    slice1 = next(r for r in rows if r["slice_id"] == 1)
    assert slice0["status"] == "RETURNED"
    assert slice0["actual_tokens_in"] == 300
    assert slice1["status"] == "PENDING"  # unchanged


def test_record_task_completion_writes_quota_row() -> None:
    ccd.record_task_completion(
        phase="critic",
        run_id="run8",
        slice_id=0,
        tokens_in=12000,
        tokens_out=400,
        model_tier="opus",
    )
    assert q.consumed_this_week("opus") == 12400


def test_cost_estimate_telemetry_only() -> None:
    # Sonnet rate: $3 in, $15 out per 1M tokens.
    # 1M in + 1M out = $3 + $15 = $18.
    assert ccd.cost_estimate("sonnet", 1_000_000, 1_000_000) == pytest.approx(18.0)
    # Haiku: $0.25 in + $1.25 out per 1M = $1.50 per 1M+1M.
    assert ccd.cost_estimate("haiku", 1_000_000, 1_000_000) == pytest.approx(1.5)


def test_cost_estimate_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown model_tier"):
        ccd.cost_estimate("turbo", 100, 100)  # type: ignore[arg-type]


def test_cost_estimate_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ccd.cost_estimate("opus", -1, 100)


def test_manifest_summary_counts_statuses(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, [{"asset_id": f"a{i}"} for i in range(3)])
    ccd.plan(
        phase="mapper",
        run_id="run9",
        input_path=inp,
        slice_size=1,
        model_tier="sonnet",
        prompt_template_path="p.md",
        expected_tokens_per_slice=100,
    )
    summary = ccd.manifest_summary("mapper", "run9")
    assert summary["PENDING"] == 3
    assert summary["RETURNED"] == 0
    ccd.record_task_completion("mapper", "run9", 1, 100, 50, "sonnet")
    summary2 = ccd.manifest_summary("mapper", "run9")
    assert summary2["PENDING"] == 2
    assert summary2["RETURNED"] == 1


def test_manifest_summary_missing_returns_zeros() -> None:
    summary = ccd.manifest_summary("forger", "nonexistent")
    assert summary == {"PENDING": 0, "DISPATCHED": 0, "RETURNED": 0, "FAILED": 0}


def test_log_dispatch_event_appends_run_log(tmp_path: Path) -> None:
    ccd.log_dispatch_event(
        phase="forger",
        run_id="run10",
        event="phase_start",
        payload={"slices": 12},
    )
    log = tmp_path / "data" / "run_log.jsonl"
    assert log.exists()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert rows[-1]["event"] == "phase_start"
    assert rows[-1]["gateway"] == "cc"
    assert rows[-1]["slices"] == 12
