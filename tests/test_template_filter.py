"""Tests for pipeline.template_filter — strip_internal_ids + enforce_v2_sections.

SKIP until Wave C creates pipeline/template_filter.py.
"""

from __future__ import annotations

import pytest

_tf = pytest.importorskip("pipeline.template_filter", reason="defensive import guard")
strip_internal_ids = _tf.strip_internal_ids
enforce_v2_sections = _tf.enforce_v2_sections

# ── Fixtures ──────────────────────────────────────────────────────────────────

_CLEAN = (
    "# Station Tolerance\n\n"
    "- **Logline:** A station master discovers a document that rewrites everything.\n"
    "- **Tagline:** Every delay has a reason.\n\n"
    "# 1. Market & Audience\n\n"
    "## Revenue Thesis (Anchored to Comps)\nSolid projection.\n\n"
    "## Primary Audience Segment\n### Who They Are\nAdults 25-45.\n"
    "### Job-to-Be-Done\nThey want to understand systems of power.\n"
    "### Tonal Contract\nTense, cerebral, earned.\n"
    "### What Loses Them\nGenre confusion.\n\n"
    "## Why Now (Market Timing)\nRecent data shows demand.\n\n"
    "## Audience Sizing\n### TAM\n**TAM:** $5.0B\n"
    "### SAM\n**SAM:** $900M\n"
    "### SOM — Serviceable Obtainable Market (Year 1 realistic capture)\n"
    "**SOM (Year 1):** $120M\n\n"
    "## Comparables\n### Financial Comps\n| Title | Year | Format | Budget |"
    " WW Revenue | Why Comparable | Source |\n"
    "### Tonal Comps\nThree titles.\n"
    "### Structural Comps\nThree more.\n\n"
    "# 2. The Concept\n\n## Format & Genre\n## The Contradiction\n"
    "## Psychological Tension\n## Indelible Image\n## Mass-Appeal Theme\n"
    "## Fact-Fiction Blend\n\n"
    "# 3. Story\n\n## Synopsis\n## Emotional Arc\n## Cinematic Parallels\n"
    "## Visual Style & Tone\n\n"
    "# 4. Characters\n\n## Protagonist\n## Antagonist\n## Ally / Supporting\n\n"
    "## References\n1. [Source](https://example.com/deep/path) — context.\n"
)

_CONTAMINATED = (
    "# Station Tolerance\n\n"
    "This story uses the TRIZ contradiction matrix.\n"
    "The protagonist follows a JTBD framework.\n"
    "Arc shape based on Booker plot type: Voyage and Return.\n"
    "McKee's controlling idea is applied here.\n"
    "Boden transformational creativity is the engine.\n"
    "Reagan arc drives the structure.\n"
    "Cell-ID: BT-042 drives the binary tension.\n"
    "Per L002, this was improved in iter-3.\n"
    "Working title: draft-concept-007.\n"
    "Lessons consulted: L001, L002.\n"
    "BT-042 is the core tension.\n"
    "PS-010 supporting premise.\n"
    "Run ID: 2026-05-12T14:00:00Z.\n"
)


# ── strip_internal_ids tests ──────────────────────────────────────────────────


class TestStripInternalIds:
    def test_clean_text_unchanged(self) -> None:
        result = strip_internal_ids(_CLEAN)
        assert result == _CLEAN

    def test_triz_removed(self) -> None:
        result = strip_internal_ids("This uses TRIZ contradiction.")
        assert "TRIZ" not in result

    def test_jtbd_removed(self) -> None:
        result = strip_internal_ids("The JTBD framework is used.")
        assert "JTBD" not in result

    def test_booker_removed(self) -> None:
        result = strip_internal_ids("Booker plot: Voyage and Return.")
        assert "Booker" not in result

    def test_mckee_removed(self) -> None:
        result = strip_internal_ids("McKee says this works.")
        assert "McKee" not in result

    def test_boden_removed(self) -> None:
        result = strip_internal_ids("Boden combinatorial creativity.")
        assert "Boden" not in result

    def test_cell_id_removed(self) -> None:
        result = strip_internal_ids("Cell-ID: BT-042")
        assert "Cell-ID:" not in result

    def test_per_lesson_ref_removed(self) -> None:
        result = strip_internal_ids("Per L002, this was improved.")
        assert "Per L" not in result

    def test_iter_ref_removed(self) -> None:
        result = strip_internal_ids("This is from iter-3 of the draft.")
        assert "iter-3" not in result

    def test_working_title_removed(self) -> None:
        result = strip_internal_ids("Working title: draft-007")
        assert "Working title" not in result

    def test_bt_id_removed(self) -> None:
        result = strip_internal_ids("Binary tension BT-042 drives this.")
        assert "BT-" not in result

    def test_lessons_consulted_removed(self) -> None:
        result = strip_internal_ids("Lessons consulted: L001, L002.")
        assert "Lessons consulted" not in result

    def test_run_id_removed(self) -> None:
        result = strip_internal_ids("Run ID: 2026-05-12T14:00:00Z")
        assert "Run ID:" not in result

    def test_all_banned_patterns_removed(self) -> None:
        result = strip_internal_ids(_CONTAMINATED)
        banned = [
            "TRIZ",
            "JTBD",
            "Booker",
            "McKee",
            "Boden",
            "Reagan arc",
            "Cell-ID:",
            "Per L",
            "iter-3",
            "Working title",
            "BT-042",
            "PS-010",
            "Lessons consulted",
            "Run ID:",
        ]
        for term in banned:
            assert term not in result, f"Expected '{term}' to be stripped"

    def test_returns_string(self) -> None:
        result = strip_internal_ids("clean text")
        assert isinstance(result, str)


# ── enforce_v2_sections tests ─────────────────────────────────────────────────


class TestEnforceV2Sections:
    def test_valid_doc_returns_no_issues(self) -> None:
        issues = enforce_v2_sections(_CLEAN)
        assert issues == []

    def test_missing_market_section_flagged(self) -> None:
        doc = _CLEAN.replace("# 1. Market & Audience", "## Removed")
        issues = enforce_v2_sections(doc)
        assert any("Market" in i for i in issues)

    def test_missing_concept_section_flagged(self) -> None:
        doc = _CLEAN.replace("# 2. The Concept", "## Removed")
        issues = enforce_v2_sections(doc)
        assert any("Concept" in i for i in issues)

    def test_missing_story_section_flagged(self) -> None:
        doc = _CLEAN.replace("# 3. Story", "## Removed")
        issues = enforce_v2_sections(doc)
        assert any("Story" in i for i in issues)

    def test_missing_characters_section_flagged(self) -> None:
        doc = _CLEAN.replace("# 4. Characters", "## Removed")
        issues = enforce_v2_sections(doc)
        assert any("Characters" in i for i in issues)

    def test_returns_list(self) -> None:
        result = enforce_v2_sections(_CLEAN)
        assert isinstance(result, list)

    def test_empty_doc_flags_all_four_sections(self) -> None:
        issues = enforce_v2_sections("# Film Title\n\nSome text.\n")
        assert len(issues) >= 4
