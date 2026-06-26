#!/usr/bin/env python3
"""Stop hook — completion gate.

HARN-09: Before allowing Claude to declare "done", verify:
  1. Anti-recursion guard: stop_hook_active=True → exit 0 immediately
  2. `make test` must pass
  3. `make eval` must pass (exit 5 = no tests collected is OK pre-P4)
  4. RESUME.md mtime must be > data/run_log.jsonl mtime (if run_log exists)

If any check fails, emit JSON {decision: "block", reason: "..."} and exit 0.
Stop hooks MUST use the top-level decision/reason fields (NOT
hookSpecificOutput, which only valid for PostToolUse / UserPromptSubmit /
PostToolBatch per the harness JSON schema).

Exit codes:
  0 → always (block signal is conveyed via JSON decision field, not exit code)

See: HARN-09, MEM-08, CLAUDE.md MUST §6.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_MAKE_PATH = shutil.which("make") or "/usr/bin/make"


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_make(target: str) -> tuple[int, str]:
    """Run a make target and return (returncode, output)."""
    result = subprocess.run(  # noqa: S603
        [_MAKE_PATH, target],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, (result.stdout + result.stderr)


def _block(reason: str) -> int:
    """Print JSON {decision: "block", reason: ...} per Stop-hook schema.

    Stop hooks MUST NOT use hookSpecificOutput — that field is reserved for
    PostToolUse / UserPromptSubmit / PostToolBatch. The harness JSON validator
    rejects hookSpecificOutput on Stop and the hook is treated as failed.
    """
    output = {"decision": "block", "reason": reason}
    print(json.dumps(output))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    # Step 1: Anti-recursion guard (prevents infinite Stop loop in auto mode)
    if payload.get("stop_hook_active"):
        return 0

    # Step 2: `make test` must pass
    test_rc, test_out = _run_make("test")
    if test_rc != 0:
        reason = (
            "BLOCKED: make test failed.\n"
            + test_out[-2000:]
            + "\nFIX: address failing tests before declaring done."
        )
        return _block(reason)

    # Step 3: `make eval` must pass (exit 5 = no tests collected is OK pre-P4)
    eval_rc, eval_out = _run_make("eval")
    if eval_rc not in (0, 5):
        reason = (
            "BLOCKED: make eval failed.\n"
            + eval_out[-2000:]
            + "\nFIX: address eval failures before declaring done."
        )
        return _block(reason)

    # Step 4: RESUME.md freshness check (HARN-09 + MEM-08)
    resume = Path(".planning/state/RESUME.md")
    run_log = Path("data/run_log.jsonl")

    if run_log.exists():
        try:
            resume_mtime = resume.stat().st_mtime if resume.exists() else 0.0
            run_log_mtime = run_log.stat().st_mtime

            if resume_mtime < run_log_mtime:
                reason = (
                    "BLOCKED: RESUME.md is older than the last run_log event.\n"
                    "FIX: update .planning/state/RESUME.md with this session's outcomes "
                    "before declaring done.\n"
                    "EXAMPLE: add a summary of what was accomplished, files created, "
                    "and decisions made in this session."
                )
                return _block(reason)
        except OSError:
            # Can't stat files — skip this check rather than false-blocking
            pass

    # All checks passed — allow Stop
    return 0


if __name__ == "__main__":
    sys.exit(main())
