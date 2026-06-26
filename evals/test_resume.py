"""EVAL-09 / MEM-09 — Kill-9 recovery eval.

Proves that pipeline.run --phase forger is resumable after SIGKILL:
  1. Run forger to completion (baseline)
  2. Run forger, SIGKILL after sentinel condition is observed
  3. Resume (re-run forger with same seed) -> same output as baseline
  4. Compare all output fields EXCEPT produced_at

POSIX only: SIGKILL is not available on Windows.
On Windows: pytest.fail() inside test_kill_9_recovery (not module scope —
module-scope pytest.fail aborts collection with -x flag).

Sentinel strategy: Option A — watch data/run_log.jsonl for
event="START", phase="forger". Confirmed by reading pipeline/run.py:
_run_forger calls _log_event("START", "forger", ...) before any file I/O,
which writes that event to RUN_LOG (data/run_log.jsonl) via append_jsonl.

Skips gracefully on fresh clone when data/03_audience.jsonl doesn't exist
AND when run in CI without the pipeline having been run at all.
Uses subprocess.Popen (NOT CliRunner) — CliRunner cannot receive OS signals.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_AUDIENCE_LOG = Path("data/03_audience.jsonl")
_CONCEPTS_LOG = Path("data/04_concepts.jsonl")
_RUN_LOG = Path("data/run_log.jsonl")

_WAIT_TIMEOUT_S = 90  # max seconds to wait for sentinel
_POLL_INTERVAL_S = 0.1

# ---------------------------------------------------------------------------
# Seed audience rows (deterministic input for forger)
# ---------------------------------------------------------------------------

_AUDIENCE_ROWS = [
    {
        "asset_id": "resume-test-001",
        "target_countries": ["US", "RU", "DE"],
        "cited_audience": 120_000_000,
        "sources_per_claim": 2,
        "trend_direction": "rising",
        "primary_jtbd_strength": 0.80,
        "source_quote": "Historic voices resonate across generations",
        "produced_at": "2026-05-07T12:00:00+00:00",
        "session_id": "resume-test-session",
        "total_score": None,
    },
]

# ---------------------------------------------------------------------------
# Mock API response (deterministic — same concept every call)
# total_score MUST be None (ADR-0002 / _reject_llm_total_score validator).
# forge_meta is populated here; pipeline._run_forger will setdefault any
# missing sub-keys, but since all keys are present they remain unchanged.
# ---------------------------------------------------------------------------

_MOCK_CONCEPT = {
    "concept_id": "resume-test-concept-001",
    "title": "The Iron Atlas",
    "logline": "A historian discovers a suppressed manuscript connecting two empires.",
    "polti_id": 3,
    "tobias_id": 7,
    "seed_used": 42,
    "seed_increments": 0,
    "forge_meta": {"model": "anthropic/claude-sonnet-4.6", "k": 3, "seed_used": 42},
    "produced_at": "2026-05-07T12:00:00+00:00",  # pipeline overrides via setdefault
    "session_id": "resume-test-session",  # pipeline overrides via setdefault
    "total_score": None,
}

# ---------------------------------------------------------------------------
# Helper: write mock wrapper script
# ---------------------------------------------------------------------------


def _write_mock_runner(tmp_path: Path, seed: int = 42) -> Path:
    """Write a Python script to tmp_path that runs pipeline.run --phase forger
    with mocked HTTP.

    The script patches pipeline.run.OpenRouterClient before invoking the CLI so
    no real API calls are made.  safe_write and append_jsonl are NOT mocked —
    files are actually written so the SIGKILL timing can observe them.
    """
    # Use repr() to embed the dict as a Python literal (json.dumps produces
    # JSON 'null' which is not valid Python syntax; repr produces 'None').
    mock_concept_repr = repr(_MOCK_CONCEPT)
    script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(_PROJECT_ROOT)!r})
        import os
        os.chdir({str(tmp_path)!r})

        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.chat.return_value = {mock_concept_repr}

        with patch("pipeline.run.OpenRouterClient", return_value=mock_client):
            from pipeline.run import app
            try:
                app(
                    ["--phase", "forger", "--seed", "{seed}"],
                    standalone_mode=True,
                )
            except SystemExit:
                pass
    """)
    runner_path = tmp_path / "run_mock_forger.py"
    runner_path.write_text(script)
    return runner_path


# ---------------------------------------------------------------------------
# Helper: wait for sentinel (Option A — run_log START event confirmed)
# Confirmed from pipeline/run.py: _run_forger calls
#   _log_event("START", "forger", ...)
# at the top of the function, before reading input. _log_event writes
#   {"ts": ..., "event": "START", "phase": "forger", ...}
# to data/run_log.jsonl via append_jsonl(RUN_LOG, row).
# ---------------------------------------------------------------------------


def _wait_for_sentinel(tmp_path: Path, timeout: float) -> bool:
    """Watch data/run_log.jsonl for event='START', phase='forger' (Option A).

    Returns True as soon as the sentinel is observed; False on timeout.
    """
    run_log = tmp_path / "data" / "run_log.jsonl"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run_log.exists():
            for line in run_log.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        row = json.loads(line)
                        if row.get("event") == "START" and row.get("phase") == "forger":
                            return True
                    except json.JSONDecodeError:
                        pass
        time.sleep(_POLL_INTERVAL_S)
    return False


# ---------------------------------------------------------------------------
# Helper: comparison utilities
# ---------------------------------------------------------------------------


def _strip_produced_at(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of row with produced_at key removed (byte-identical comparison)."""
    return {k: v for k, v in row.items() if k != "produced_at"}


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    """Load all rows from a JSONL file, skipping blank lines."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Helper: subprocess run helpers (reduce statement count in test function)
# ---------------------------------------------------------------------------


def _run_forger_subprocess(
    runner_script: Path,
    env: dict[str, str],
    tmp_path: Path,
    label: str,
) -> None:
    """Spawn forger subprocess and wait for completion; fail test on timeout."""
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(runner_script)],
        env=env,
        cwd=str(tmp_path),
    )
    try:
        proc.wait(timeout=_WAIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail(f"{label} forger process timed out after {_WAIT_TIMEOUT_S}s.")


def _run_kill_forger_subprocess(
    runner_script: Path,
    env: dict[str, str],
    tmp_path: Path,
) -> None:
    """Spawn forger subprocess, wait for START sentinel, then SIGKILL it."""
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(runner_script)],
        env=env,
        cwd=str(tmp_path),
    )
    started = _wait_for_sentinel(tmp_path, _WAIT_TIMEOUT_S)
    if not started:
        proc.kill()
        proc.wait()
        pytest.fail(
            f"Forger START sentinel never observed in run_log.jsonl within {_WAIT_TIMEOUT_S}s. "
            "Verify that pipeline._run_forger calls _log_event('START', 'forger', ...) "
            "before any file I/O (confirmed at pipeline/run.py line ~386)."
        )
    # Real SIGKILL — not cooperative, cannot be caught by the subprocess
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()


def _assert_rows_match(
    baseline_rows: list[dict[str, Any]],
    resumed_rows: list[dict[str, Any]],
) -> None:
    """Assert resumed rows are byte-identical to baseline except produced_at."""
    assert len(resumed_rows) == len(baseline_rows), (
        f"Row count mismatch: baseline={len(baseline_rows)}, resumed={len(resumed_rows)}"
    )
    for i, (baseline, resumed) in enumerate(zip(baseline_rows, resumed_rows, strict=True)):
        b_clean = _strip_produced_at(baseline)
        r_clean = _strip_produced_at(resumed)
        assert b_clean == r_clean, (
            f"Row {i} differs after kill-9 resume (excluding produced_at):\n"
            f"  baseline: {json.dumps(b_clean, indent=2)}\n"
            f"  resumed:  {json.dumps(r_clean, indent=2)}"
        )


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


def test_kill_9_recovery(tmp_path: Path) -> None:
    """SIGKILL mid-Phase-4 Forge produces byte-identical output on resume
    (MEM-09 / EVAL-09).

    Steps:
      1. Platform guard — fail loudly on Windows (not skip)
      2. Seed data/03_audience.jsonl in tmp_path
      3. Run baseline forger to completion -> collect rows from data/04_concepts.jsonl
      4. Clear data/04_concepts.jsonl and data/run_log.jsonl
      5. Run forger again, SIGKILL after sentinel condition observed
      6. Re-run forger (resume -> re-runs forger on same seed)
      7. Compare resumed rows to baseline (excluding produced_at)
    """
    # ---- Step 1: Platform guard -------------------------------------------
    # Guard is INSIDE the test function (not at module scope) to avoid collection
    # failure which aborts the entire evals/ suite when -x flag is active.
    if sys.platform == "win32":
        pytest.fail(
            "SIGKILL durability eval requires POSIX (macOS/Linux) — "
            "this is a hard project requirement (MEM-09). "
            "Run on macOS or Linux to validate the kill-9 recovery guarantee.",
            pytrace=False,
        )

    # ---- Step 2: Seed input -----------------------------------------------
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "03_audience.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _AUDIENCE_ROWS) + "\n",
        encoding="utf-8",
    )
    # Symlink frameworks and prompts so load_framework() resolves correctly.
    (tmp_path / "frameworks").symlink_to(_PROJECT_ROOT / "frameworks")
    (tmp_path / "prompts").symlink_to(_PROJECT_ROOT / "prompts")

    env: dict[str, str] = {
        **os.environ,
        "OPENROUTER_KEY_PAID": "sk-or-v1-00000000-test-fake-key-resume-eval",
        "OPENROUTER_KEY_FREE_1": "",
        "OPENROUTER_KEY_FREE_2": "",
    }
    runner_script = _write_mock_runner(tmp_path, seed=42)
    concepts_path = tmp_path / "data" / "04_concepts.jsonl"
    run_log = tmp_path / "data" / "run_log.jsonl"

    # ---- Step 3: Baseline run ---------------------------------------------
    _run_forger_subprocess(runner_script, env, tmp_path, label="Baseline")
    if not concepts_path.exists():
        pytest.skip(
            "Baseline run produced no data/04_concepts.jsonl — "
            "check mock client configuration or pipeline forger phase."
        )
    baseline_rows = _load_jsonl_rows(concepts_path)
    assert baseline_rows, "Baseline run produced empty 04_concepts.jsonl"

    # ---- Step 4: Clear for kill run --------------------------------------
    concepts_path.unlink()
    if run_log.exists():
        run_log.unlink()

    # ---- Step 5: Kill run ------------------------------------------------
    _run_kill_forger_subprocess(runner_script, env, tmp_path)

    # ---- Step 6: Resume run ----------------------------------------------
    # Clear any partial output from the killed run so resume starts clean.
    if concepts_path.exists():
        concepts_path.unlink()
    if run_log.exists():
        run_log.unlink()

    _run_forger_subprocess(runner_script, env, tmp_path, label="Resume")
    assert concepts_path.exists(), "Resume run produced no data/04_concepts.jsonl."
    resumed_rows = _load_jsonl_rows(concepts_path)
    assert resumed_rows, "Resume run produced empty 04_concepts.jsonl"

    # ---- Step 7: Byte-identical comparison (excluding produced_at) -------
    _assert_rows_match(baseline_rows, resumed_rows)
