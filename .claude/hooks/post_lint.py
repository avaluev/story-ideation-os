#!/usr/bin/env python3
"""PostToolUse(Write|Edit|MultiEdit) hook — Sakasegawa self-correction loop.

HARN-06, MEM-07: After every file write/edit, auto-fix with ruff and run
pyright. If violations remain, return a JSON hookSpecificOutput.additionalContext
so the agent self-corrects instead of silently shipping broken code.

This hook also bumps the session checkpoint after each file edit (MEM-07),
ensuring kill-9 recovery can reconstruct the session.

Sakasegawa pattern reference:
  - Return JSON {hookSpecificOutput: {hookEventName, additionalContext}}
  - Exit 0 always (PostToolUse never blocks — only injects feedback)
  - The additionalContext is re-injected into the agent's context window

Exit codes:
  0 → always (PostToolUse never blocks)

See: HARN-06, MEM-07, ADR-0001.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run a command and return (returncode, combined stdout+stderr)."""
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, (result.stdout + result.stderr)


def _bump_checkpoint(file_edited: str) -> None:
    """Bump session checkpoint after file edit (MEM-07).

    Calls pipeline.state.bump_session_checkpoint — P0 stub raises
    NotImplementedError; fallback ships P0 functionality.
    # substrate stub raises until P3; fallback ships P0 functionality.
    """
    try:
        from pipeline.state import bump_session_checkpoint  # noqa: PLC0415

        bump_session_checkpoint(file_edited=file_edited)
    except NotImplementedError:
        # P0: pipeline.state stub raises NotImplementedError until P3.
        # Fallback: write minimal checkpoint to .planning/state/sessions/
        # This ships P0 functionality while P3 fills the real body.
        import os  # noqa: PLC0415

        session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")[:64]
        state_dir = Path(".planning/state/sessions") / session_id
        state_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "schema_version": "1.0",
            "session_id": session_id,
            "last_updated_at": _iso_now(),
            "last_artifact_path": file_edited,
            "notes": "P0 fallback checkpoint (P3 implements full body)",
        }
        tmp = state_dir / "checkpoint.json.tmp"
        target = state_dir / "checkpoint.json"
        tmp.write_text(json.dumps(checkpoint, indent=2))
        os.replace(str(tmp), str(target))
    except Exception:  # noqa: S110
        # Never crash the agent context over a checkpoint write failure
        pass


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path: str = payload.get("tool_input", {}).get("file_path", "") or ""

    if not file_path:
        return 0

    # Skip if file doesn't exist (e.g., delete operations)
    if not Path(file_path).exists():
        return 0

    # Branch: prompts/*.md files trigger lint_prompts.py (PROMPT-08 hook)
    if file_path.endswith(".md") and "/prompts/" in file_path:
        _bump_checkpoint(file_path)
        prompts_rc, prompts_out = _run(["uv", "run", "python", "scripts/lint_prompts.py"])
        if prompts_rc != 0 and prompts_out.strip():
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": f"lint_prompts:\n{prompts_out[:2000]}",
                }
            }
            print(json.dumps(output))
        return 0

    # Branch: only process Python files for the ruff/pyright pipeline below
    if not (file_path.endswith(".py") or file_path.endswith(".pyi")):
        return 0

    # Step 1: Auto-fix with ruff format + ruff check --fix
    _run(["uv", "run", "ruff", "format", file_path])
    _run(["uv", "run", "ruff", "check", "--fix", file_path])

    # Step 2: Re-check for remaining violations
    ruff_rc, ruff_out = _run(["uv", "run", "ruff", "check", file_path])

    # Step 3: Run pyright type check
    pyright_rc, pyright_out = _run(["uv", "run", "pyright", file_path])

    # Step 4: Bump session checkpoint (MEM-07)
    _bump_checkpoint(file_path)

    # Step 5: Build additionalContext from remaining violations
    msg_parts: list[str] = []
    if ruff_rc != 0:
        # Filter out the ruff warning about removed rules — not actionable
        ruff_lines = [
            line
            for line in ruff_out.splitlines()
            if "ANN101" not in line and "ANN102" not in line and "have been removed" not in line
        ]
        ruff_filtered = "\n".join(ruff_lines).strip()
        if ruff_filtered:
            msg_parts.append(f"ruff:\n{ruff_filtered[:2000]}")

    if pyright_rc != 0 and pyright_out.strip():
        msg_parts.append(f"pyright:\n{pyright_out[:2000]}")

    # Step 6: Emit JSON if there are remaining violations
    if msg_parts:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n\n".join(msg_parts),
            }
        }
        print(json.dumps(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
