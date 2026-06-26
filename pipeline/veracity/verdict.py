"""Deterministic verdict logic for the veracity subsystem (ADR-0002).

No LLM ever writes a verdict. The reality-verifier agent returns *booleans* — a
fetched page is reachable, its text supports (or contradicts) a claimed value —
and :func:`decide` turns those booleans plus a deterministic URL probe and the
claim's own type into one of the verdicts below. This keeps the judgement
reproducible and auditable: the same inputs always yield the same verdict.
"""

from __future__ import annotations

from enum import StrEnum

from pipeline.veracity.claims import Claim


class Verdict(StrEnum):
    """The seven possible outcomes for a single claim."""

    #: External fact: reachable deep-link source AND an agent confirmed the
    #: quoted text supports the claimed value.
    VERIFIED = "VERIFIED"
    #: Reachable deep-link source, but no agent confirmation yet (structural pass).
    SUPPORTED = "SUPPORTED"
    #: Python-executed derivation (SAM/SOM/lifetime) with the invariant intact.
    COMPUTED = "COMPUTED"
    #: No usable source: unreachable, not a deep link, banned host, or no URL.
    UNVERIFIED = "UNVERIFIED"
    #: No source, but the value is an estimate shown with explicit arithmetic.
    INFERRED = "INFERRED"
    #: The source is reachable but its content contradicts the claimed value,
    #: or an agent actively refuted the claim. The most serious outcome.
    FABRICATED = "FABRICATED"


#: Probe verdicts that mean "a real deep-link source is reachable".
_REACHABLE_PROBE: frozenset[str] = frozenset({"PASS", "BOT_BLOCK"})

#: Verdicts that count as credible toward the composite score.
CREDIBLE_VERDICTS: frozenset[Verdict] = frozenset(
    {Verdict.VERIFIED, Verdict.COMPUTED, Verdict.SUPPORTED}
)


def decide(
    claim: Claim,
    probe_verdict: str | None = None,
    *,
    agent_supports: bool | None = None,
    agent_refutes: bool = False,
    calculation_method: str = "",
    invariant_ok: bool = True,
    has_shown_arithmetic: bool = False,
) -> Verdict:
    """Return the deterministic :class:`Verdict` for one claim.

    Args:
        claim: the claim under test.
        probe_verdict: result of :func:`pipeline.veracity.probe.probe_url`
            (``"PASS"`` / ``"BOT_BLOCK"`` / ``"FAIL"`` / ``"NOT_DEEP"`` /
            ``"BANNED"`` / ``"ERROR"``). ``None`` when the URL was not probed.
        agent_supports: a reality-verifier confirmed the source supports the
            value (``True``), contradicts it (``False``), or has not judged it
            yet (``None``).
        agent_refutes: a credibility-auditor actively refuted the claim.
        calculation_method: for computed claims, the source's calculation method.
        invariant_ok: for computed claims, whether SOM < SAM < TAM held.
        has_shown_arithmetic: the value is an estimate accompanied by an equation.
    """
    # 1. Computed derivations are proven by the calculation, never by a URL.
    if claim.is_computed:
        ok = calculation_method == "python_executed" and invariant_ok
        return Verdict.COMPUTED if ok else Verdict.UNVERIFIED

    # 2. Only an ACTIVE contradiction is a fabrication. "Could not confirm" is
    #    not the same as "the source says otherwise" — conflating them would
    #    unfairly brand an unverifiable claim as fabricated.
    if agent_refutes:
        return Verdict.FABRICATED

    # 3. Reachable deep-link source:
    #    - agent confirmed the value          -> VERIFIED
    #    - agent looked and the value is absent (supports False, no contradiction)
    #                                          -> UNVERIFIED (reachable but unstood-up)
    #    - no agent judgment yet (None)        -> SUPPORTED (structural pass, pending)
    if probe_verdict in _REACHABLE_PROBE:
        if agent_supports is True:
            return Verdict.VERIFIED
        return Verdict.UNVERIFIED if agent_supports is False else Verdict.SUPPORTED

    # 4. No usable source. An estimate with shown arithmetic is INFERRED
    #    (honest, defensible); anything else is UNVERIFIED.
    if has_shown_arithmetic and not claim.cited_url:
        return Verdict.INFERRED
    return Verdict.UNVERIFIED
