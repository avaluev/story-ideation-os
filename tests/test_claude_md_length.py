"""Assert CLAUDE.md is <=250 lines (HARN-01)."""
from __future__ import annotations

from pathlib import Path


def test_claude_md_under_250_lines() -> None:
    """CLAUDE.md must not exceed 250 lines.

    Exceeding 250 lines signals that non-policy content (examples, rationale,
    commentary) has crept in. CLAUDE.md is a MUST/MUST NOT contract only.
    """
    lines = Path("CLAUDE.md").read_text().splitlines()
    assert len(lines) <= 250, (
        f"CLAUDE.md has {len(lines)} lines; maximum is 250.\n"
        "FIX: extract commentary/examples to docs/ or ADRs; keep MUST/MUST NOT only."
    )
