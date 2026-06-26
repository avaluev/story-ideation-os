"""Tests for pipeline.run_cc — Typer CLI for the Pure-CC dispatch shim.

Each test invokes the Typer app via typer.testing.CliRunner so we exercise
the full CLI surface without spawning subprocesses; environment isolation
follows the same pattern as test_cc_dispatch.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import pipeline.cc_dispatch as ccd
import pipeline.quota as q
from pipeline.run_cc import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect cc_dispatch + quota roots into per-test tmp dirs."""
    monkeypatch.setattr(ccd, "DISPATCH_ROOT", tmp_path / "dispatch")
    monkeypatch.setattr(ccd, "CHUNKS_ROOT", tmp_path / "chunks")
    monkeypatch.setattr(q, "QUOTA_LOG", tmp_path / "quota.jsonl")
    monkeypatch.chdir(tmp_path)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_plan_writes_manifest_and_prints_path(tmp_path: Path) -> None:
    inp = tmp_path / "01_assets.jsonl"
    _write_jsonl(inp, [{"asset_id": f"a{i}"} for i in range(6)])

    result = runner.invoke(
        app,
        [
            "plan",
            "--phase",
            "mapper",
            "--run-id",
            "r1",
            "--input-path",
            str(inp),
            "--slice-size",
            "3",
            "--model-tier",
            "sonnet",
            "--prompt-template-path",
            "prompts/02-jtbd-mapper.md",
            "--expected-tokens",
            "4000",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest_path = Path(result.output.strip())
    assert manifest_path.exists()
    rows = [json.loads(line) for line in manifest_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 2  # 6 / 3
    assert rows[0]["model_tier"] == "sonnet"
    assert rows[0]["expected_tokens"] == 4000


def test_plan_rejects_invalid_model_tier(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    inp.write_text("", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "plan",
            "--phase",
            "miner",
            "--run-id",
            "r2",
            "--input-path",
            str(inp),
            "--model-tier",
            "turbo",  # not a valid tier
        ],
    )
    assert result.exit_code == 2
    assert "invalid model_tier" in result.output


def test_plan_rejects_invalid_phase(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    inp.write_text("", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "plan",
            "--phase",
            "synthesizer",  # not a valid phase
            "--run-id",
            "r3",
            "--input-path",
            str(inp),
        ],
    )
    assert result.exit_code == 2
    assert "phase must be one of" in result.output


def test_merge_concatenates_chunks_and_prints_count(tmp_path: Path) -> None:
    chunks = ccd.CHUNKS_ROOT / "r4" / "forger"
    chunks.mkdir(parents=True)
    _write_jsonl(chunks / "slice_0000.jsonl", [{"concept_id": "c1"}])
    _write_jsonl(chunks / "slice_0001.jsonl", [{"concept_id": "c2"}, {"concept_id": "c3"}])
    target = tmp_path / "data" / "04_concepts.jsonl"

    result = runner.invoke(
        app,
        [
            "merge",
            "--phase",
            "forger",
            "--run-id",
            "r4",
            "--target-path",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "merged: 3" in result.output
    written = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    assert len(written) == 3


def test_status_emits_json_with_four_keys(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, [{"asset_id": "a1"}, {"asset_id": "a2"}])
    runner.invoke(
        app,
        [
            "plan",
            "--phase",
            "mapper",
            "--run-id",
            "r5",
            "--input-path",
            str(inp),
            "--slice-size",
            "1",
        ],
    )
    result = runner.invoke(
        app,
        ["status", "--phase", "mapper", "--run-id", "r5"],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.strip())
    assert set(summary.keys()) == {"PENDING", "DISPATCHED", "RETURNED", "FAILED"}
    assert summary["PENDING"] == 2


def test_record_marks_slice_returned_and_logs_quota(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, [{"asset_id": "a1"}, {"asset_id": "a2"}])
    runner.invoke(
        app,
        [
            "plan",
            "--phase",
            "mapper",
            "--run-id",
            "r6",
            "--input-path",
            str(inp),
            "--slice-size",
            "1",
        ],
    )
    result = runner.invoke(
        app,
        [
            "record",
            "--phase",
            "mapper",
            "--run-id",
            "r6",
            "--slice-id",
            "0",
            "--tokens-in",
            "500",
            "--tokens-out",
            "100",
            "--model-tier",
            "sonnet",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "recorded slice=0" in result.output
    assert q.consumed_this_week("sonnet") == 600


def test_record_rejects_invalid_tier(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "record",
            "--phase",
            "mapper",
            "--run-id",
            "r7",
            "--slice-id",
            "0",
            "--tokens-in",
            "1",
            "--tokens-out",
            "1",
            "--model-tier",
            "premium",
        ],
    )
    assert result.exit_code == 2


def test_quota_subcommand_prints_three_tiers() -> None:
    result = runner.invoke(app, ["quota"])
    assert result.exit_code == 0, result.output
    assert "opus" in result.output
    assert "sonnet" in result.output
    assert "haiku" in result.output


def test_full_plan_record_status_cycle(tmp_path: Path) -> None:
    """End-to-end: plan a 3-slice phase, record one slice, status reflects it."""
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, [{"asset_id": f"a{i}"} for i in range(3)])
    plan_res = runner.invoke(
        app,
        [
            "plan",
            "--phase",
            "miner",
            "--run-id",
            "r8",
            "--input-path",
            str(inp),
            "--slice-size",
            "1",
            "--model-tier",
            "sonnet",
        ],
    )
    assert plan_res.exit_code == 0
    record_res = runner.invoke(
        app,
        [
            "record",
            "--phase",
            "miner",
            "--run-id",
            "r8",
            "--slice-id",
            "1",
            "--tokens-in",
            "200",
            "--tokens-out",
            "60",
            "--model-tier",
            "sonnet",
        ],
    )
    assert record_res.exit_code == 0
    status_res = runner.invoke(
        app,
        ["status", "--phase", "miner", "--run-id", "r8"],
    )
    assert status_res.exit_code == 0
    summary = json.loads(status_res.output.strip())
    assert summary["PENDING"] == 2
    assert summary["RETURNED"] == 1
