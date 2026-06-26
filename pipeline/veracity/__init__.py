"""pipeline.veracity — reality-verification + evidence-amplification subsystem.

Sits *after* concept generation. Takes a finished concept (a portfolio_enriched
concept dict or a rendered NARRATOR/portfolio markdown file), pulls every
externally-checkable factual claim out of it, lets the reality-verifier /
credibility-auditor agents confirm each claim against a primary source (deep
link + direct quote), and produces a deterministic credibility scorecard.

Division of labour (honours ADR-0002 / ADR-0011):
  * **Python (this package)** — extract claims, probe URLs, compute every verdict
    and every score. No LLM ever writes a number or a verdict here.
  * **Agents** (``.claude/agents/reality-verifier`` etc.) — read one claim, fetch
    its source, and return *booleans* ("does the fetched text support this
    value?") + a captured quote. Those booleans feed :func:`verdict.decide`.

External facts (demand stats, comp grosses, TAM aggregates) require a reachable
deep-link source whose content supports the value. Python-computed derivations
(SAM, SOM, lifetime) are verified-by-computation: ``calculation_method ==
"python_executed"`` plus the SOM < SAM < TAM invariant — never by a URL.
"""

from __future__ import annotations

from pipeline.veracity.claims import (
    CLAIM_TYPES,
    COMPUTED_TYPES,
    Claim,
    extract_from_concept,
    extract_from_markdown,
    extract_from_portfolio,
)
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.scorecard import CredibilityScore, score_claims
from pipeline.veracity.verdict import Verdict, decide

__all__ = [
    "CLAIM_TYPES",
    "COMPUTED_TYPES",
    "Claim",
    "CredibilityScore",
    "Provenance",
    "Verdict",
    "decide",
    "extract_from_concept",
    "extract_from_markdown",
    "extract_from_portfolio",
    "score_claims",
]
