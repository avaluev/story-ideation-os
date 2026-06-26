"""tests/hooks/test_post_lint_returns_json.py — HARN-06 verification.

Verifies that post_lint.py:
  1. Returns exit code 0 (PostToolUse never blocks)
  2. Returns valid JSON with hookSpecificOutput.additionalContext on lint violations
  3. The additionalContext mentions the specific lint error

Plan 00-03, Task 3 (TDD verify step for post_lint.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(".claude/hooks/post_lint.py")


def test_post_lint_returns_exit_zero(tmp_path: Path) -> None:
    """PostToolUse hook MUST exit 0 — it never blocks, only injects context."""
    # Write a valid Python file (no lint errors)
    good_file = tmp_path / "good.py"
    good_file.write_text('"""Good module."""\n\n\ndef foo() -> None:\n    pass\n')

    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(good_file)}})
    cmd = ["uv", "run", "python", str(HOOK)]
    result = subprocess.run(  # noqa: S603
        cmd, input=payload, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, (
        f"post_lint.py must exit 0 (PostToolUse never blocks)\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_post_lint_returns_json_on_violation(tmp_path: Path) -> None:
    """post_lint.py MUST return JSON hookSpecificOutput on lint violations (HARN-06).

    Creates a Python file with a deliberate F401 unused-import violation,
    invokes post_lint.py as a subprocess, and verifies:
      - exit code == 0 (never blocks)
      - stdout is valid JSON
      - JSON has hookSpecificOutput.hookEventName == "PostToolUse"
      - JSON has hookSpecificOutput.additionalContext (non-empty)
      - additionalContext mentions 'ruff' or 'F401'
    """
    # Write a file with a deliberate lint violation: unused import (F401).
    # The bare `import os` triggers F401 without a noqa to silence it.
    bad_file = tmp_path / "bad_lint.py"
    bad_source = '"""Module with lint violation."""\nimport os\n\n\ndef foo() -> None:\n    pass\n'
    bad_file.write_text(bad_source)

    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(bad_file)}})
    cmd = ["uv", "run", "python", str(HOOK)]
    result = subprocess.run(  # noqa: S603
        cmd, input=payload, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, (
        f"post_lint.py must exit 0 (PostToolUse never blocks)\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # If no lint errors were found, the hook outputs nothing (also valid)
    # But for our bad file, we expect JSON output
    if result.stdout.strip():
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"post_lint.py stdout is not valid JSON: {exc}\nstdout: {result.stdout!r}")

        assert "hookSpecificOutput" in output, (
            f"JSON must have 'hookSpecificOutput' key (Sakasegawa pattern)\nGot: {output}"
        )
        hook_output = output["hookSpecificOutput"]
        assert hook_output.get("hookEventName") == "PostToolUse", (
            f"hookEventName must be 'PostToolUse', got: {hook_output.get('hookEventName')}"
        )
        additional_context = hook_output.get("additionalContext", "")
        assert additional_context, "additionalContext must be non-empty when lint violations exist"
        assert "ruff" in additional_context.lower() or "F401" in additional_context, (
            f"additionalContext must mention 'ruff' or 'F401' for F401 violations\n"
            f"Got: {additional_context!r}"
        )


def test_post_lint_skips_non_python_files(tmp_path: Path) -> None:
    """post_lint.py skips non-.py files and exits 0 with no stdout."""
    md_file = tmp_path / "README.md"
    md_file.write_text("# Hello\n")

    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(md_file)}})
    cmd = ["uv", "run", "python", str(HOOK)]
    result = subprocess.run(  # noqa: S603
        cmd, input=payload, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    # Non-Python files produce no output
    assert result.stdout.strip() == "", (
        f"post_lint.py should produce no output for non-Python files\nGot stdout: {result.stdout!r}"
    )
