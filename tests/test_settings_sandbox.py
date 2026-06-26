"""Tests for .claude/settings.json sandbox permissions — SEC-08.

Validates the deny and allow lists are structurally complete.
Does NOT test runtime sandbox enforcement (that is a Claude Code runtime behavior).

Verifies:
- JSON parses without error
- deny list contains required security entries (curl, wget, sudo, chmod 777)
- deny list blocks .env reads
- deny list blocks protected config writes
- allow list includes uv/make/git commands
- allow list includes project write paths

Policy note (2026-05-11): Inputs/ reads are permanently allowed by operator
decision. The prior Inputs/ read-block was removed alongside this test's
removal. Inputs/ is operator-curated source material; if the operator
chooses to keep plaintext secrets there, that is on the operator. Secrets
remain protected via the .env and .env.* deny rules above.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SETTINGS_FILE = Path(".claude/settings.json")


@pytest.fixture(scope="module")
def settings() -> dict:  # type: ignore[type-arg]
    """Load .claude/settings.json once for all tests."""
    with open(SETTINGS_FILE) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def deny(settings: dict) -> list[str]:  # type: ignore[type-arg]
    """Extract deny list from settings."""
    return settings["permissions"]["deny"]


@pytest.fixture(scope="module")
def allow(settings: dict) -> list[str]:  # type: ignore[type-arg]
    """Extract allow list from settings."""
    return settings["permissions"]["allow"]


def test_settings_json_parses(settings: dict) -> None:
    """SEC-08: .claude/settings.json must be valid JSON with permissions block."""
    assert "permissions" in settings, ".claude/settings.json missing 'permissions' key"
    assert "allow" in settings["permissions"], "permissions missing 'allow' list"
    assert "deny" in settings["permissions"], "permissions missing 'deny' list"


def test_deny_list_blocks_curl_wget_sudo_chmod(deny: list[str]) -> None:
    """SEC-08: deny list must block dangerous shell commands."""
    required = {"Bash(curl:*)", "Bash(wget:*)", "Bash(sudo:*)", "Bash(chmod 777:*)"}
    missing = required - set(deny)
    assert not missing, (
        f"deny list is missing required blocks: {sorted(missing)}\n"
        "These commands must be denied to prevent data exfiltration and privilege escalation."
    )


def test_deny_list_blocks_env_reads(deny: list[str]) -> None:
    """SEC-08: deny list must block reads of .env and .env.* files."""
    assert "Read(./.env)" in deny, "deny list missing 'Read(./.env)'"
    assert "Read(./.env.*)" in deny, "deny list missing 'Read(./.env.*)'"


def test_deny_list_blocks_protected_writes(deny: list[str]) -> None:
    """SEC-08: deny list must block writes to protected config files.

    Agent MUST NOT silence linters by editing pyproject.toml, .ruff.toml,
    lefthook.yml, or uv.lock (belt-and-suspenders beyond the pre_protect.py hook).
    """
    required = {
        "Write(./pyproject.toml)",
        "Write(./.ruff.toml)",
        "Write(./lefthook.yml)",
        "Write(./uv.lock)",
        "Write(./.claude/settings.json)",
    }
    missing = required - set(deny)
    assert not missing, (
        f"deny list is missing protected-write blocks: {sorted(missing)}\n"
        "Agents must not be able to silence linters by editing config files."
    )


def test_allow_list_includes_uv_make_git(allow: list[str]) -> None:
    """SEC-08: allow list must include development commands."""
    required = {
        "Bash(uv run:*)",
        "Bash(make:*)",
        "Bash(git status)",
        "Bash(git push:*)",
    }
    missing = required - set(allow)
    assert not missing, (
        f"allow list is missing required entries: {sorted(missing)}\n"
        "Development commands must be explicitly allowed."
    )


def test_allow_list_includes_project_writes(allow: list[str]) -> None:
    """SEC-08: allow list must include Write permissions for project subdirectories."""
    assert "Write(./pipeline/**)" in allow, "allow list missing 'Write(./pipeline/**)'"
    assert "Write(./.planning/**)" in allow, "allow list missing 'Write(./.planning/**)'"
