"""Tests for Issue #10: pipeline/lessons_loader.py."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.lessons_loader import load_failures


def test_load_failures_empty_when_no_runs_dir(tmp_path: Path) -> None:
    """Returns [] when runs/ directory does not exist."""
    result = load_failures(run_root=tmp_path / "nonexistent")
    assert result == []


def test_load_failures_empty_when_no_lessons_files(tmp_path: Path) -> None:
    """Returns [] when runs/ exists but no lessons.json files are present."""
    (tmp_path / "run_001").mkdir()
    (tmp_path / "run_001" / "seed.json").write_text("{}", encoding="utf-8")
    result = load_failures(run_root=tmp_path)
    assert result == []


def test_load_failures_returns_strings_from_lessons(tmp_path: Path) -> None:
    """Returns key_failures strings from a lessons.json file."""
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    lessons = {"key_failures": ["premise was too generic", "audience sizing was off"]}
    (run_dir / "lessons.json").write_text(json.dumps(lessons), encoding="utf-8")
    result = load_failures(run_root=tmp_path)
    assert "premise was too generic" in result
    assert "audience sizing was off" in result


def test_load_failures_respects_max_items(tmp_path: Path) -> None:
    """Returns at most max_items unique failures."""
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    failures = [f"failure {i}" for i in range(20)]
    (run_dir / "lessons.json").write_text(json.dumps({"key_failures": failures}), encoding="utf-8")
    result = load_failures(run_root=tmp_path, max_items=3)
    assert len(result) <= 3


def test_load_failures_deduplicates_across_runs(tmp_path: Path) -> None:
    """Duplicate failure strings are returned only once."""
    for name in ("run_a", "run_b"):
        d = tmp_path / name
        d.mkdir()
        (d / "lessons.json").write_text(
            json.dumps({"key_failures": ["same failure"]}), encoding="utf-8"
        )
    result = load_failures(run_root=tmp_path)
    assert result.count("same failure") == 1


def test_load_failures_finds_lessons_in_trail(tmp_path: Path) -> None:
    """Finds lessons.json inside a _trail/ subdirectory (post-reorganize_run)."""
    run_dir = tmp_path / "run_001"
    trail_dir = run_dir / "_trail"
    trail_dir.mkdir(parents=True)
    (trail_dir / "lessons.json").write_text(
        json.dumps({"key_failures": ["trail failure"]}), encoding="utf-8"
    )
    result = load_failures(run_root=tmp_path)
    assert "trail failure" in result


def test_load_failures_skips_malformed_json(tmp_path: Path) -> None:
    """Skips runs whose lessons.json is not valid JSON without raising."""
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    (run_dir / "lessons.json").write_text("{not valid json", encoding="utf-8")
    result = load_failures(run_root=tmp_path)
    assert result == []


def test_load_failures_skips_non_list_key_failures(tmp_path: Path) -> None:
    """Skips entries where key_failures is not a list."""
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    (run_dir / "lessons.json").write_text(
        json.dumps({"key_failures": "not a list"}), encoding="utf-8"
    )
    result = load_failures(run_root=tmp_path)
    assert result == []
