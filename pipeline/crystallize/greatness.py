"""pipeline.crystallize.greatness — C001-C007 rubric loader + scorer.

Loads ``Inputs/GeniusFilm/GREATNESS_CHECKLIST.json`` and maps each criterion
to an offline-computable proxy using only fields already produced by
``CompoundSeedEngine``. No LLM calls. The aggregate ``weighted_total``
reproduces the rubric's own weighted sum (the JSON file ships 0.25 / 0.15 /
0.20 / 0.10 / 0.10 / 0.10 / 0.10 = 1.00).

The 4 kill-switch criteria (C001, C003, C005, C006 per the JSON) are flagged
when their sub-score drops below ``_KILL_SWITCH_THRESHOLD`` (default 0.4).
Flagged candidates are NOT auto-rejected — the operator sees them in a
separate HTML lane and can override deliberately.

Each proxy is intentionally conservative: the engine's existing fields are
honest signals (genius_score, goldilocks_score, etc.) but they're proxies
themselves. Layering proxies on proxies risks compounding error, so this
module deliberately uses each field for a single criterion only.

MUST NOT import LLM clients. MUST NOT import from frameworks/.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEFAULT_CHECKLIST_PATH: Final[Path] = (
    _REPO_ROOT / "Inputs" / "GeniusFilm" / "GREATNESS_CHECKLIST.json"
)

_KILL_SWITCH_THRESHOLD: Final[float] = 0.4
"""Sub-score below which a kill-switch criterion is flagged as failed."""

_WEIGHT_SUM_TOLERANCE: Final[float] = 1e-6
"""Allowed deviation from 1.0 when summing criterion weights."""

_LORE_DENSITY_CAP: Final[int] = 5
"""Decorative-slot count above which lore density saturates at 1.0."""


@dataclass(frozen=True)
class Criterion:
    """One row from GREATNESS_CHECKLIST.json — typed and immutable."""

    id: str  # C001..C007
    name: str
    domain: str
    question: str
    weight_default: float
    kill_switch: bool


@dataclass(frozen=True)
class Checklist:
    """The complete rubric — version + criteria list."""

    version: str
    criteria: tuple[Criterion, ...]

    def __post_init__(self) -> None:
        total = sum(c.weight_default for c in self.criteria)
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            _log.warning(
                "Checklist weights sum to %.6f (expected 1.0) — rubric will still work",
                total,
            )

    def weight(self, criterion_id: str) -> float:
        """Return the default weight for a criterion id, or 0.0 if unknown."""
        for c in self.criteria:
            if c.id == criterion_id:
                return c.weight_default
        return 0.0

    def is_kill_switch(self, criterion_id: str) -> bool:
        for c in self.criteria:
            if c.id == criterion_id:
                return c.kill_switch
        return False


def load_checklist(path: Path | None = None) -> Checklist:
    """Parse the on-disk JSON checklist into a typed Checklist object.

    Returns a default-empty Checklist if the file is missing — callers can
    still call ``greatness_subscores`` and get all-zero sub-scores rather
    than crashing.
    """
    p = (path or _DEFAULT_CHECKLIST_PATH).resolve()
    if not p.exists():
        _log.warning("load_checklist: %s does not exist; returning empty checklist", p)
        return Checklist(version="0.0", criteria=tuple())

    raw: dict[str, Any] = cast("dict[str, Any]", json.loads(p.read_text(encoding="utf-8")))
    version = str(raw.get("version", "0.0"))
    raw_criteria = raw.get("criteria")
    criteria_raw: list[Any] = (
        cast("list[Any]", raw_criteria) if isinstance(raw_criteria, list) else []
    )

    criteria: list[Criterion] = []
    for entry in criteria_raw:
        if not isinstance(entry, dict):
            continue
        d: dict[str, Any] = cast("dict[str, Any]", entry)
        criteria.append(
            Criterion(
                id=str(d.get("id", "")),
                name=str(d.get("name", "")),
                domain=str(d.get("domain", "")),
                question=str(d.get("question", "")),
                weight_default=float(d.get("weight_default", 0.0) or 0.0),
                kill_switch=bool(d.get("kill_switch", False)),
            )
        )

    return Checklist(version=version, criteria=tuple(criteria))


# ---------------------------------------------------------------------------
# Per-candidate scoring
# ---------------------------------------------------------------------------


def _clamp01(x: float) -> float:
    """Clamp a value to [0.0, 1.0]; treat NaN-ish as 0.0."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v):
        return 0.0
    return max(0.0, min(1.0, v))


def _lore_density_proxy(seed_dict: dict[str, Any]) -> float:
    """Estimate lore density from the count of world-texture-adjacent fields.

    More populated decorative slots (era_collision, conspiracy_engine,
    cultural_moment, open_problem, reptile_trigger, additional_world_textures,
    additional_moral_fault_lines) means more external lore required and
    therefore lower agency (worse C006). We cap the count at
    _LORE_DENSITY_CAP so we don't penalise rich seeds unfairly: a seed with
    7 decorative items isn't 1.4 times worse than one with 5.
    """
    decorative_lists = [
        "era_collision",
        "conspiracy_engine",
        "reptile_trigger",
        "open_problem",
        "cultural_moment",
        "additional_world_textures",
        "additional_moral_fault_lines",
    ]
    total = 0
    for k in decorative_lists:
        v = seed_dict.get(k)
        if isinstance(v, list):
            total += len(cast("list[Any]", v))
    return min(1.0, total / float(_LORE_DENSITY_CAP))


def greatness_subscores(
    seed_dict: dict[str, Any],
    derivative_distance: float = 1.0,
    checklist: Checklist | None = None,
) -> dict[str, Any]:
    """Compute the C001-C007 rubric sub-scores for one candidate.

    Args:
        seed_dict: A ``CompoundSeedResult.to_dict()`` output. Must include
            the ``scores`` sub-dict (with the 21 ``CompoundScore`` fields).
        derivative_distance: 0.0-1.0, novelty vs the films corpus. Default 1.0
            (treat as fully novel) when the corpus is absent — that way
            ``crystallization_score`` doesn't double-penalise.
        checklist: Optional preloaded Checklist; loaded lazily if None.

    Returns:
        Dict with keys ``C001..C007`` (each 0.0-1.0), ``weighted_total``
        (0.0-1.0 weighted sum), and ``kill_switch_failed`` (list of criterion
        ids that fell below the threshold).
    """
    scores: dict[str, Any] = cast("dict[str, Any]", seed_dict.get("scores") or {})

    def _f(key: str, default: float = 0.0) -> float:
        return _clamp01(scores.get(key, default))

    # C001 Expert Surprise Delta: derivative distance vs films corpus.
    c001 = _clamp01(derivative_distance)
    # C002 Associative Goldilocks: peaks at distance ≈ 0.4 — engine already
    # computes this as goldilocks_score.
    c002 = _f("goldilocks_score")
    # C003 Emotional Anchor Stability: scale 0-5 → 0-1.
    emo = float(scores.get("emotional_universality_score") or 0.0)
    c003 = _clamp01(emo / 5.0)
    # C004 Narrative Arc Congruence: thematic anchor (variable coherence
    # around structural_inversion) is the engine's closest analogue.
    c004 = _f("thematic_anchor_score")
    # C005 Homework Coefficient: cultural_field_alignment — how culturally
    # readable is the premise without external homework.
    c005 = _f("cultural_field_alignment")
    # C006 Agency-to-Lore Ratio: inverse of lore density.
    c006 = _clamp01(1.0 - _lore_density_proxy(seed_dict))
    # C007 Compression Progress (Interestingness): engine already proxies this.
    c007 = _f("compression_score")

    sub_scores = {
        "C001": c001,
        "C002": c002,
        "C003": c003,
        "C004": c004,
        "C005": c005,
        "C006": c006,
        "C007": c007,
    }

    cl = checklist or load_checklist()
    weighted_total = sum(cl.weight(cid) * sub for cid, sub in sub_scores.items())
    kill_switch_failed: list[str] = [
        cid
        for cid, sub in sub_scores.items()
        if cl.is_kill_switch(cid) and sub < _KILL_SWITCH_THRESHOLD
    ]

    return {
        **sub_scores,
        "weighted_total": _clamp01(weighted_total),
        "kill_switch_failed": kill_switch_failed,
    }


__all__ = [
    "Checklist",
    "Criterion",
    "greatness_subscores",
    "load_checklist",
]
