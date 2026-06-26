"""Deterministic credibility scoring for the veracity subsystem (ADR-0002).

Aggregates per-claim verdicts into a 0-100 composite credibility score and a
letter grade. Every number here is computed in Python — no LLM writes a score.

The composite is a verdict-weighted coverage measure with a hard fabrication
penalty: VERIFIED/COMPUTED claims count fully, a reachable-but-unconfirmed
SUPPORTED claim counts partially (so the score *rises* as agents confirm
content), and any FABRICATED claim caps the grade. This makes the score honest
both before agent confirmation (structural pass) and after.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pipeline.veracity.claims import Claim
from pipeline.veracity.probe import is_deep_path
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.verdict import Verdict

#: How much each verdict contributes to the credible-coverage numerator.
_VERDICT_WEIGHT: dict[Verdict, float] = {
    Verdict.VERIFIED: 1.0,
    Verdict.COMPUTED: 1.0,
    Verdict.SUPPORTED: 0.6,
    Verdict.INFERRED: 0.3,
    Verdict.UNVERIFIED: 0.0,
    Verdict.FABRICATED: 0.0,
}

_FABRICATION_PENALTY: float = 30.0
_FABRICATION_GRADE_CAP: float = 49.0
_GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "A"),
    (80.0, "B"),
    (70.0, "C"),
    (60.0, "D"),
    (0.0, "F"),
)

#: Probe mode stamped onto a scorecard. ``"online"`` means every cited URL was
#: actually fetched over the network (content can be agent-verified); ``"offline"``
#: means the structural pass rewrote unprobed deep links to a SUPPORTED *structural*
#: verdict WITHOUT touching the network -- so an offline grade reflects citation
#: *form*, never confirmed reachability. A publication gate MUST require "online".
MODE_ONLINE: str = "online"
MODE_OFFLINE: str = "offline"

#: Grade letters best-to-worst, for ``grade_meets`` ordering comparisons.
_GRADE_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "F")


def grade_meets(grade: str, minimum: str) -> bool:
    """Return True iff ``grade`` is at least as good as ``minimum`` (A best).

    ``grade_meets("A", "A")`` is True; ``grade_meets("B", "A")`` is False.
    Unknown letters are treated as worst (never meet a real minimum).
    """
    try:
        return _GRADE_ORDER.index(grade) <= _GRADE_ORDER.index(minimum)
    except ValueError:
        return False


def _empty_counts() -> dict[str, int]:
    return {}


@dataclass(frozen=True)
class ClaimAssessment:
    """One claim + its deterministic verdict + its provenance record."""

    claim: Claim
    verdict: Verdict
    provenance: Provenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim.claim_id,
            "concept_id": self.claim.concept_id,
            "concept_title": self.claim.concept_title,
            "claim_type": self.claim.claim_type,
            "text": self.claim.text,
            "value": self.claim.value,
            "cited_url": self.claim.cited_url,
            "verdict": str(self.verdict),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class CredibilityScore:
    """The document-level deterministic credibility scorecard."""

    composite: float
    grade: str
    n_total: int
    n_external: int
    n_computed: int
    verdict_counts: dict[str, int] = field(default_factory=_empty_counts)
    quote_coverage_pct: float = 0.0
    deep_link_pct: float = 0.0
    distinct_source_count: int = 0
    fabricated_count: int = 0
    #: "online" iff every cited URL was network-probed; "offline" otherwise. An
    #: offline scorecard reflects citation *form*, not confirmed reachability, so
    #: it MUST NOT be treated as content-verified (see :data:`MODE_OFFLINE`). The
    #: assess_* helpers stamp this; bare :func:`score_claims` defaults to offline.
    mode: str = MODE_OFFLINE
    #: Honest evidence density: the fraction of EXTERNAL claims that are fully
    #: stood up (verdict VERIFIED = reachable deep link + verbatim quote +
    #: agent-confirmed support), over ALL external claims. Distinct from
    #: deep_link_pct (URL *form* only — counts even an unconfirmed URL) and from
    #: quote_coverage_pct (a quote is present). The publish gate's
    #: ``--assert-density`` floor reads this. 0.0 on a structural/offline pass —
    #: nothing is agent-confirmed without the network.
    claim_density_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _grade_for(composite: float) -> str:
    for floor, letter in _GRADE_BANDS:
        if composite >= floor:
            return letter
    return "F"


def score_by_concept(results: list[ClaimAssessment]) -> dict[str, CredibilityScore]:
    """Score each concept independently — so one weak card cannot mask the rest.

    Keyed by concept title (falling back to concept id). This is what the
    assembler reads to decide which cards are ship-ready.
    """
    groups: dict[str, list[ClaimAssessment]] = {}
    for r in results:
        key = r.claim.concept_title or r.claim.concept_id or "Document"
        groups.setdefault(key, []).append(r)
    return {k: score_claims(v) for k, v in groups.items()}


def mean_card_composite(per_concept: dict[str, CredibilityScore]) -> float:
    """Portfolio-level headline: the mean of the per-card composites.

    Unlike a single :func:`score_claims` over the whole slate (where one
    contradicted claim caps the global grade), this reflects the slate's
    *average* card quality — the honest portfolio summary.
    """
    if not per_concept:
        return 0.0
    return round(sum(s.composite for s in per_concept.values()) / len(per_concept), 1)


def score_claims(results: list[ClaimAssessment]) -> CredibilityScore:
    """Compute the deterministic credibility scorecard for a set of assessments."""
    if not results:
        return CredibilityScore(composite=0.0, grade="F", n_total=0, n_external=0, n_computed=0)

    n_total = len(results)
    externals = [r for r in results if not r.claim.is_computed]
    n_external = len(externals)
    n_computed = n_total - n_external

    verdict_counts: dict[str, int] = {}
    weighted = 0.0
    for r in results:
        verdict_counts[str(r.verdict)] = verdict_counts.get(str(r.verdict), 0) + 1
        weighted += _VERDICT_WEIGHT.get(r.verdict, 0.0)

    fabricated = verdict_counts.get(str(Verdict.FABRICATED), 0)

    quoted = sum(1 for r in externals if r.provenance.quote.strip())
    quote_coverage = quoted / n_external if n_external else 1.0
    deep = sum(1 for r in externals if r.claim.cited_url and is_deep_path(r.claim.cited_url))
    deep_link_pct = deep / n_external if n_external else 1.0
    distinct_sources = len({r.claim.cited_url for r in externals if r.claim.cited_url})
    # Evidence density: external claims fully stood up (VERIFIED) over all external
    # claims. Honest by construction — 0 until agents confirm content online.
    verified_external = sum(1 for r in externals if r.verdict == Verdict.VERIFIED)
    claim_density = verified_external / n_external if n_external else 0.0

    composite = 100.0 * weighted / n_total
    composite -= _FABRICATION_PENALTY * fabricated
    composite = max(0.0, min(100.0, composite))
    if fabricated:
        composite = min(composite, _FABRICATION_GRADE_CAP)

    return CredibilityScore(
        composite=round(composite, 1),
        grade=_grade_for(composite),
        n_total=n_total,
        n_external=n_external,
        n_computed=n_computed,
        verdict_counts=verdict_counts,
        quote_coverage_pct=round(quote_coverage * 100, 1),
        deep_link_pct=round(deep_link_pct * 100, 1),
        distinct_source_count=distinct_sources,
        fabricated_count=fabricated,
        claim_density_pct=round(claim_density * 100, 1),
    )
