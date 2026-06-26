"""Tests that ADR-0001..0006 exist and have the correct structure (HARN-10)."""
from __future__ import annotations

import re
from pathlib import Path


ADR_DIR = Path("docs/adr")
REQUIRED_ADR_NUMBERS = {"0001", "0002", "0003", "0004", "0005", "0006"}
REQUIRED_SECTIONS = ["Context", "Decision", "Consequences", "Verifies"]


def _get_adr_files() -> list[Path]:
    """Return all ADR files matching the NNNN-*.md pattern."""
    return list(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_six_adrs_exist() -> None:
    """At least 6 ADR files must exist at docs/adr/000N-*.md."""
    adrs = _get_adr_files()
    assert len(adrs) >= 6, (
        f"Expected at least 6 ADR files in {ADR_DIR}, found {len(adrs)}: {adrs}"
    )


def test_each_adr_accepted() -> None:
    """Every ADR file must contain 'Status:** Accepted' or 'Status: Accepted'.

    Handles both plain and bold markdown formatting:
    - **Status:** Accepted   (bold markdown)
    - Status: Accepted       (plain)
    """
    adrs = _get_adr_files()
    assert adrs, f"No ADR files found in {ADR_DIR}"
    failures = []
    for adr in adrs:
        body = adr.read_text().lower()
        # Match both "status: accepted" and "status:** accepted" (bold markdown strips)
        has_accepted = (
            "status: accepted" in body
            or "status:** accepted" in body
            or re.search(r"\*?\*?status\*?\*?:\s*\*?\*?accepted", body) is not None
        )
        if not has_accepted:
            failures.append(str(adr))
    assert not failures, (
        "ADR files missing 'Status: Accepted' (or '**Status:** Accepted'):\n"
        + "\n".join(failures)
    )


def test_template_present() -> None:
    """docs/adr/template.md must exist."""
    assert (ADR_DIR / "template.md").exists(), (
        "docs/adr/template.md not found. Create it to guide new ADR authors."
    )


def test_readme_present() -> None:
    """docs/adr/README.md must exist."""
    assert (ADR_DIR / "README.md").exists(), (
        "docs/adr/README.md not found. Create it with numbering convention and index."
    )


def test_adr_numbers_sequential() -> None:
    """ADR numbers 0001..0006 must all be present with no gaps."""
    adrs = _get_adr_files()
    found_numbers = set()
    for adr in adrs:
        # Extract leading 4-digit number from filename
        match = re.match(r"^(\d{4})-", adr.name)
        if match:
            found_numbers.add(match.group(1))

    missing = REQUIRED_ADR_NUMBERS - found_numbers
    assert not missing, (
        f"Missing ADR numbers: {sorted(missing)}. "
        f"Found: {sorted(found_numbers)}. "
        f"Numbering must be sequential 0001..0006."
    )


def test_each_adr_has_required_sections() -> None:
    """Each ADR must have Context, Decision, Consequences, and Verifies sections."""
    adrs = _get_adr_files()
    assert adrs, f"No ADR files found in {ADR_DIR}"
    failures = []
    for adr in adrs:
        body = adr.read_text()
        missing_sections = [
            section for section in REQUIRED_SECTIONS
            if section not in body
        ]
        if missing_sections:
            failures.append(f"{adr.name}: missing sections {missing_sections}")
    assert not failures, (
        "ADR files missing required sections:\n" + "\n".join(failures)
    )
