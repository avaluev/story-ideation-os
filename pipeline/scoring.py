"""Pure-Python scoring module for the Anomaly Engine pipeline.

This is the ONLY place in the pipeline where numeric scores are computed (ADR-0002).
LLMs MUST NOT populate total_score, sdt_score, or ajtbd_score fields directly.

Rules:
- MUST NOT import openrouter_client, anthropic, or httpx (ANOMALY-001,
  enforced by scripts/lint_imports.py).
- MUST NOT import from frameworks/ (ANOMALY-002,
  enforced by scripts/lint_imports.py).
- Formulas are verbatim from framework files, cited per ADR-0005.

Functions:
    sdt_score               — SDT score [0..70]
    ajtbd_score             — AJTBD audience score [0..30]
    polti_tobias_coherence  — Anti-pattern check (bool)
    overall_score           — Combined score dict with passes_85_floor

References:
    ADR-0002: LLMs no arithmetic — scoring.py is the single source of truth.
    ADR-0005: Frameworks read-only — cite section when implementing formula.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pipeline.empirical_genius import EGI_AXIS_MAX
from pipeline.empirical_genius import score_concept as _egi_score_concept

# ── Named constants (avoids PLR2004 magic-number lint) ───────────────────────

# sdt_score thresholds and coefficients
_SDT_PRIMARY_FLOOR: float = 0.7
_SDT_PRIMARY_COEFF: int = 50
_SDT_SECONDARY_COEFF: int = 20
_SDT_CAP: int = 70
_SDT_DEPRIVATION_AMP: float = 1.5

# ajtbd_score thresholds and point values
_AJTBD_AUDIENCE_MIN: int = 50_000_000
_AJTBD_COUNTRY_MIN: int = 3
_AJTBD_SOURCES_MIN: int = 2
_AJTBD_JTBD_STRENGTH_MIN: float = 0.6
_AJTBD_CAP: int = 30

# overall_score thresholds
_OVERALL_AGREEMENT_WINDOW: int = 10
_OVERALL_READINESS_FLOOR: int = 85
_OVERALL_CAP: int = 100


def sdt_score(
    primary_need: str,
    primary_strength: float,
    secondary_need: str | None,
    secondary_strength: float,
    deprivation_amplifier_active: bool,
) -> int:
    """Compute SDT (Self-Determination Theory) score in [0..70].

    Returns 0 when primary_strength < 0.7 (hard floor — concept fails SDT gate).
    Capped at 70; remaining 30 points live in ajtbd_score.

    Formula: frameworks/sdt-spine.md §The sdt_score Formula (ADR-0005).

    Args:
        primary_need: One of "autonomy", "competence", "relatedness".
        primary_strength: Float in [0.0, 1.0] — Forge-assigned strength.
        secondary_need: Second SDT need name, or None.
        secondary_strength: Float in [0.0, 1.0] — strength of secondary need.
        deprivation_amplifier_active: True if cited deprivation evidence provided.

    Returns:
        Integer score in [0..70].
    """
    s1 = primary_strength
    s2 = secondary_strength
    amp = 1.5 if deprivation_amplifier_active else 1.0
    amplified = (_SDT_PRIMARY_COEFF * s1 * amp) + (_SDT_SECONDARY_COEFF * s2)
    return min(round(amplified), _SDT_CAP) if s1 >= _SDT_PRIMARY_FLOOR else 0


def ajtbd_score(
    cited_audience: int,
    country_count: int,
    sources_per_claim: int,
    trend_direction: str,
    primary_jtbd_strength: float,
) -> int:
    """Compute AJTBD (Audience Jobs-to-be-Done) score in [0..30].

    Five binary thresholds, each worth 5 or 10 points, capped at 30.

    Formula: frameworks/ajtbd-segmentation.md §The ajtbd_score Formula (ADR-0005).

    Args:
        cited_audience: Total addressable audience in absolute count.
        country_count: Number of distinct countries with cited evidence.
        sources_per_claim: Distinct source URLs per audience claim.
        trend_direction: "rising" | "stable" | "declining".
        primary_jtbd_strength: Float in [0.0, 1.0] — Forge-assigned fit strength.

    Returns:
        Integer score in [0..30].
    """
    score = 0
    if cited_audience >= _AJTBD_AUDIENCE_MIN:
        score += 10
    if country_count >= _AJTBD_COUNTRY_MIN:
        score += 5
    if sources_per_claim >= _AJTBD_SOURCES_MIN:
        score += 5
    if trend_direction in ("rising", "stable"):
        score += 5
    if primary_jtbd_strength >= _AJTBD_JTBD_STRENGTH_MIN:
        score += 5
    return min(score, _AJTBD_CAP)


@lru_cache(maxsize=1)
def _load_coherence_matrix() -> dict[str, Any]:
    """Load pipeline/data/polti_tobias_coherence.json exactly once (LRU cached).

    Returns:
        The full parsed JSON dict with an "anti_patterns" list.
    """
    path = Path("pipeline/data/polti_tobias_coherence.json")
    return json.loads(path.read_text())  # type: ignore[return-value]


def polti_tobias_coherence(polti_id: int, tobias_id: int) -> bool:
    """Return True if the Polti x Tobias combination is coherent (not an anti-pattern).

    Loads pipeline/data/polti_tobias_coherence.json via an LRU-cached reader.
    Returns False if the pair appears in the "anti_patterns" list; True otherwise.

    Args:
        polti_id: Polti dramatic situation ID (1..36).
        tobias_id: Tobias master plot ID (1..20).

    Returns:
        False if the combination is a documented anti-pattern; True otherwise.
    """
    matrix = _load_coherence_matrix()
    anti_patterns: list[dict[str, Any]] = matrix.get("anti_patterns", [])
    for entry in anti_patterns:
        if entry.get("polti_id") == polti_id and entry.get("tobias_id") == tobias_id:
            return False
    return True


def overall_score(
    upstream_sdt: int,
    upstream_ajtbd: int,
    critic_novelty: int,
    critic_jtbd: int,
    critic_contradiction: int,
    critic_specificity: int,
    cap_at_70_triggered: bool,
) -> dict[str, Any]:
    """Compute the overall concept score and return a full breakdown dict.

    Combines upstream Forge scores with Critic scores, applies an agreement
    bonus when both signals converge, and flags the 85-point readiness floor.

    Formula: FEATURES.md REQ-P-006. Pure Python — ADR-0002.
    agreement_bonus: +5 if |critic_raw - upstream| <= 10 (trust convergent signals).

    Args:
        upstream_sdt: sdt_score result from the Forge [0..70].
        upstream_ajtbd: ajtbd_score result from the Forge [0..30].
        critic_novelty: Critic novelty_score [0..30].
        critic_jtbd: Critic jtbd_score [0..25].
        critic_contradiction: Critic contradiction_score [0..25].
        critic_specificity: Critic specificity_score [0..20].
        cap_at_70_triggered: True if Phase5Critique.cap_at_70_triggered is set.

    Returns:
        Dict with keys:
            upstream (int): upstream_sdt + upstream_ajtbd
            critic (int): raw critic total (after cap if triggered)
            base (int): min(critic_raw, upstream)
            agreement_bonus (int): 5 if signals converge, else 0
            final (int): min(base + agreement_bonus, 100)
            passes_85_floor (bool): final >= 85
    """
    upstream = upstream_sdt + upstream_ajtbd
    critic_raw = critic_novelty + critic_jtbd + critic_contradiction + critic_specificity
    if cap_at_70_triggered:
        critic_raw = min(critic_raw, 70)
    base = min(critic_raw, upstream)
    agreement_bonus = 5 if abs(critic_raw - upstream) <= _OVERALL_AGREEMENT_WINDOW else 0
    final = min(base + agreement_bonus, _OVERALL_CAP)
    return {
        "upstream": upstream,
        "critic": critic_raw,
        "base": base,
        "agreement_bonus": agreement_bonus,
        "final": final,
        "passes_85_floor": final >= _OVERALL_READINESS_FLOOR,
    }


# ── 5th axis: Empirical Genius Index integration (post-Synthesizer) ──────────


def overall_score_with_egi(
    upstream_sdt: int,
    upstream_ajtbd: int,
    critic_novelty: int,
    critic_jtbd: int,
    critic_contradiction: int,
    critic_specificity: int,
    cap_at_70_triggered: bool,
    *,
    concept_row: dict[str, Any],
    critique_row: dict[str, Any],
    audience_row: dict[str, Any],
    jtbd_row: dict[str, Any],
    asset_row: dict[str, Any],
) -> dict[str, Any]:
    """Compute overall_score plus the 5th axis (Empirical Genius Index).

    Wraps overall_score() and adds the EGI sub-composite from
    pipeline/empirical_genius.py (consumes GREATNESS_CHECKLIST.json compiled
    by the Cinema Idea Genius Synthesizer).

    Stage 1 (kill switches C006, C007): if any fires, the concept is REJECTED
    regardless of the 4-axis result. final = 0; passes_85_floor = False;
    egi_kill_switches lists the IDs.

    Stage 2 (additive): when kill switches pass, EGI in [0, EGI_AXIS_MAX] is
    added to the legacy 4-axis final, capped at the 4-axis cap + EGI_AXIS_MAX
    (i.e. 100 + 25 = 125). passes_85_floor still uses the legacy final (≥85
    out of 100) to preserve the existing publication contract.

    Args:
        upstream_sdt..cap_at_70_triggered: same as overall_score().
        concept_row..asset_row: phase-row joins for the EGI computation.

    Returns:
        Same keys as overall_score() PLUS:
            egi (float): EGI 5th axis score in [0, EGI_AXIS_MAX].
            egi_breakdown (dict): {"novelty": float, "shape": float,
                                   "survival": float, "criteria_pass": dict,
                                   "kill_switches_triggered": list[str],
                                   "degraded": bool, "message": str}.
            final_5axis (float): legacy_final + egi, capped at 100+EGI_AXIS_MAX.
            egi_kill_switches (list[str]): IDs that fired (empty if Stage 1 OK).
    """
    legacy = overall_score(
        upstream_sdt,
        upstream_ajtbd,
        critic_novelty,
        critic_jtbd,
        critic_contradiction,
        critic_specificity,
        cap_at_70_triggered,
    )

    egi_result = _egi_score_concept(
        concept_row,
        critique_row,
        audience_row,
        jtbd_row,
        asset_row,
    )
    egi_value = float(egi_result.get("final", 0.0) or 0.0)
    triggered_raw: object = egi_result.get("kill_switches_triggered", []) or []
    triggered: list[str] = (
        [str(x) for x in triggered_raw]  # type: ignore[reportUnknownArgumentType]
        if isinstance(triggered_raw, list)
        else []
    )

    if triggered:
        return {
            **legacy,
            "final": 0,
            "passes_85_floor": False,
            "egi": 0.0,
            "egi_breakdown": egi_result,
            "final_5axis": 0.0,
            "egi_kill_switches": triggered,
        }

    final_5axis = min(legacy["final"] + egi_value, _OVERALL_CAP + EGI_AXIS_MAX)

    return {
        **legacy,
        "egi": egi_value,
        "egi_breakdown": egi_result,
        "final_5axis": round(final_5axis, 1),
        "egi_kill_switches": [],
    }
