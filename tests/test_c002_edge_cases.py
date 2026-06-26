"""Edge cases for the C002 embedding-novelty kill-switch.

The happy path lives in ``tests/test_empirical_genius.py``. This file
pins the degradation paths so a future refactor that drops one of the
guards in ``_embedding_novelty`` fails loudly:

  - sentence-transformers not installed → ``(_NOVELTY_NEUTRAL, True)``
  - CorpusIndex absent (e.g., .npz file missing) → degraded neutral
  - concept_row missing both logline AND synopsis → degraded neutral
  - degenerate all-zero embedding through max_cosine → novelty stays
    clamped in [0, 1]
  - index_cache singleton survives a None index without thrashing
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from pipeline import empirical_genius as eg
from pipeline.crystallize import embeddings as emb_mod


@pytest.fixture(autouse=True)
def _reset_index_cache() -> None:
    """Each test gets a fresh lazy-singleton state."""
    eg._NOVELTY_INDEX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]


class _StubCorpusIndex:
    """In-memory corpus index that returns a configurable max-cosine."""

    def __init__(self, fixed_max_sim: float) -> None:
        self._fixed = fixed_max_sim

    def max_cosine(self, text: str) -> float:
        _ = text  # ignored; deterministic
        return self._fixed


class TestSentenceTransformersAbsent:
    def test_returns_neutral_when_library_missing(self) -> None:
        with patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", False):
            novelty, degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "anything"}
            )
        assert novelty == pytest.approx(eg._NOVELTY_NEUTRAL)  # pyright: ignore[reportPrivateUsage]
        assert degraded is True


class TestCorpusIndexMissing:
    def test_returns_neutral_when_index_load_returns_none(self) -> None:
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=None),
        ):
            novelty, degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "anything"}
            )
        assert novelty == pytest.approx(eg._NOVELTY_NEUTRAL)  # pyright: ignore[reportPrivateUsage]
        assert degraded is True

    def test_cache_stores_none_to_prevent_retry_loops(self) -> None:
        """When CorpusIndex.load() returns None, the cache must still
        hold that None so the next call doesn't re-trigger the (~3s)
        first-load path."""

        with patch.object(emb_mod.CorpusIndex, "load", return_value=None):
            first = eg._get_corpus_index()  # pyright: ignore[reportPrivateUsage]
            second = eg._get_corpus_index()  # pyright: ignore[reportPrivateUsage]
        assert first is None
        assert second is None
        # Confirm CorpusIndex.load was called exactly once.
        with patch.object(emb_mod.CorpusIndex, "load", return_value=None) as mock:
            eg._get_corpus_index()  # pyright: ignore[reportPrivateUsage]
            assert mock.call_count == 0  # already cached from previous block


class TestDegenerateInput:
    def test_empty_logline_and_empty_synopsis_returns_neutral(self) -> None:
        stub = _StubCorpusIndex(fixed_max_sim=0.3)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            novelty, degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "", "synopsis": ""}
            )
        assert novelty == pytest.approx(eg._NOVELTY_NEUTRAL)  # pyright: ignore[reportPrivateUsage]
        assert degraded is True

    def test_whitespace_only_logline_returns_neutral(self) -> None:
        stub = _StubCorpusIndex(fixed_max_sim=0.3)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            row: dict[str, Any] = {"logline": "   ", "synopsis": "  "}
            novelty, degraded = eg._embedding_novelty(row)  # pyright: ignore[reportPrivateUsage]
        assert novelty == pytest.approx(eg._NOVELTY_NEUTRAL)  # pyright: ignore[reportPrivateUsage]
        assert degraded is True

    def test_missing_logline_field_falls_back_to_synopsis(self) -> None:
        stub = _StubCorpusIndex(fixed_max_sim=0.30)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            row: dict[str, Any] = {"synopsis": "a meaningful story"}
            novelty, degraded = eg._embedding_novelty(row)  # pyright: ignore[reportPrivateUsage]
        assert novelty == pytest.approx(0.70)  # 1 - 0.30
        assert degraded is False


class TestClampingBoundaries:
    def test_max_sim_zero_yields_novelty_one(self) -> None:
        stub = _StubCorpusIndex(fixed_max_sim=0.0)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            novelty, degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "hello world"}
            )
        assert novelty == pytest.approx(1.0)
        assert degraded is False

    def test_max_sim_one_yields_novelty_zero(self) -> None:
        stub = _StubCorpusIndex(fixed_max_sim=1.0)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            novelty, _degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "hello world"}
            )
        assert novelty == pytest.approx(0.0)

    def test_max_sim_above_one_is_clamped(self) -> None:
        """Defensive: even if cosine somehow returns >1.0 (e.g.,
        non-unit vectors slipped through), novelty must stay in [0, 1]."""
        stub = _StubCorpusIndex(fixed_max_sim=1.5)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            novelty, _degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "hello world"}
            )
        assert 0.0 <= novelty <= 1.0

    def test_negative_max_sim_is_clamped_to_zero_novelty_one(self) -> None:
        """If the cosine somehow returns negative (orthogonal-ish vectors),
        novelty = 1 - (-0.2) = 1.2, must clamp to 1.0."""
        stub = _StubCorpusIndex(fixed_max_sim=-0.2)
        with (
            patch.object(eg, "_HAVE_SENTENCE_TRANSFORMERS", True),
            patch.object(eg, "_get_corpus_index", return_value=stub),
        ):
            novelty, _degraded = eg._embedding_novelty(  # pyright: ignore[reportPrivateUsage]
                {"logline": "hello world"}
            )
        assert novelty == pytest.approx(1.0)
        assert 0.0 <= novelty <= 1.0
