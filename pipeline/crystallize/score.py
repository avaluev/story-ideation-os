"""pipeline.crystallize.score — single-scalar crystallization quality score.

Geometric mean of eight engine facets multiplied by a gate factor::

    crystallization_score(s, derivative_distance=1.0) =
        s.genius_score                                          ** 0.30
      * s.goldilocks_score                                       ** 0.18
      * s.cluster_coherence                                      ** 0.17
      * min(1.0, s.emotional_universality_score / 5.0)           ** 0.13
      * min(1.0, s.som_floor_M / 300.0)                          ** 0.09
      * derivative_distance                                       ** 0.13
      * (1.0 if (s.passes_500m_gate and s.passes_genius_gate)
                                              else 0.5)

Geometric (not arithmetic) so any near-zero facet collapses the total —
matches the "crystal" intuition: every facet must be present. The
``derivative_distance`` factor (default 1.0) penalises candidates whose
dimension set is too close to an existing film in the 294-film corpus —
this is the C001 Expert Surprise Delta gate from GREATNESS_CHECKLIST.

Pure Python — no LLM, no sklearn, no numpy. ADR-0002 compatible.
Lives in ``pipeline/crystallize/`` (not ``pipeline/scoring.py``) so the
ADR-0002-locked module stays untouched.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Final

# Canonical v4 facet defaults live in goal.py; import the single source so the
# fallback below cannot drift from it (pinned by a no-divergence test). The two
# modules are deliberately coupled on the scoring contract.
from pipeline.goal import _V4_DEFAULT_WEIGHTS  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pipeline.goal import Goal

# Exponents sum to 1.0 (verified by test_crystallize_score_exponents_sum_to_one).
_W_GENIUS: Final[float] = 0.30
_W_GOLDILOCKS: Final[float] = 0.18
_W_CLUSTER_COHERENCE: Final[float] = 0.17
_W_EMO: Final[float] = 0.13
_W_SOM: Final[float] = 0.09
_W_DERIV: Final[float] = 0.13
_W_OP_ALIGN: Final[float] = 0.0
"""Step 5 facet 7 (``operator_alignment``). Starts at 0.0 so the geometric
mean is byte-identical to today's 6-facet output until the operator
promotes this weight (and redistributes one of the others to keep the
exponent sum at 1.0). The facet's value is computed by
:func:`pipeline.feedback.compute_operator_alignment` and degrades to
:data:`pipeline.feedback.OPERATOR_ALIGNMENT_NEUTRAL` (1.0) when ratings
are insufficient -- double defence so this commit cannot shift any
pre-rating score by even one ULP."""

_W_STANDALONE_IP: Final[float] = 0.0
"""v5.1.0 facet 8 (``standalone_ip``) — de-franchise pressure. Starts 0.0 so the
v4 fallback is byte-identical until a Goal (config/goal.json) promotes it. Live
goal.json sets 0.08, funded by derivative_distance 0.20->0.12 (the 0.20
"originality budget" splits into corpus-novelty + franchise-independence)."""

_STANDALONE_IP_NEUTRAL: Final[float] = 0.5
"""Factor for an ambiguous / undetectable IP signal — never 0 so the geometric
mean cannot collapse on a missing flag."""
_STANDALONE_IP_FLOOR: Final[float] = 0.25
"""Factor for a franchise/sequel/adaptation-dependent concept (penalised)."""

_EMO_MAX: Final[float] = 5.0
"""``emotional_universality_score`` is on a 0-5 scale; rescale to 0-1."""

_SOM_NORMALISER_M: Final[float] = 300.0
"""``som_floor_M`` is capped at $400M by the engine; saturate at $300M
(top-quartile original IP territory)."""

_SOM_LOG_FLOOR_USD: Final[float] = 50_000_000.0
_SOM_LOG_CEILING_USD: Final[float] = 1_500_000_000.0
"""R5 (ADR-0011): map the python-executed post-derate Year-1 SOM to the quality
facet on a LOG scale between these bounds instead of saturating at a single
$200M cap.  ~$50M -> 0.0, ~$1.5B -> 1.0, so a $1.1B-SOM idea materially outranks
a $250M one (the old ``min(1.0, som/200M)`` form scored every >=$200M candidate
identically, making revenue invisible to the ranker -- A2/A3/RC2).  Anchored to
the SOM (post-derate) range, NOT the corpus gross ECDF, to avoid compressing
every current idea into the bottom percentile."""

_GATE_FAILURE_PENALTY: Final[float] = 0.5
"""Multiplier applied when either passes_500m_gate or passes_genius_gate is False."""

_FLOOR: Final[float] = 1e-6
"""Numerical floor: zero-replacement before raising to fractional power."""


def _safe_factor(value: float | None) -> float:
    """Clamp a single facet to ``[_FLOOR, 1.0]``; None / NaN → ``_FLOOR``."""
    if value is None:
        return _FLOOR
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _FLOOR
    if math.isnan(v):
        return _FLOOR
    if v <= 0.0:
        return _FLOOR
    if v >= 1.0:
        return 1.0
    return v


def _standalone_ip_factor(flag: bool | None) -> float:
    """De-franchise factor. ``True`` (original standalone) -> 1.0;
    ``None`` (ambiguous) -> :data:`_STANDALONE_IP_NEUTRAL`; ``False``
    (franchise/sequel/adaptation-dependent) -> :data:`_STANDALONE_IP_FLOOR`."""
    if flag is True:
        return 1.0
    if flag is False:
        return _STANDALONE_IP_FLOOR
    return _STANDALONE_IP_NEUTRAL


def _som_factor_y1(som_y1_usd: float, content_format: str | None = None) -> float:
    """R5: log-scale the python-executed Year-1 SOM into a discriminating
    ``[0, 1]`` facet (see :data:`_SOM_LOG_FLOOR_USD` / :data:`_SOM_LOG_CEILING_USD`).

    A monotonic gradient across the realistic post-derate SOM range so the
    crystallization score finally rewards higher revenue instead of saturating
    every candidate >= $200M at 1.0.

    v5.1.0: when ``content_format`` is supplied, the (floor, ceiling) bounds are
    taken from :func:`pipeline.crystallize.format_economics.som_log_bounds` so a
    structurally-smaller streaming-license ($20M-$500M) or microdrama ($5M-$200M)
    Year-1 SOM discriminates on its OWN scale instead of collapsing to ~0 on the
    theatrical $50M-$1.5B scale (monoculture-via-selector fix). ``None`` keeps the
    theatrical bounds -> byte-identical to the pre-format score.
    """
    if som_y1_usd <= 0.0:
        return _FLOOR
    if content_format:
        from pipeline.crystallize import format_economics  # noqa: PLC0415

        floor_usd, ceiling_usd = format_economics.som_log_bounds(content_format)
    else:
        floor_usd, ceiling_usd = _SOM_LOG_FLOOR_USD, _SOM_LOG_CEILING_USD
    lo = math.log(floor_usd)
    hi = math.log(ceiling_usd)
    fraction = (math.log(som_y1_usd) - lo) / (hi - lo)
    return _safe_factor(max(0.0, min(1.0, fraction)))


def crystallization_score(
    scores: dict[str, Any],
    derivative_distance: float = 1.0,
    *,
    goal: Goal | None = None,
    operator_alignment: float = 1.0,
) -> float:
    """Compute the single-scalar quality score for a candidate.

    Args:
        scores: A ``CompoundScore.to_dict()`` output (21 fields).
        derivative_distance: 0.0-1.0, novelty vs corpus. Default 1.0 when
            the corpus is unavailable so the factor becomes a no-op.
        goal: Optional ``pipeline.goal.Goal`` instance. When supplied, its
            ``facet_weights`` replace the module-level ``_W_*`` constants
            for THIS call only -- the constants stay frozen so pre-Step-3
            tests are unaffected. When ``None`` (default), the v4
            hardcoded weights apply (full backward compatibility).
        operator_alignment: 0.0-1.0, Step 5 facet 7 -- cosine of candidate
            facet vector vs rated-positive centroid. Default 1.0 (no-op).
            Caller computes via :func:`pipeline.feedback.compute_operator_alignment`;
            see ``_W_OP_ALIGN`` constant for the (currently zero) exponent.

    Returns:
        Float in ``[0.0, 1.0]``. Geometric mean of 8 facets with
        multiplicative gate penalty.
    """
    genius = _safe_factor(scores.get("genius_score"))
    goldilocks = _safe_factor(scores.get("goldilocks_score"))
    coherence = _safe_factor(scores.get("cluster_coherence"))

    emo_raw = scores.get("emotional_universality_score")
    emo_factor = _safe_factor(min(1.0, float(emo_raw) / _EMO_MAX) if emo_raw is not None else None)

    # v5.0 (ADR-0011): prefer the python-executed ``som_y1_usd`` (post-derate,
    # USD) over the legacy estimated ``som_floor_M`` (pre-derate, M-USD).
    # Either input is normalised to the [0.0, 1.0] facet bucket.
    som_y1_usd = scores.get("som_y1_usd")
    if som_y1_usd is not None:
        som_factor = _som_factor_y1(float(som_y1_usd), scores.get("content_format"))
    else:
        som_raw = scores.get("som_floor_M")
        som_factor = _safe_factor(
            min(1.0, float(som_raw) / _SOM_NORMALISER_M) if som_raw is not None else None
        )

    deriv_factor = _safe_factor(derivative_distance)
    op_align_factor = _safe_factor(operator_alignment)
    standalone_factor = _standalone_ip_factor(scores.get("standalone_ip_flag"))

    # WEDGE Step 3: weight injection. When goal is None, use the v4 frozen
    # constants. When goal is supplied, read facet_weights from it. ADR-0002
    # boundary preserved -- the math (geometric mean + gate penalty) stays
    # entirely in this module; goal.py is data only.
    w = _weights_from_goal(goal)

    base = (
        (genius ** w["genius"])
        * (goldilocks ** w["goldilocks"])
        * (coherence ** w["cluster_coherence"])
        * (emo_factor ** w["emotional_universality"])
        * (som_factor ** w["som_y1"])
        * (deriv_factor ** w["derivative_distance"])
        * (op_align_factor ** w["operator_alignment"])
        * (standalone_factor ** w["standalone_ip"])
    )

    passes_500m = bool(scores.get("passes_500m_gate", False))
    passes_genius = bool(scores.get("passes_genius_gate", False))
    gate_mult = 1.0 if (passes_500m and passes_genius) else _GATE_FAILURE_PENALTY

    result = base * gate_mult
    return max(0.0, min(1.0, result))


# v4 weights used when no Goal is supplied. DERIVED from goal._V4_DEFAULT_WEIGHTS
# (the single canonical source of the 7 facet defaults) plus the score.py-only
# `operator_alignment` facet, so the two dicts CANNOT drift -- a divergence the
# audit flagged as a latent hazard. The module-level `_W_*` constants below stay
# as the documented per-facet exponents (and are pinned == the canonical dict by
# test_v4_fallback_cannot_diverge_from_goal_canonical).
_V4_WEIGHTS_FALLBACK: Final[dict[str, float]] = {
    **_V4_DEFAULT_WEIGHTS,
    "operator_alignment": _W_OP_ALIGN,
}


def _weights_from_goal(goal: Goal | None) -> dict[str, float]:
    """Resolve the active 8-facet weight dict for one ``crystallization_score``
    call. When ``goal`` is None: return the v4 fallback. When ``goal`` carries
    ``facet_weights``: pull those values, filling any missing facet from the
    v4 fallback (forward-compatible if Step 5 adds operator_alignment).
    """
    if goal is None:
        return dict(_V4_WEIGHTS_FALLBACK)
    fw_attr: dict[str, float] = goal.facet_weights
    out = dict(_V4_WEIGHTS_FALLBACK)
    for k in out:
        if k in fw_attr:
            out[k] = float(fw_attr[k])
    return out


__all__ = ["crystallization_score"]
