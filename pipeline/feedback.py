"""pipeline.feedback -- operator-taste -> fitness-weight recalibration.

WEDGE Step 5 of the plan. Step 4 (``pipeline.labels``) gave the engine
a taste signal. This module converts that signal into shifted
``Goal.facet_weights`` via pure-Python logistic regression -- no sklearn,
no numpy, no LLM. The whole module is ~250 LOC of straight gradient
descent so the operator can audit the math line by line.

The contract
============

1. Read every rated row from ``data/labels.jsonl`` (via ``pipeline.labels``).
2. For each rated run_id, look up its winners.json sidecar and extract
   the six engine facets (genius, goldilocks, cluster_coherence,
   emotional_universality, som_y1, derivative_distance) that produced
   its score.
3. Convert each rating to a binary target: ``y = 1`` when ``rating >= +1``,
   ``y = 0`` when ``rating <= -1``. Decay each row by ``0.5 ** (age_days /
   half_life_days)`` so stale taste fades naturally.
4. Fit logistic regression of ``y`` vs the six facet values via gradient
   descent (40 iters, L2=0.5, learning rate 0.1).
5. Normalise the fitted coefficients to a probability simplex (positives
   only, sum to 1.0) -- that gives the *operator-derived* facet weights.
6. Blend with the prior ``Goal.facet_weights`` via ``new = 0.7 * fitted
   + 0.3 * prior`` -- the ADR-0012-style anti-overfit ceiling that
   prevents 10 ratings from flipping the engine into a corner.

What this module does NOT do
============================

- Recompute the operator_alignment 7th facet. That belongs in
  ``crystallize/score.py`` because ADR-0002 keeps numeric scoring math
  in one place. This module shifts the weight VECTOR; score.py applies
  it. The operator_alignment facet itself is a separate concern (a
  cosine-distance facet against rated-positive centroids in axis space)
  -- TODO marker below.
- Auto-save the new Goal. The caller (``loop_wedge.py`` Step 6) decides
  when to persist. ``refit_weights`` returns the new weights dict; the
  caller composes a new Goal and calls ``Goal.save()``.

Operator_alignment facet status: wired structurally in
``pipeline.crystallize.score`` at weight ``_W_OP_ALIGN = 0.0``
(commit cee0984). Activation is operator-driven: rate ≥5 winners,
then promote the weight in ``config/goal.json``. Until promotion,
``compute_operator_alignment`` returns the neutral 1.0 (which raises
to the 0.0 exponent and contributes nothing to the geometric mean).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pipeline import labels

_log = logging.getLogger(__name__)

# The six v4 facets that have always shipped on every winners.json
# scored row. operator_alignment (Step 5 facet 7) appears here only
# when the operator-alignment wire lands in crystallize/score.py.
_V4_FACETS: Final[tuple[str, ...]] = (
    "genius",
    "goldilocks",
    "cluster_coherence",
    "emotional_universality",
    "som_y1",
    "derivative_distance",
)

DEFAULT_HALF_LIFE_DAYS: Final[float] = 30.0
DEFAULT_PRIOR_BLEND: Final[float] = 0.3
"""``new = (1 - prior_blend) * fitted + prior_blend * prior``. 0.3 means
operator-fit weights move ~70 percent of the way toward the data each
recalibration; prior keeps a floor so 10 ratings cannot flip the
engine into a corner."""

DEFAULT_RECALIBRATION_TRIGGER: Final[int] = 10
"""Step 6 loop_wedge calls feedback.refit when ``len(read_since(last_refit))
>= DEFAULT_RECALIBRATION_TRIGGER``. Anything smaller is noise; anything
larger keeps the loop on stale weights."""

_L2_REGULARISER: Final[float] = 0.5
_LR: Final[float] = 0.1
_ITERS: Final[int] = 40

_BINARY_MIDPOINT: Final[float] = 0.5
"""y values are 0.0 / 1.0; > midpoint = positive class, < midpoint = negative."""

_STRONG_RATING_THRESHOLD: Final[int] = 2
"""abs(rating) >= this -> apply STRONG_RATING_WEIGHT_BONUS sample weight."""

_STRONG_RATING_WEIGHT_BONUS: Final[float] = 1.5


def refit_weights(
    rated_rows: list[dict[str, object]],
    winners_by_run_id: dict[str, dict[str, float]],
    *,
    prior_weights: dict[str, float] | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prior_blend: float = DEFAULT_PRIOR_BLEND,
    now: datetime | None = None,
) -> dict[str, float]:
    """Refit ``Goal.facet_weights`` from rated rows + their winners' facet values.

    Args:
        rated_rows: As returned by ``pipeline.labels.read_all`` (rows with
            ``ts``, ``run_id``, ``rating``, optional ``goal_sha``).
        winners_by_run_id: ``{run_id: {facet_name: value}}`` mapping. Each
            inner dict must include the six v4 facets. Built by
            ``read_winner_facets()`` below from runs/*/winners.json sidecars.
        prior_weights: The pre-refit ``Goal.facet_weights`` to blend with.
            When None, defaults to a uniform 1/6 prior.
        half_life_days: Decay rate. 30d means a 60-day-old rating counts
            1/4 as much as today's.
        prior_blend: ``new = (1 - prior_blend) * fitted + prior_blend * prior``.
        now: Override for testing.

    Returns:
        New ``{facet_name: weight}`` with weights >= 0 summing to 1.0.

    Edge cases:
        - No usable rated rows -> returns the prior unchanged.
        - All ratings positive or all negative -> the fit degenerates;
          we fall back to the prior to avoid pushing the engine into a
          single-facet corner.
    """
    if prior_weights is None:
        prior_weights = {f: 1.0 / len(_V4_FACETS) for f in _V4_FACETS}
    if now is None:
        now = datetime.now(UTC)

    samples = _build_samples(rated_rows, winners_by_run_id, now, half_life_days)
    if not samples:
        return _normalised(prior_weights)

    labels_y = [s.y for s in samples]
    if all(y > _BINARY_MIDPOINT for y in labels_y) or all(y < _BINARY_MIDPOINT for y in labels_y):
        # Degenerate -- not enough variance to fit. Keep prior.
        _log.info("feedback.refit_weights: degenerate labels (all same class); keeping prior")
        return _normalised(prior_weights)

    coefs = _fit_logistic(samples)
    fitted = _coefs_to_weights(coefs)
    blended = _blend(fitted, _normalised(prior_weights), prior_blend)
    return _normalised(blended)


def read_winner_facets(
    rated_rows: list[dict[str, object]],
    runs_root: Path | str = Path("runs"),
) -> dict[str, dict[str, float]]:
    """For every rated run, load its winners.json sidecar and pull the
    six v4 facet values. Skips runs whose sidecar is missing or whose
    facets do not parse -- the loop is operator-driven and we don't
    crash on one bad row."""
    out: dict[str, dict[str, float]] = {}
    root = Path(runs_root)
    seen: set[str] = set()
    for row in rated_rows:
        rid = str(row.get("run_id", ""))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        sidecar = _find_winners_sidecar(root, rid)
        if sidecar is None:
            continue
        facets = _parse_facets(sidecar)
        if facets is not None:
            out[rid] = facets
    return out


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


class _Sample:
    """One training row. ``x`` is the six-facet feature vector in
    ``_V4_FACETS`` order; ``y`` is 1.0 (positive rating) or 0.0
    (negative); ``w`` is the time-decayed sample weight."""

    __slots__ = ("w", "x", "y")

    def __init__(self, x: list[float], y: float, w: float) -> None:
        self.x = x
        self.y = y
        self.w = w


def _build_samples(
    rated_rows: list[dict[str, object]],
    winners_by_run_id: dict[str, dict[str, float]],
    now: datetime,
    half_life_days: float,
) -> list[_Sample]:
    samples: list[_Sample] = []
    for row in rated_rows:
        rid = str(row.get("run_id", ""))
        if not rid:
            continue
        facets = winners_by_run_id.get(rid)
        if facets is None:
            continue
        rating_obj = row.get("rating")
        if not isinstance(rating_obj, int):
            continue
        # Binary target: +1/+2 -> 1.0, -1/-2 -> 0.0. Rating == 0 is not
        # in VALID_RATINGS but we'd skip it anyway.
        if rating_obj >= 1:
            y = 1.0
        elif rating_obj <= -1:
            y = 0.0
        else:
            continue
        x = [float(facets.get(f, 0.0)) for f in _V4_FACETS]
        w = _decay_weight(row.get("ts", ""), now, half_life_days)
        # Stronger ratings (+2 / -2) get 1.5x weight relative to +1/-1.
        if abs(rating_obj) >= _STRONG_RATING_THRESHOLD:
            w *= _STRONG_RATING_WEIGHT_BONUS
        samples.append(_Sample(x=x, y=y, w=w))
    return samples


def _decay_weight(ts_obj: object, now: datetime, half_life_days: float) -> float:
    if not isinstance(ts_obj, str) or not ts_obj:
        return 1.0
    try:
        ts = datetime.fromisoformat(ts_obj)
    except ValueError:
        return 1.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return 0.5 ** (age_days / max(0.001, half_life_days))


def _fit_logistic(samples: list[_Sample]) -> list[float]:
    """Pure-Python gradient descent on weighted logistic regression.

    Returns the per-facet coefficient vector. Positive coef -> facet
    correlates with positive operator rating. Coefficients pass
    through ``_coefs_to_weights`` to become non-negative simplex
    weights.
    """
    n_features = len(_V4_FACETS)
    coefs: list[float] = [0.0] * n_features
    for _ in range(_ITERS):
        grads: list[float] = [0.0] * n_features
        for s in samples:
            z = sum(c * xi for c, xi in zip(coefs, s.x, strict=True))
            p = 1.0 / (1.0 + math.exp(-_clip(z, -30.0, 30.0)))
            err = (p - s.y) * s.w
            for j in range(n_features):
                grads[j] += err * s.x[j]
        # L2 regulariser pulls coefficients toward 0.
        for j in range(n_features):
            grads[j] += _L2_REGULARISER * coefs[j]
            coefs[j] -= _LR * grads[j] / max(1, len(samples))
    return coefs


def _coefs_to_weights(coefs: list[float]) -> dict[str, float]:
    """Project raw logistic coefficients onto the probability simplex
    (non-negative, sum to 1.0).

    Negative coefficients get floored at 0 -- they encode "the operator
    dislikes this facet", which becomes "do not weight it" in the
    fitness vector. If every coefficient is non-positive (degenerate
    fit), fall back to a uniform 1/N split.
    """
    raw = [max(0.0, c) for c in coefs]
    total = sum(raw)
    if total <= 0.0:
        uniform = 1.0 / len(_V4_FACETS)
        return {f: uniform for f in _V4_FACETS}
    return {f: raw[i] / total for i, f in enumerate(_V4_FACETS)}


def _blend(
    fitted: dict[str, float],
    prior: dict[str, float],
    prior_blend: float,
) -> dict[str, float]:
    blend = max(0.0, min(1.0, prior_blend))
    return {f: (1.0 - blend) * fitted.get(f, 0.0) + blend * prior.get(f, 0.0) for f in _V4_FACETS}


def _normalised(weights: dict[str, float]) -> dict[str, float]:
    pos = {k: max(0.0, v) for k, v in weights.items()}
    total = sum(pos.values())
    if total <= 0.0:
        uniform = 1.0 / len(_V4_FACETS)
        return {f: uniform for f in _V4_FACETS}
    return {k: v / total for k, v in pos.items()}


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _find_winners_sidecar(runs_root: Path, run_id: str) -> Path | None:
    """Locate runs/<run_id>/.../winners.json. Returns None when not found.

    Evolve runs land at runs/<run_id>/evolve/gen0/winners.json. Single-idea
    runs use a different layout but currently don't get rated by run_id
    (Step 5 is /evolve-centric -- single-idea concepts are slug-named
    NARRATOR.md files).
    """
    direct = runs_root / run_id / "evolve" / "gen0" / "winners.json"
    if direct.exists():
        return direct
    # Defensive glob -- in case the layout shifts.
    matches = list(runs_root.glob(f"{run_id}/**/winners.json"))
    return matches[0] if matches else None


def _parse_facets(sidecar: Path) -> dict[str, float] | None:
    """Extract the six v4 facet values from a winners.json sidecar.

    Looks at ``winners[0].scores`` -- the top-1 scored row, which is the
    one the operator rated. Returns None if the schema doesn't match
    (e.g., older sidecar layout) so the caller can skip silently.
    """
    try:
        raw_obj: object = json.loads(sidecar.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw_obj, dict):
        return None
    raw: dict[str, object] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    winners_obj: object = raw.get("winners")
    if not isinstance(winners_obj, list) or not winners_obj:
        return None
    winners_list: list[object] = list(winners_obj)  # type: ignore[reportUnknownArgumentType]
    top_obj: object = winners_list[0]
    if not isinstance(top_obj, dict):
        return None
    top: dict[str, object] = {str(k): v for k, v in top_obj.items()}  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    scores_obj: object = top.get("scores")
    if not isinstance(scores_obj, dict):
        return None
    scores: dict[str, object] = {str(k): v for k, v in scores_obj.items()}  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    emo = _safe_float(scores.get("emotional_universality_score"))
    som_y1 = _safe_float(scores.get("som_y1_usd"))
    deriv = _safe_float(top.get("derivative_distance"))
    return {
        "genius": _safe_float(scores.get("genius_score")),
        "goldilocks": _safe_float(scores.get("goldilocks_score")),
        "cluster_coherence": _safe_float(scores.get("cluster_coherence")),
        "emotional_universality": min(1.0, emo / 5.0) if emo > 0 else 0.0,
        "som_y1": min(1.0, som_y1 / 200_000_000.0) if som_y1 > 0 else 0.0,
        "derivative_distance": max(0.0, min(1.0, deriv)),
    }


def _safe_float(v: object) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------
# operator_alignment facet (Step 5 facet 7) -- WIRED 2026-05-27
# ----------------------------------------------------------------------
#
# Structural wire only. The facet returns a meaningful cosine value when
# the operator has rated >= MIN_POSITIVE_FOR_ALIGNMENT winners; until
# then it returns OPERATOR_ALIGNMENT_NEUTRAL (1.0). score.py's _W_OP_ALIGN
# exponent is 0.0 today, so the facet is also a no-op at the score-math
# level -- double defence so this commit cannot shift any pre-rating
# score by even one ULP. The day the operator promotes _W_OP_ALIGN (and
# redistributes another facet's weight to keep the exponent sum at 1.0),
# the facet starts steering fitness. Validation against real labels
# happens then, not now.

MIN_POSITIVE_FOR_ALIGNMENT: Final[int] = 5
"""Below this many rated-positive (+1/+2) winners, the centroid is too
noisy to predict operator taste; compute_operator_alignment returns the
no-op value OPERATOR_ALIGNMENT_NEUTRAL (1.0) instead."""

OPERATOR_ALIGNMENT_NEUTRAL: Final[float] = 1.0
"""No-signal output. score.py multiplies the geometric mean by this
raised to _W_OP_ALIGN; with _W_OP_ALIGN currently 0.0 the factor is
x**0 = 1 anyway, so this neutral value is defence-in-depth for the day
the operator promotes _W_OP_ALIGN."""


def compute_operator_alignment(
    candidate_facets: dict[str, float],
    rated_rows: list[dict[str, object]],
    winners_by_run_id: dict[str, dict[str, float]],
    *,
    min_positive: int = MIN_POSITIVE_FOR_ALIGNMENT,
) -> float:
    """Return the operator_alignment facet value for one candidate.

    Math: the rated-positive centroid is the mean of the 6-facet vectors
    across all winners the operator rated +1 or +2. The candidate's
    6-facet vector is compared to that centroid via cosine similarity,
    mapped from [-1, 1] to [0, 1] as (1 + cos) / 2.

    Args:
        candidate_facets: 6-facet dict keyed by names in :data:`_V4_FACETS`.
            Missing facets default to 0.0.
        rated_rows: Rows from :func:`pipeline.labels.read_all`.
        winners_by_run_id: Output of :func:`read_winner_facets` -- the
            facet vector for each rated run.
        min_positive: Floor on the count of rated-positive winners needed
            for the centroid to be meaningful. Below this, returns
            :data:`OPERATOR_ALIGNMENT_NEUTRAL`.

    Returns:
        Float in ``[0.0, 1.0]``. ``OPERATOR_ALIGNMENT_NEUTRAL`` (1.0)
        when insufficient signal -- in that branch, score.py's geometric
        mean is unchanged.
    """
    positive_vectors: list[list[float]] = []
    for row in rated_rows:
        rating = row.get("rating")
        if not isinstance(rating, int) or rating < 1:
            continue
        rid = str(row.get("run_id", ""))
        if not rid:
            continue
        facets = winners_by_run_id.get(rid)
        if facets is None:
            continue
        positive_vectors.append([float(facets.get(f, 0.0)) for f in _V4_FACETS])

    if len(positive_vectors) < min_positive:
        return OPERATOR_ALIGNMENT_NEUTRAL

    n = len(_V4_FACETS)
    centroid = [sum(vec[i] for vec in positive_vectors) / len(positive_vectors) for i in range(n)]
    cand_vec = [float(candidate_facets.get(f, 0.0)) for f in _V4_FACETS]
    cos = _cosine(cand_vec, centroid)
    return max(0.0, min(1.0, 0.5 * (1.0 + cos)))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors. Returns 0.0 when
    either norm is zero (degenerate / all-zero vector)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


__all__ = [
    "DEFAULT_HALF_LIFE_DAYS",
    "DEFAULT_PRIOR_BLEND",
    "DEFAULT_RECALIBRATION_TRIGGER",
    "MIN_POSITIVE_FOR_ALIGNMENT",
    "OPERATOR_ALIGNMENT_NEUTRAL",
    "compute_operator_alignment",
    "read_winner_facets",
    "refit_weights",
]


# Module-level smoke import to confirm pipeline.labels is reachable
# without circular dep (regression: an earlier draft accidentally
# imported labels at the module level and broke pyright).
_ = labels.DEFAULT_LABELS_PATH
