"""tests/test_settings_hooks.py — HARN-05 verification.

Verifies that .claude/settings.json has a valid hooks block with:
  - All 4 event types: PreToolUse, PostToolUse, Stop, PreCompact
  - PreToolUse has Write|Edit|MultiEdit and Bash matchers
  - PostToolUse has Write|Edit|MultiEdit and Task matchers
  - Each hook command starts with 'uv run python .claude/hooks/'
  - All referenced hook .py files exist on disk

Plan 00-03, Task 8 (HARN-05).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SETTINGS = Path(".claude/settings.json")


@pytest.fixture(scope="module")
def settings() -> dict:  # type: ignore[type-arg]
    """Load and return the parsed .claude/settings.json."""
    assert SETTINGS.exists(), f".claude/settings.json not found at {SETTINGS}"
    with SETTINGS.open() as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def hooks(settings: dict) -> dict:  # type: ignore[type-arg]
    """Return the hooks sub-dict from settings."""
    assert "hooks" in settings, (
        ".claude/settings.json must have a 'hooks' block (HARN-05).\n"
        f"Current keys: {list(settings.keys())}"
    )
    return settings["hooks"]  # type: ignore[return-value]


def test_settings_has_permissions_block(settings: dict) -> None:  # type: ignore[type-arg]
    """Settings must have the permissions block (from plan 00-01)."""
    assert "permissions" in settings, (
        ".claude/settings.json must have 'permissions' block (from plan 00-01)"
    )


def test_settings_has_hooks_block(settings: dict) -> None:  # type: ignore[type-arg]
    """Settings must have the hooks block (HARN-05)."""
    assert "hooks" in settings, ".claude/settings.json must have a 'hooks' block (HARN-05)"


def test_hooks_has_4_event_types(hooks: dict) -> None:  # type: ignore[type-arg]
    """Hooks block must have exactly the 4 required event types."""
    expected = sorted(["PostToolUse", "PreCompact", "PreToolUse", "Stop"])
    actual = sorted(hooks.keys())
    assert actual == expected, f"hooks block must have event types {expected}\nGot: {actual}"


def test_pretooluse_has_write_and_bash_matchers(hooks: dict) -> None:  # type: ignore[type-arg]
    """PreToolUse must have Write|Edit|MultiEdit and Bash matchers.

    After STAB-02 (plan 05-04), PreToolUse has 3 entries:
    - pre_protect.py (Write|Edit|MultiEdit)
    - pre_anti_slop_gate.py (Write|Edit|MultiEdit)
    - pre_bash_gate.py (Bash)
    """
    pre_tool = hooks.get("PreToolUse", [])
    assert len(pre_tool) >= 2, f"PreToolUse must have at least 2 hook entries, got {len(pre_tool)}"
    matchers = [entry.get("matcher") for entry in pre_tool]
    assert "Write|Edit|MultiEdit" in matchers, (
        f"PreToolUse must have 'Write|Edit|MultiEdit' matcher. Got: {matchers}"
    )
    assert "Bash" in matchers, f"PreToolUse must have 'Bash' matcher. Got: {matchers}"


def test_posttooluse_has_write_and_task_matchers(hooks: dict) -> None:  # type: ignore[type-arg]
    """PostToolUse must have Write|Edit|MultiEdit and Task matchers."""
    post_tool = hooks.get("PostToolUse", [])
    assert len(post_tool) == 2, f"PostToolUse must have 2 hook entries, got {len(post_tool)}"
    matchers = {entry.get("matcher") for entry in post_tool}
    assert "Write|Edit|MultiEdit" in matchers, (
        f"PostToolUse must have 'Write|Edit|MultiEdit' matcher. Got: {matchers}"
    )
    assert "Task" in matchers, f"PostToolUse must have 'Task' matcher. Got: {matchers}"


def _collect_all_hook_commands(hooks: dict) -> list[str]:  # type: ignore[type-arg]
    """Collect all command strings from the hooks block.

    Per Claude Code hooks schema (code.claude.com/docs/en/hooks), every event
    entry MUST have an inner `hooks: [...]` array. Top-level `command` keys
    are NOT valid Claude Code schema and were rejected at session-start with
    a Settings Error in May 2026.
    """
    commands: list[str] = []
    for _event_type, entries in hooks.items():
        if isinstance(entries, list):
            for entry in entries:
                if "hooks" in entry and isinstance(entry["hooks"], list):
                    for hook in entry["hooks"]:
                        if "command" in hook:
                            commands.append(hook["command"])
    return commands


def test_every_event_entry_has_inner_hooks_array(hooks: dict) -> None:  # type: ignore[type-arg]
    """Every event entry MUST have an inner `hooks: [...]` array.

    Regression for the 2026-05-06 settings.json schema bug where Stop and
    PreCompact entries had `{type, command}` directly instead of being
    wrapped in `{hooks: [{type, command}]}`. Claude Code rejected the file
    at session start with a Settings Error.

    Per docs (code.claude.com/docs/en/hooks): all 4 event types
    (PreToolUse, PostToolUse, Stop, PreCompact) take a list of entries
    where each entry has shape `{matcher?: str, hooks: [{type, command}]}`.
    The `matcher` is optional for Stop/PreCompact. The `hooks` array is
    REQUIRED for every entry.
    """
    for event_type, entries in hooks.items():
        assert isinstance(entries, list), (
            f"hooks.{event_type} must be a list, got {type(entries).__name__}"
        )
        for i, entry in enumerate(entries):
            assert "hooks" in entry, (
                f"hooks.{event_type}[{i}] missing inner 'hooks' array.\n"
                f"  Got: {entry!r}\n"
                f"  WHY: Claude Code rejects entries without the inner hooks array "
                f"with a Settings Error at session start (2026-05-06 incident).\n"
                f"  FIX: wrap commands in {{'hooks': [{{...}}]}} — see "
                f"code.claude.com/docs/en/hooks for the canonical schema.\n"
                f"  EXAMPLE:\n"
                f"    BAD:  {{'type': 'command', 'command': '...'}}\n"
                f"    GOOD: {{'hooks': [{{'type': 'command', 'command': '...'}}]}}"
            )
            assert isinstance(entry["hooks"], list), (
                f"hooks.{event_type}[{i}].hooks must be a list, got {type(entry['hooks']).__name__}"
            )
            assert len(entry["hooks"]) > 0, (
                f"hooks.{event_type}[{i}].hooks is empty — must contain at "
                f"least one {{type, command}} entry"
            )
            for j, hook in enumerate(entry["hooks"]):
                assert hook.get("type") == "command", (
                    f"hooks.{event_type}[{i}].hooks[{j}].type must be 'command', "
                    f"got {hook.get('type')!r}"
                )
                assert hook.get("command"), (
                    f"hooks.{event_type}[{i}].hooks[{j}].command is missing or empty"
                )


def test_each_hook_invokes_uv_run(hooks: dict) -> None:  # type: ignore[type-arg]
    """Every hook command must start with 'uv run python .claude/hooks/'."""
    commands = _collect_all_hook_commands(hooks)
    assert commands, "No hook commands found in settings.json"

    for cmd in commands:
        assert cmd.startswith("uv run python .claude/hooks/"), (
            f"Hook command must start with 'uv run python .claude/hooks/'\nGot: {cmd!r}"
        )


def test_all_hook_scripts_exist(hooks: dict) -> None:  # type: ignore[type-arg]
    """Every hook command must reference an existing .py script."""
    commands = _collect_all_hook_commands(hooks)
    assert commands, "No hook commands found"

    for cmd in commands:
        # Extract the script path from 'uv run python <path>'
        parts = cmd.split()
        if len(parts) >= 4 and parts[0] == "uv" and parts[2] == "python":
            script_path = Path(parts[3])
            assert script_path.exists(), (
                f"Hook command references non-existent script: {script_path}\n"
                f"Command: {cmd!r}\n"
                f"Create the script or fix the path in settings.json"
            )
