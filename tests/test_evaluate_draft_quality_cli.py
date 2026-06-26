"""tests/test_evaluate_draft_quality_cli.py — NB.11 thin CLI wrapper.

Surfaces ``pipeline.single_idea.evaluate_draft_quality`` as a one-liner the
``/single-idea`` skill can invoke after STEP 4:

    uv run python -m pipeline.evaluate_draft_quality --run-dir runs/{id}

Contract:

- exits 0 on success and prints a one-line JSON summary
  (``overall_pass``, ``failing_vectors``, ``failing_axes``)
- soft-fails (exit 0) on any exception so the wrapper never blocks the pipeline
- the underlying ``evaluate_draft_quality`` is invoked exactly once per call
  and writes ``runs/{id}/quality.json`` via ``pipeline.state.safe_write``

The tests mirror the shape-assertion philosophy used in
``test_drafter_quality_gate.py`` and ``test_quality_report.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _write_draft(run_dir: Path, draft: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "draft_v0.json").write_text(json.dumps(draft), encoding="utf-8")


@pytest.fixture
def deep_draft() -> dict[str, Any]:
    return {
        "slug": "the-quota",
        "logline": (
            "A public defender named Maya forces a corrupt judge to choose "
            "between her son's freedom and the truth she swore to defend."
        ),
        "characters": {
            "protagonist": {
                "name": "Maya",
                "want": "expose the judge",
                "need": "forgive her father's silence",
                "contradiction": "the system that protects her son is the one she must dismantle",
            },
            "antagonist": {
                "name": "Judge Reed",
                "belief": "law without mercy is the only law that survives",
                "method": "weaponize procedure to make injustice legal",
                "entity_type": "human",
            },
            "key_characters": [{"name": "Father", "function": "moral mirror"}],
        },
        "hidden_attrs": {
            "cast_size_principal": 3,
            "antagonist_entity_type": "human",
            "ip_origin": "original",
        },
    }


def _run_cli(run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # trusted: argv is built from fixed strings + tmp paths
        [
            sys.executable,
            "-m",
            "pipeline.evaluate_draft_quality",
            "--run-dir",
            str(run_dir),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_writes_quality_json(tmp_path: Path, deep_draft: dict[str, Any]) -> None:
    """End-to-end: invoking the CLI produces quality.json in run_dir."""
    _write_draft(tmp_path, deep_draft)
    rules = tmp_path / "no_rules.jsonl"
    rules.write_text("", encoding="utf-8")

    result = _run_cli(tmp_path, "--rules-path", str(rules))

    assert result.returncode == 0, f"CLI failed: stderr={result.stderr!r}"
    assert (tmp_path / "quality.json").exists(), "quality.json sidecar not produced"


def test_cli_prints_json_summary(tmp_path: Path, deep_draft: dict[str, Any]) -> None:
    """stdout is a single line of JSON with the documented keys."""
    _write_draft(tmp_path, deep_draft)
    rules = tmp_path / "no_rules.jsonl"
    rules.write_text("", encoding="utf-8")

    result = _run_cli(tmp_path, "--rules-path", str(rules))

    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert set(payload.keys()) == {"overall_pass", "failing_vectors", "failing_axes"}
    assert isinstance(payload["overall_pass"], bool)
    assert isinstance(payload["failing_vectors"], list)
    assert isinstance(payload["failing_axes"], list)


def test_cli_soft_fails_when_draft_missing(tmp_path: Path) -> None:
    """No draft_v0.json → CLI logs warning and exits 0 (never blocks pipeline)."""
    result = _run_cli(tmp_path)
    assert result.returncode == 0, (
        f"CLI must soft-fail (exit 0) when draft_v0 missing; got {result.returncode}"
    )


def test_cli_help_includes_run_dir_flag() -> None:
    """--run-dir is the required, documented flag."""
    result = subprocess.run(  # trusted: argv is built from fixed strings
        [sys.executable, "-m", "pipeline.evaluate_draft_quality", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--run-dir" in result.stdout


def test_cli_module_has_no_public_surface() -> None:
    """The wrapper exposes nothing beyond its __main__ entry point."""
    from pipeline import evaluate_draft_quality as mod  # noqa: PLC0415

    assert mod.__all__ == []
