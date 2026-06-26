"""EVAL-04 — Anti-slop output scanner.

Two modes:
  1. Unit tests with inline fixtures (always run — no output required)
  2. Output scan over data/04_concepts.jsonl and out/concepts/*.md (skips if absent)

Term list loaded at call-time from prompts/anti_slop.md via evals.anti_slop.
ONLINE=1 has no effect on this eval (no network I/O needed).
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from evals.anti_slop import load_banned_terms

_CONCEPTS_LOG = Path("data/04_concepts.jsonl")
_CONCEPTS_OUT_GLOB = "out/concepts/*.md"

# ── Inline fixtures ────────────────────────────────────────────────────────────

# A clean concept string (no banned terms).
# Verified manually: contains no terms from prompts/anti_slop.md.
_CLEAN_CONCEPT = (
    "An original film about a historian who discovers a suppressed manuscript "
    "connecting two historical events separated by 500 years. "
    "The discovery forces her to choose between career and truth."
)

# A dirty concept string with a planted banned phrase.
# "chosen one" is the first bullet term under ## Category 1: Forbidden Premises
# in prompts/anti_slop.md — confirmed present in load_banned_terms() output.
_DIRTY_CONCEPT = (
    "This concept features a chosen one destined to save the world from destruction. "
    "The protagonist discovers their special bloodline sets them apart from everyone else."
)


def _concept_has_banned_term(text: str, terms: list[str]) -> list[str]:
    """Return list of banned terms found in text (case-insensitive)."""
    text_lower = text.lower()
    return [t for t in terms if t in text_lower]


# ── Unit tests (always run) ───────────────────────────────────────────────────


def test_anti_slop_clean_concept_passes(tmp_path: Path) -> None:
    """A clean concept with no banned terms must produce zero violations (EVAL-04 positive)."""
    anti_slop_path = Path("prompts/anti_slop.md")
    if not anti_slop_path.exists():
        pytest.skip("prompts/anti_slop.md not found — run Phase 2 first.")
    terms = load_banned_terms(anti_slop_path)
    assert terms, "load_banned_terms() returned empty list — check anti_slop.md"
    found = _concept_has_banned_term(_CLEAN_CONCEPT, terms)
    assert not found, (
        f"Clean concept unexpectedly matched banned terms: {found}\nConcept: {_CLEAN_CONCEPT!r}"
    )


def test_anti_slop_dirty_concept_flagged(tmp_path: Path) -> None:
    """A concept with a planted banned phrase must be flagged (EVAL-04 negative case)."""
    anti_slop_path = Path("prompts/anti_slop.md")
    if not anti_slop_path.exists():
        pytest.skip("prompts/anti_slop.md not found — run Phase 2 first.")
    terms = load_banned_terms(anti_slop_path)
    assert terms, "load_banned_terms() returned empty list — check anti_slop.md"
    found = _concept_has_banned_term(_DIRTY_CONCEPT, terms)
    assert found, (
        f"Dirty concept was NOT flagged — planted banned term not in term list.\n"
        f"Dirty concept: {_DIRTY_CONCEPT!r}\n"
        f"Term list sample (first 10): {terms[:10]}"
    )


# ── Output scan (skips if no output) ─────────────────────────────────────────


def _load_output_texts() -> list[tuple[str, str]]:
    """Return list of (source_label, text) pairs from all output files."""
    results: list[tuple[str, str]] = []
    if _CONCEPTS_LOG.exists():
        for line in _CONCEPTS_LOG.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                concept_id = row.get("concept_id", "unknown")
                # Exclude anti_slop_self_check — that field is *meant* to name
                # the inverted patterns; scanning it would always produce false positives.
                scan_row = {k: v for k, v in row.items() if k != "anti_slop_self_check"}
                text = json.dumps(scan_row)
                results.append((f"jsonl:{concept_id}", text))
    for md_file in glob.glob(_CONCEPTS_OUT_GLOB):
        text = Path(md_file).read_text()
        results.append((f"md:{md_file}", text))
    return results


def test_anti_slop_no_banned_terms_in_output() -> None:
    """No banned anti-slop term in data/04_concepts.jsonl or out/concepts/*.md (EVAL-04)."""
    output_texts = _load_output_texts()
    if not output_texts:
        pytest.skip("No pipeline output found — run the pipeline first.")

    anti_slop_path = Path("prompts/anti_slop.md")
    if not anti_slop_path.exists():
        pytest.skip("prompts/anti_slop.md not found — run Phase 2 first.")

    terms = load_banned_terms(anti_slop_path)
    violations: list[str] = []
    for label, text in output_texts:
        found = _concept_has_banned_term(text, terms)
        if found:
            violations.append(f"{label}: {found}")
    assert not violations, (
        f"Banned anti-slop terms found in output ({len(violations)} concepts):\n"
        + "\n".join(violations)
    )
