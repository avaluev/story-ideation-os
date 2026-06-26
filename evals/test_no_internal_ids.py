"""EVAL -- No internal IDs in investor-facing .md files.

Scans final runs/*.md files for banned framework labels, internal IDs, and
pipeline metadata. Any match is a FAIL.

SKIP until Wave C creates pipeline/template_filter.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_tf = pytest.importorskip("pipeline.template_filter", reason="defensive import guard")
scan_for_internal_ids = _tf.scan_for_internal_ids

# ── Inline fixtures ───────────────────────────────────────────────────────────

_CLEAN_DOC = """\
# Station Tolerance

- **Logline:** A station master uncovers evidence that rewrites history.
- **Tagline:** Every delay has a reason.

# 1. Market & Audience

## Revenue Thesis (Anchored to Comps)
A mid-budget thriller targeting the same audience as Parasite (2019, $258M WW).

## Primary Audience Segment
### Who They Are
Adults 25-45 drawn to procedural drama.
### Job-to-Be-Done
They want to understand how institutions fail.
### Tonal Contract
Tense and cerebral with earned emotional release.
### What Loses Them
Pacing that mistakes opacity for depth.

## Why Now (Market Timing)
A 2024 Reuters/Ipsos poll found 67% of adults distrust large institutions
([Reuters](https://www.reuters.com/business/media/poll-2024/trust-survey/)).

## Audience Sizing
### TAM
**TAM:** $4.8B
### SAM
**SAM:** $800M
### SOM -- Serviceable Obtainable Market (Year 1 realistic capture)
**SOM (Year 1):** $120M

# 2. The Concept

## Format & Genre
Feature film. Thriller. This story requires theatrical compression.

## The Contradiction
The protagonist must expose the truth about the system she depends on.

# 3. Story

## Synopsis
A station master discovers a forty-year cover-up and must decide whether to publish.

# 4. Characters

## Protagonist
**Elsa | 38 | Station safety inspector**

## References
1. [Reuters trust poll](https://www.reuters.com/business/2024/trust-survey/) -- 2024 survey.
"""

_DIRTY_TRIZ = _CLEAN_DOC + "\nThis uses the TRIZ contradiction matrix.\n"
_DIRTY_JTBD = _CLEAN_DOC + "\nJTBD: Segment C2 -- Rehearse-a-Decision audience.\n"
_DIRTY_BOOKER = _CLEAN_DOC + "\nBooker plot: Voyage and Return is the structure.\n"
_DIRTY_MCKEE = _CLEAN_DOC + "\nMcKee's controlling idea drives the protagonist.\n"
_DIRTY_ITER = _CLEAN_DOC + "\nThis was produced in iter-3 of the pipeline.\n"
_DIRTY_CELL_ID = _CLEAN_DOC + "\nCell-ID: BT-042 is the binary tension.\n"
_DIRTY_WORKING_TITLE = _CLEAN_DOC + "\n(Working title: draft-station-007)\n"
_DIRTY_LESSONS = _CLEAN_DOC + "\nLessons consulted: L001, L002.\n"
_DIRTY_BT_ID = _CLEAN_DOC + "\nBT-042 drives the narrative engine.\n"
_DIRTY_PS_ID = _CLEAN_DOC + "\nPS-010 is the supporting premise.\n"
_DIRTY_STANTON = _CLEAN_DOC + "\nStanton's storytelling framework underpins the concept.\n"
_DIRTY_POLTI = _CLEAN_DOC + "\nPolti's 36 dramatic situations are referenced here.\n"
_DIRTY_EGRI = _CLEAN_DOC + "\nEgri's premise construction shapes the arc.\n"
_DIRTY_MEDNICK = _CLEAN_DOC + "\nMednick's associative hierarchy informs the concept.\n"
_DIRTY_HAIDT = _CLEAN_DOC + "\nHaidt's moral foundations are mapped to the characters.\n"


class TestScanForInternalIds:
    def test_clean_doc_returns_empty_list(self) -> None:
        findings = scan_for_internal_ids(_CLEAN_DOC)
        assert findings == []

    def test_triz_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_TRIZ)
        assert len(findings) > 0
        assert any("TRIZ" in f["match"] for f in findings)

    def test_jtbd_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_JTBD)
        assert any("JTBD" in f["match"] for f in findings)

    def test_booker_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_BOOKER)
        assert any("Booker" in f["match"] for f in findings)

    def test_mckee_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_MCKEE)
        assert any("McKee" in f["match"] for f in findings)

    def test_iter_ref_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_ITER)
        assert len(findings) > 0

    def test_cell_id_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_CELL_ID)
        assert any("Cell-ID" in f["match"] for f in findings)

    def test_working_title_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_WORKING_TITLE)
        assert any("Working title" in f["match"] for f in findings)

    def test_lessons_consulted_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_LESSONS)
        assert any("Lessons" in f["match"] for f in findings)

    def test_bt_id_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_BT_ID)
        assert any("BT-" in f["match"] for f in findings)

    def test_ps_id_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_PS_ID)
        assert any("PS-" in f["match"] for f in findings)

    def test_bare_stanton_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_STANTON)
        assert any("Stanton" in f["match"] for f in findings)

    def test_bare_polti_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_POLTI)
        assert any("Polti" in f["match"] for f in findings)

    def test_bare_egri_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_EGRI)
        assert any("Egri" in f["match"] for f in findings)

    def test_bare_mednick_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_MEDNICK)
        assert any("Mednick" in f["match"] for f in findings)

    def test_bare_haidt_detected(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_HAIDT)
        assert any("Haidt" in f["match"] for f in findings)

    def test_finding_has_line_number(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_TRIZ)
        assert all("line" in f for f in findings)
        assert all(isinstance(f["line"], int) for f in findings)

    def test_finding_has_match_text(self) -> None:
        findings = scan_for_internal_ids(_DIRTY_TRIZ)
        assert all("match" in f for f in findings)
        assert all(isinstance(f["match"], str) for f in findings)

    def test_multiple_violations_all_reported(self) -> None:
        multi = _DIRTY_TRIZ + "\nJTBD again.\nBooker and McKee here.\n"
        findings = scan_for_internal_ids(multi)
        assert len(findings) >= 3

    def test_returns_list(self) -> None:
        assert isinstance(scan_for_internal_ids(_CLEAN_DOC), list)


# ── Output-scan tests (v4 runs only — identified by eval.json sidecar) ───────
# v3.1 runs predate ADR-0010 and legitimately contain framework labels.
# Only directories produced by the v4 pipeline contain eval.json.

_RUNS_DIR = Path("runs")
_V4_RUN_DIRS = (
    [d for d in _RUNS_DIR.glob("*/") if (d / "eval.json").exists()] if _RUNS_DIR.exists() else []
)


@pytest.mark.skipif(
    not _V4_RUN_DIRS,
    reason="No v4 runs (eval.json) in runs/ yet — ADR-0010 applies to v4 output only",
)
class TestOutputScan:
    def test_no_investor_md_contains_internal_ids(self) -> None:
        v4_sidecars = {
            "draft.v0.md",
            "eval.md",
            "seed.json",
            "research.json",
            "challenge.json",
            "amplification.json",
            "genius.json",
            "consistency.json",
            "lessons.json",
        }
        for run_dir in _V4_RUN_DIRS:
            for md_path in run_dir.glob("*.md"):
                if md_path.name in v4_sidecars:
                    continue
                # Internal audit docs are allowed to contain framework names
                if md_path.name.endswith("-CHALLENGE.md"):
                    continue
                text = md_path.read_text()
                findings = scan_for_internal_ids(text)
                assert findings == [], f"{md_path}: contains internal IDs: " + ", ".join(
                    f"{f['line']}:{f['match']}" for f in findings
                )
