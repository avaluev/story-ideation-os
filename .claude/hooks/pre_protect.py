#!/usr/bin/env python3
"""PreToolUse(Write|Edit|MultiEdit) hook — protected config guard.

HARN-07: The agent MUST NOT silently edit linter/type-checker configs to
suppress errors. This hook blocks any Write/Edit/MultiEdit operation targeting
a protected config file and injects a WHY/FIX/EXAMPLE message so the agent
understands what to do instead.

Exit codes:
  0 → allow (not a protected file)
  2 → block (protected file — stderr re-injected into agent context)

See: ADR-0001/0002, CLAUDE.md MUST NOT §5.
"""

from __future__ import annotations

import json
import sys
from fnmatch import fnmatch

PROTECTED = [
    "pyproject.toml",
    ".ruff.toml",
    "ruff.toml",
    "lefthook.yml",
    "pyrightconfig.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    "Makefile",
    "uv.lock",
]

BLOCKED_MSG = """\
BLOCKED: {file_path!r} is a protected config file.
  WHY: the agent must fix the source code, not silence the linter \
(ADR-0001/0002 + HARN-07).
  FIX: address the lint/type errors in the source files instead of \
editing the linter config.
  EXAMPLE: if `ruff` reports F401 unused-import, REMOVE the import. \
Don't add F401 to ignore list.
"""


def is_protected(file_path: str) -> bool:
    """Return True if file_path resolves to a protected config."""
    if not file_path:
        return False

    # Check full path suffix match first (handles .claude/settings.json etc.)
    for protected in PROTECTED:
        if file_path == protected:
            return True
        if file_path.endswith("/" + protected):
            return True

    # Check basename match for simple filenames
    basename = file_path.rsplit("/", 1)[-1]
    return any(
        "/" not in protected and fnmatch(basename, protected)
        for protected in PROTECTED
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed payload — allow (don't block on our own error)
        return 0

    file_path: str = payload.get("tool_input", {}).get("file_path", "") or ""

    if is_protected(file_path):
        print(BLOCKED_MSG.format(file_path=file_path), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
