"""tests/test_themes_queue.py — OPS-09: Themes queue add/next mechanics.

Tests for scripts/themes_queue.py — the add_theme() and next_theme()
CLI helpers that manage data/themes_queue.jsonl.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import scripts.themes_queue as tq  # type: ignore[import-untyped]
from scripts.themes_queue import add_theme, next_theme  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect QUEUE_PATH to a temp dir for every test."""
    monkeypatch.setattr(tq, "QUEUE_PATH", tmp_path / "themes_queue.jsonl")


# ---------------------------------------------------------------------------
# add_theme tests
# ---------------------------------------------------------------------------


def test_add_theme_appends_jsonl() -> None:
    """add_theme writes one JSONL line with correct fields."""
    queue_path: Path = tq.QUEUE_PATH
    add_theme("Cold War spy satellites")
    assert queue_path.exists(), "JSONL file not created"
    lines = [ln for ln in queue_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
    row = json.loads(lines[0])
    assert row["theme"] == "Cold War spy satellites"
    assert row["status"] == "pending"
    assert "added_at" in row


def test_add_theme_prints_position(capsys: pytest.CaptureFixture) -> None:
    """add_theme output must match 'Added: {theme} (position N/N)'."""
    add_theme("Cold War spy satellites")
    captured = capsys.readouterr()
    assert "Added: Cold War spy satellites (position 1/1)" in captured.out


def test_add_theme_empty_string_rejected() -> None:
    """add_theme('') must raise SystemExit(1)."""
    with pytest.raises(SystemExit) as exc_info:
        add_theme("")
    assert exc_info.value.code == 1


def test_add_theme_whitespace_only_rejected() -> None:
    """add_theme('   ') must raise SystemExit(1)."""
    with pytest.raises(SystemExit) as exc_info:
        add_theme("   ")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# next_theme tests
# ---------------------------------------------------------------------------


def test_next_theme_prints_format(capsys: pytest.CaptureFixture) -> None:
    """next_theme() prints '[1/1] {theme} (added YYYY-MM-DD)'."""
    add_theme("Cold War spy satellites")
    next_theme()
    captured = capsys.readouterr()
    out = captured.out
    assert "[1/1] Cold War spy satellites" in out, f"Unexpected output: {out!r}"
    assert re.search(r"\(added \d{4}-\d{2}-\d{2}\)", out), (
        f"No 'added YYYY-MM-DD' pattern in output: {out!r}"
    )


def test_next_theme_empty_queue_prints_message(capsys: pytest.CaptureFixture) -> None:
    """next_theme() on empty queue prints 'Queue is empty.'."""
    next_theme()
    captured = capsys.readouterr()
    assert "Queue is empty." in captured.out, f"Unexpected output: {captured.out!r}"


def test_next_theme_is_readonly(capsys: pytest.CaptureFixture) -> None:
    """Calling next_theme() twice returns the same entry (queue not advanced)."""
    add_theme("Cold War spy satellites")
    capsys.readouterr()  # drain add_theme output before comparing next_theme calls
    next_theme()
    first = capsys.readouterr().out
    next_theme()
    second = capsys.readouterr().out
    assert first == second, f"next_theme() is not idempotent: first={first!r}, second={second!r}"
