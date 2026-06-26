"""pipeline.crystallize.embeddings — corpus embedding index for novelty.

Provides a small numpy-backed nearest-neighbor index over the 894-film
corpus. Used by:
  - pipeline.empirical_genius._embedding_novelty (C002 kill-switch)
  - pipeline.loop_wedge (mean_novelty_last_20 KPI population)

No FAISS dependency. The corpus is small (< 1000 films, 384-dim
embeddings) so a single dense matrix-vector product is ~50µs.

Build flow:
  1. ``scripts/build_corpus_embeddings.py`` reads the FilmsCorpus,
     concatenates ``log_line + synopsis`` per film, embeds with
     all-MiniLM-L6-v2, normalises to unit norm, saves to
     ``pipeline/data/films_corpus_embeddings.npz``.
  2. ``CorpusIndex.load()`` reads that file at runtime.
  3. ``CorpusIndex.max_cosine(query_text)`` embeds the query, normalises,
     returns max cosine similarity against the corpus.

Cosine on unit vectors == dot product, so the lookup is one matmul.

Forward-compat: if the .npz file is missing, ``load()`` returns ``None``
and consumers (C002, loop_wedge) keep their degraded fallback. The
operator runs ``uv run python scripts/build_corpus_embeddings.py`` to
materialise the index.
"""

from __future__ import annotations

import logging
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_log = logging.getLogger(__name__)

_HAVE_SENTENCE_TRANSFORMERS: Final[bool] = find_spec("sentence_transformers") is not None

DEFAULT_MODEL_NAME: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_INDEX_PATH: Final[Path] = Path("pipeline/data/films_corpus_embeddings.npz")
EMBEDDING_DIM: Final[int] = 384
_EMBEDDING_NDIM: Final[int] = 2


class CorpusIndex:
    """In-memory unit-normalised embedding matrix + slug list.

    The index is built offline by scripts/build_corpus_embeddings.py and
    loaded once per process. Cosine similarity is computed as the dot
    product against the row-normalised matrix.
    """

    __slots__ = ("_model", "_slug_to_idx", "embeddings", "slugs")

    def __init__(self, embeddings: np.ndarray, slugs: tuple[str, ...]) -> None:
        if embeddings.ndim != _EMBEDDING_NDIM:
            raise ValueError(f"embeddings must be 2-D, got shape {embeddings.shape}")
        if embeddings.shape[0] != len(slugs):
            raise ValueError(f"row count {embeddings.shape[0]} != len(slugs) {len(slugs)}")
        self.embeddings = embeddings.astype(np.float32, copy=False)
        self.slugs = slugs
        self._model: SentenceTransformer | None = None
        #: slug -> row index, for O(1) offline slug-to-slug cosine (no model).
        self._slug_to_idx: dict[str, int] = {s: i for i, s in enumerate(slugs)}

    @classmethod
    def load(cls, path: Path | str = DEFAULT_INDEX_PATH) -> CorpusIndex | None:
        """Load the index from disk. Returns ``None`` when the file is
        absent (operator hasn't run scripts/build_corpus_embeddings.py
        yet) -- callers degrade gracefully."""
        p = Path(path)
        if not p.exists():
            _log.info("CorpusIndex.load: %s does not exist; novelty degrades", p)
            return None
        try:
            data = np.load(p, allow_pickle=False)
            embeddings = data["embeddings"]
            slugs_arr = data["slugs"]
        except (OSError, ValueError, KeyError) as exc:
            _log.warning("CorpusIndex.load: failed to read %s (%s)", p, exc)
            return None
        slugs: tuple[str, ...] = tuple(str(s) for s in slugs_arr.tolist())
        return cls(embeddings=embeddings, slugs=slugs)

    def _ensure_model(self) -> SentenceTransformer:
        """Lazy-import + cache the sentence-transformer model. The model
        loads in ~3s the first time per process (weights are on disk;
        no network call when the HuggingFace cache has them)."""
        if self._model is None:
            if not _HAVE_SENTENCE_TRANSFORMERS:
                raise RuntimeError(
                    "sentence-transformers not installed; CorpusIndex.max_cosine "
                    "requires it (was the index built with a stub?)"
                )
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(DEFAULT_MODEL_NAME)
        return self._model

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text + unit-normalise. Returns a 1-D float32 array."""
        model = self._ensure_model()
        vec_raw = model.encode(  # type: ignore[reportUnknownMemberType]
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        vec = np.asarray(vec_raw, dtype=np.float32)
        return vec[0]  # type: ignore[no-any-return]

    def max_cosine(self, text: str) -> float:
        """Return max cosine similarity between ``text`` and any corpus film.

        Cosine in [-1, 1] for arbitrary vectors; for sentence-transformer
        embeddings of natural language, the practical range is [0, 1].
        Returns 0.0 on empty input.
        """
        if not text.strip():
            return 0.0
        q = self.embed(text)
        # All vectors already unit-normalised => dot == cosine.
        sims = self.embeddings @ q
        return float(np.max(sims))

    def slug_to_embedding(self, slug: str) -> np.ndarray | None:
        """Return the pre-baked unit embedding for ``slug`` (a corpus film), or
        ``None`` when the slug is absent. OFFLINE — pure index lookup into the
        persisted .npz; needs NO sentence-transformer model. This is the only
        embedding path usable when sentence-transformers is not installed."""
        idx = self._slug_to_idx.get(slug)
        if idx is None:
            return None
        return self.embeddings[idx]

    def cosine_with_film(self, query_vec: np.ndarray, slug: str) -> float | None:
        """Cosine similarity between a pre-existing unit ``query_vec`` and the
        corpus film ``slug``. Returns ``None`` when the slug is absent. OFFLINE
        (dot product of unit vectors); no model encode."""
        emb = self.slug_to_embedding(slug)
        if emb is None:
            return None
        return float(np.dot(query_vec, emb))

    def nearest(self, text: str, k: int = 5) -> list[tuple[str, float]]:
        """Top-k nearest neighbors by cosine. Returns [(slug, similarity), ...]
        sorted descending."""
        if not text.strip() or k <= 0:
            return []
        q = self.embed(text)
        sims = self.embeddings @ q
        k = min(k, len(self.slugs))
        # argpartition is O(n); only sort the top-k.
        idx_partition = np.argpartition(-sims, k - 1)[:k]
        ranked = sorted(idx_partition, key=lambda i: -sims[i])
        return [(self.slugs[int(i)], float(sims[int(i)])) for i in ranked]


def build_index(
    texts_by_slug: dict[str, str],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    out_path: Path | str = DEFAULT_INDEX_PATH,
) -> CorpusIndex:
    """Build (and persist) the index from a {slug: text} mapping.

    Used by scripts/build_corpus_embeddings.py. Returns the loaded
    CorpusIndex so the caller can verify before exiting.

    The .npz file holds two arrays:
      - embeddings: (N, D) float32, row-normalised to unit norm.
      - slugs: (N,) <U... unicode array.
    """
    if not _HAVE_SENTENCE_TRANSFORMERS:
        raise RuntimeError("build_index requires sentence-transformers; install via `uv sync`")
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model = SentenceTransformer(model_name)
    slugs = tuple(sorted(texts_by_slug.keys()))
    texts = [texts_by_slug[s] for s in slugs]
    raw = model.encode(  # type: ignore[reportUnknownMemberType]
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    embeddings = np.asarray(raw, dtype=np.float32)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, embeddings=embeddings, slugs=np.array(slugs))

    _log.info(
        "embeddings.build_index: persisted %d x %d embeddings to %s",
        embeddings.shape[0],
        embeddings.shape[1],
        out,
    )
    return CorpusIndex(embeddings=embeddings, slugs=slugs)


__all__ = [
    "DEFAULT_INDEX_PATH",
    "DEFAULT_MODEL_NAME",
    "EMBEDDING_DIM",
    "CorpusIndex",
    "build_index",
]
