"""Eval: the veracity subsystem's structural pass over the real portfolio.

Offline + resilient (skips when the enriched portfolio is absent). Guards the
invariants the credibility layer must always hold:

  * no claim is silently FABRICATED in the shipped artifact,
  * computed economics (SOM/SAM/lifetime) verify-by-computation,
  * deep-link coverage stays high (the deep-link evidence policy),
  * the composite + grade are deterministic (same input → same score).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.veracity import Verdict, score_claims
from pipeline.veracity.assess import assess_portfolio
from pipeline.veracity.claims import Claim
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.scorecard import ClaimAssessment

_PORTFOLIO = Path("outputs/portfolio/portfolio_enriched.json")
_MIN_CLAIMS = 100
_MIN_DEEP_LINK_PCT = 90.0


def _load() -> dict[str, object]:
    if not _PORTFOLIO.exists():
        pytest.skip(f"{_PORTFOLIO} not present")
    return json.loads(_PORTFOLIO.read_text(encoding="utf-8"))


def test_portfolio_structural_pass_has_no_fabrication() -> None:
    assessments, score = assess_portfolio(_load(), offline=True)
    assert score.n_total >= _MIN_CLAIMS
    assert score.fabricated_count == 0
    assert not any(a.verdict == Verdict.FABRICATED for a in assessments)


def test_computed_economics_verify_by_computation() -> None:
    assessments, _ = assess_portfolio(_load(), offline=True)
    computed = [a for a in assessments if a.claim.is_computed]
    assert computed, "portfolio should contain computed economics claims"
    # Every computed claim must resolve to COMPUTED (python_executed + invariant)
    # or, if a concept's data is incomplete, UNVERIFIED — never a false-positive.
    assert all(a.verdict in (Verdict.COMPUTED, Verdict.UNVERIFIED) for a in computed)
    assert sum(1 for a in computed if a.verdict == Verdict.COMPUTED) >= len(computed) // 2


def test_deep_link_coverage_meets_policy() -> None:
    _, score = assess_portfolio(_load(), offline=True)
    assert score.deep_link_pct >= _MIN_DEEP_LINK_PCT


def test_score_is_deterministic() -> None:
    data = _load()
    a = assess_portfolio(data, offline=True)[1]
    b = assess_portfolio(data, offline=True)[1]
    assert a.composite == b.composite
    assert a.grade == b.grade
    assert a.verdict_counts == b.verdict_counts


def test_fabrication_caps_grade_invariant() -> None:
    # synthetic guard independent of the portfolio file

    good = [
        ClaimAssessment(
            Claim(f"id{i}", "c", "t", "box_office", "x", "$1M", "https://x.com/a/b"),
            Verdict.VERIFIED,
            Provenance("https://x.com/a/b", 200, "t", None, "q", True),
        )
        for i in range(20)
    ]
    bad = ClaimAssessment(
        Claim("idF", "c", "t", "cultural_signal", "t", "9%", "https://y.com/a/b"),
        Verdict.FABRICATED,
        Provenance("https://y.com/a/b", 200, "t", None, "", False),
    )
    assert score_claims([*good, bad]).grade == "F"
