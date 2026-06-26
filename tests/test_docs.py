"""tests/test_docs.py — STAB-01, MEM-12 documentation existence and content tests.

Asserts:
- docs/stabilization-cycle.md exists with 4 numbered steps and a worked example
- docs/durability.md exists with the exact required sentence (MEM-12)
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
STAB_CYCLE = ROOT / "docs" / "stabilization-cycle.md"
DURABILITY = ROOT / "docs" / "durability.md"
QUARTERLY_TEMPLATE = ROOT / "docs" / "quarterly-review-template.md"

REQUIRED_DURABILITY_SENTENCE = (
    "Literal 100% durability is unreachable; we deliver atomic writes"
    " + per-boundary checkpoints + deterministic replay on same seed"
    " + recovery eval (MEM-09)."
)


def test_stabilization_cycle_exists() -> None:
    """docs/stabilization-cycle.md must exist (STAB-01)."""
    assert STAB_CYCLE.exists(), (
        f"{STAB_CYCLE} not found — create it with the 4-step stabilization playbook"
    )


def test_stabilization_cycle_has_4_steps() -> None:
    """stabilization-cycle.md must contain at least 4 numbered step headings."""
    assert STAB_CYCLE.exists(), f"{STAB_CYCLE} missing"
    content = STAB_CYCLE.read_text()
    # Match patterns like "Step 1", "## Step 1", "## 1.", "**Step 1**", etc.
    step_pattern = re.compile(
        r"(?:^|\n)\s*(?:#+\s*)?(?:Step\s+[1-4]|[1-4]\.\s+(?:Detect|Diagnose|Act|Verify))",
        re.IGNORECASE,
    )
    matches = step_pattern.findall(content)
    assert len(matches) >= 4, (
        f"Expected at least 4 numbered step headings in {STAB_CYCLE}, found {len(matches)}. "
        f"Matches: {matches!r}"
    )


def test_stabilization_cycle_has_worked_example() -> None:
    """stabilization-cycle.md must contain a worked example section."""
    assert STAB_CYCLE.exists(), f"{STAB_CYCLE} missing"
    content = STAB_CYCLE.read_text()
    # Accept "example" (case-insensitive) or specific concept ID patterns like MEM-xx, STAB-xx
    has_example = bool(re.search(r"example", content, re.IGNORECASE))
    has_concept_ref = bool(re.search(r"(?:MEM|STAB|OPS|PIPE)-\d+", content))
    assert has_example or has_concept_ref, (
        f"{STAB_CYCLE} must contain a worked example section "
        "(include 'example' or a concept ID reference like STAB-02)"
    )


def test_durability_md_exists() -> None:
    """docs/durability.md must exist (MEM-12)."""
    assert DURABILITY.exists(), (
        f"{DURABILITY} not found — create it with the honest durability reference"
    )


def test_durability_md_required_sentence() -> None:
    """docs/durability.md must contain the exact required sentence verbatim (MEM-12)."""
    assert DURABILITY.exists(), f"{DURABILITY} missing"
    content = DURABILITY.read_text()
    assert REQUIRED_DURABILITY_SENTENCE in content, (
        f"Required sentence not found verbatim in {DURABILITY}.\n"
        f"Expected: {REQUIRED_DURABILITY_SENTENCE!r}"
    )


def test_quarterly_review_template_exists() -> None:
    """docs/quarterly-review-template.md must exist (STAB-05)."""
    assert QUARTERLY_TEMPLATE.exists(), (
        f"{QUARTERLY_TEMPLATE} not found — create it with the quarterly stabilization review"
        " template (STAB-05)"
    )


def test_quarterly_review_template_has_rejection_rate_section() -> None:
    """Template must contain a rejection rate by category section (STAB-05)."""
    assert QUARTERLY_TEMPLATE.exists(), f"{QUARTERLY_TEMPLATE} missing"
    content = QUARTERLY_TEMPLATE.read_text()
    assert "Rejection Rate by Category" in content, (
        f"'Rejection Rate by Category' section not found in {QUARTERLY_TEMPLATE}"
    )
