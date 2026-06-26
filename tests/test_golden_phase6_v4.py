"""V4A-003e — Golden v4 14-section A4 fixture validation.

`tests/fixtures/golden_phase6_v4.md` is the canonical worked example for the
v4 14-section A4 layout described in:
  - prompts/06-a4-formatter.md  (formatter prompt + bifurcation rule)
  - docs/report_v4_schema.md    (canonical 14-section schema spec)
  - pipeline/schema.py          (Phase4Concept v4 fields)

Tests in this file enforce that the golden fixture continues to obey the v4
spec: exactly 14 H2 sections in canonical order, Mutation Provenance at §12,
Closing Image at §13 with ≤30-word body, Score at §14 as the literal
placeholder. Drift between the fixture and the spec is a regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GOLDEN_V4 = Path("tests/fixtures/golden_phase6_v4.md")
CLOSING_IMAGE_MAX_WORDS = 30  # mirror pipeline/schema.py:CLOSING_IMAGE_MAX_WORDS

V4_CANONICAL_HEADERS: tuple[str, ...] = (
    "## High-Concept Logline",
    "## Audience Size & Evidence",
    "## JTBD",
    "## Asset",
    "## TRIZ Contradiction",
    "## Narrative Grid",
    "## Key Roles",
    "## Cinema-School Floor",
    "## SDT Analysis",
    "## Critic Verdict",
    "## Mutation Provenance",
    "## Closing Image",
    "## Score",
)
V4_EXPECTED_H2_COUNT = len(V4_CANONICAL_HEADERS)  # 13 (H1 is `# ...` not `## ...`)
V4_EXPECTED_TOTAL_SECTIONS = 14  # H1 + 13 H2


def _read_golden() -> str:
    if not GOLDEN_V4.is_file():
        pytest.fail(f"missing v4 golden fixture: {GOLDEN_V4}")
    return GOLDEN_V4.read_text(encoding="utf-8")


def test_golden_v4_has_exactly_one_h1() -> None:
    text = _read_golden()
    h1_lines = [ln for ln in text.splitlines() if re.match(r"^# [^#]", ln)]
    assert len(h1_lines) == 1, (
        f"v4 golden must have exactly one H1 (the title); got {len(h1_lines)}: {h1_lines}"
    )


def test_golden_v4_h2_count_is_thirteen() -> None:
    """13 H2 sections + 1 H1 = 14 sections total per v4 spec."""
    text = _read_golden()
    h2_lines = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert len(h2_lines) == V4_EXPECTED_H2_COUNT, (
        f"v4 golden must have {V4_EXPECTED_H2_COUNT} H2 sections; got {len(h2_lines)}: {h2_lines}"
    )


def test_golden_v4_section_order_matches_canonical_spec() -> None:
    text = _read_golden()
    h2_lines = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert tuple(h2_lines) == V4_CANONICAL_HEADERS, (
        "v4 golden H2 order drift from docs/report_v4_schema.md canonical order:\n"
        f"  expected: {V4_CANONICAL_HEADERS}\n"
        f"  actual:   {tuple(h2_lines)}"
    )


def test_golden_v4_section_12_is_mutation_provenance() -> None:
    text = _read_golden()
    h2_lines = [ln for ln in text.splitlines() if ln.startswith("## ")]
    # h2_lines is 0-indexed; section §12 is the 11th H2 (after the H1).
    assert h2_lines[10] == "## Mutation Provenance"


def test_golden_v4_section_13_is_closing_image() -> None:
    text = _read_golden()
    h2_lines = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert h2_lines[11] == "## Closing Image"


def test_golden_v4_section_14_is_score() -> None:
    text = _read_golden()
    h2_lines = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert h2_lines[12] == "## Score"


def _section_body(text: str, header: str) -> str:
    """Return the markdown body between `header` and the next H1/H2."""
    idx = text.find(header + "\n")
    if idx == -1:
        pytest.fail(f"section header not found in golden v4 fixture: {header!r}")
    rest = text[idx + len(header) + 1 :]
    next_section = re.search(r"^(## |# )", rest, re.MULTILINE)
    if next_section:
        return rest[: next_section.start()].strip()
    return rest.strip()


def test_golden_v4_closing_image_body_under_max_words() -> None:
    text = _read_golden()
    body = _section_body(text, "## Closing Image")
    word_count = len(body.split())
    assert word_count <= CLOSING_IMAGE_MAX_WORDS, (
        f"Closing Image body has {word_count} words; max is {CLOSING_IMAGE_MAX_WORDS}"
    )


def test_golden_v4_score_body_is_placeholder_literal() -> None:
    text = _read_golden()
    body = _section_body(text, "## Score")
    assert body == "**[SCORE_PLACEHOLDER]/100**", (
        f"Score section must be the literal placeholder; got: {body!r}"
    )


def test_golden_v4_mutation_provenance_body_has_operator_and_parents() -> None:
    """Section 12 body must declare the operator label and at least one parent."""
    text = _read_golden()
    body = _section_body(text, "## Mutation Provenance")
    assert "**Operator:**" in body, "Mutation Provenance body missing **Operator:** line"
    assert "**Parent concept(s):**" in body, (
        "Mutation Provenance body missing **Parent concept(s):** line"
    )
