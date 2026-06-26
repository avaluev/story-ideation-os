"""pipeline.select.diversity_select -- top-K with cluster floor (ADR-0012).

The v4 single-idea pipeline picked the highest ``crystallization_score``
candidate and walked away.  At ``n_base=64``, the top-K by raw score
clusters tightly around the dominant attractor: 8 of the top 10 candidates
share the same ``(primary_cluster, protagonist_archetype, world_texture)``
triple, and three of the eight thematic clusters never appear at all.

This module fixes that with two orthogonal mechanisms:

1. **Triple repeat-penalty (greedy).**  For each survivor already chosen,
   we multiply the raw score of any further candidate sharing its
   ``(cluster, archetype, world_texture)`` triple by ``alpha ** k`` where
   ``k`` is how many existing survivors share that triple.  ``alpha=0.5``
   means a duplicate's effective score drops by 50% per copy already in
   the survivor set.

2. **Cluster-floor swap-in.**  After the greedy fill, count the distinct
   ``primary_cluster`` values represented.  If below ``cluster_floor``,
   find the best remaining candidate per *missing* cluster whose raw
   score is at least ``quality_threshold`` and swap it in for the
   weakest survivor sitting in an *over-represented* cluster.  Anchors
   below the quality floor are never force-promoted (a quota-filling
   garbage candidate is worse than a coherent winner).

Pure Python.  ADR-0001 (no hidden state) + ADR-0002 (no LLM) + ADR-0012.

The module deliberately does NOT import ``CompoundSeedResult`` -- callers
wrap their objects in :class:`SelectCandidate` so this stays trivially
unit-testable and decoupled from the engine.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Final

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: Engine ships eight thematic clusters (see ``_CLUSTER_NAMES`` in
#: ``pipeline/compound_seed.py``).  Asking for half-coverage is a reasonable
#: starting floor: the v4 baseline reliably hits 1-2.
DEFAULT_CLUSTER_FLOOR: Final[int] = 4

#: Top-K size.  Day-3 wiring in ``one_shot.py`` will pass ``top_k=5`` for
#: the operator-facing slate; 10 is the diagnostic default.
DEFAULT_TOP_K: Final[int] = 10

#: Anchors weaker than this are not force-promoted to fill the cluster
#: floor.  0.55 maps to "above the median crystallization_score across
#: a 64-candidate base population" in current smoke runs.
DEFAULT_QUALITY_THRESHOLD: Final[float] = 0.55

#: Multiplier per existing duplicate of a ``(cluster, archetype, texture)``
#: triple.  ``0.5`` halves a duplicate's effective score per copy.
DEFAULT_REPEAT_PENALTY_ALPHA: Final[float] = 0.5


# ---------------------------------------------------------------------------
# Lightweight candidate adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectCandidate:
    """Adapter that exposes only the fields the selector needs.

    Callers wrap their domain object (typically a ``CompoundSeedResult``)
    and keep a reference via :attr:`payload` so the selector's output can
    round-trip back to the original.

    Attributes:
        score: The pre-computed scalar quality (``crystallization_score``).
            Higher is better.  Must be a finite float.
        primary_cluster: The dominant thematic cluster name (one of the
            eight engine clusters).  Empty string is allowed but never
            counts toward cluster coverage.
        archetype_id: ``protagonist_archetype.id`` -- used in the triple
            that powers the repeat-penalty.
        world_texture_id: ``world_texture.id`` -- same purpose.
        payload: Free-form back-reference.  The selector never inspects
            it.
    """

    score: float
    primary_cluster: str
    archetype_id: str
    world_texture_id: str
    payload: Any = None

    @property
    def triple(self) -> tuple[str, str, str]:
        """The ``(cluster, archetype, texture)`` key used for repeat-penalty."""
        return (self.primary_cluster, self.archetype_id, self.world_texture_id)


# ---------------------------------------------------------------------------
# Core selector
# ---------------------------------------------------------------------------


def select_top_k(
    candidates: list[SelectCandidate],
    k: int = DEFAULT_TOP_K,
    cluster_floor: int = DEFAULT_CLUSTER_FLOOR,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    repeat_penalty_alpha: float = DEFAULT_REPEAT_PENALTY_ALPHA,
) -> list[SelectCandidate]:
    """Return up to ``k`` survivors with cluster coverage enforced.

    Algorithm:

    1. Greedy fill.  Repeat ``k`` times: from the not-yet-selected pool,
       pick the candidate whose ``score * alpha ** k_dup`` is highest,
       where ``k_dup`` is how many existing survivors already share that
       candidate's ``(cluster, archetype, texture)`` triple.  Ties broken
       by raw score, then by stable insertion order.
    2. Cluster-floor swap-in.  Count distinct ``primary_cluster`` values
       in the survivors.  While fewer than ``cluster_floor``, find the
       best remaining candidate per *missing* cluster whose raw score
       is at least ``quality_threshold``.  Replace the survivor whose
       cluster has the most representatives and whose own raw score is
       lowest within that over-represented cluster.

    Edge cases:

    - Empty input -> empty output.
    - ``len(candidates) < k`` -> returns all candidates (greedy-ranked).
    - ``cluster_floor`` impossible to satisfy (not enough qualifying
      anchors) -> returns the best feasible coverage and stops; never
      raises.  Callers can inspect the result's cluster distribution to
      decide whether to widen the pool.

    Args:
        candidates: The candidate population.  Need not be sorted.
        k: Maximum survivors to return.  ``k <= 0`` returns ``[]``.
        cluster_floor: Distinct-cluster minimum.  Soft target -- never
            raises when unsatisfiable.
        quality_threshold: Anchor floor.  Anchors below this are not
            force-promoted.
        repeat_penalty_alpha: ``(0, 1]`` -- 1.0 disables the penalty,
            0.5 halves duplicates per copy.

    Returns:
        A new list of ``SelectCandidate`` -- the survivor set, in
        selection order (greedy picks first, then any swaps).  Length
        is at most ``min(k, len(candidates))``.
    """
    if k <= 0 or not candidates:
        return []

    survivors: list[SelectCandidate] = _greedy_fill(
        candidates,
        k=k,
        repeat_penalty_alpha=repeat_penalty_alpha,
    )

    if cluster_floor <= 0:
        return survivors

    _enforce_cluster_floor(
        survivors=survivors,
        candidates=candidates,
        cluster_floor=cluster_floor,
        quality_threshold=quality_threshold,
    )
    return survivors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _adjusted_score(
    candidate: SelectCandidate,
    triple_counts: dict[tuple[str, str, str], int],
    alpha: float,
) -> float:
    """``score * alpha ** dup_count`` -- duplicates discounted exponentially."""
    dup = triple_counts.get(candidate.triple, 0)
    if dup <= 0 or alpha >= 1.0:
        return candidate.score
    if alpha <= 0.0:
        # Fully ban duplicates -- adjusted score becomes 0.
        return 0.0
    return candidate.score * (alpha**dup)


def _greedy_fill(
    candidates: list[SelectCandidate],
    *,
    k: int,
    repeat_penalty_alpha: float,
) -> list[SelectCandidate]:
    # Stable insertion order is preserved via the index tiebreaker so equal
    # adjusted-scores keep determinism.
    indexed: list[tuple[int, SelectCandidate]] = list(enumerate(candidates))
    survivors: list[SelectCandidate] = []
    triple_counts: dict[tuple[str, str, str], int] = {}
    chosen_ids: set[int] = set()

    while len(survivors) < k and len(chosen_ids) < len(indexed):
        best_idx: int | None = None
        best_score = float("-inf")
        for idx, cand in indexed:
            if idx in chosen_ids:
                continue
            adj = _adjusted_score(cand, triple_counts, repeat_penalty_alpha)
            # Strict > breaks ties toward earlier insertion (stable).
            if adj > best_score:
                best_score = adj
                best_idx = idx
        if best_idx is None:
            break
        chosen = indexed[best_idx][1]
        survivors.append(chosen)
        chosen_ids.add(best_idx)
        triple_counts[chosen.triple] = triple_counts.get(chosen.triple, 0) + 1

    return survivors


def _find_best_anchor_per_missing_cluster(
    candidates: list[SelectCandidate],
    survivor_ids: set[int],
    present: set[str],
    quality_threshold: float,
) -> dict[str, SelectCandidate]:
    """Return ``{cluster: highest-scoring candidate}`` for missing clusters."""
    anchors: dict[str, SelectCandidate] = {}
    for cand in candidates:
        if id(cand) in survivor_ids:
            continue
        if not cand.primary_cluster or cand.primary_cluster in present:
            continue
        if cand.score < quality_threshold:
            continue
        existing = anchors.get(cand.primary_cluster)
        if existing is None or cand.score > existing.score:
            anchors[cand.primary_cluster] = cand
    return anchors


def _pick_swap_victim(survivors: list[SelectCandidate]) -> int | None:
    """Return survivor index whose removal does not shrink cluster coverage.

    Empty-cluster survivors are always swappable first (they contribute zero
    to coverage).  Otherwise pick the lowest-score survivor from an
    over-represented cluster.  Returns ``None`` when every survivor uniquely
    represents its cluster -- the caller must stop.
    """
    # Phase 1: prefer survivors that don't belong to any cluster.
    empties = [(i, s.score) for i, s in enumerate(survivors) if not s.primary_cluster]
    if empties:
        return min(empties, key=lambda pair: pair[1])[0]

    # Phase 2: lowest-score survivor in an over-represented cluster.
    cluster_counts = Counter(s.primary_cluster for s in survivors)
    redundant = [
        (i, s.score) for i, s in enumerate(survivors) if cluster_counts[s.primary_cluster] > 1
    ]
    if not redundant:
        return None
    return min(redundant, key=lambda pair: pair[1])[0]


def _enforce_cluster_floor(
    *,
    survivors: list[SelectCandidate],
    candidates: list[SelectCandidate],
    cluster_floor: int,
    quality_threshold: float,
) -> None:
    """In-place mutate ``survivors`` to widen cluster coverage."""
    survivor_ids = {id(s) for s in survivors}
    while True:
        present = {s.primary_cluster for s in survivors if s.primary_cluster}
        if len(present) >= cluster_floor:
            return
        anchors = _find_best_anchor_per_missing_cluster(
            candidates, survivor_ids, present, quality_threshold
        )
        if not anchors:
            return  # No qualifying anchors left.
        victim_idx = _pick_swap_victim(survivors)
        if victim_idx is None:
            return  # Every survivor uniquely represents its cluster.
        best_anchor = max(anchors.values(), key=lambda c: c.score)
        survivor_ids.discard(id(survivors[victim_idx]))
        survivors[victim_idx] = best_anchor
        survivor_ids.add(id(best_anchor))


__all__ = [
    "DEFAULT_CLUSTER_FLOOR",
    "DEFAULT_QUALITY_THRESHOLD",
    "DEFAULT_REPEAT_PENALTY_ALPHA",
    "DEFAULT_TOP_K",
    "SelectCandidate",
    "select_top_k",
]
