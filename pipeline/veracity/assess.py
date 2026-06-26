"""Glue: extract → probe → decide → score, for a whole portfolio or one doc.

This is the deterministic *structural* pass an operator runs directly
(``python -m pipeline.veracity``). It establishes, for every claim, whether its
cited source is a reachable deep link and whether computed numbers honour the
SOM < SAM < TAM invariant. The agent layer (reality-verifier / credibility-
auditor) later upgrades SUPPORTED → VERIFIED by confirming the page content and
capturing a direct quote; those agent booleans flow back through
:func:`merge_agent_judgments`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import httpx

from pipeline.veracity.claims import Claim, extract_from_markdown, extract_from_portfolio
from pipeline.veracity.enumerate import (
    card_quote_judgments,
    enumerate_claims,
    frozen_economics,
)
from pipeline.veracity.probe import probe_url
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.scorecard import (
    MODE_OFFLINE,
    MODE_ONLINE,
    ClaimAssessment,
    CredibilityScore,
    score_claims,
)
from pipeline.veracity.verdict import Verdict, decide

#: (calculation_method, invariant_ok) per concept — drives the COMPUTED verdict.
ConceptMeta = dict[str, tuple[str, bool]]


def _as_float(val: object) -> float:
    if isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def concept_meta(data: dict[str, Any]) -> ConceptMeta:
    """Map each concept id to ``(calculation_method, invariant_ok)``.

    ``invariant_ok`` is ``True`` only when every present economic figure obeys
    ``som < sam < tam`` (the floor the revenue model guarantees).
    """
    out: ConceptMeta = {}
    concepts_raw = data.get("concepts")
    if not isinstance(concepts_raw, list):
        return out
    for c_raw in cast("list[object]", concepts_raw):
        if not isinstance(c_raw, dict):
            continue
        c = cast("dict[str, Any]", c_raw)
        cid = str(c.get("id") or c.get("economics_key") or "").strip()
        if not cid:
            continue
        calc = str(c.get("calculation_method", "")).strip()
        som, sam, tam = (
            _as_float(c.get("som_y1_usd")),
            _as_float(c.get("sam_usd")),
            _as_float(c.get("tam_usd")),
        )
        present = [v for v in (som, sam, tam) if v > 0]
        invariant_ok = present == sorted(present) and len(set(present)) == len(present)
        out[cid] = (calc, invariant_ok)
    return out


def _offline_structural_verdict(claim: Claim, fetched_at: str) -> ClaimAssessment:
    """Return a SUPPORTED verdict for a deep-link claim in offline mode.

    This path is taken when ``probe_url`` returns ``SKIPPED_OFFLINE`` — the URL
    has the correct structural form (a deep path, not a bare domain or banned
    host) but the network was never touched.  We grant SUPPORTED (weight 0.6)
    because the citation is policy-compliant; we leave ``http_status=None`` so
    any downstream consumer can detect that no HTTP round-trip occurred.  The
    scorecard is separately stamped ``mode="offline"`` (see
    :func:`assess_portfolio` / :func:`assess_markdown`), which is what the
    publication gate uses to refuse certification.
    """
    prov = Provenance(
        url=claim.cited_url,
        http_status=None,  # no network round-trip
        fetched_at=fetched_at,
        content_sha256=None,
        quote="",
        supports_claim=False,
    )
    return ClaimAssessment(claim, Verdict.SUPPORTED, prov)


def _assess_one(
    claim: Claim,
    meta: ConceptMeta,
    *,
    offline: bool,
    client: httpx.Client | None,
) -> ClaimAssessment:
    if claim.is_computed:
        calc, inv = meta.get(claim.concept_id, ("", True))
        verdict = decide(claim, calculation_method=calc, invariant_ok=inv)
        return ClaimAssessment(claim, verdict, Provenance.empty())

    probe = probe_url(claim.cited_url, client=client, offline=offline)
    if probe.verdict == "SKIPPED_OFFLINE":
        # Offline — the network was never touched. The citation has the correct
        # *form* (a deep-link URL) so it earns a structural SUPPORTED (weight
        # 0.6). We do NOT call decide() with "PASS" here because that would
        # misrepresent an untested URL as network-confirmed. Instead we produce
        # SUPPORTED directly and leave http_status=None so any consumer can
        # detect that no HTTP round-trip occurred.
        return _offline_structural_verdict(claim, probe.fetched_at)
    verdict = decide(claim, probe.verdict)
    prov = Provenance(
        url=claim.cited_url,
        http_status=probe.status,
        fetched_at=probe.fetched_at,
        content_sha256=probe.content_sha256,
        quote="",
        supports_claim=False,
    )
    return ClaimAssessment(claim, verdict, prov)


def assess_portfolio(
    data: dict[str, Any],
    *,
    offline: bool = True,
) -> tuple[list[ClaimAssessment], CredibilityScore]:
    """Run the structural pass over a full enriched-portfolio dict."""
    claims = extract_from_portfolio(data)
    meta = concept_meta(data)
    client = (
        None
        if offline
        else httpx.Client(
            headers={"User-Agent": "AnomalyEngine/5.0 veracity-probe"},
            timeout=12.0,
            follow_redirects=True,
        )
    )
    try:
        assessments = [_assess_one(c, meta, offline=offline, client=client) for c in claims]
    finally:
        if client is not None:
            client.close()
    score = score_claims(assessments)
    return assessments, replace(score, mode=(MODE_OFFLINE if offline else MODE_ONLINE))


def assess_markdown(
    md: str,
    *,
    offline: bool = True,
    concept_id: str = "doc",
) -> tuple[list[ClaimAssessment], CredibilityScore]:
    """Run the structural pass over an arbitrary markdown document."""
    claims = extract_from_markdown(md, concept_id=concept_id)
    client = (
        None
        if offline
        else httpx.Client(
            headers={"User-Agent": "AnomalyEngine/5.0 veracity-probe"},
            timeout=12.0,
            follow_redirects=True,
        )
    )
    try:
        assessments = [_assess_one(c, {}, offline=offline, client=client) for c in claims]
    finally:
        if client is not None:
            client.close()
    score = score_claims(assessments)
    return assessments, replace(score, mode=(MODE_OFFLINE if offline else MODE_ONLINE))


def assess_card(
    md: str,
    *,
    offline: bool = True,
    concept_id: str = "doc",
    concept_title: str = "",
) -> tuple[list[ClaimAssessment], CredibilityScore]:
    """Score a rendered concept CARD using the section-aware enumerator.

    Unlike :func:`assess_markdown` (which harvests only already-linked claims and
    so reports a tautological ~100% deep-link coverage), this counts EVERY
    external claim — comps without inline links, prose statistics, market
    conclusions — so ``deep_link_pct`` is the *honest* density. Verbatim quotes
    already rendered in the card's Verified Proof of Demand bullets are bound
    onto their claims (raising quote coverage) without minting a VERIFIED — only
    a live re-fetch (the sourcing workflow) sets agent support.
    """
    claims = enumerate_claims(md, concept_id=concept_id, concept_title=concept_title)
    frozen = frozen_economics(md)
    present = [v for v in (frozen.get("som"), frozen.get("sam"), frozen.get("tam")) if v]
    invariant_ok = present == sorted(present) and len(set(present)) == len(present)
    meta: ConceptMeta = {concept_id: ("python_executed", invariant_ok)}
    client = (
        None
        if offline
        else httpx.Client(
            headers={"User-Agent": "AnomalyEngine/5.0 veracity-probe"},
            timeout=12.0,
            follow_redirects=True,
        )
    )
    try:
        assessments = [_assess_one(c, meta, offline=offline, client=client) for c in claims]
    finally:
        if client is not None:
            client.close()
    target_mode = MODE_OFFLINE if offline else MODE_ONLINE
    judgments = card_quote_judgments(md, concept_id=concept_id)
    if judgments:
        merged, score = merge_agent_judgments(assessments, judgments, meta)
        return merged, replace(score, mode=target_mode)
    return assessments, replace(score_claims(assessments), mode=target_mode)


def merge_agent_judgments(
    assessments: list[ClaimAssessment],
    judgments: dict[str, dict[str, Any]],
    meta: ConceptMeta | None = None,
) -> tuple[list[ClaimAssessment], CredibilityScore]:
    """Re-decide every claim with agent judgments folded in, then re-score.

    ``judgments`` maps ``claim_id`` → ``{"supports": bool|None, "refutes": bool,
    "quote": str}`` as returned by the reality-verifier / credibility-auditor
    agents. External claims with no judgment keep their structural verdict.
    """
    meta = meta or {}
    out: list[ClaimAssessment] = []
    for a in assessments:
        j = judgments.get(a.claim.claim_id, {})
        if a.claim.is_computed:
            out.append(a)
            continue
        supports = j.get("supports")
        refutes = bool(j.get("refutes", False))
        quote = str(j.get("quote", "") or "")
        probe_verdict = "PASS" if (a.provenance.http_status or 0) else None
        # Preserve a structural reachable verdict so a missing probe doesn't
        # silently downgrade an already-reachable source.
        if a.verdict in (Verdict.SUPPORTED, Verdict.VERIFIED):
            probe_verdict = "PASS"
        verdict = decide(
            a.claim,
            probe_verdict,
            agent_supports=cast("bool | None", supports),
            agent_refutes=refutes,
        )
        prov = Provenance(
            url=a.provenance.url,
            http_status=a.provenance.http_status,
            fetched_at=a.provenance.fetched_at,
            content_sha256=a.provenance.content_sha256,
            quote=quote or a.provenance.quote,
            supports_claim=supports is True,
        )
        out.append(ClaimAssessment(a.claim, verdict, prov))
    # Folding in agent judgments means content was checked over the live network
    # (the amplify workflow WebFetches each source), so the merged scorecard is
    # content-verified -> online. With no judgments it is still a structural pass.
    merged_mode = MODE_ONLINE if judgments else MODE_OFFLINE
    return out, replace(score_claims(out), mode=merged_mode)
