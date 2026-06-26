"""Tests for load_framework() in pipeline/run.py (PIPE-14).

Verifies:
- load_framework(["sdt-spine"]) returns XML-tagged framework content
- Module-level cache: second call does NOT re-read from disk
- load_framework(["anti_slop"]) resolves to prompts/anti_slop.md

These tests are RED until pipeline/run.py is implemented (Task 3).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipeline.run")

from pipeline.run import _FRAMEWORK_CACHE, load_framework


def test_load_framework_xml_tags(tmp_path: pytest.MonkeyPatch) -> None:
    """load_framework(['sdt-spine']) wraps content in <framework name="sdt-spine">."""
    result = load_framework(["sdt-spine"])
    assert '<framework name="sdt-spine">' in result
    assert "</framework>" in result


def test_load_framework_contains_content() -> None:
    """Returned string must contain non-empty framework body text."""
    result = load_framework(["sdt-spine"])
    # Strip the XML wrapper — content must be non-trivial
    assert len(result) > len('<framework name="sdt-spine"></framework>')


def test_load_framework_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call to load_framework must use cache — file not re-read from disk."""
    # Clear cache before test
    _FRAMEWORK_CACHE.clear()

    read_count = 0

    original_read_text = type(__import__("pathlib").Path(".")).read_text

    def counting_read_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal read_count
        read_count += 1
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("pathlib.Path.read_text", counting_read_text)

    _FRAMEWORK_CACHE.clear()  # ensure cold cache
    load_framework(["sdt-spine"])
    first_count = read_count

    load_framework(["sdt-spine"])  # cache hit — no disk read
    assert read_count == first_count, (
        f"Expected no additional disk reads on second call; "
        f"got {read_count - first_count} extra read(s)"
    )


def test_load_framework_anti_slop() -> None:
    """load_framework(['anti_slop']) resolves prompts/anti_slop.md."""
    result = load_framework(["anti_slop"])
    assert '<framework name="anti_slop">' in result
    assert "</framework>" in result
    # anti_slop.md has content about slop patterns
    assert len(result) > 50


def test_load_framework_not_found() -> None:
    """load_framework raises FileNotFoundError for unknown framework names."""
    with pytest.raises(FileNotFoundError, match="nonexistent_framework"):
        load_framework(["nonexistent_framework"])


def test_load_framework_multiple() -> None:
    """load_framework(['sdt-spine', 'anti_slop']) concatenates both with newline."""
    result = load_framework(["sdt-spine", "anti_slop"])
    assert '<framework name="sdt-spine">' in result
    assert '<framework name="anti_slop">' in result
