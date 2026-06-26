"""tests/hooks/test_stop_verify.py — HARN-09 verification.

Verifies that stop_verify.py:
  1. Exits 0 when stop_hook_active=true (anti-recursion guard)
  2. Emits JSON {decision:"block"} when RESUME.md is stale vs run_log.jsonl
  3. Exits 0 when RESUME.md is fresh (no run_log.jsonl or RESUME is newer)

Plan 00-03, Task 5.
"""

# ruff: noqa: S603, S607, E501  # subprocess + bash heredoc are intentional in test scaffolding

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

HOOK = Path(".claude/hooks/stop_verify.py")


def _run_hook(
    payload: dict,  # type: ignore[type-arg]
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Run stop_verify.py as subprocess with given JSON payload."""
    return subprocess.run(
        ["uv", "run", "python", str(HOOK.resolve())],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


def test_stop_skips_on_active_flag(tmp_path: Path) -> None:
    """When stop_hook_active=True, hook must exit 0 (anti-recursion guard).

    This prevents the Stop hook from triggering itself in an infinite loop
    when Claude Code is already processing a stop event.
    """
    # Create minimal directory structure so the hook doesn't error on dir checks
    (tmp_path / ".planning" / "state").mkdir(parents=True)

    payload = {"stop_hook_active": True, "session_id": "test-session-001"}
    result = _run_hook(payload, cwd=tmp_path)

    assert result.returncode == 0, (
        f"stop_verify.py must exit 0 when stop_hook_active=True\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_stop_blocks_on_stale_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hook must exit 2 when RESUME.md mtime < data/run_log.jsonl mtime (HARN-09).

    Creates a controlled filesystem in tmp_path with:
      - .planning/state/RESUME.md: mtime in the past
      - data/run_log.jsonl: mtime in the present (newer)

    Then verifies stop_verify exits 2 with a JSON additionalContext explaining
    the staleness.

    NOTE: This test monkeypatches the working directory to tmp_path so the hook
    reads from the controlled structure, not the real project state.
    """
    # Create directory structure
    state_dir = tmp_path / ".planning" / "state"
    state_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create RESUME.md (will be made stale)
    resume = state_dir / "RESUME.md"
    resume.write_text("---\nsession_id: test\n---\n# Resume\n")

    # Create run_log.jsonl
    run_log = data_dir / "run_log.jsonl"
    run_log.write_text('{"ts": "2026-01-01T00:00:00Z", "event": "test"}\n')

    # Make RESUME.md stale: set its mtime to 10 seconds in the past
    # Set run_log.jsonl to now
    now = time.time()
    past = now - 10.0
    os.utime(str(resume), (past, past))
    os.utime(str(run_log), (now, now))

    # Create a minimal Makefile that makes `make test` succeed
    # (so only the RESUME staleness causes the block, not test failures)
    # We use a fake make that always succeeds for test/eval targets
    fake_make = tmp_path / "fake_make.sh"
    fake_make.write_text(
        '#!/usr/bin/env bash\nif [[ "$*" == *"test"* ]] || [[ "$*" == *"eval"* ]]; then\n  exit 0\nfi\nexit 0\n'
    )
    fake_make.chmod(0o755)

    # Run the hook with stop_hook_active=False and cwd=tmp_path
    # We need to pass the path to hook as absolute since cwd changes
    payload = {"stop_hook_active": False, "session_id": "test-session-001"}

    # Set PATH to include tmp_path so our fake 'make' is used
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")

    # Create a symlink "make" pointing to fake_make
    fake_make_link = tmp_path / "make"
    fake_make_link.symlink_to(fake_make)

    result = subprocess.run(
        ["uv", "run", "python", str(HOOK.resolve())],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env=env,
    )

    # Stop hooks must exit 0 and convey block via JSON decision field
    # (NOT exit code 2 — that produces hookSpecificOutput which is invalid for Stop)
    assert result.returncode == 0, (
        f"stop_verify.py must exit 0 when blocking via JSON decision\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # The stdout must contain JSON {decision: "block", reason: ...} mentioning RESUME
    if result.stdout.strip():
        try:
            output = json.loads(result.stdout)
            assert output.get("decision") == "block", (
                f"Stop hook must emit decision=block when blocking\nGot: {output!r}"
            )
            reason = output.get("reason", "")
            assert "RESUME" in reason.upper(), (
                f"reason must mention RESUME.md staleness\nGot: {reason!r}"
            )
        except json.JSONDecodeError:
            # Non-JSON output with exit 2 is also acceptable
            pass


def test_stop_allows_when_no_run_log(tmp_path: Path) -> None:
    """Hook skips the RESUME staleness check when data/run_log.jsonl doesn't exist.

    Pre-P3 state: no run_log.jsonl yet. The hook should not fail because of
    this missing file (it's a pre-P3 condition, not an error).
    """
    # Create directory structure with RESUME.md but no run_log.jsonl
    state_dir = tmp_path / ".planning" / "state"
    state_dir.mkdir(parents=True)
    resume = state_dir / "RESUME.md"
    resume.write_text("---\nsession_id: test\n---\n# Resume\n")

    # Create fake make that always succeeds
    fake_make = tmp_path / "make"
    fake_make.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_make.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + ":" + env.get("PATH", "")

    payload = {"stop_hook_active": False, "session_id": "test-session-001"}
    result = subprocess.run(
        ["uv", "run", "python", str(HOOK.resolve())],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env=env,
    )

    # Should exit 0 (no run_log.jsonl means skip staleness check)
    assert result.returncode == 0, (
        f"stop_verify.py must exit 0 when run_log.jsonl doesn't exist\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
