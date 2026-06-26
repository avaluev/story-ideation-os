"""Tests for .env.example — SEC-06.

Asserts:
- .env.example exists with all 6 required keys
- placeholder values (not real secrets)
- no real .env* files are tracked by git
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ENV_EXAMPLE = Path(".env.example")

REQUIRED_KEYS = {
    "OPENROUTER_KEY_PAID",
    "OPENROUTER_KEY_FREE_1",
    "OPENROUTER_KEY_FREE_2",
    "ANTHROPIC_API_KEY",
    "DAILY_USD_CAP",
    "MONTHLY_USD_CAP",
}


def _parse_env_example() -> dict[str, str]:
    """Parse .env.example as KEY=VALUE pairs; skip comments and blank lines."""
    result: dict[str, str] = {}
    for raw_line in ENV_EXAMPLE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def test_env_example_exists() -> None:
    """SEC-06: .env.example must exist."""
    assert ENV_EXAMPLE.exists(), (
        ".env.example does not exist.\n"
        "Create it with all required keys: "
        f"{', '.join(sorted(REQUIRED_KEYS))}"
    )


def test_env_example_lists_required_keys() -> None:
    """SEC-06: .env.example must enumerate all 6 required keys."""
    parsed = _parse_env_example()
    missing = REQUIRED_KEYS - set(parsed.keys())
    assert not missing, (
        f".env.example is missing required keys: {sorted(missing)}\n"
        f"Found keys: {sorted(parsed.keys())}"
    )


def test_env_example_has_placeholder_values() -> None:
    """SEC-06: .env.example values must be placeholders, not real keys.

    OPENROUTER_KEY_* and ANTHROPIC_API_KEY must contain 'REPLACE-ME' (uppercase).
    Budget cap values must be all-digit strings.
    """
    parsed = _parse_env_example()

    key_fields = {
        "OPENROUTER_KEY_PAID",
        "OPENROUTER_KEY_FREE_1",
        "OPENROUTER_KEY_FREE_2",
        "ANTHROPIC_API_KEY",
    }
    cap_fields = {"DAILY_USD_CAP", "MONTHLY_USD_CAP"}

    for field in key_fields:
        if field not in parsed:
            continue  # covered by test_env_example_lists_required_keys
        value = parsed[field]
        assert "REPLACE-ME" in value, (
            f".env.example[{field}] does not contain 'REPLACE-ME'.\n"
            f"Value: {value!r}\n"
            "Use placeholder values like 'sk-or-v1-REPLACE-ME-PAID'."
        )

    for field in cap_fields:
        if field not in parsed:
            continue
        value = parsed[field]
        assert value.isdigit(), (
            f".env.example[{field}] must be a digit-only string (e.g. '15').\n"
            f"Value: {value!r}"
        )


def test_env_example_not_real_env() -> None:
    """SEC-06: git must NOT track .env, .env.local, or other .env* variants.

    Only .env.example is allowed; all others should be gitignored.
    """
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()  # noqa: S607
    # Filter for .env* files
    env_files = [f for f in tracked if f.startswith(".env")]
    # Only .env.example is acceptable
    disallowed = [f for f in env_files if f != ".env.example"]
    assert not disallowed, (
        f"The following .env* files are tracked by git: {disallowed}\n"
        "Only .env.example should be committed; real .env files must be gitignored."
    )
