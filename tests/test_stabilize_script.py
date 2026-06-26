"""tests/test_stabilize_script.py — Unit + integration tests for scripts/stabilize.py.

Tests STAB-04: make stabilize reads data/stabilization_queue.jsonl,
appends formatted entries to prompts/anti_slop.md, and stages via git add.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

scripts_stabilize = pytest.importorskip(
    "scripts.stabilize",
    reason="scripts/stabilize.py not yet implemented (RED state)",
)

stage_patterns = scripts_stabilize.stage_patterns
main = scripts_stabilize.main
QUEUE_PATH = scripts_stabilize.QUEUE_PATH
ANTI_SLOP_PATH = scripts_stabilize.ANTI_SLOP_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_queue(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _sample_row(concept_id: str = "cid-001", pattern: str = "No clichéd openings") -> dict:
    return {
        "concept_id": concept_id,
        "pattern": pattern,
        "queued_at": "2026-05-08T03:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_queue_no_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """When QUEUE_PATH does not exist, main() exits 0 and prints 'No patterns queued.'"""
    queue_path = tmp_path / "queue.jsonl"
    anti_slop_path = tmp_path / "anti_slop.md"
    anti_slop_path.write_text("# existing content\n")

    with (
        patch.object(scripts_stabilize, "QUEUE_PATH", queue_path),
        patch.object(scripts_stabilize, "ANTI_SLOP_PATH", anti_slop_path),
    ):
        result = stage_patterns(queue_path=queue_path, anti_slop_path=anti_slop_path)

    captured = capsys.readouterr()
    assert result == 0
    assert "No patterns queued." in captured.out


def test_empty_queue(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """An existing but empty queue file also exits 0 and prints 'No patterns queued.'"""
    queue_path = tmp_path / "queue.jsonl"
    queue_path.write_text("")  # empty file
    anti_slop_path = tmp_path / "anti_slop.md"
    anti_slop_path.write_text("# existing content\n")

    result = stage_patterns(queue_path=queue_path, anti_slop_path=anti_slop_path)

    captured = capsys.readouterr()
    assert result == 0
    assert "No patterns queued." in captured.out


def test_stage_patterns_nonempty(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """With one queued row, stage_patterns() writes to anti_slop file and calls git add."""
    queue_path = tmp_path / "queue.jsonl"
    anti_slop_path = tmp_path / "anti_slop.md"
    anti_slop_path.write_text("# Anti-Slop Patterns\n")
    _write_queue(queue_path, [_sample_row()])

    git_calls: list = []

    def fake_subprocess_run(cmd: list, **kwargs: object) -> MagicMock:
        git_calls.append(cmd)
        mock = MagicMock()
        mock.returncode = 0
        return mock

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = stage_patterns(queue_path=queue_path, anti_slop_path=anti_slop_path)

    assert result == 0
    # anti_slop file must have been written
    content = anti_slop_path.read_text()
    assert "No clichéd openings" in content
    # git add must have been called
    assert len(git_calls) >= 1
    assert "git" in git_calls[0]
    assert "add" in git_calls[0]


def test_comment_format(tmp_path: Path) -> None:
    """Each staged line must match: '- <pattern>  # added YYYY-MM-DD, triggered by <concept_id>'"""
    queue_path = tmp_path / "queue.jsonl"
    anti_slop_path = tmp_path / "anti_slop.md"
    anti_slop_path.write_text("# Anti-Slop Patterns\n")
    _write_queue(queue_path, [_sample_row(concept_id="cid-007", pattern="No redemption arcs")])

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        stage_patterns(queue_path=queue_path, anti_slop_path=anti_slop_path)

    content = anti_slop_path.read_text()
    comment_pattern = re.compile(
        r"- .+  # added \d{4}-\d{2}-\d{2}, triggered by \w+",
    )
    matches = comment_pattern.findall(content)
    assert len(matches) >= 1, f"No line matching comment format found in:\n{content!r}"


def test_multiple_rows_all_staged(tmp_path: Path) -> None:
    """All rows in the queue are written to anti_slop and git add is called once."""
    queue_path = tmp_path / "queue.jsonl"
    anti_slop_path = tmp_path / "anti_slop.md"
    anti_slop_path.write_text("# Anti-Slop\n")
    rows = [
        _sample_row("cid-001", "Pattern alpha"),
        _sample_row("cid-002", "Pattern beta"),
        _sample_row("cid-003", "Pattern gamma"),
    ]
    _write_queue(queue_path, rows)

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        result = stage_patterns(queue_path=queue_path, anti_slop_path=anti_slop_path)

    assert result == 0
    content = anti_slop_path.read_text()
    assert "Pattern alpha" in content
    assert "Pattern beta" in content
    assert "Pattern gamma" in content
