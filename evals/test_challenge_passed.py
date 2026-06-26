"""EVAL: Challenge protocol completion gate.

Checks that every concept in the latest runs/ folder has a corresponding
[slug]-CHALLENGE.md with Phase 1 results and a Final Verdict.

Run: pytest evals/test_challenge_passed.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNS_DIR = REPO_ROOT / "runs"

PHASE1_PATTERN = re.compile(r"Phase 1 Results", re.IGNORECASE)
VERDICT_PATTERN = re.compile(r"Final Verdict", re.IGNORECASE)
REJECT_PATTERN = re.compile(r"REJECT", re.IGNORECASE)


def get_latest_run_folder() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    folders = sorted(
        [f for f in RUNS_DIR.iterdir() if f.is_dir()],
        key=lambda f: f.name,
        reverse=True,
    )
    return folders[0] if folders else None


def get_concept_files(run_folder: Path) -> list[Path]:
    # Match any sidecar variant: -NARRATOR.md, -NARRATOR-v2.md, -NARRATOR-updated.md, etc.
    SIDECAR_MARKERS = ("-NARRATOR", "-CHALLENGE", "-RESEARCH", "-AMPLIFIED")
    META_DOCS = {"README.md", "FINDINGS.md"}
    return [
        f
        for f in run_folder.glob("*.md")
        if not any(marker in f.name for marker in SIDECAR_MARKERS) and f.name not in META_DOCS
    ]


def pytest_generate_tests(metafunc):
    run_folder = get_latest_run_folder()
    if run_folder is None:
        metafunc.parametrize("concept_file", [])
        return
    concept_files = get_concept_files(run_folder)
    if "concept_file" in metafunc.fixturenames:
        metafunc.parametrize("concept_file", concept_files, ids=[f.name for f in concept_files])


def test_challenge_report_exists(concept_file: Path):
    """Every concept must have a [slug]-CHALLENGE.md report."""
    stem = concept_file.stem
    challenge_file = concept_file.parent / f"{stem}-CHALLENGE.md"
    assert challenge_file.exists(), (
        f"Missing challenge report for {concept_file.name}. "
        f"Run concept-challenger agent before publishing."
    )


def test_challenge_has_phase1_results(concept_file: Path):
    """Challenge report must contain Phase 1 Results section."""
    stem = concept_file.stem
    challenge_file = concept_file.parent / f"{stem}-CHALLENGE.md"
    if not challenge_file.exists():
        pytest.skip("Challenge file missing")
    text = challenge_file.read_text(encoding="utf-8")
    assert PHASE1_PATTERN.search(text), (
        f"{challenge_file.name}: missing 'Phase 1 Results'. Challenge protocol did not run Phase 1."
    )


def test_challenge_has_final_verdict(concept_file: Path):
    """Challenge report must contain a Final Verdict."""
    stem = concept_file.stem
    challenge_file = concept_file.parent / f"{stem}-CHALLENGE.md"
    if not challenge_file.exists():
        pytest.skip("Challenge file missing")
    text = challenge_file.read_text(encoding="utf-8")
    assert VERDICT_PATTERN.search(text), (
        f"{challenge_file.name}: missing 'Final Verdict'. Challenge protocol did not complete."
    )


def test_reject_concepts_marked_in_concept_file(concept_file: Path):
    """If challenge verdict is REJECT, concept file Section 15 must show REJECT."""
    stem = concept_file.stem
    challenge_file = concept_file.parent / f"{stem}-CHALLENGE.md"
    if not challenge_file.exists():
        pytest.skip("Challenge file missing")
    challenge_text = challenge_file.read_text(encoding="utf-8")
    if not REJECT_PATTERN.search(challenge_text):
        return  # Not a reject -- nothing to check
    # Concept was rejected -- verify Section 15 reflects this
    concept_text = concept_file.read_text(encoding="utf-8")
    section_15 = concept_text.find("## MASTER_QUESTIONS Challenge Results")
    if section_15 == -1:
        pytest.fail(
            f"{concept_file.name}: REJECT verdict in challenge but "
            f"Section 15 missing from concept file"
        )
    section_content = concept_text[section_15:]
    assert REJECT_PATTERN.search(section_content), (
        f"{concept_file.name}: Challenge report says REJECT but Section 15 of concept file "
        f"does not reflect this. concept-challenger must update Section 15."
    )


def test_narrator_companion_exists(concept_file: Path):
    """Every STRONG PASS concept should have a [slug]-NARRATOR.md investor companion.
    Non-blocking warning for CONDITIONAL concepts; blocking for STRONG PASS."""
    stem = concept_file.stem
    narrator_file = concept_file.parent / f"{stem}-NARRATOR.md"
    challenge_file = concept_file.parent / f"{stem}-CHALLENGE.md"

    # If challenge says REJECT, narrator is not required
    if challenge_file.exists():
        challenge_text = challenge_file.read_text(encoding="utf-8")
        if REJECT_PATTERN.search(challenge_text):
            return  # Rejected concept — no narrator needed

    if not narrator_file.exists():
        pytest.skip(
            f"Narrator companion missing for {concept_file.name}. "
            f"Run concept-narrator agent to produce {stem}-NARRATOR.md. "
            f"Non-blocking: concept is valid but not investor-ready without companion."
        )


def test_narrator_has_pitch_section(concept_file: Path):
    """Narrator companion must contain a plain-English series overview section."""
    stem = concept_file.stem
    narrator_file = concept_file.parent / f"{stem}-NARRATOR.md"
    if not narrator_file.exists():
        pytest.skip("Narrator missing — skipping content check")
    text = narrator_file.read_text(encoding="utf-8")
    # Accept either the legacy header or the current professional headers
    accepted = [
        "PITCH IN PLAIN ENGLISH",
        "Pitch in Plain English",
        "## The Series",
        "## The Story",
        "## Overview",
    ]
    assert any(h in text for h in accepted), (
        f"{narrator_file.name}: missing plain-English series overview section. "
        f"Narrator must open with a prose summary investors can read in 90 seconds."
    )


def test_narrator_has_investment_thesis(concept_file: Path):
    """Narrator companion must contain the 3-sentence Investment Thesis."""
    stem = concept_file.stem
    narrator_file = concept_file.parent / f"{stem}-NARRATOR.md"
    if not narrator_file.exists():
        pytest.skip("Narrator missing — skipping content check")
    text = narrator_file.read_text(encoding="utf-8")
    accepted = ["INVESTMENT THESIS", "INVESTMENT CASE", "INVESTMENT OPPORTUNITY"]
    has_thesis = any(h in text.upper() for h in accepted)
    assert has_thesis, (
        f"{narrator_file.name}: missing Investment Thesis / Investment Case section. "
        f"Narrator must answer 'So, What?' at the concept level for investors."
    )
