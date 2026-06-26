# ruff: noqa: E501 - the CARD fixture mirrors real card prose (long sentences are intentional)
"""Tests for the honest evidence-density metric, the card-scoring path, and the
``--assert-density`` publish gate (Movement 2).

``claim_density_pct`` is VERIFIED-external / all-external — distinct from
``deep_link_pct`` (URL form only) and ``quote_coverage_pct`` (quote present).
``assess_card`` feeds the section-aware enumerator so ``deep_link_pct`` stops
being the tautological ~100% and becomes the true density. All offline.
"""

from __future__ import annotations

from pipeline.veracity.__main__ import _enforce_density_gate
from pipeline.veracity.assess import assess_card
from pipeline.veracity.claims import Claim
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.scorecard import (
    MODE_OFFLINE,
    MODE_ONLINE,
    ClaimAssessment,
    CredibilityScore,
    score_claims,
)
from pipeline.veracity.verdict import Verdict

CARD = """# Mini

#### Logline
A child has nine days to save two thousand people.

# 1. Market & Audience

## Audience Sizing

The total addressable market is $328.2 billion. Animated features are the most durable revenue category in that market.

## Why Now

11 million people were displaced by disaster in 2024.

# 3. Story

## Comparables

| Title | Year | WW Revenue | Budget | ROI |
|---|---|---|---|---|
| The Bodyguard | 1992 | $411.0M | $25.0M | 15.4x |

## Verified Proof of Demand

- **A comp crossed $1.009B worldwide** — "grand total to $1.009 billion globally" ([source](https://variety.com/2025/film/box-office/x-1236272527/), 2025-01-19)

## Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $328.20B | sourced ([THEME.pdf](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf)). |
| **SAM** | $39.38B | a transparent derivation. |
| **SOM (Year 1)** | $540M | python_executed. |
"""


def _ext(verdict: Verdict, quote: str = "q") -> ClaimAssessment:
    claim = Claim("i", "c", "t", "box_office", "text", "v", "https://x.com/a/b")
    prov = Provenance("https://x.com/a/b", 200, "t", None, quote, verdict == Verdict.VERIFIED)
    return ClaimAssessment(claim, verdict, prov)


# --------------------------------------------------------------------------- #
# Density metric
# --------------------------------------------------------------------------- #


def test_claim_density_field_defaults_zero() -> None:
    s = score_claims([])
    assert s.claim_density_pct == 0.0
    assert "claim_density_pct" in s.to_dict()


def test_claim_density_counts_verified_over_all_external() -> None:
    items = [_ext(Verdict.VERIFIED) for _ in range(2)] + [_ext(Verdict.SUPPORTED) for _ in range(3)]
    s = score_claims(items)
    assert s.claim_density_pct == 40.0  # 2 verified / 5 external
    # density is stricter than deep-link coverage (all 5 have a deep-link URL)
    assert s.deep_link_pct == 100.0
    assert s.claim_density_pct < s.deep_link_pct


def test_density_is_zero_when_nothing_verified() -> None:
    s = score_claims([_ext(Verdict.SUPPORTED) for _ in range(4)])
    assert s.claim_density_pct == 0.0


# --------------------------------------------------------------------------- #
# assess_card — the honest denominator
# --------------------------------------------------------------------------- #


def test_assess_card_deep_link_pct_is_honest_not_tautological() -> None:
    _assessments, score = assess_card(CARD, offline=True, concept_id="mini", concept_title="Mini")
    # 5 external: TAM(url) + Bodyguard(no url) + "most durable"(no url) +
    # "11 million"(no url) + proof bullet(url) -> 2/5 deep-linked = 40% (NOT 100%)
    assert score.n_external == 5
    assert score.deep_link_pct == 40.0


def test_assess_card_binds_already_rendered_quote() -> None:
    _assessments, score = assess_card(CARD, offline=True, concept_id="mini")
    # the proof bullet's verbatim quote binds -> quote coverage rises ...
    assert score.quote_coverage_pct > 0
    # ... but an offline bind never mints a VERIFIED (no live confirmation)
    assert score.claim_density_pct == 0.0
    assert score.mode == MODE_OFFLINE


def test_assess_card_marks_economics_computed() -> None:
    assessments, _ = assess_card(CARD, offline=True, concept_id="mini")
    by_type = {a.claim.claim_type: a.verdict for a in assessments}
    assert by_type["market_sam"] == Verdict.COMPUTED
    assert by_type["market_som"] == Verdict.COMPUTED
    assert by_type["market_tam"] != Verdict.COMPUTED  # TAM is external


# --------------------------------------------------------------------------- #
# --assert-density publish gate
# --------------------------------------------------------------------------- #


def _score(*, mode: str, density: float, fabricated: int = 0) -> CredibilityScore:
    return CredibilityScore(
        composite=90.0,
        grade="A",
        n_total=10,
        n_external=10,
        n_computed=0,
        mode=mode,
        claim_density_pct=density,
        fabricated_count=fabricated,
    )


def test_density_gate_fails_offline_even_at_zero_floor() -> None:
    assert _enforce_density_gate(_score(mode=MODE_OFFLINE, density=100.0), floor=0.0) != 0


def test_density_gate_fails_below_floor_online() -> None:
    assert _enforce_density_gate(_score(mode=MODE_ONLINE, density=50.0), floor=0.9) != 0


def test_density_gate_fails_on_fabrication() -> None:
    assert (
        _enforce_density_gate(_score(mode=MODE_ONLINE, density=99.0, fabricated=1), floor=0.9) != 0
    )


def test_density_gate_passes_online_above_floor() -> None:
    assert _enforce_density_gate(_score(mode=MODE_ONLINE, density=95.0), floor=0.9) == 0
