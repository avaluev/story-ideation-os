# ruff: noqa: E501
"""Eval: every EXTERNAL numeric claim in a rendered report must carry either
an inline deep-link OR shown arithmetic.

Rule (ADR-0011 + FilmIntel deep-link policy):
  * COMPUTED claims (market_sam, market_som, lifetime) are EXEMPT -- they are
    proven by python_executed calculation, not by a URL.
  * EXTERNAL claims (comp_roi, box_office, demand, cultural_signal, market_tam,
    market_claim) MUST have at least one of:
      (a) cited_url non-empty (inline deep-link), or
      (b) the claim sits in prose that contains an explicit arithmetic expression
          (a "shown arithmetic" signal: e.g. "X x Y = Z", "X% of Y", "calc ...",
          "python_executed", "modeled at ...", "= $NM").

Artifacts scanned (skipped gracefully when absent):
  * runs/**/*-NARRATOR.md
  * outputs/portfolio/*VERIFIED*.md

The eval is LOUD on its own inline fixtures: a clean card → 0 violations;
a card with a bare unsourced "$4.8B" → >= 1 violation.

Offline / pure-parsing — no network, no LLM (ADR-0002).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

from pipeline.veracity.claims import COMPUTED_TYPES
from pipeline.veracity.enumerate import enumerate_claims

# --------------------------------------------------------------------------- #
# Arithmetic / deep-link helpers
# --------------------------------------------------------------------------- #

# Patterns that indicate shown arithmetic in or near the claim sentence.
# We look for these in the FULL TEXT of the claim (which for prose claims is
# the whole sentence, not just the anchor).
_LINK_IN_TEXT_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

_ARITHMETIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d+\s*[xx\*]\s*\d", re.IGNORECASE),  # e.g. "3 x $100M"
    re.compile(r"\d+\s*%\s+of\s+\$?\d", re.IGNORECASE),  # e.g. "12% of $328B"
    re.compile(r"python[_\s]executed", re.IGNORECASE),  # explicit flag
    re.compile(r"calculation_method", re.IGNORECASE),  # inline JSON snippet
    re.compile(r"modeled\s+(?:at|floor|upside)", re.IGNORECASE),
    re.compile(r"=\s*\$[\d.,]+\s*[BMK]?\b", re.IGNORECASE),  # e.g. "= $540M"
    re.compile(r"\bbase\s+case\b.*\bpython\b", re.IGNORECASE),
    re.compile(r"\bcalc(?:ulation)?\b", re.IGNORECASE),
    re.compile(r"\bSOM\s*<\s*SAM\s*<\s*TAM\b"),  # invariant callout
    re.compile(r"\bcomp[- ]anchor", re.IGNORECASE),  # comp-anchored estimate
]


def _has_shown_arithmetic(claim_text: str) -> bool:
    """True if the claim sentence contains a recognisable arithmetic expression."""
    return any(pat.search(claim_text) for pat in _ARITHMETIC_PATTERNS)


def _is_deep_link(url: str) -> bool:
    """True if the URL looks like a deep-path link (path beyond bare domain).

    Per FilmIntel policy: bare-domain URLs (e.g. https://variety.com/) are NOT
    valid citations.  A deep link has a path with at least one non-slash segment.
    """
    if not url.startswith(("http://", "https://")):
        return False
    # strip scheme
    rest = url.split("://", 1)[1]
    # rest is host/path[?query]
    slash = rest.find("/")
    if slash == -1:
        return False  # no path at all
    path = rest[slash:]
    # strip trailing slash + query
    path = path.rstrip("/").split("?")[0].split("#")[0]
    return bool(path) and path != ""


# --------------------------------------------------------------------------- #
# Violation record
# --------------------------------------------------------------------------- #


class Violation(NamedTuple):
    file: str
    claim_id: str
    claim_type: str
    anchor: str
    text_snippet: str


def _check_doc(content: str, source_label: str) -> list[Violation]:
    """Return one Violation per external, unsourced, non-arithmetic claim."""
    claims = enumerate_claims(content, concept_id=source_label, concept_title=source_label)
    violations: list[Violation] = []
    for claim in claims:
        if claim.is_computed:
            # COMPUTED (market_sam, market_som, lifetime) — exempt
            continue
        # Check deep-link on cited_url field
        if _is_deep_link(claim.cited_url):
            continue
        # Prose claims never carry cited_url, but the full sentence may embed
        # a markdown link -- extract and check it.
        if any(_is_deep_link(m.group(2)) for m in _LINK_IN_TEXT_RE.finditer(claim.text)):
            continue
        # Check shown arithmetic in the claim sentence
        if _has_shown_arithmetic(claim.text):
            continue
        # Also allow: if the anchor text contains a citation marker (↑ / ✅ / source)
        if re.search(r"✅|↑|\bsource\b", claim.text, re.IGNORECASE):
            continue
        violations.append(
            Violation(
                file=source_label,
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                anchor=claim.anchor[:80],
                text_snippet=claim.text[:120],
            )
        )
    return violations


# --------------------------------------------------------------------------- #
# Inline fixtures
# --------------------------------------------------------------------------- #

# A card where every external claim carries either a deep-link or arithmetic.
_CLEAN_CARD = """\
# Mockfilm

## 1. Market & Audience

### Comparables

| Title | Year | WW Revenue | Budget | ROI |
|---|---|---|---|---|
| [Inside Out 2 (2024)](https://www.boxofficemojo.com/title/tt1979376/) | 2024 | $1.699B | $200M | 8.5x |
| [Elemental (2023)](https://www.boxofficemojo.com/title/tt14208870/) | 2023 | $496M | $200M | 2.5x |

### Why Now

Forced relocation is a present headline; [11 million people were displaced](https://www.unhcr.org/global-trends) by disaster in 2024.

### Verified Proof of Demand

- **$1.46B** — "grossed $1.46 billion worldwide" ([Disney IR](https://thewaltdisneycompany.com/news/inside-out-2-highest-grossing-animated-film-globally/), 2024-07-14)

### Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $328.20B | Global content market ([MPA THEME](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf)). |
| **SAM** | $39.38B | Serviceable share — python_executed derivation (~12% of TAM). |
| **SOM (Year 1)** | $540M | Obtainable Year-1 revenue — python_executed. |
"""

# A card that has a bare unsourced "$4.8B" in the market section — no link,
# no arithmetic. Must generate >= 1 violation.
_DIRTY_UNSOURCED = """\
# Mockfilm

## 1. Market & Audience

### Audience Sizing

The total addressable market for this genre is $4.8B globally.

### Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $328.20B | Global content market. |
| **SAM** | $39.38B | Derivation. |
| **SOM (Year 1)** | $540M | python_executed. |
"""

# A card where a claim has no deep-link but HAS shown arithmetic -> INFERRED, not a violation.
_INFERRED_CARD = """\
# Mockfilm

## 1. Market & Audience

### Audience Sizing

At a 12% of TAM capture rate (SAM = 12% of $328.2B), the serviceable market is $39.4B.
Year-1 SOM is modeled at 1.4% of SAM = $540M (python_executed).

### Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $328.20B | [MPA THEME](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf). |
| **SAM** | $39.38B | Derivation. |
| **SOM (Year 1)** | $540M | python_executed. |
"""


class TestInlineFixtures:
    def test_clean_card_zero_violations(self) -> None:
        violations = _check_doc(_CLEAN_CARD, "clean_fixture")
        assert violations == [], (
            f"Clean card unexpectedly flagged {len(violations)} violation(s):\n"
            + "\n".join(str(v) for v in violations)
        )

    def test_dirty_unsourced_has_violation(self) -> None:
        """The bare '$4.8B' without a link or arithmetic must be flagged."""
        violations = _check_doc(_DIRTY_UNSOURCED, "dirty_fixture")
        assert len(violations) >= 1, (
            "Expected >= 1 violation for unsourced '$4.8B' market claim, got 0.\n"
            "Claim types enumerated: "
            + str(
                [
                    (c.claim_type, c.value, c.cited_url)
                    for c in enumerate_claims(_DIRTY_UNSOURCED, concept_id="dirty_fixture")
                ]
            )
        )

    def test_dirty_unsourced_flags_tam_type(self) -> None:
        violations = _check_doc(_DIRTY_UNSOURCED, "dirty_fixture")
        types = {v.claim_type for v in violations}
        # market_tam or demand or market_claim — whichever the enumerator assigns
        # to a bare $N.NB market-size prose claim.
        assert types & {"market_tam", "demand", "box_office", "market_claim"}, (
            f"Violation types were {types!r}, expected a market-size type."
        )

    def test_inferred_arithmetic_card_zero_violations(self) -> None:
        """Prose with shown arithmetic (% of TAM / python_executed) must not be
        flagged even without an inline deep-link."""
        violations = _check_doc(_INFERRED_CARD, "inferred_fixture")
        assert violations == [], (
            f"Inferred card unexpectedly flagged {len(violations)} violation(s):\n"
            + "\n".join(str(v) for v in violations)
        )

    def test_computed_claims_always_exempt(self) -> None:
        """market_sam / market_som / lifetime must never appear as violations
        regardless of whether a URL is present."""

        claims = enumerate_claims(_DIRTY_UNSOURCED, concept_id="dirty_fixture")
        computed = [c for c in claims if c.claim_type in COMPUTED_TYPES]
        violations = _check_doc(_DIRTY_UNSOURCED, "dirty_fixture")
        viol_ids = {v.claim_id for v in violations}
        for c in computed:
            assert c.claim_id not in viol_ids, (
                f"Computed claim {c.claim_type!r} was incorrectly flagged as a violation."
            )


# --------------------------------------------------------------------------- #
# Artifact scans — skipped gracefully when no outputs exist
# --------------------------------------------------------------------------- #

_RUNS_DIR = Path("runs")
_PORTFOLIO_DIR = Path("outputs/portfolio")


def _collect_narrator_paths() -> list[Path]:
    if not _RUNS_DIR.exists():
        return []
    return sorted(_RUNS_DIR.glob("**/*-NARRATOR.md"))


def _collect_verified_portfolio_paths() -> list[Path]:
    if not _PORTFOLIO_DIR.exists():
        return []
    return sorted(_PORTFOLIO_DIR.glob("*VERIFIED*.md"))


_NARRATOR_PATHS = _collect_narrator_paths()
_VERIFIED_PATHS = _collect_verified_portfolio_paths()


@pytest.mark.skipif(
    not _NARRATOR_PATHS,
    reason="No *-NARRATOR.md files found in runs/ — skipping artifact scan",
)
class TestNarratorArtifacts:
    """NARRATOR markdown: every external claim must be sourced or have arithmetic."""

    def test_narrator_files_have_no_bare_numeric_claims(self) -> None:
        all_violations: list[Violation] = []
        for path in _NARRATOR_PATHS:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            label = str(path.relative_to(_RUNS_DIR))
            all_violations.extend(_check_doc(content, label))

        if all_violations:
            summary = "\n".join(
                f"  [{v.file}] {v.claim_type} — {v.text_snippet!r}" for v in all_violations[:30]
            )
            extra = (
                f"\n  ... and {len(all_violations) - 30} more" if len(all_violations) > 30 else ""
            )
            pytest.fail(
                f"{len(all_violations)} unsourced external numeric claim(s) in NARRATOR files:\n"
                + summary
                + extra
            )


@pytest.mark.skipif(
    not _VERIFIED_PATHS,
    reason="No *VERIFIED*.md files found in outputs/portfolio/ — skipping artifact scan",
)
class TestVerifiedPortfolioArtifacts:
    """Verified portfolio markdown: every external claim must be sourced or arithmetic."""

    def test_verified_portfolio_files_have_no_bare_numeric_claims(self) -> None:
        all_violations: list[Violation] = []
        for path in _VERIFIED_PATHS:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            label = str(path.relative_to(_PORTFOLIO_DIR))
            all_violations.extend(_check_doc(content, label))

        if all_violations:
            summary = "\n".join(
                f"  [{v.file}] {v.claim_type} — {v.text_snippet!r}" for v in all_violations[:30]
            )
            extra = (
                f"\n  ... and {len(all_violations) - 30} more" if len(all_violations) > 30 else ""
            )
            pytest.fail(
                f"{len(all_violations)} unsourced external numeric claim(s) in VERIFIED portfolio files:\n"
                + summary
                + extra
            )
