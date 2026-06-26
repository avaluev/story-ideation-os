"""evals/test_long_run.py — OPS-08-rev: Budget-exhaustion integration test.

Simulates a 100-concept formatter run where BudgetExceeded is raised after
47 safe_write calls.  Asserts:
  - exit code 0  (graceful stop, not a crash)
  - stop checkpoint written to data/state/stop_BUDGET_{session_id}.json
  - 47 .md files written to out/concepts/ before BudgetExceeded
  - graceful BudgetExceeded handling in pipeline/run.py main()

Simulation strategy:
  - Seed data/05_critiques.jsonl with 100 rows whose overall_score passes
    the 85-floor (passes_85_floor=True) so the formatter writes all 100.
  - Patch pipeline.run.safe_write to count calls and raise BudgetExceeded
    after the 47th concept .md write (ignoring the last_run_n.txt write).
  - Run pipeline --phase formatter in a subprocess (same pattern as test_resume.py).
  - Assert stop checkpoint exists and returncode == 0.

POSIX note: This test does not use SIGKILL — it runs to subprocess completion.
It works on all platforms.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pipeline.openrouter_client import BudgetExceeded  # noqa: F401 — confirms importable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_WAIT_TIMEOUT_S = 120
_BUDGET_EXHAUST_AFTER = 47  # concepts written before BudgetExceeded


# ---------------------------------------------------------------------------
# Seed data builders
# ---------------------------------------------------------------------------


def _make_critique_row(i: int) -> dict:
    """Return a minimal 05_critiques.jsonl row that passes the 85-floor."""
    concept_id = f"budget-test-concept-{i:04d}"
    return {
        "concept_id": concept_id,
        "title": f"Test Concept {i}",
        "logline": "A test logline.",
        "polti_id": 1,
        "tobias_id": 1,
        "seed_used": 42,
        "seed_increments": 0,
        "forge_meta": {"model": "test/mock", "k": 1, "seed_used": 42},
        "produced_at": "2026-05-07T00:00:00+00:00",
        "session_id": "budget-test-session",
        "total_score": 88,
        "novelty_score": 8,
        "jtbd_score": 8,
        "contradiction_score": 8,
        "specificity_score": 8,
        "cap_at_70_triggered": False,
        "overall_score": {
            "final": 88,
            "passes_85_floor": True,
            "sdt": 70,
            "ajtbd": 18,
        },
    }


# ---------------------------------------------------------------------------
# Mock runner script builder
# ---------------------------------------------------------------------------


def _write_budget_mock_runner(tmp_path: Path, exhaust_after: int = _BUDGET_EXHAUST_AFTER) -> Path:
    """Write a Python runner script that raises BudgetExceeded after N safe_write calls.

    The script:
    1. Patches pipeline.run.safe_write to count .md writes and raise
       BudgetExceeded after `exhaust_after` concept files.
    2. Runs pipeline --phase formatter (formatter reads 05_critiques.jsonl
       and writes out/concepts/{id}.md via safe_write).
    3. The BudgetExceeded propagates to main()'s outer except clause,
       which writes the stop checkpoint and exits 0.
    """
    script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(_PROJECT_ROOT)!r})
        import os
        os.chdir({str(tmp_path)!r})

        from unittest.mock import patch, MagicMock
        from pathlib import Path
        from pipeline.openrouter_client import BudgetExceeded
        from pipeline.state import safe_write as _real_safe_write

        _md_write_count = 0

        def _patched_safe_write(path, content):
            global _md_write_count
            # Only count .md writes (concept files); let other writes through
            if str(path).endswith('.md'):
                _md_write_count += 1
                if _md_write_count > {exhaust_after}:
                    raise BudgetExceeded(
                        f"budget exhausted at concept {{_md_write_count}}"
                    )
            _real_safe_write(path, content)

        mock_client = MagicMock()
        mock_client.chat.return_value = {{}}

        with patch("pipeline.run.OpenRouterClient", return_value=mock_client), \\
             patch("pipeline.run.safe_write", side_effect=_patched_safe_write):
            from pipeline.run import app
            try:
                app(
                    ["--phase", "formatter"],
                    standalone_mode=True,
                )
            except SystemExit:
                pass
    """)
    runner_path = tmp_path / "run_budget_formatter.py"
    runner_path.write_text(script)
    return runner_path


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_budget_exhausted_at_47(tmp_path: Path) -> None:
    """BudgetExceeded during formatter produces exit 0 + stop checkpoint.

    Steps:
    1. Seed data/05_critiques.jsonl with 100 passing rows.
    2. Run formatter subprocess with patched safe_write that raises
       BudgetExceeded after the 47th .md write.
    3. Assert returncode == 0.
    4. Assert stop_BUDGET_{session_id}.json exists in data/state/.
    """
    # ---- Step 1: Seed input --------------------------------------------------
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (tmp_path / "data" / "state").mkdir(parents=True)
    (tmp_path / "out" / "concepts").mkdir(parents=True)

    critiques_path = data_dir / "05_critiques.jsonl"
    rows = [_make_critique_row(i) for i in range(1, 101)]  # 100 rows
    critiques_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    # Symlink frameworks so load_framework() resolves
    (tmp_path / "frameworks").symlink_to(_PROJECT_ROOT / "frameworks")
    (tmp_path / "prompts").symlink_to(_PROJECT_ROOT / "prompts")

    runner_script = _write_budget_mock_runner(tmp_path, exhaust_after=_BUDGET_EXHAUST_AFTER)

    env: dict[str, str] = {
        **os.environ,
        "OPENROUTER_KEY_PAID": "sk-or-v1-00000000-test-fake-key-budget-eval",
        "OPENROUTER_KEY_FREE_1": "",
        "OPENROUTER_KEY_FREE_2": "",
    }

    # ---- Step 2: Run subprocess ----------------------------------------------
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(runner_script)],
        env=env,
        cwd=str(tmp_path),
        timeout=_WAIT_TIMEOUT_S,
        capture_output=True,
        text=True,
        check=False,
    )

    # ---- Step 3: Assert exit 0 -----------------------------------------------
    assert result.returncode == 0, (
        f"Pipeline exited with code {result.returncode} (expected 0)\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # ---- Step 4: Assert stop checkpoint exists -------------------------------
    state_dir = tmp_path / "data" / "state"
    checkpoint_files = list(state_dir.glob("stop_BUDGET_*.json"))
    assert checkpoint_files, (
        f"No stop_BUDGET_*.json checkpoint found in {state_dir}.\n"
        f"Files present: {list(state_dir.iterdir())}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    chk = json.loads(checkpoint_files[0].read_text(encoding="utf-8"))
    assert chk.get("reason") == "BUDGET", f"Expected reason=BUDGET, got: {chk}"
    assert "session_id" in chk, f"stop checkpoint missing session_id: {chk}"
    assert "stopped_at" in chk, f"stop checkpoint missing stopped_at: {chk}"

    # ---- Step 5: Assert 47 concept .md files were written --------------------
    concept_files = list((tmp_path / "out" / "concepts").glob("*.md"))
    assert len(concept_files) == 47, (
        f"Expected 47 concept files in out/concepts/, got {len(concept_files)}\n"
        f"Files present: {sorted(f.name for f in concept_files)}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
