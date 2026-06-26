"""SEC-09: CI grep for OpenRouter/Anthropic/GitHub key prefixes in tracked files.

Greps all files tracked by git for known API key prefixes.
Fails if any match is found outside the exempt set.

Defense-in-depth layer 3: independent of git hooks; runs in CI on every push/PR.

Exempt set: {".env.example"} — contains intentional REPLACE-ME placeholders
that start with the key prefix format but are not real keys.

Note: .env.example placeholders use format 'sk-or-v1-REPLACE-ME-PAID' which
contains hyphens and uppercase after the prefix, so they would NOT match the
real-key regex patterns below (which require hex chars or long base62 strings).
The EXEMPT set is belt-and-suspenders for any future changes.
"""
from __future__ import annotations

import re
import subprocess

PREFIXES = [
    re.compile(r"sk-or-v1-[a-f0-9]{40,}"),
    re.compile(r"sk-ant-[a-zA-Z0-9_-]{40,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{30,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{60,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xoxb-[0-9a-zA-Z-]{40,}"),
]
EXEMPT = {".env.example"}


def test_no_secrets_in_tracked_files() -> None:
    """SEC-09: No tracked file (except .env.example) may contain a real API key prefix."""
    files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()  # noqa: S607
    failures: list[str] = []
    for f in files:
        if f in EXEMPT:
            continue
        try:
            content = open(f, "rb").read().decode("utf-8", errors="replace")  # noqa: SIM115
        except OSError:
            continue
        for prefix in PREFIXES:
            if prefix.search(content):
                failures.append(f"{f}: matched {prefix.pattern}")
    assert not failures, (
        "Secrets found in tracked files:\n"
        + "\n".join(failures)
        + "\n\nFIX: remove the secrets, rotate any exposed keys, "
        + "and commit a sanitized version."
    )
