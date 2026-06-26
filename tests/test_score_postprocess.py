"""Tests for pipeline/score_postprocess.py — placeholder replacement."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.score_postprocess import PLACEHOLDER, apply


def test_replaces_placeholder_with_integer_score(tmp_path: Path) -> None:
    """Standard case: critique row has overall_score.final=87 → placeholder becomes '87'."""
    out_dir = tmp_path / "out" / "concepts"
    out_dir.mkdir(parents=True)
    md_file = out_dir / "concept-001.md"
    md_file.write_text(f"# Title\n\n## Score\n\n**{PLACEHOLDER}/100**\n", encoding="utf-8")

    critiques = tmp_path / "data" / "05_critiques.jsonl"
    critiques.parent.mkdir(parents=True)
    critiques.write_text(
        json.dumps({"concept_id": "concept-001", "overall_score": {"final": 87}}) + "\n",
        encoding="utf-8",
    )

    n = apply(out_dir=out_dir, critiques_path=critiques)
    assert n == 1
    content = md_file.read_text(encoding="utf-8")
    assert PLACEHOLDER not in content
    assert "**87/100**" in content


def test_skips_files_without_placeholder(tmp_path: Path) -> None:
    """Files that already have the score (no placeholder) are not modified."""
    out_dir = tmp_path / "out" / "concepts"
    out_dir.mkdir(parents=True)
    md_file = out_dir / "concept-002.md"
    original = "# Title\n\n## Score\n\n**91/100**\n"
    md_file.write_text(original, encoding="utf-8")

    critiques = tmp_path / "data" / "05_critiques.jsonl"
    critiques.parent.mkdir(parents=True)
    critiques.write_text(
        json.dumps({"concept_id": "concept-002", "overall_score": {"final": 91}}) + "\n",
        encoding="utf-8",
    )

    n = apply(out_dir=out_dir, critiques_path=critiques)
    assert n == 0
    assert md_file.read_text(encoding="utf-8") == original


def test_skips_files_without_matching_critique(tmp_path: Path) -> None:
    """If a concept has no critique row, the file is left as-is."""
    out_dir = tmp_path / "out" / "concepts"
    out_dir.mkdir(parents=True)
    md_file = out_dir / "concept-orphan.md"
    md_file.write_text(f"## Score\n\n**{PLACEHOLDER}/100**\n", encoding="utf-8")

    critiques = tmp_path / "data" / "05_critiques.jsonl"
    critiques.parent.mkdir(parents=True)
    critiques.write_text("", encoding="utf-8")

    n = apply(out_dir=out_dir, critiques_path=critiques)
    assert n == 0
    assert PLACEHOLDER in md_file.read_text(encoding="utf-8")


def test_renders_decimal_score(tmp_path: Path) -> None:
    """A score of 86.5 is rendered as '86.5', not '86' or '86.50'."""
    out_dir = tmp_path / "out" / "concepts"
    out_dir.mkdir(parents=True)
    md_file = out_dir / "concept-003.md"
    md_file.write_text(f"**{PLACEHOLDER}/100**", encoding="utf-8")

    critiques = tmp_path / "data" / "05_critiques.jsonl"
    critiques.parent.mkdir(parents=True)
    critiques.write_text(
        json.dumps({"concept_id": "concept-003", "overall_score": {"final": 86.5}}) + "\n",
        encoding="utf-8",
    )

    apply(out_dir=out_dir, critiques_path=critiques)
    assert md_file.read_text(encoding="utf-8") == "**86.5/100**"


def test_handles_empty_out_dir(tmp_path: Path) -> None:
    """No concept files → returns 0; does not raise."""
    out_dir = tmp_path / "out" / "concepts"  # does not exist
    critiques = tmp_path / "critiques.jsonl"
    critiques.write_text("", encoding="utf-8")

    n = apply(out_dir=out_dir, critiques_path=critiques)
    assert n == 0
