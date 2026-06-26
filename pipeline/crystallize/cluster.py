"""pipeline.crystallize.cluster — KMeans clustering of candidate seeds.

Each candidate is mapped to a 29-dimensional feature vector::

    15 numeric scores (z-scored via StandardScaler)
  +  8 one-hot of `primary_cluster` (engine's existing 8-cluster taxonomy)
  +  6 one-hot of `arc_shape_6` (Reagan/Kim/Dodds 6 narrative shapes)
  = 29 dims

KMeans is fixed at k=8 (matching ``_CLUSTER_NAMES``) so the visualisation
maps 1:1 to the engine's existing cluster names. HDBSCAN's auto-k would
produce noise-labelled outliers that confuse the operator and discard the
strong prior the engine already provides.

When ``max(cluster_sizes) > 0.6 * N`` we emit a WARNING and embed
``cluster_collapse: true`` in the result dict so the HTML template can
surface it. This catches "all candidates fall into 1 cluster" failures
that suggest the theme is over-constraining the sampler.

Null fields (e.g., ``primary_cluster`` is unset because template-fallback
fired) are bucketed into "unknown" rather than producing NaN — KMeans
crashes on NaN.

MUST NOT import LLM clients. MUST NOT import from frameworks/.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final, cast

import numpy as np
from sklearn.cluster import KMeans  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

# _CLUSTER_NAMES is the canonical cluster-id → name map; duplicating it
# locally would create a drift hazard.
from pipeline.compound_seed import (
    _CLUSTER_NAMES,  # pyright: ignore[reportPrivateUsage]
)

_log = logging.getLogger(__name__)

# 15 numeric score fields — order is the canonical feature axis order.
_NUMERIC_FIELDS: Final[tuple[str, ...]] = (
    "genius_score",
    "associative_distance",
    "goldilocks_score",
    "sdt_intensity",
    "structural_surprise",
    "compression_score",
    "divisiveness_score",
    "organic_marketing_mult",
    "thematic_anchor_score",
    "emotional_universality_score",
    "cluster_coherence",
    "cultural_field_alignment",
    "audience_overlap_M",
    "som_floor_M",
    "tam_M",
)

_PRIMARY_CLUSTER_VALUES: Final[tuple[str, ...]] = tuple(_CLUSTER_NAMES.values())
"""8 cluster name strings from the engine — institutional / emotional / etc."""

_ARC_SHAPE_VALUES: Final[tuple[str, ...]] = (
    "Cinderella",
    "Man in a Hole",
    "Rags to Riches",
    "Icarus",
    "Oedipus",
    "Tragedy",
)
"""6 Reagan/Kim/Dodds narrative shapes used by the engine."""

_UNKNOWN_BUCKET_INDEX: Final[int] = -1
"""Sentinel for fields that don't match any known category."""

_COLLAPSE_THRESHOLD: Final[float] = 0.6
"""If one cluster contains > this fraction of N, we flag collapse."""

_DEFAULT_K: Final[int] = 8
_DEFAULT_RANDOM_STATE: Final[int] = 42
_DEFAULT_N_INIT: Final[int] = 10

_UNKNOWN_LABEL: Final[str] = "unknown"


def _numeric_value(scores: dict[str, Any], key: str) -> float:
    """Fetch a numeric score; return 0.0 on missing / None / NaN / non-numeric."""
    v = scores.get(key)
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f):
        return 0.0
    return f


def _onehot(value: str | None, known: tuple[str, ...]) -> list[float]:
    """One-hot encode ``value`` against ``known``. Unknown / None → all zeros."""
    out = [0.0] * len(known)
    if value is None:
        return out
    for i, k in enumerate(known):
        if k == value:
            out[i] = 1.0
            return out
    return out  # unknown → all-zeros bucket


def _vectorise_one(candidate_scores: dict[str, Any]) -> list[float]:
    """Map one candidate's score dict to a 29-element feature vector."""
    numerics = [_numeric_value(candidate_scores, k) for k in _NUMERIC_FIELDS]
    pc = candidate_scores.get("primary_cluster")
    pc_str = pc if isinstance(pc, str) else None
    primary_onehot = _onehot(pc_str, _PRIMARY_CLUSTER_VALUES)
    arc = candidate_scores.get("arc_shape_6")
    arc_str = arc if isinstance(arc, str) else None
    arc_onehot = _onehot(arc_str, _ARC_SHAPE_VALUES)
    return numerics + primary_onehot + arc_onehot


def cluster_candidates(
    candidate_score_dicts: list[dict[str, Any]],
    k: int = _DEFAULT_K,
    random_state: int = _DEFAULT_RANDOM_STATE,
) -> dict[str, Any]:
    """Cluster N candidates into k thematic groups via KMeans on 29-dim vectors.

    Args:
        candidate_score_dicts: One ``CompoundScore.to_dict()`` per candidate
            (the dict that lives under ``CompoundSeedResult.to_dict()["scores"]``).
        k: Number of clusters. Default 8 to match ``_CLUSTER_NAMES``.
        random_state: Passed to KMeans for determinism.

    Returns:
        Dict with keys:
          * ``cluster_ids``: list[int] of length N — cluster index per candidate.
          * ``cluster_names``: list[str] of length N — name from ``_CLUSTER_NAMES``
            or ``"cluster_<i>"`` when k != 8.
          * ``cluster_collapse``: bool — True when one cluster holds > 60% of N.
          * ``cluster_sizes``: list[int] — size of each of the k clusters, in
            cluster-id order.

    Returns ids = [0]*N + names = [_CLUSTER_NAMES[0]]*N when fewer than k
    candidates are supplied (no point clustering when N < k).
    """
    n = len(candidate_score_dicts)
    if n == 0:
        return {
            "cluster_ids": [],
            "cluster_names": [],
            "cluster_collapse": False,
            "cluster_sizes": [0] * k,
        }
    if n < k:
        ids = [0] * n
        name0 = _CLUSTER_NAMES.get(0, "cluster_0")  # pyright: ignore[reportPrivateUsage]
        sizes = [n] + [0] * (k - 1)
        return {
            "cluster_ids": ids,
            "cluster_names": [name0] * n,
            "cluster_collapse": True,  # n is already validated >= 1 above
            "cluster_sizes": sizes,
        }

    matrix = np.array([_vectorise_one(c) for c in candidate_score_dicts], dtype=np.float64)
    # Standard-scale ONLY the first 15 numeric columns; the one-hots are
    # already on 0/1 scale and shouldn't be normalised.
    scaler = StandardScaler()
    numeric_cols = matrix[:, : len(_NUMERIC_FIELDS)]
    scaled_numeric = cast(
        "Any",
        scaler.fit_transform(numeric_cols),  # pyright: ignore[reportUnknownMemberType]
    )
    matrix[:, : len(_NUMERIC_FIELDS)] = scaled_numeric

    km = KMeans(
        n_clusters=k,
        random_state=random_state,
        n_init=_DEFAULT_N_INIT,  # type: ignore[arg-type]
    )
    raw_labels = cast(
        "Any",
        km.fit_predict(matrix),  # pyright: ignore[reportUnknownMemberType]
    )
    cluster_ids: list[int] = [int(v) for v in raw_labels]

    # Cluster sizes in cluster-id order.
    sizes = [0] * k
    for cid in cluster_ids:
        if 0 <= cid < k:
            sizes[cid] += 1

    # Collapse guard.
    cluster_collapse = max(sizes) > _COLLAPSE_THRESHOLD * n
    if cluster_collapse:
        _log.warning(
            "cluster_candidates: cluster collapse detected — sizes=%s (max %.0f%% of N=%d)",
            sizes,
            100 * max(sizes) / n,
            n,
        )

    # Name lookup (8-cluster default; otherwise generic).
    if k == _DEFAULT_K:
        names = [_CLUSTER_NAMES.get(cid, _UNKNOWN_LABEL) for cid in cluster_ids]
    else:
        names = [f"cluster_{cid}" for cid in cluster_ids]

    return {
        "cluster_ids": cluster_ids,
        "cluster_names": names,
        "cluster_collapse": cluster_collapse,
        "cluster_sizes": sizes,
    }


__all__ = ["cluster_candidates"]
