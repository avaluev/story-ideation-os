"""Tests for scripts/lint_imports.py custom architectural lint (HARN-11)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_lint(*args: str) -> subprocess.CompletedProcess:
    """Run the lint_imports script and return the result."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "scripts/lint_imports.py", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_clean_tree_exits_0() -> None:
    """lint_imports.py must exit 0 on a clean tree (no violations)."""
    result = _run_lint()
    assert result.returncode == 0, (
        f"lint_imports.py exited {result.returncode} on a clean tree.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_violation_emits_why_fix_example(tmp_path: Path) -> None:
    """ANOMALY-001 fires when pipeline/scoring.py imports httpx.

    Writes a scratch scoring.py with a forbidden import, verifies exit 1
    and WHY/FIX/EXAMPLE format. Cleans up in finally block.
    """
    scoring_path = Path("pipeline/scoring.py")
    existed_before = scoring_path.exists()
    original_content = scoring_path.read_text() if existed_before else None

    try:
        scoring_path.write_text(
            '"""Scratch scoring file for lint test."""\nimport httpx  # forbidden by ADR-0002\n'
        )
        result = _run_lint()

        assert result.returncode == 1, (
            f"Expected exit 1 when scoring.py imports httpx, got {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        output = result.stdout
        assert "WHY:" in output, f"Output missing 'WHY:' section:\n{output}"
        assert "FIX:" in output, f"Output missing 'FIX:' section:\n{output}"
        assert "EXAMPLE:" in output, f"Output missing 'EXAMPLE:' section:\n{output}"
        assert "ANOMALY-001" in output, f"Output missing rule code 'ANOMALY-001':\n{output}"

    finally:
        if existed_before and original_content is not None:
            scoring_path.write_text(original_content)
        elif not existed_before and scoring_path.exists():
            scoring_path.unlink()


def test_frameworks_import_blocked(tmp_path: Path) -> None:
    """ANOMALY-002 fires when pipeline/*.py imports from frameworks.

    Writes a scratch pipeline module, verifies ANOMALY-002 fires.
    Cleans up in finally block.
    """
    scratch_path = Path("pipeline/scratch_lint_test.py")
    try:
        scratch_path.write_text(
            '"""Scratch file for lint test — imports frameworks (forbidden)."""\n'
            "from frameworks import some_module  # forbidden by ADR-0005\n"
        )
        result = _run_lint()

        assert result.returncode == 1, (
            f"Expected exit 1 when pipeline file imports frameworks, "
            f"got {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        output = result.stdout
        assert "ANOMALY-002" in output, f"Output missing rule code 'ANOMALY-002':\n{output}"
        assert "WHY:" in output, f"Output missing 'WHY:' section:\n{output}"
        assert "FIX:" in output, f"Output missing 'FIX:' section:\n{output}"
        assert "EXAMPLE:" in output, f"Output missing 'EXAMPLE:' section:\n{output}"

    finally:
        if scratch_path.exists():
            scratch_path.unlink()
