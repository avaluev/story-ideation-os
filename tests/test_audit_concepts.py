"""tests/test_audit_concepts.py — RED/GREEN tests for OPS-01 audit subcommands.

Tests cmd_check_concepts behavior:
- empty out/concepts/ → exit 0 (no concepts)
- valid concept → exit 0 (all pass)
- anti-slop term in concept → exit 1 (FAIL)
- quote >14 words in concept → exit 1 (FAIL)
- report file written on non-empty audit run
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

# Import under test — will raise NotImplementedError in RED state
import scripts.audit as audit_mod
from scripts.audit import cmd_check_citations, cmd_check_concepts, cmd_check_quotes

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_CONCEPT_MD = """\
---
concept_id: test_concept_01
overall_score: 85
---

# Test Concept Title

## Overview
A short description of the concept.

## Audience Evidence
Source: https://example.com/study-1
Source: https://other-domain.com/study-2

> Short quote here is fine.

## Market Opportunity
Some market claims with sources.
"""

ANTI_SLOP_CONCEPT_MD = """\
---
concept_id: test_concept_bad
---

# Slop Concept

## Overview
This concept is absolutely perfect and truly unique and visionary.

## Audience Evidence
Source: https://example.com/study
"""

LONG_QUOTE_CONCEPT_MD = """\
---
concept_id: test_concept_longquote
---

# Quote Concept

## Overview
A concept with a too-long quote.

## Audience Evidence
> This is a very long blockquote that has way more than fourteen words total in it and must fail.

Source: https://example.com/study
"""


def _make_args(concepts_dir: Path) -> argparse.Namespace:
    """Create a Namespace with concepts_dir pointing to tmp_path."""
    ns = argparse.Namespace()
    ns.concepts_dir = str(concepts_dir)
    return ns


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_dir_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Empty concepts directory → exit 0, prints 'No concepts found'."""
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir()
    args = _make_args(concepts_dir)
    result = cmd_check_concepts(args)
    assert result == 0
    captured = capsys.readouterr()
    assert "No concepts found" in captured.out or "No concepts found" in captured.err


def test_all_pass_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Valid concept with no banned terms and short quotes → exit 0, prints pass message."""
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir()
    (concepts_dir / "test_concept_01.md").write_text(VALID_CONCEPT_MD, encoding="utf-8")
    args = _make_args(concepts_dir)
    result = cmd_check_concepts(args)
    assert result == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "All 1 concepts passed audit." in combined


def test_fail_anti_slop_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concept with banned anti-slop term → exit 1, prints [FAIL] line with anti_slop_term."""
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir()
    (concepts_dir / "test_concept_bad.md").write_text(ANTI_SLOP_CONCEPT_MD, encoding="utf-8")

    # Inject a known banned term that appears in the fixture
    monkeypatch.setattr(
        "scripts.audit._load_banned_terms_for_concepts",
        lambda: ["truly unique"],
    )

    args = _make_args(concepts_dir)
    result = cmd_check_concepts(args)
    assert result == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "[FAIL]" in combined
    assert "anti_slop_term" in combined


def test_fail_quote_too_long_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concept with blockquote >14 words → exit 1, prints [FAIL] line with quote_too_long."""
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir()
    (concepts_dir / "test_concept_longquote.md").write_text(LONG_QUOTE_CONCEPT_MD, encoding="utf-8")
    monkeypatch.setattr("scripts.audit._load_banned_terms_for_concepts", lambda: [])

    args = _make_args(concepts_dir)
    result = cmd_check_concepts(args)
    assert result == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "[FAIL]" in combined
    assert "quote_too_long" in combined


def test_report_file_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On any non-empty audit run, data/audit/audit_report_*.md is created."""
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir()
    (concepts_dir / "test_concept_01.md").write_text(VALID_CONCEPT_MD, encoding="utf-8")
    monkeypatch.setattr("scripts.audit._load_banned_terms_for_concepts", lambda: [])

    # Override AUDIT_OUT_DIR so we write to tmp_path
    audit_out = tmp_path / "data" / "audit"

    monkeypatch.setattr(audit_mod, "AUDIT_OUT_DIR", audit_out)

    args = _make_args(concepts_dir)
    cmd_check_concepts(args)

    reports = list(audit_out.glob("audit_report_*.md"))
    assert len(reports) >= 1, f"No audit report file found in {audit_out}"


def test_check_quotes_help_available() -> None:
    """cmd_check_quotes should be callable without raising NotImplementedError (GREEN)."""
    # This test verifies the stub is replaced; it will fail in RED state.
    args = argparse.Namespace(concepts_dir="out/concepts")
    # Just ensure it doesn't raise NotImplementedError when concepts_dir is empty/missing
    # (may raise SystemExit or return int — both acceptable)
    try:
        result = cmd_check_quotes(args)
        assert isinstance(result, int)
    except NotImplementedError:
        pytest.fail("cmd_check_quotes still raises NotImplementedError (stub not implemented)")


def test_check_citations_help_available() -> None:
    """cmd_check_citations should be callable without raising NotImplementedError (GREEN)."""
    args = argparse.Namespace(concepts_dir="out/concepts")
    try:
        result = cmd_check_citations(args)
        assert isinstance(result, int)
    except NotImplementedError:
        pytest.fail("cmd_check_citations still raises NotImplementedError (stub not implemented)")
