"""Unit tests for pipeline.bridge — V4A-003b cross-domain semantic mapping.

Forces the deterministic-fallback embedder so tests don't depend on the
sentence-transformers model download (~90MB).
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.bridge import (
    DEFAULT_TOP_K,
    EMBEDDING_DIM,
    _DeterministicEmbedder,
    cosine,
    get_embedder,
    map_asset_to_seed_axes,
)


@pytest.fixture
def fallback_embedder() -> _DeterministicEmbedder:
    return _DeterministicEmbedder()


def test_get_embedder_returns_fallback_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANOMALY_BRIDGE_FALLBACK", "1")
    from pipeline.bridge import reset_embedder_cache  # noqa: PLC0415

    reset_embedder_cache()
    emb = get_embedder()
    # NB.8: production path is wrapped in _CachingEmbedder; assert via .inner
    inner = getattr(emb, "inner", emb)
    assert isinstance(inner, _DeterministicEmbedder)


def test_get_embedder_force_fallback() -> None:
    emb = get_embedder(force_fallback=True)
    # force_fallback returns the bare deterministic embedder (no cache wrapper).
    assert isinstance(emb, _DeterministicEmbedder)


def test_deterministic_embedder_returns_correct_dim(
    fallback_embedder: _DeterministicEmbedder,
) -> None:
    vec = fallback_embedder.encode("antarctic ice cores")
    assert vec.shape == (EMBEDDING_DIM,)
    assert vec.dtype == np.float32


def test_deterministic_embedder_returns_unit_norm_for_nonempty(
    fallback_embedder: _DeterministicEmbedder,
) -> None:
    vec = fallback_embedder.encode("antarctic ice cores winter rituals")
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5


def test_deterministic_embedder_returns_zero_for_empty(
    fallback_embedder: _DeterministicEmbedder,
) -> None:
    vec = fallback_embedder.encode("")
    assert float(np.linalg.norm(vec)) == 0.0


def test_deterministic_embedder_is_deterministic(
    fallback_embedder: _DeterministicEmbedder,
) -> None:
    vec_a = fallback_embedder.encode("antarctic ice")
    vec_b = fallback_embedder.encode("antarctic ice")
    assert np.allclose(vec_a, vec_b)


def test_cosine_returns_zero_for_zero_vector() -> None:
    z = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    a = np.ones(EMBEDDING_DIM, dtype=np.float32)
    assert cosine(z, a) == 0.0


def test_cosine_self_is_one(fallback_embedder: _DeterministicEmbedder) -> None:
    v = fallback_embedder.encode("hello world")
    assert abs(cosine(v, v) - 1.0) < 1e-5


def test_map_asset_to_seed_axes_returns_top_k() -> None:
    seed_axes = {
        "axis_a": "antarctic ice cores winter ritual",
        "axis_b": "mongolian throat singing nomadic steppe",
        "axis_c": "pacific tide pools coastal ecosystem",
    }
    hits = map_asset_to_seed_axes(
        "antarctic ice cores",
        seed_axes,
        top_k=2,
        embedder=_DeterministicEmbedder(),
    )
    assert len(hits) == 2
    # First hit is a (axis_id, score) tuple
    axis_ids = [a for a, _ in hits]
    assert "axis_a" in axis_ids


def test_map_asset_to_seed_axes_empty_dict_returns_empty() -> None:
    assert map_asset_to_seed_axes("anything", {}, embedder=_DeterministicEmbedder()) == []


def test_map_asset_to_seed_axes_default_top_k_is_3() -> None:
    seed_axes = {f"axis_{i}": f"asset summary {i}" for i in range(10)}
    hits = map_asset_to_seed_axes(
        "asset summary 1",
        seed_axes,
        embedder=_DeterministicEmbedder(),
    )
    assert len(hits) == DEFAULT_TOP_K


def test_map_asset_returns_descending_by_score() -> None:
    seed_axes = {
        "axis_a": "alpha beta gamma",
        "axis_b": "delta epsilon zeta",
        "axis_c": "alpha beta delta",
    }
    hits = map_asset_to_seed_axes(
        "alpha beta gamma",
        seed_axes,
        top_k=3,
        embedder=_DeterministicEmbedder(),
    )
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_map_asset_self_lookup_ranks_first() -> None:
    """When asset_text matches one axis exactly, that axis ranks first."""
    seed_axes = {
        "exact_match": "antarctic ice cores winter rituals",
        "other": "completely different topic about something else entirely",
    }
    hits = map_asset_to_seed_axes(
        "antarctic ice cores winter rituals",
        seed_axes,
        top_k=2,
        embedder=_DeterministicEmbedder(),
    )
    assert hits[0][0] == "exact_match"
    assert hits[0][1] >= hits[1][1]


def test_get_embedder_returns_usable_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_embedder returns something that produces a (EMBEDDING_DIM,) ndarray.

    Forces fallback to keep test deterministic + fast (sentence-transformers
    model download is ~38 seconds first time and unrelated to this contract).
    The integration path is exercised by `make eval` when EMBEDDINGS_AVAILABLE=1.
    """
    monkeypatch.setenv("ANOMALY_BRIDGE_FALLBACK", "1")
    emb = get_embedder()
    vec = emb.encode("hello")
    assert vec.shape == (EMBEDDING_DIM,)
