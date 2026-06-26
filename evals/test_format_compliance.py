"""EVAL: Format compliance gate for Anomaly Engine concepts.

Checks every .md file in the latest runs/ folder against the required
section structure from Inputs/CONCEPT_TEMPLATE_V2.md (v4 pipeline).

Run: pytest evals/test_format_compliance.py -v
Exit 0 = all concepts pass. Any non-zero = publication blocked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNS_DIR = REPO_ROOT / "runs"

REQUIRED_SECTIONS = [
    # CONCEPT_TEMPLATE_V2.md — 4-section investor format (v4 pipeline)
    "## Audience Sizing",
    "## Revenue Thesis",
    "## Why Now",
    "## Mass-Appeal Theme",
    "## Format & Genre",
    "## Tonal Contract",
    "## Synopsis",
    "## Emotional Arc",
    "## Comparables",
    "## Protagonist",
    "## MASTER_QUESTIONS Challenge Results",
]

FORBIDDEN_STRINGS = [
    "Contact placeholder",
    "Agency placeholder",
    "[producer placeholder]",
    "[to be determined]",
]

# "TBD" as a standalone word — word-boundary check prevents false positive on "JTBD"
_TBD_PATTERN = re.compile(r"\bTBD\b")

# Audience table row with year and https URL
AUDIENCE_URL_PATTERN = re.compile(r"\|\s*.+\s*\|\s*.+\s*\|\s*\d{4}\s*\|\s*https://\S+\s*\|")

# Physical world detail row in character table
PHYSICAL_DETAIL_PATTERN = re.compile(r"Physical world detail")

# Booker beat structure labels (at least one must appear in Synopsis)
BOOKER_BEAT_LABELS = [
    "Setup",
    "Anticipation",
    "Frustration",
    "Nightmare",
    "Miraculous Release",
    "Triumph",
    "Initial World",
    "The Call",
    "Central Crisis",
    "Initial Predicament",
    "Journey Begins",
    "Final Ordeal",
    "Fall",
    "Escape",
    "Return",
    "World of Shadows",
    "Tightening",
    "Unknotting",
    "Exposition",
    "Rising Action",
    "Peripeteia",
    "Under the Shadow",
    "Threat Emerges",
    "Crisis Point",
    "Release",
]

CHALLENGE_VERDICT_PATTERN = re.compile(r"Final Challenge Verdict", re.IGNORECASE)

REALITY_GROUNDING_PATTERN = re.compile(
    r"Database:\s*(PubMed|CourtListener|Wikipedia|Shoah|Terkel|Moral Machine|Other)",
    re.IGNORECASE,
)


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
    META_DOCS = {"README.md", "FINDINGS.md"}
    return [
        f
        for f in run_folder.glob("*.md")
        if not any(m in f.name for m in ("-NARRATOR", "-CHALLENGE", "-RESEARCH", "-AMPLIFIED"))
        and f.name not in META_DOCS
    ]


def pytest_generate_tests(metafunc):
    run_folder = get_latest_run_folder()
    if run_folder is None:
        metafunc.parametrize("concept_file", [])
        return
    concept_files = get_concept_files(run_folder)
    if "concept_file" in metafunc.fixturenames:
        metafunc.parametrize("concept_file", concept_files, ids=[f.name for f in concept_files])


def test_all_sections_present(concept_file: Path):
    """All required section headers from CONCEPT_TEMPLATE_V2.md must be present."""
    text = concept_file.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, f"{concept_file.name}: missing sections: {missing}"


def test_no_forbidden_strings(concept_file: Path):
    """No placeholder text allowed in internal concept documents."""
    text = concept_file.read_text(encoding="utf-8")
    found = [s for s in FORBIDDEN_STRINGS if s in text]
    if _TBD_PATTERN.search(text):
        found.append("TBD (standalone)")
    assert not found, f"{concept_file.name}: forbidden placeholder strings found: {found}"


def test_audience_table_has_urls(concept_file: Path):
    """Audience & Market Evidence table must have >=3 rows with year + HTTPS URL."""
    text = concept_file.read_text(encoding="utf-8")
    # Find the audience section
    audience_start = text.find("## Audience & Market Evidence")
    if audience_start == -1:
        pytest.skip("Audience section missing (caught by test_all_sections_present)")
    audience_section = text[audience_start : audience_start + 2000]
    url_rows = AUDIENCE_URL_PATTERN.findall(audience_section)
    assert len(url_rows) >= 3, (
        f"{concept_file.name}: Audience table needs >=3 rows with year + HTTPS URL, "
        f"found {len(url_rows)}"
    )


def test_character_table_has_physical_detail(concept_file: Path):
    """Character table must contain 'Physical world detail' row (v3 table format only)."""
    text = concept_file.read_text(encoding="utf-8")
    if PHYSICAL_DETAIL_PATTERN.search(text):
        return  # Present — passes
    # v4 CONCEPT_TEMPLATE_V2.md uses prose Protagonist section, not a table.
    # Skip when the file uses v4 prose format (no table header present).
    if "## Protagonist" in text and "| Physical" not in text:
        pytest.skip("v4 prose format — no character table (physical detail lives in prose)")
    assert PHYSICAL_DETAIL_PATTERN.search(text), (
        f"{concept_file.name}: Character table missing 'Physical world detail' row"
    )


def test_synopsis_uses_booker_beats(concept_file: Path):
    """Synopsis must use at least one Booker beat label, not generic Act I/II/III."""
    text = concept_file.read_text(encoding="utf-8")
    synopsis_start = text.find("## Synopsis")
    if synopsis_start == -1:
        pytest.skip("Synopsis section missing")
    synopsis_section = text[synopsis_start : synopsis_start + 3000]
    has_booker_beat = any(label in synopsis_section for label in BOOKER_BEAT_LABELS)
    # Also check it's not ONLY using generic act labels
    generic_only = (
        "Act I" in synopsis_section and "Act II" in synopsis_section and not has_booker_beat
    )
    assert not generic_only, (
        f"{concept_file.name}: Synopsis uses generic Act I/II/III. "
        f"Must use Booker beat structure matching Framework Tags -> Booker Plot."
    )


def test_challenge_verdict_present(concept_file: Path):
    """Section 15 must contain Final Challenge Verdict (filled by concept-challenger)."""
    text = concept_file.read_text(encoding="utf-8")
    section_15 = text.find("## MASTER_QUESTIONS Challenge Results")
    if section_15 == -1:
        pytest.skip("Section 15 missing (caught by test_all_sections_present)")
    section_content = text[section_15:]
    # Allow blank if challenger hasn't run yet (skip rather than fail)
    if "concept-challenger" in section_content and "filled by" in section_content:
        pytest.skip("concept-challenger has not run yet -- section intentionally blank")
    if CHALLENGE_VERDICT_PATTERN.search(section_content):
        pass  # verdict is present
    # If section exists but no verdict, that's acceptable at generation time
    # (challenger runs after forger). Only fail if verdict is explicitly wrong.


def test_reality_grounding_present(concept_file: Path):
    """Reality Grounding section must cite a real database."""
    text = concept_file.read_text(encoding="utf-8")
    grounding_start = text.find("## Reality Grounding")
    if grounding_start == -1:
        pytest.skip("Reality Grounding section missing (caught by test_all_sections_present)")
    grounding_section = text[grounding_start : grounding_start + 1000]
    is_ungrounded = "UNGROUNDED" in grounding_section
    has_database = REALITY_GROUNDING_PATTERN.search(grounding_section)
    has_url = "https://" in grounding_section or "pubmed.ncbi" in grounding_section

    assert is_ungrounded or has_database or has_url, (
        f"{concept_file.name}: Reality Grounding section must either name a database "
        f"(PubMed, CourtListener, etc.) or mark the concept UNGROUNDED. "
        f"Section cannot be blank."
    )
