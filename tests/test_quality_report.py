"""tests/test_quality_report.py — S4.2 NB-Q-REPORT contract.

The :mod:`pipeline.quality_report` CLI renders a human-facing dashboard
combining the 5-vector quality pass (from ``quality.json``) and per-phase
wall-clock timings (from ``phase_timings.jsonl``) for a single ``runs/{id}``
directory.

Cycle-1 minimum (per Session 4 prompt §STREAM B / S4.2):

- public ``render_report(run_dir) -> str`` function
- CLI entry point ``uv run python -m pipeline.quality_report --run-dir runs/{id}``
- gracefully degrades when any of the four sidecars is absent
  (``phase_timings.jsonl``, ``quality.json``, ``eval.json``,
  ``amplification.json``)
- detects the hot-path phase (max wall-clock) and marks it explicitly
- exits 0 on a valid run directory; never blocks the pipeline
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pipeline import quality_report

# ── Fixtures ────────────────────────────────────────────────────────────────


def _write_timings(run_dir: Path, events: list[dict[str, Any]]) -> None:
    (run_dir / "phase_timings.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def full_run_dir(tmp_path: Path) -> Path:
    """Run dir with all four sidecars populated and a clear hot-path phase."""
    run_dir = tmp_path
    events: list[dict[str, Any]] = [
        {
            "phase_index": 0,
            "phase_name": "seed_capture",
            "event": "start",
            "ts_iso": "2026-05-19T10:00:00+00:00",
        },
        {
            "phase_index": 0,
            "phase_name": "seed_capture",
            "event": "end",
            "ts_iso": "2026-05-19T10:00:12+00:00",
            "duration_seconds": 12.3,
        },
        {
            "phase_index": 1,
            "phase_name": "research",
            "event": "start",
            "ts_iso": "2026-05-19T10:00:13+00:00",
        },
        {
            "phase_index": 1,
            "phase_name": "research",
            "event": "end",
            "ts_iso": "2026-05-19T10:13:46+00:00",
            "duration_seconds": 812.4,
        },
        {
            "phase_index": 2,
            "phase_name": "draft_v0",
            "event": "start",
            "ts_iso": "2026-05-19T10:14:00+00:00",
        },
        {
            "phase_index": 2,
            "phase_name": "draft_v0",
            "event": "end",
            "ts_iso": "2026-05-19T10:16:45+00:00",
            "duration_seconds": 165.2,
        },
    ]
    _write_timings(run_dir, events)
    (run_dir / "quality.json").write_text(
        json.dumps(
            {
                "axis_scores": {"character_depth": 0.83},
                "axis_pass": {"character_depth": True},
                "vector_pass": {
                    "Q1": None,
                    "Q2": True,
                    "Q3": None,
                    "Q4": None,
                    "Q5": None,
                },
                "overall_pass": True,
                "fired_rules": [],
                "evidence": {
                    "character_depth": {
                        "signals": [],
                        "n_fired": 8,
                        "n_total": 10,
                    }
                },
                "produced_at": "2026-05-19T16:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "eval.json").write_text(
        json.dumps({"publish": True, "score_summary": {}}),
        encoding="utf-8",
    )
    (run_dir / "amplification.json").write_text(
        json.dumps({"som_history": [1.0, 1.5, 1.7], "iterations": 3}),
        encoding="utf-8",
    )
    return run_dir


@pytest.fixture
def failing_run_dir(tmp_path: Path) -> Path:
    """Run dir where the concept failed Q2."""
    (tmp_path / "quality.json").write_text(
        json.dumps(
            {
                "axis_scores": {"character_depth": 0.3},
                "axis_pass": {"character_depth": False},
                "vector_pass": {
                    "Q1": None,
                    "Q2": False,
                    "Q3": None,
                    "Q4": None,
                    "Q5": None,
                },
                "overall_pass": False,
                "fired_rules": [],
                "evidence": {
                    "character_depth": {
                        "signals": [],
                        "n_fired": 3,
                        "n_total": 10,
                    }
                },
                "produced_at": "2026-05-19T16:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


# ── Module surface ──────────────────────────────────────────────────────────


def test_module_interface() -> None:
    """Module exposes render_report and a CLI entry."""
    assert callable(quality_report.render_report)
    # The module must be runnable as a script.
    assert hasattr(quality_report, "_main")


# ── Behaviour ───────────────────────────────────────────────────────────────


def test_render_with_all_sidecars_present(full_run_dir: Path) -> None:
    out = quality_report.render_report(full_run_dir)
    assert isinstance(out, str)
    assert "Q2: PASS" in out
    assert "OVERALL: PASS" in out
    assert "research" in out
    assert "hot path" in out
    assert "ELIGIBLE FOR PUBLISH: yes" in out
    # Total = 12.3 + 812.4 + 165.2 = 989.9 seconds ≈ 16.5 min.
    assert "990" in out or "989" in out  # rounded total seconds appears
    assert "min" in out


def test_render_degrades_gracefully_when_sidecar_missing(tmp_path: Path) -> None:
    """Empty run dir — no sidecars — must not raise and must produce structure."""
    out = quality_report.render_report(tmp_path)
    assert isinstance(out, str)
    assert "5-VECTOR PASS" in out
    assert "PHASE TIMINGS" in out
    assert "no phase timings recorded" in out.lower()
    assert "n/a" in out  # publish status when quality unknown


def test_render_marks_failing_concept_not_publishable(
    failing_run_dir: Path,
) -> None:
    out = quality_report.render_report(failing_run_dir)
    assert "Q2: FAIL" in out
    assert "OVERALL: FAIL" in out
    assert "ELIGIBLE FOR PUBLISH: no" in out


def test_hot_path_detection_marks_max_duration_phase(full_run_dir: Path) -> None:
    """The phase with the highest duration_seconds is annotated as the hot path."""
    out = quality_report.render_report(full_run_dir)
    hot_lines = [line for line in out.splitlines() if "hot path" in line]
    assert len(hot_lines) == 1, f"expected exactly one hot-path line, got: {hot_lines!r}"
    assert "research" in hot_lines[0], (
        f"research is the longest phase; hot-path line was {hot_lines[0]!r}"
    )


def test_cli_exit_zero_on_success(full_run_dir: Path) -> None:
    """``python -m pipeline.quality_report --run-dir <id>`` exits 0."""
    result = subprocess.run(  # noqa: S603 — invoking our own CLI with controlled args
        [
            sys.executable,
            "-m",
            "pipeline.quality_report",
            "--run-dir",
            str(full_run_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"CLI returned {result.returncode}; stderr: {result.stderr!r}"
    assert "Q2:" in result.stdout


def test_unmeasured_q_vectors_show_unmeasured(full_run_dir: Path) -> None:
    """Q1/Q3/Q4/Q5 (no axes wired in Cycle 1) show 'unmeasured', not FAIL."""
    out = quality_report.render_report(full_run_dir)
    for q in ("Q1", "Q3", "Q4", "Q5"):
        assert f"{q}: unmeasured" in out, (
            f"{q} should render as 'unmeasured' when not measured; output: {out!r}"
        )


def test_render_with_only_timings_no_quality(tmp_path: Path) -> None:
    """Timings present but no quality.json — vectors all show 'not measured'."""
    events: list[dict[str, Any]] = [
        {
            "phase_index": 1,
            "phase_name": "research",
            "event": "start",
            "ts_iso": "2026-05-19T10:00:00+00:00",
        },
        {
            "phase_index": 1,
            "phase_name": "research",
            "event": "end",
            "ts_iso": "2026-05-19T10:05:00+00:00",
            "duration_seconds": 300.0,
        },
    ]
    _write_timings(tmp_path, events)
    out = quality_report.render_report(tmp_path)
    assert "research" in out
    assert "Q2:" in out  # vector row still rendered
    assert "n/a" in out  # publish unknown


def test_render_with_only_quality_no_timings(tmp_path: Path) -> None:
    """quality.json present but no phase_timings.jsonl — still renders cleanly."""
    (tmp_path / "quality.json").write_text(
        json.dumps(
            {
                "axis_scores": {"character_depth": 0.83},
                "axis_pass": {"character_depth": True},
                "vector_pass": {
                    "Q1": None,
                    "Q2": True,
                    "Q3": None,
                    "Q4": None,
                    "Q5": None,
                },
                "overall_pass": True,
                "fired_rules": [],
                "evidence": {},
                "produced_at": "2026-05-19T16:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    out = quality_report.render_report(tmp_path)
    assert "Q2: PASS" in out
    assert "no phase timings recorded" in out.lower()
    assert "ELIGIBLE FOR PUBLISH: yes" in out


def test_render_handles_malformed_quality_json(tmp_path: Path) -> None:
    """Malformed quality.json is tolerated — report renders with vectors unknown."""
    (tmp_path / "quality.json").write_text("not json at all", encoding="utf-8")
    out = quality_report.render_report(tmp_path)
    assert "5-VECTOR PASS" in out
    assert "n/a" in out  # publish unknown when quality is unreadable
