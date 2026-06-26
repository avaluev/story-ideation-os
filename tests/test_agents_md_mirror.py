"""Assert AGENTS.md is a byte-equal mirror of CLAUDE.md (HARN-02)."""
from __future__ import annotations

from pathlib import Path


def test_agents_md_byte_equal_or_symlink() -> None:
    """AGENTS.md must be a byte-equal copy of CLAUDE.md or a symlink pointing to it.

    AGENTS.md is the cross-tool mirror of CLAUDE.md for agents that read AGENTS.md
    by convention (e.g. Cursor, Windsurf). Byte-equality guarantees no drift.
    """
    claude_path = Path("CLAUDE.md")
    agents_path = Path("AGENTS.md")

    assert claude_path.exists(), "CLAUDE.md does not exist"
    assert agents_path.exists(), "AGENTS.md does not exist"

    # Case 1: symlink pointing to CLAUDE.md
    if agents_path.is_symlink():
        target = agents_path.resolve()
        expected = claude_path.resolve()
        assert target == expected, (
            f"AGENTS.md is a symlink but points to {target}, not {expected}."
        )
        return

    # Case 2: byte-equal copy
    claude_bytes = claude_path.read_bytes()
    agents_bytes = agents_path.read_bytes()
    assert claude_bytes == agents_bytes, (
        "CLAUDE.md and AGENTS.md are not byte-equal.\n"
        "FIX: run `cp CLAUDE.md AGENTS.md` after editing CLAUDE.md."
    )
