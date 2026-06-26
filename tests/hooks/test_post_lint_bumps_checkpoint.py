"""tests/hooks/test_post_lint_bumps_checkpoint.py — MEM-07 durability assertion.

Plan 00-04 owns this test (asserts the durability invariant:
PostToolUse(Write|Edit) hook MUST call bump_session_checkpoint from
pipeline.state); plan 00-03 shipped the hook script body
(.claude/hooks/post_lint.py).

MEM-07 requirement:
  Hooks for durability — PostToolUse(Write|Edit) bumps session checkpoint;
  this test verifies the hook imports and calls bump_session_checkpoint
  from pipeline.state.

Validation row: 0-04-04 (MEM-07) in 00-VALIDATION.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HOOK = Path(".claude/hooks/post_lint.py")


def test_post_lint_hook_calls_bump_checkpoint() -> None:
    """post_lint.py must import and call bump_session_checkpoint (MEM-07)."""
    src = HOOK.read_text()

    assert "from pipeline.state import" in src or "import pipeline.state" in src, (
        ".claude/hooks/post_lint.py must import from pipeline.state to bump "
        "checkpoint (MEM-07).\n"
        "Expected: 'from pipeline.state import ...' or 'import pipeline.state'"
    )
    assert "bump_session_checkpoint" in src, (
        ".claude/hooks/post_lint.py must call bump_session_checkpoint(...) per MEM-07.\n"
        "The PostToolUse(Write|Edit) hook must update the session checkpoint "
        "after each file edit to ensure kill-9 survivability."
    )


def test_post_lint_hook_returns_json_on_violation() -> None:
    """post_lint.py must return JSON hookSpecificOutput on lint violations (HARN-06).

    SKIP — this test is owned by plan 00-03 and will be implemented in
    tests/hooks/test_post_lint_returns_json.py (plan 00-03 task).

    Cross-cutting with HARN-06: PostToolUse hook returns JSON
    hookSpecificOutput.additionalContext so the agent self-corrects.
    """
    pytest.skip("owned by plan 00-03 (tests/hooks/test_post_lint_returns_json.py)")
