"""Render a human-readable CREDIBILITY.md from a set of claim assessments.

The markdown is investor-facing, so it goes through
:func:`pipeline.template_filter.strip_internal_ids` before it is returned
(ADR-0010). URLs are rendered as ``[host](url)`` links -- never bare domains,
never the ``<url>`` auto-link form (content-quality-gate policy).
"""

from __future__ import annotations

from collections import OrderedDict
from urllib.parse import urlparse

from pipeline.template_filter import strip_internal_ids
from pipeline.veracity.scorecard import (
    MODE_OFFLINE,
    ClaimAssessment,
    CredibilityScore,
    mean_card_composite,
    score_by_concept,
)

_VERDICT_BADGE: dict[str, str] = {
    "VERIFIED": "✅ Verified",
    "COMPUTED": "\U0001f9ee Computed",
    "SUPPORTED": "\U0001f517 Source reachable",
    "INFERRED": "➗ Estimated (arithmetic shown)",
    "UNVERIFIED": "⚠️ Unverified",
    "FABRICATED": "❌ Contradicted",
}

_MAX_QUOTE_CHARS: int = 180

#: Banner injected at the top of every offline scorecard so it is never
#: mistaken for a content-verified or network-confirmed result.
_OFFLINE_CAVEAT: str = (
    "> **STRUCTURAL PASS -- citation FORM only, NOT network-confirmed; "
    "not an A-grade certification.**  "
    "URL reachability and page content have not been verified. "
    "Run with `--online` (or fold in agent judgments) for a certified grade."
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "source").removeprefix("www.")


def _source_cell(url: str) -> str:
    if not url:
        return "—"
    return f"[{_host(url)}]({url})"


def _quote_cell(quote: str) -> str:
    q = quote.strip().replace("|", "\\|").replace("\n", " ")
    if len(q) > _MAX_QUOTE_CHARS:
        q = q[: _MAX_QUOTE_CHARS - 1].rstrip() + "…"
    return f"“{q}”" if q else "—"


def render_credibility_md(
    assessments: list[ClaimAssessment],
    score: CredibilityScore,
    *,
    title: str = "Credibility Scorecard",
    subtitle: str = "",
) -> str:
    lines: list[str] = [f"# {title}", ""]
    if subtitle:
        lines += [subtitle, ""]

    # Offline runs reflect citation *form* only -- surface the caveat
    # prominently so the report is never mistaken for a content-verified or
    # certified grade.
    if score.mode == MODE_OFFLINE:
        lines += [_OFFLINE_CAVEAT, ""]

    per_concept = score_by_concept(assessments)
    headline = mean_card_composite(per_concept) if len(per_concept) > 1 else score.composite

    lines += [
        f"**Composite credibility: {headline}/100 -- Grade {score.grade}**",
        "",
        f"- Claims assessed: **{score.n_total}** "
        f"({score.n_external} external facts · {score.n_computed} python-computed)",
        f"- Cards graded: **{len(per_concept)}** "
        f"(mean card credibility {mean_card_composite(per_concept)}/100)",
        f"- Distinct sources: **{score.distinct_source_count}**",
        f"- Deep-link coverage: **{score.deep_link_pct}%** · "
        f"Direct-quote coverage: **{score.quote_coverage_pct}%**",
        f"- Evidence density (verified / external): **{score.claim_density_pct}%**",
        f"- Contradicted / fabricated claims: **{score.fabricated_count}**",
        "",
        "Verdict mix: " + " · ".join(f"{v} {n}" for v, n in sorted(score.verdict_counts.items())),
        "",
    ]

    by_concept: OrderedDict[str, list[ClaimAssessment]] = OrderedDict()
    for a in assessments:
        key = a.claim.concept_title or a.claim.concept_id or "Document"
        by_concept.setdefault(key, []).append(a)

    for concept, items in by_concept.items():
        card = per_concept.get(concept)
        grade_tag = f" -- **{card.composite}/100 · Grade {card.grade}**" if card else ""
        lines += [f"## {concept}{grade_tag}", ""]
        lines += [
            "| Claim | Value | Verdict | Source | Direct quote |",
            "| --- | --- | --- | --- | --- |",
        ]
        for a in items:
            badge = _VERDICT_BADGE.get(str(a.verdict), str(a.verdict))
            claim_text = a.claim.text.replace("|", "\\|")
            if len(claim_text) > _MAX_QUOTE_CHARS:
                claim_text = claim_text[: _MAX_QUOTE_CHARS - 1].rstrip() + "…"
            lines.append(
                f"| {claim_text} | {a.claim.value or chr(0x2014)} | {badge} | "
                f"{_source_cell(a.claim.cited_url)} | {_quote_cell(a.provenance.quote)} |"
            )
        lines.append("")

    return strip_internal_ids("\n".join(lines))
