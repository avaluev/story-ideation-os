"""Unit tests for the veracity subsystem (claims · verdict · scorecard · assess).

All offline — no network. The probe network path is covered separately in
``test_veracity_probe.py``.
"""

from __future__ import annotations

from pipeline.veracity import (
    Claim,
    Verdict,
    decide,
    extract_from_concept,
    extract_from_markdown,
    score_claims,
)
from pipeline.veracity.assess import assess_portfolio, concept_meta, merge_agent_judgments
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.report import render_credibility_md
from pipeline.veracity.scorecard import (
    ClaimAssessment,
    mean_card_composite,
    score_by_concept,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

CONCEPT = {
    "id": "c1",
    "title": "The Repository",
    "format": "Feature Film",
    "calculation_method": "python_executed",
    "tam_usd": 152_000_000_000.0,
    "tam_source_url": "https://www.motionpictures.org/wp-content/uploads/2024/03/report.pdf",
    "sam_usd": 18_240_000_000.0,
    "som_y1_usd": 801_000_000.0,
    "lifetime_usd": 2_360_000_000.0,
    "demand_evidence": [
        {
            "claim": "Only 56% of US adults trust national news.",
            "stat": "56% (down 20 pts)",
            "source_url": "https://www.pewresearch.org/short-reads/2025/10/29/trust.html",
            "date": "2025-10",
        },
        {
            "claim": "The Drama crossed $100M worldwide on a $28M budget.",
            "stat": "$100M WW on $28M",
            "source_url": "https://deadline.com/2026/04/the-drama-box-office-1236867132/",
            "date": "2026-04",
        },
    ],
    "comps": [
        {
            "title": "Maleficent (2014)",
            "imdb_id": "tt1587310",
            "worldwide_gross_usd": 758_539_785.0,
            "budget_usd": 180_000_000.0,
            "roi": 3.21,
            "imdb_url": "https://www.imdb.com/title/tt1587310/",
            "boxofficemojo_url": "https://www.boxofficemojo.com/title/tt1587310/",
        },
    ],
}

PORTFOLIO = {"concepts": [CONCEPT]}


# --------------------------------------------------------------------------- #
# Claim extraction
# --------------------------------------------------------------------------- #


def test_extract_from_concept_covers_all_sources() -> None:
    claims = extract_from_concept(CONCEPT)
    types = {c.claim_type for c in claims}
    # 2 demand rows + 1 comp + tam/sam/som/lifetime
    assert "cultural_signal" in types  # the 56% row
    assert "box_office" in types  # the $100M WW row
    assert "comp_roi" in types
    assert "market_tam" in types
    assert "market_sam" in types
    assert "market_som" in types
    assert "lifetime" in types
    assert len(claims) == 7


def test_claim_ids_are_stable_and_unique() -> None:
    claims = extract_from_concept(CONCEPT)
    ids = [c.claim_id for c in claims]
    assert len(ids) == len(set(ids))  # unique
    # deterministic across re-extraction
    assert ids == [c.claim_id for c in extract_from_concept(CONCEPT)]


def test_computed_flag() -> None:
    claims = {c.claim_type: c for c in extract_from_concept(CONCEPT)}
    assert claims["market_som"].is_computed
    assert claims["market_sam"].is_computed
    assert claims["lifetime"].is_computed
    assert not claims["market_tam"].is_computed
    assert not claims["comp_roi"].is_computed


def test_extract_from_markdown_pulls_links() -> None:
    md = (
        "Audience is large ([56% trust](https://www.pewresearch.org/x/y.html)). "
        "Box office ([$100M WW](https://www.boxofficemojo.com/title/tt1/))."
    )
    claims = extract_from_markdown(md)
    assert len(claims) == 2
    assert any(c.claim_type == "box_office" for c in claims)
    assert all(c.cited_url.startswith("https://") for c in claims)


# --------------------------------------------------------------------------- #
# Verdict logic
# --------------------------------------------------------------------------- #


def _mk(ctype: str, url: str = "https://x.com/a/b") -> Claim:
    return Claim("id", "c", "t", ctype, "text", "v", url)


def test_computed_claim_verdict() -> None:
    c = _mk("market_som", url="")
    assert decide(c, calculation_method="python_executed", invariant_ok=True) == Verdict.COMPUTED
    assert decide(c, calculation_method="llm_guessed", invariant_ok=True) == Verdict.UNVERIFIED
    assert decide(c, calculation_method="python_executed", invariant_ok=False) == Verdict.UNVERIFIED


def test_external_claim_verdicts() -> None:
    c = _mk("box_office")
    assert decide(c, "PASS") == Verdict.SUPPORTED  # reachable, not yet confirmed
    assert decide(c, "PASS", agent_supports=True) == Verdict.VERIFIED
    # reachable but the agent could not stand the value up -> UNVERIFIED, NOT fabricated
    assert decide(c, "PASS", agent_supports=False) == Verdict.UNVERIFIED
    # only an active contradiction is a fabrication
    assert decide(c, "PASS", agent_refutes=True) == Verdict.FABRICATED
    assert decide(c, "BOT_BLOCK") == Verdict.SUPPORTED
    assert decide(c, "FAIL") == Verdict.UNVERIFIED
    assert decide(c, "NOT_DEEP") == Verdict.UNVERIFIED
    assert decide(c, None) == Verdict.UNVERIFIED


def test_refutation_overrides_reachable() -> None:
    c = _mk("cultural_signal")
    assert decide(c, "PASS", agent_refutes=True) == Verdict.FABRICATED


def test_inferred_only_with_arithmetic_and_no_url() -> None:
    c = _mk("market_tam", url="")
    assert decide(c, None, has_shown_arithmetic=True) == Verdict.INFERRED
    assert decide(c, None, has_shown_arithmetic=False) == Verdict.UNVERIFIED


# --------------------------------------------------------------------------- #
# Scorecard
# --------------------------------------------------------------------------- #


def _assess(
    ctype: str, verdict: Verdict, url: str = "https://x.com/a/b", quote: str = ""
) -> ClaimAssessment:
    claim = _mk(ctype, url)
    prov = Provenance(url, 200, "t", None, quote, verdict == Verdict.VERIFIED)
    return ClaimAssessment(claim, verdict, prov)


def test_empty_scorecard() -> None:
    s = score_claims([])
    assert s.composite == 0.0
    assert s.grade == "F"


def test_all_verified_scores_high() -> None:
    items = [_assess("box_office", Verdict.VERIFIED, quote="q") for _ in range(5)]
    s = score_claims(items)
    assert s.composite == 100.0
    assert s.grade == "A"
    assert s.quote_coverage_pct == 100.0


def test_fabrication_caps_grade() -> None:
    items = [_assess("box_office", Verdict.VERIFIED, quote="q") for _ in range(9)]
    items.append(_assess("cultural_signal", Verdict.FABRICATED))
    s = score_claims(items)
    assert s.fabricated_count == 1
    assert s.composite <= 49.0  # any fabrication caps the grade
    assert s.grade == "F"


def test_supported_scores_between_unverified_and_verified() -> None:
    supported = score_claims([_assess("box_office", Verdict.SUPPORTED) for _ in range(4)]).composite
    verified = score_claims([_assess("box_office", Verdict.VERIFIED) for _ in range(4)]).composite
    unverified = score_claims(
        [_assess("box_office", Verdict.UNVERIFIED) for _ in range(4)]
    ).composite
    assert unverified < supported < verified


# --------------------------------------------------------------------------- #
# Assess (structural pass, offline)
# --------------------------------------------------------------------------- #


def test_concept_meta_invariant() -> None:
    meta = concept_meta(PORTFOLIO)
    calc, inv = meta["c1"]
    assert calc == "python_executed"
    assert inv is True  # som < sam < tam holds


def test_concept_meta_invariant_violation() -> None:
    bad = {
        "concepts": [
            {
                "id": "c2",
                "calculation_method": "python_executed",
                "som_y1_usd": 100.0,
                "sam_usd": 50.0,
                "tam_usd": 200.0,
            }
        ]
    }
    _, inv = concept_meta(bad)["c2"]
    assert inv is False  # som > sam violates the floor


def test_assess_portfolio_offline_structural() -> None:
    assessments, score = assess_portfolio(PORTFOLIO, offline=True)
    by_type = {a.claim.claim_type: a.verdict for a in assessments}
    # computed → COMPUTED; external deep-link → SUPPORTED offline
    assert by_type["market_som"] == Verdict.COMPUTED
    assert by_type["market_tam"] == Verdict.SUPPORTED
    assert by_type["box_office"] == Verdict.SUPPORTED
    assert score.fabricated_count == 0
    assert 0 < score.composite <= 100


def test_merge_agent_judgments_upgrades_supported() -> None:
    assessments, before = assess_portfolio(PORTFOLIO, offline=True)
    # confirm every external claim
    judgments = {
        a.claim.claim_id: {"supports": True, "quote": "confirmed in source"}
        for a in assessments
        if not a.claim.is_computed
    }
    after_items, after = merge_agent_judgments(assessments, judgments)
    assert after.composite > before.composite
    assert all(a.verdict == Verdict.VERIFIED for a in after_items if not a.claim.is_computed)


def test_merge_agent_refutation_marks_fabricated() -> None:
    assessments, _ = assess_portfolio(PORTFOLIO, offline=True)
    target = next(a for a in assessments if a.claim.claim_type == "box_office")
    judgments = {target.claim.claim_id: {"refutes": True}}
    _after_items, after = merge_agent_judgments(assessments, judgments)
    assert after.fabricated_count == 1


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def test_score_by_concept_isolates_cards() -> None:
    a = ClaimAssessment(
        Claim("1", "cA", "Card A", "box_office", "t", "$1M", "https://x.com/a/b"),
        Verdict.VERIFIED,
        Provenance("https://x.com/a/b", 200, "t", None, "q", True),
    )
    b = ClaimAssessment(
        Claim("2", "cB", "Card B", "cultural_signal", "t", "9%", "https://y.com/a/b"),
        Verdict.FABRICATED,
        Provenance("https://y.com/a/b", 200, "t", None, "", False),
    )
    per = score_by_concept([a, b])
    assert per["Card A"].grade == "A"  # one bad card does not drag the good one
    assert per["Card B"].grade == "F"
    assert mean_card_composite(per) == round(
        (per["Card A"].composite + per["Card B"].composite) / 2, 1
    )


def test_report_renders_and_is_clean() -> None:
    assessments, score = assess_portfolio(PORTFOLIO, offline=True)
    md = render_credibility_md(assessments, score, title="Test")
    assert "Composite credibility" in md
    assert "The Repository" in md
    # URLs rendered as [host](url), never bare auto-link form
    assert "<https://" not in md
    assert "](https://www.boxofficemojo.com" in md


# --------------------------------------------------------------------------- #
# Online/offline mode is first-class — the offline structural pass can never be
# mistaken for content-verified, and the publication gate requires --online.
# --------------------------------------------------------------------------- #


def test_grade_meets_ordering() -> None:
    from pipeline.veracity.scorecard import grade_meets  # noqa: PLC0415

    assert grade_meets("A", "A") is True
    assert grade_meets("A", "B") is True
    assert grade_meets("B", "A") is False
    assert grade_meets("F", "D") is False
    assert grade_meets("?", "A") is False  # unknown letter never meets a real minimum


def test_assess_portfolio_offline_stamps_offline_mode() -> None:
    from pipeline.veracity.scorecard import MODE_OFFLINE  # noqa: PLC0415

    _, score = assess_portfolio(PORTFOLIO, offline=True)
    assert score.mode == MODE_OFFLINE


def test_merge_agent_judgments_stamps_online_mode() -> None:
    from pipeline.veracity.scorecard import MODE_ONLINE  # noqa: PLC0415

    assessments, _ = assess_portfolio(PORTFOLIO, offline=True)
    judgments = {
        a.claim.claim_id: {"supports": True, "quote": "q"}
        for a in assessments
        if not a.claim.is_computed
    }
    _, after = merge_agent_judgments(assessments, judgments)
    assert after.mode == MODE_ONLINE


def test_grade_gate_blocks_offline_run_even_at_lowest_grade() -> None:
    """The core anti-masquerade contract: an OFFLINE scorecard fails the gate
    even at the most lenient grade, because offline reflects citation form, not
    confirmed reachability."""
    from pipeline.veracity.__main__ import _GATE_EXIT_FAIL, _enforce_grade_gate  # noqa: PLC0415

    assessments, score = assess_portfolio(PORTFOLIO, offline=True)
    assert _enforce_grade_gate(assessments, score, minimum="F") == _GATE_EXIT_FAIL


def test_grade_gate_passes_online_all_verified() -> None:
    from pipeline.veracity.__main__ import _enforce_grade_gate  # noqa: PLC0415
    from pipeline.veracity.scorecard import MODE_ONLINE  # noqa: PLC0415

    assessments, _ = assess_portfolio(PORTFOLIO, offline=True)
    judgments = {
        a.claim.claim_id: {"supports": True, "quote": "q"}
        for a in assessments
        if not a.claim.is_computed
    }
    merged, score = merge_agent_judgments(assessments, judgments)
    assert score.mode == MODE_ONLINE
    assert _enforce_grade_gate(merged, score, minimum="A") == 0


# --------------------------------------------------------------------------- #
# Offline-verdict honesty (FIX 1)
# --------------------------------------------------------------------------- #


def test_offline_assessment_freezes_mode_before_verdicts() -> None:
    """Offline assessments must carry mode=='offline' and no external claim
    may carry a network http_status -- the network was never touched."""
    from pipeline.veracity.scorecard import MODE_OFFLINE  # noqa: PLC0415

    assessments, score = assess_portfolio(PORTFOLIO, offline=True)

    # scorecard mode is established as offline
    assert score.mode == MODE_OFFLINE

    # no external claim provenance should have an http_status set
    for a in assessments:
        if not a.claim.is_computed:
            assert a.provenance.http_status is None, (
                f"claim {a.claim.claim_id!r} has http_status={a.provenance.http_status!r} "
                "but the network was never probed in offline mode"
            )


def test_report_offline_carries_structural_caveat() -> None:
    """The rendered report for an offline run must include the STRUCTURAL PASS
    caveat banner and must not present the grade as network-certified."""
    assessments, score = assess_portfolio(PORTFOLIO, offline=True)
    md = render_credibility_md(assessments, score, title="Test")

    # caveat banner is present
    assert "STRUCTURAL PASS" in md, "offline report missing STRUCTURAL PASS caveat"
    assert "NOT network-confirmed" in md, "offline report missing network caveat"

    # grade must not be presented as certified -- the word 'certified' may
    # only appear inside the caveat itself (as 'not an A-grade certification')
    # and never as a standalone affirmative claim
    assert "certified grade" not in md.lower() or "not an A-grade certification" in md, (
        "offline report presents grade as certified without caveat"
    )
    # the caveat must appear before the grade summary line
    caveat_pos = md.find("STRUCTURAL PASS")
    grade_pos = md.find("Composite credibility")
    assert caveat_pos < grade_pos, "STRUCTURAL PASS caveat must precede the grade summary"
