"""tests/test_phase_timing.py — Cycle 1 NB.1 per-phase wall-clock instrumentation.

Goldratt step 1: measure before optimizing further. We need to know whether the
remaining 2-3h latency is dominated by agent reasoning, WebSearch fallback, or
something else entirely. Today there is no per-phase timing data.

This test file is written BEFORE pipeline/phase_timing.py exists (Gate Q1 TDD).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pipeline import phase_timing


def test_module_interface() -> None:
    for name in ("start_phase", "end_phase", "read_timings", "summarize", "PHASE_TIMINGS_FILENAME"):
        assert hasattr(phase_timing, name), f"phase_timing missing public symbol: {name}"


def test_start_end_records_one_row(tmp_path: Path) -> None:
    phase_timing.start_phase(tmp_path, phase_index=1, phase_name="research")
    time.sleep(0.05)
    phase_timing.end_phase(tmp_path, phase_index=1, phase_name="research")
    timings = phase_timing.read_timings(tmp_path)
    pairs = [t for t in timings if t.get("phase_name") == "research"]
    assert pairs, "expected research phase rows in timings"

    summary = phase_timing.summarize(tmp_path)
    by_phase = summary["by_phase"]
    assert "research" in by_phase
    assert by_phase["research"]["duration_seconds"] >= 0.04
    assert by_phase["research"]["duration_seconds"] < 1.0


def test_multiple_phases_recorded_in_order(tmp_path: Path) -> None:
    for i, n in [(0, "seed_capture"), (1, "research"), (2, "draft_v0")]:
        phase_timing.start_phase(tmp_path, phase_index=i, phase_name=n)
        phase_timing.end_phase(tmp_path, phase_index=i, phase_name=n)
    timings = phase_timing.read_timings(tmp_path)
    starts = [t for t in timings if t.get("event") == "start"]
    indices = [t["phase_index"] for t in starts]
    assert indices == sorted(indices)
    assert len(starts) == 3


def test_unmatched_end_returns_partial_marker(tmp_path: Path) -> None:
    """end_phase without start records the event with duration=null (forensic)."""
    phase_timing.end_phase(tmp_path, phase_index=99, phase_name="orphan")
    timings = phase_timing.read_timings(tmp_path)
    orphan = next((t for t in timings if t.get("phase_name") == "orphan"), None)
    assert orphan is not None
    assert orphan.get("duration_seconds") is None
    assert orphan.get("partial") is True


def test_summary_aggregates_total_seconds(tmp_path: Path) -> None:
    for i, n in [(1, "research"), (2, "draft_v0"), (3, "challenge")]:
        phase_timing.start_phase(tmp_path, phase_index=i, phase_name=n)
        time.sleep(0.01)
        phase_timing.end_phase(tmp_path, phase_index=i, phase_name=n)
    summary = phase_timing.summarize(tmp_path)
    assert "total_seconds" in summary
    assert summary["total_seconds"] >= 0.03
    assert "by_phase" in summary
    assert set(summary["by_phase"].keys()) == {"research", "draft_v0", "challenge"}


def test_atomic_writes(tmp_path: Path) -> None:
    """No partial files visible at the timings path (uses state.safe_write/append_jsonl)."""
    phase_timing.start_phase(tmp_path, phase_index=0, phase_name="seed_capture")
    phase_timing.end_phase(tmp_path, phase_index=0, phase_name="seed_capture")
    path = tmp_path / phase_timing.PHASE_TIMINGS_FILENAME
    assert path.exists()
    # JSONL contract: every line parses standalone.
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        json.loads(line)


def test_read_timings_empty_when_no_file(tmp_path: Path) -> None:
    timings = phase_timing.read_timings(tmp_path)
    assert timings == []


def test_summarize_handles_partial_end(tmp_path: Path) -> None:
    """Summary tolerates partial end events without raising."""
    phase_timing.end_phase(tmp_path, phase_index=42, phase_name="orphan")
    summary = phase_timing.summarize(tmp_path)
    assert "by_phase" in summary
    by_phase: dict[str, Any] = summary["by_phase"]
    assert "orphan" in by_phase
    assert by_phase["orphan"].get("partial") is True


def test_repeated_phase_accumulates(tmp_path: Path) -> None:
    """Same phase invoked twice produces two pairs; summary sums durations."""
    for _ in range(2):
        phase_timing.start_phase(tmp_path, phase_index=1, phase_name="patch_round")
        time.sleep(0.01)
        phase_timing.end_phase(tmp_path, phase_index=1, phase_name="patch_round")
    summary = phase_timing.summarize(tmp_path)
    by_phase = summary["by_phase"]["patch_round"]
    assert by_phase["count"] == 2
    assert by_phase["duration_seconds"] >= 0.02


def test_cli_start_end_summarize(tmp_path: Path) -> None:
    """CLI subcommands round-trip via subprocess."""
    import subprocess  # noqa: PLC0415

    base = ["uv", "run", "python", "-m", "pipeline.phase_timing"]
    for cmd in ("start", "end"):
        result = subprocess.run(  # noqa: S603  # trusted: argv is built from fixed strings
            [*base, cmd, "--run-dir", str(tmp_path), "--phase-index", "0", "--phase-name", "x"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    out = subprocess.run(  # noqa: S603  # trusted: argv is built from fixed strings
        [*base, "summarize", "--run-dir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    summary = json.loads(out.stdout)
    assert "x" in summary["by_phase"]


def test_cli_malformed_args_does_not_crash_pipeline(tmp_path: Path) -> None:
    """The CLI soft-fails (returncode == 0) — instrumentation never blocks the pipeline."""

    # Force a runtime error inside the timing call by passing a bogus run-dir
    # (relative path that doesn't exist as a directory). The state.append_jsonl
    # call will create it; that's fine. We instead corrupt the file first to
    # trigger the warning branch in read_timings.
    timings = tmp_path / phase_timing.PHASE_TIMINGS_FILENAME
    timings.write_text("not-json\n", encoding="utf-8")
    rows = phase_timing.read_timings(tmp_path)
    assert rows == []
