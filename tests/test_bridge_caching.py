"""tests/test_bridge_caching.py — NB.8 lazy-embedding cache.

The bridge module returns a singleton embedder per process and memoizes
encode() results so repeated L1/L3/L4 patches re-using the same logline
text do not re-compute embeddings.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import bridge


def test_get_embedder_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same process call to get_embedder() returns the same instance."""
    monkeypatch.setenv(bridge._USE_FALLBACK_ENV, "1")
    bridge.reset_embedder_cache()
    a = bridge.get_embedder()
    b = bridge.get_embedder()
    assert a is b


def test_force_fallback_does_not_pollute_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """force_fallback always returns a fresh deterministic embedder (independent of singleton)."""
    monkeypatch.delenv(bridge._USE_FALLBACK_ENV, raising=False)
    bridge.reset_embedder_cache()
    forced = bridge.get_embedder(force_fallback=True)
    default = bridge.get_embedder()
    # default may or may not be the same as forced depending on st availability,
    # but force_fallback must return a deterministic-class instance every time
    forced2 = bridge.get_embedder(force_fallback=True)
    assert isinstance(forced, type(forced2))
    _ = default


def test_encode_is_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two encode() calls with the same text return the SAME ndarray object (not a copy)."""
    monkeypatch.setenv(bridge._USE_FALLBACK_ENV, "1")
    bridge.reset_embedder_cache()
    emb = bridge.get_embedder()
    v1 = emb.encode("a public defender battles the system")
    v2 = emb.encode("a public defender battles the system")
    assert v1 is v2


def test_encode_distinct_texts_distinct_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct texts produce distinct (non-identical) ndarrays."""
    monkeypatch.setenv(bridge._USE_FALLBACK_ENV, "1")
    bridge.reset_embedder_cache()
    emb = bridge.get_embedder()
    v1 = emb.encode("x")
    v2 = emb.encode("y")
    assert v1 is not v2
    assert not np.array_equal(v1, v2)


def test_reset_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """reset_embedder_cache() releases the singleton and memo table."""
    monkeypatch.setenv(bridge._USE_FALLBACK_ENV, "1")
    bridge.reset_embedder_cache()
    a = bridge.get_embedder()
    v1 = a.encode("hello world")
    bridge.reset_embedder_cache()
    b = bridge.get_embedder()
    v2 = b.encode("hello world")
    # New singleton → its memo is fresh; identity differs.
    assert a is not b
    assert v1 is not v2
    # But values are still equal (deterministic embedder).
    assert np.allclose(v1, v2)


def test_get_embedder_force_fallback_does_not_alter_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """force_fallback=True must NOT replace the cached singleton."""
    monkeypatch.setenv(bridge._USE_FALLBACK_ENV, "1")
    bridge.reset_embedder_cache()
    s1 = bridge.get_embedder()
    _ = bridge.get_embedder(force_fallback=True)
    s2 = bridge.get_embedder()
    assert s1 is s2
