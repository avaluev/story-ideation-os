#!/usr/bin/env python3
"""PreToolUse(Write|Edit|MultiEdit) hook — anti-slop write gate.

STAB-02 / M3.2: The agent MUST NOT silently edit prompts/anti_slop.md in
Auto Mode. A false-positive entry in anti_slop.md permanently neuters a
valid asset class — every future concept touching that token will be
suppressed without human review.

This hook blocks any Write/Edit/MultiEdit operation targeting
prompts/anti_slop.md and injects a WHY/FIX/EXAMPLE message so the agent
understands what to do instead.

Exit codes:
  0 → allow (not the protected anti-slop file)
  2 → block (protected file — stderr re-injected into agent context)

See: STAB-01 (docs/stabilization-cycle.md), STAB-02, CLAUDE.md.
"""

from __future__ import annotations

import json
import sys

PROTECTED_PATHS = ["prompts/anti_slop.md"]

BLOCKED_MSG = """\
BLOCKED: {file_path!r} requires human approval before editing.
  WHY: prompts/anti_slop.md guards the engine's slop prevention. A false-positive
       entry permanently neuters a valid asset class (STAB-02 / M3.2).
  FIX: review the proposed change with the operator. Obtain explicit approval.
  EXAMPLE: run 'make eval' first to confirm the pattern is genuinely sloppy,
           then manually approve and edit.
"""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed payload — allow (don't block on our own error)
        return 0

    file_path: str = payload.get("tool_input", {}).get("file_path", "") or ""

    for protected in PROTECTED_PATHS:
        if file_path == protected or file_path.endswith("/" + protected):
            print(BLOCKED_MSG.format(file_path=file_path), file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
