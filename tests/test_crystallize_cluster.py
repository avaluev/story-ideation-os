"""Tests for pipeline/crystallize/cluster.py — KMeans on the 29-dim feature vector.

Covers:
- cluster_candidates deterministic with fixed random_state.
- Empty input returns empty lists, no crash.
- N < k early-returns with all-zero cluster_ids.
- Output shapes: cluster_ids/cluster_names length N, cluster_sizes length k.
- cluster_collapse fires when one cluster holds > 60% of N.
- Null primary_cluster / arc_shape_6 → unknown-bucket onehots (no NaN crash).
- NaN numeric fields handled (treated as 0.0, no NaN propagates to KMeans).
- Cluster names map to _CLUSTER_NAMES when k=8.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from pipeline.crystallize.cluster import (
    _ARC_SHAPE_VALUES,
    _COLLAPSE_THRESHOLD,
    _PRIMARY_CLUSTER_VALUES,
    _numeric_value,
    _onehot,
    _vectorise_one,
    cluster_candidates,
)


def _make_candidate(
    *,
    primary_cluster: str | None = "institutional",
    arc_shape: str | None = "Tragedy",
    genius: float = 0.5,
    goldilocks: float = 0.5,
    seed: float = 0.0,
) -> dict[str, Any]:
    """Build one CompoundScore-shaped dict. ``seed`` perturbs numerics for diversity."""
    return {
        "genius_score": genius,
        "associative_distance": 0.4 + seed * 0.01,
        "goldilocks_score": goldilocks,
        "sdt_intensity": 1.0 + seed * 0.05,
        "structural_surprise": 0.5 + seed * 0.01,
        "compression_score": 0.5 + seed * 0.01,
        "divisiveness_score": 7.0 + seed * 0.1,
        "organic_marketing_mult": 2.0,
        "thematic_anchor_score": 0.5,
        "emotional_universality_score": 3.0,
        "cluster_coherence": 0.6,
        "cultural_field_alignment": 0.5,
        "audience_overlap_M": 300.0 + seed,
        "som_floor_M": 200.0,
        "tam_M": 40000.0,
        "primary_cluster": primary_cluster,
        "arc_shape_6": arc_shape,
    }


def _diverse_candidates(n: int = 50, seed: int = 42) -> list[dict[str, Any]]:
    """Build a synthetic batch with varied primary_cluster / arc_shape."""
    rng = random.Random(seed)  # noqa: S311  # deterministic test fixture, not crypto
    cands = []
    for i in range(n):
        cands.append(
            _make_candidate(
                primary_cluster=rng.choice(list(_PRIMARY_CLUSTER_VALUES)),
                arc_shape=rng.choice(list(_ARC_SHAPE_VALUES)),
                genius=rng.random(),
                goldilocks=rng.random(),
                seed=float(i),
            )
        )
    return cands


# ---------------------------------------------------------------------------
# _numeric_value
# ---------------------------------------------------------------------------


def test_numeric_value_present() -> None:
    assert _numeric_value({"x": 1.5}, "x") == pytest.approx(1.5)


def test_numeric_value_missing() -> None:
    assert _numeric_value({}, "x") == pytest.approx(0.0)


def test_numeric_value_none() -> None:
    assert _numeric_value({"x": None}, "x") == pytest.approx(0.0)


def test_numeric_value_nan() -> None:
    assert _numeric_value({"x": float("nan")}, "x") == pytest.approx(0.0)


def test_numeric_value_string() -> None:
    """Strings that parse → float work; strings that don't → 0.0."""
    assert _numeric_value({"x": "1.5"}, "x") == pytest.approx(1.5)
    assert _numeric_value({"x": "garbage"}, "x") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _onehot
# ---------------------------------------------------------------------------


def test_onehot_known() -> None:
    out = _onehot("technology", _PRIMARY_CLUSTER_VALUES)
    expected_idx = _PRIMARY_CLUSTER_VALUES.index("technology")
    assert out[expected_idx] == pytest.approx(1.0)
    assert sum(out) == pytest.approx(1.0)


def test_onehot_unknown_all_zeros() -> None:
    out = _onehot("not-a-known-cluster", _PRIMARY_CLUSTER_VALUES)
    assert all(v == 0.0 for v in out)
    assert len(out) == len(_PRIMARY_CLUSTER_VALUES)


def test_onehot_none_all_zeros() -> None:
    out = _onehot(None, _PRIMARY_CLUSTER_VALUES)
    assert all(v == 0.0 for v in out)


# ---------------------------------------------------------------------------
# _vectorise_one
# ---------------------------------------------------------------------------


def test_vectorise_one_total_length_is_29() -> None:
    """15 numeric + 8 primary_cluster + 6 arc_shape = 29."""
    v = _vectorise_one(_make_candidate())
    assert len(v) == 29


def test_vectorise_one_handles_missing_categoricals() -> None:
    v = _vectorise_one(_make_candidate(primary_cluster=None, arc_shape=None))
    # First 15 numeric, then 8 primary_cluster (all 0), then 6 arc (all 0).
    assert sum(v[15:]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# cluster_candidates — main behaviour
# ---------------------------------------------------------------------------


def test_cluster_empty_input() -> None:
    r = cluster_candidates([])
    assert r["cluster_ids"] == []
    assert r["cluster_names"] == []
    assert r["cluster_collapse"] is False
    assert r["cluster_sizes"] == [0] * 8


def test_cluster_n_less_than_k_early_returns() -> None:
    cands = _diverse_candidates(n=3)
    r = cluster_candidates(cands, k=8)
    assert len(r["cluster_ids"]) == 3
    assert all(cid == 0 for cid in r["cluster_ids"])
    assert r["cluster_sizes"] == [3, 0, 0, 0, 0, 0, 0, 0]
    # cluster_collapse always True when n < k since the 1 used cluster is 100%.
    assert r["cluster_collapse"] is True


def test_cluster_output_shapes() -> None:
    cands = _diverse_candidates(n=40)
    r = cluster_candidates(cands, k=8)
    assert len(r["cluster_ids"]) == 40
    assert len(r["cluster_names"]) == 40
    assert len(r["cluster_sizes"]) == 8
    assert sum(r["cluster_sizes"]) == 40


def test_cluster_deterministic_same_input_same_labels() -> None:
    """Same input + same random_state → identical labels."""
    cands = _diverse_candidates(n=40, seed=42)
    r1 = cluster_candidates(cands, k=8, random_state=42)
    r2 = cluster_candidates(cands, k=8, random_state=42)
    assert r1["cluster_ids"] == r2["cluster_ids"]


def test_cluster_names_drawn_from_cluster_names_constant() -> None:
    cands = _diverse_candidates(n=40)
    r = cluster_candidates(cands, k=8)
    # Allow "unknown" only when k != 8, but here k=8 so every name must be valid.
    valid_names = set(_PRIMARY_CLUSTER_VALUES)
    for name in r["cluster_names"]:
        assert name in valid_names, f"unexpected cluster name: {name}"


def test_cluster_collapse_warning_fires_when_one_cluster_dominates() -> None:
    """All-identical candidates → all land in one cluster → collapse=True."""
    identical = [_make_candidate() for _ in range(20)]
    r = cluster_candidates(identical, k=8)
    max_size = max(r["cluster_sizes"])
    assert max_size / len(identical) > _COLLAPSE_THRESHOLD
    assert r["cluster_collapse"] is True


def test_cluster_no_collapse_with_diverse_candidates() -> None:
    """40 diverse candidates spread across 8 clusters → no collapse."""
    cands = _diverse_candidates(n=40, seed=7)
    r = cluster_candidates(cands, k=8)
    max_size = max(r["cluster_sizes"])
    assert max_size / 40 <= _COLLAPSE_THRESHOLD
    assert r["cluster_collapse"] is False


def test_cluster_handles_nan_numeric_fields() -> None:
    """NaN in score fields must not crash KMeans."""
    cands = _diverse_candidates(n=20)
    cands[0]["genius_score"] = float("nan")
    cands[5]["som_floor_M"] = float("nan")
    r = cluster_candidates(cands, k=8)
    assert len(r["cluster_ids"]) == 20
    # Cluster ids must be valid integers in [0, k).
    assert all(0 <= cid < 8 for cid in r["cluster_ids"])


def test_cluster_handles_none_categoricals() -> None:
    cands = _diverse_candidates(n=20)
    cands[0]["primary_cluster"] = None
    cands[1]["arc_shape_6"] = None
    r = cluster_candidates(cands, k=8)
    assert len(r["cluster_ids"]) == 20
