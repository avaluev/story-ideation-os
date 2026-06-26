"""Cross-domain bridge for the Genius Engine v4.0 (V4A-003b, Track B.3).

Maps any cross-domain asset (a one-paragraph summary string) to its closest
existing 25-axis seed bucket via cosine similarity. The phase-1-miner-cross-
domain subagent calls `map_asset_to_seed_axes` to fold a freshly mined
asset into the seed_engine's coordinate system.

Two embedding paths:

1. **sentence-transformers** (default): `all-MiniLM-L6-v2` (90MB, CPU-fast).
   Loaded lazily; cached to `data/_embeddings/.cache/`. Used in production
   and integration tests with `EMBEDDINGS_AVAILABLE=1`.
2. **Deterministic hash fallback**: 384-dim float vector derived from the
   tokens of the input via stable SHA-1 hashing. Used in unit tests and on
   environments where the sentence-transformers model can't download.

Both paths return numpy float32 vectors of the same shape, so callers don't
care which path was used. The fallback is NOT semantically meaningful; it
exists purely to keep the API + tests green when the model is unavailable.

ADR-0005: no `frameworks/` imports.
ADR-0007: no anthropic / httpx / openrouter_client (lint-imports enforces).
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

EMBEDDING_DIM: int = 384  # all-MiniLM-L6-v2 native dimension
DEFAULT_TOP_K: int = 3
DEFAULT_CACHE_DIR: Path = Path("data/_embeddings/.cache")
ST_MODEL_NAME: str = "all-MiniLM-L6-v2"
_USE_FALLBACK_ENV: str = "ANOMALY_BRIDGE_FALLBACK"  # set to "1" to force fallback


# ── Embedder protocol + implementations ───────────────────────────────────────


class Embedder(Protocol):
    """Anything with `.encode(text) -> ndarray` works as an embedder."""

    def encode(self, text: str) -> np.ndarray: ...


@dataclass(frozen=True)
class _DeterministicEmbedder:
    """Hash-based 384-dim embedder; deterministic; ZERO dependencies.

    Each token contributes 4 floats per SHA-1 byte to the bucket whose index
    is derived from the token hash. The output is L2-normalized. Tokens
    sharing prefixes share buckets, so synonyms with overlap rank closer
    than unrelated tokens — but only weakly. Use ONLY for tests.
    """

    dim: int = EMBEDDING_DIM

    def encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = [t.lower() for t in text.split() if t]
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.sha1(tok.encode("utf-8"), usedforsecurity=False).digest()
            for i in range(0, len(digest), 4):
                idx_high, val = struct.unpack(">HH", digest[i : i + 4])
                bucket = idx_high % self.dim
                vec[bucket] += float(val) / 65535.0
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm
        return vec


class _CachingEmbedder:
    """Wraps any Embedder with a per-instance text→ndarray memo (NB.8).

    The same logline is embedded many times across L1/L3/L4 patches; caching
    eliminates the redundant CPU/GPU work. The memo lives for the embedder's
    lifetime (a process-wide singleton; see ``get_embedder``).
    """

    def __init__(self, inner: Embedder) -> None:
        self._inner: Embedder = inner
        self._cache: dict[str, np.ndarray] = {}

    @property
    def inner(self) -> Embedder:
        """The wrapped embedder. Tests use this to assert provenance."""
        return self._inner

    def encode(self, text: str) -> np.ndarray:
        hit = self._cache.get(text)
        if hit is not None:
            return hit
        vec = self._inner.encode(text)
        self._cache[text] = vec
        return vec


# Module-level singleton holder. List-of-one avoids `global` / PLW0603.
_embedder_singleton: list[_CachingEmbedder | None] = [None]


def reset_embedder_cache() -> None:
    """Release the singleton + its memo. Used in tests; harmless in production."""
    _embedder_singleton[0] = None


def _load_st_embedder() -> Embedder | None:
    """Lazy-load sentence-transformers; return None if unavailable."""
    if os.environ.get(_USE_FALLBACK_ENV) == "1":
        return None
    try:  # pragma: no cover — exercised only when the model is downloaded
        from sentence_transformers import (  # noqa: PLC0415
            SentenceTransformer,  # type: ignore[import-not-found]
        )
    except Exception:
        return None
    try:  # pragma: no cover
        cache = DEFAULT_CACHE_DIR
        cache.mkdir(parents=True, exist_ok=True)
        model = SentenceTransformer(ST_MODEL_NAME, cache_folder=str(cache))
    except Exception:
        return None

    class _StWrapper:
        def encode(self, text: str) -> np.ndarray:  # pragma: no cover
            raw = model.encode(text, normalize_embeddings=True)  # type: ignore[arg-type]
            return np.asarray(raw, dtype=np.float32)

    return _StWrapper()


def get_embedder(*, force_fallback: bool = False) -> Embedder:
    """Return the active embedder. Production path tries sentence-transformers
    first; on any import / download failure (or if force_fallback is True),
    returns the deterministic fallback.

    NB.8: a process-wide singleton wraps the inner embedder with a text→ndarray
    cache. ``force_fallback`` returns a *fresh* uncached deterministic embedder
    without disturbing the singleton — used for tests and debugging only.
    """
    if force_fallback:
        return _DeterministicEmbedder()
    if _embedder_singleton[0] is None:
        st = _load_st_embedder()
        inner: Embedder = st if st is not None else _DeterministicEmbedder()
        _embedder_singleton[0] = _CachingEmbedder(inner)
    return _embedder_singleton[0]


# ── Cosine similarity ─────────────────────────────────────────────────────────


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1.0, 1.0]; returns 0 if either vector is zero."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0 or math.isnan(na) or math.isnan(nb):
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ── Public API: map_asset_to_seed_axes ────────────────────────────────────────


def map_asset_to_seed_axes(
    asset_text: str,
    seed_axes: dict[str, str],
    *,
    top_k: int = DEFAULT_TOP_K,
    embedder: Embedder | None = None,
) -> list[tuple[str, float]]:
    """Return the top-k seed-axis IDs by cosine similarity to `asset_text`.

    `seed_axes` is a dict `{axis_id: axis_summary_text}` from the caller. The
    miner agent typically loads it from `data/seeds/*.csv` (one row per axis,
    the summary column joined into a string). Returns sorted (axis_id,
    score) pairs in descending score order.
    """
    if not seed_axes:
        return []
    emb = embedder if embedder is not None else get_embedder()
    asset_vec = emb.encode(asset_text)
    scored: list[tuple[str, float]] = []
    for axis_id, axis_text in seed_axes.items():
        axis_vec = emb.encode(axis_text)
        score = cosine(asset_vec, axis_vec)
        scored.append((axis_id, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[: max(0, top_k)]
