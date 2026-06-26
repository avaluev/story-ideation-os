"""Tests for pipeline.crystallize.embeddings.

Two layers:
  1. CorpusIndex shape/load contract — verifies the persisted .npz format
     round-trips correctly and that load() degrades to None when the file
     is missing.
  2. Cosine math — verifies max_cosine and nearest() against synthetic
     unit vectors (no real model call needed for math correctness).

The sentence-transformer model itself is NOT exercised in unit tests
(loading the model + downloading weights is slow and out of scope for
the test suite). The smoke against the real index lives in the
build_corpus_embeddings.py CLI run, not here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pipeline.crystallize.corpus import Film, FilmsCorpus
from pipeline.crystallize.embeddings import EMBEDDING_DIM, CorpusIndex


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


class _StubIndex(CorpusIndex):
    """Test-only subclass that lets embed() be overridden without the
    sentence-transformer model -- CorpusIndex uses __slots__ so we can't
    monkeypatch the method on the instance."""

    def __init__(
        self,
        embeddings: np.ndarray,
        slugs: tuple[str, ...],
        stub_vec: np.ndarray | None = None,
    ) -> None:
        super().__init__(embeddings=embeddings, slugs=slugs)
        self._stub_vec = stub_vec

    def embed(self, text: str) -> np.ndarray:  # type: ignore[override]
        if self._stub_vec is None:
            raise RuntimeError("stub_vec not set")
        _ = text
        return self._stub_vec


_StubIndex.__slots__ = ()  # type: ignore[attr-defined] -- avoid double-slot pyright warn


def _fixture_index(stub_vec: np.ndarray | None = None) -> _StubIndex:
    """Three synthetic unit vectors on the first three coordinate axes.
    Any query that aligns with axis 0 should max-cosine on film 0; etc."""
    e0 = _unit(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    e1 = _unit(np.array([0.0, 1.0, 0.0], dtype=np.float32))
    e2 = _unit(np.array([0.0, 0.0, 1.0], dtype=np.float32))
    embeddings = np.stack([e0, e1, e2])
    return _StubIndex(
        embeddings=embeddings,
        slugs=("axis0", "axis1", "axis2"),
        stub_vec=stub_vec,
    )


class TestCorpusIndexShape:
    def test_constructor_requires_2d_embeddings(self) -> None:
        with pytest.raises(ValueError, match="2-D"):
            CorpusIndex(
                embeddings=np.zeros(5, dtype=np.float32),
                slugs=("a", "b", "c", "d", "e"),
            )

    def test_constructor_requires_matching_slug_count(self) -> None:
        with pytest.raises(ValueError, match="row count"):
            CorpusIndex(
                embeddings=np.zeros((3, 4), dtype=np.float32),
                slugs=("only_one",),
            )

    def test_embedding_dim_constant_matches_model(self) -> None:
        # all-MiniLM-L6-v2 is 384-dim; the constant pins that expectation.
        assert EMBEDDING_DIM == 384


class TestCorpusIndexLoad:
    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = CorpusIndex.load(tmp_path / "does_not_exist.npz")
        assert result is None

    def test_load_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "corrupt.npz"
        p.write_bytes(b"not a real npz file")
        result = CorpusIndex.load(p)
        assert result is None

    def test_round_trip(self, tmp_path: Path) -> None:
        idx = _fixture_index()
        out = tmp_path / "index.npz"
        np.savez_compressed(out, embeddings=idx.embeddings, slugs=np.array(idx.slugs))

        loaded = CorpusIndex.load(out)
        assert loaded is not None
        assert loaded.slugs == idx.slugs
        np.testing.assert_array_almost_equal(loaded.embeddings, idx.embeddings)


class TestCosineMath:
    """Bypass the sentence-transformer model by injecting a stub embed()
    via the _StubIndex subclass (CorpusIndex uses __slots__ so the
    method can't be monkeypatched on the instance)."""

    def test_max_cosine_perfect_alignment(self) -> None:
        idx = _fixture_index(stub_vec=np.array([1.0, 0.0, 0.0], dtype=np.float32))
        assert idx.max_cosine("anything") == pytest.approx(1.0)

    def test_max_cosine_orthogonal(self) -> None:
        # Query "negative axis 0" -> cosine -1 with axis0, 0 with others; max = 0.
        idx = _fixture_index(stub_vec=_unit(np.array([-1.0, 0.0, 0.0], dtype=np.float32)))
        assert idx.max_cosine("anything") == pytest.approx(0.0)

    def test_max_cosine_empty_text_returns_zero(self) -> None:
        idx = _fixture_index()
        assert idx.max_cosine("") == 0.0
        assert idx.max_cosine("   ") == 0.0

    def test_nearest_top_k(self) -> None:
        q = _unit(np.array([0.3, 0.9, 0.1], dtype=np.float32))
        idx = _fixture_index(stub_vec=q)
        ranked = idx.nearest("anything", k=2)
        assert len(ranked) == 2
        assert ranked[0][0] == "axis1"
        assert ranked[1][0] == "axis0"
        assert ranked[0][1] >= ranked[1][1]

    def test_nearest_empty_text(self) -> None:
        idx = _fixture_index()
        assert idx.nearest("", k=3) == []

    def test_nearest_zero_k(self) -> None:
        idx = _fixture_index(stub_vec=np.array([1.0, 0.0, 0.0], dtype=np.float32))
        assert idx.nearest("anything", k=0) == []

    def test_nearest_k_larger_than_corpus(self) -> None:
        idx = _fixture_index(stub_vec=np.array([1.0, 0.0, 0.0], dtype=np.float32))
        ranked = idx.nearest("anything", k=100)
        assert len(ranked) == 3  # capped at corpus size


# ── R6b: offline slug-cosine + hybrid comp blend ─────────────────────────────


def _mk_film(slug: str, ww: float, genres: tuple[str, ...]) -> Film:
    return Film(
        slug=slug,
        title=slug.title(),
        imdb_id=None,
        worldwide_gross_usd=ww,
        domestic_gross_usd=ww * 0.4,
        international_gross_usd=ww * 0.6,
        budget_usd=ww * 0.25,
        genres=genres,
        genres_display=tuple(g.title() for g in genres),
        distributor="Universal",
        release_year=2022,
        mpaa="PG-13",
        imdb_url=None,
        boxofficemojo_url=None,
    )


class TestSlugCosine:
    def test_slug_to_embedding_lookup(self) -> None:
        idx = _fixture_index()
        vec = idx.slug_to_embedding("axis1")
        assert vec is not None
        assert float(vec[1]) == pytest.approx(1.0)
        assert idx.slug_to_embedding("not-a-slug") is None

    def test_cosine_with_film(self) -> None:
        idx = _fixture_index()
        q = _unit(np.array([1.0, 0.0, 0.0], dtype=np.float32))
        assert idx.cosine_with_film(q, "axis0") == pytest.approx(1.0)
        assert idx.cosine_with_film(q, "axis1") == pytest.approx(0.0)
        assert idx.cosine_with_film(q, "missing") is None


class TestHybridCompBlend:
    def _corpus(self) -> FilmsCorpus:
        films = (
            _mk_film("axis0", 500_000_000, ("drama", "thriller")),
            _mk_film("axis1", 250_000_000, ("drama", "mystery")),
            _mk_film("axis2", 900_000_000, ("drama", "crime")),
        )
        c = FilmsCorpus(films=films, root=None)  # type: ignore[arg-type]
        c._build_indices()
        return c

    def test_disabled_is_pure_jaccard(self) -> None:
        c = self._corpus()
        # No enable_semantic_comps call -> pure Jaccard, similarity in [0,1].
        comps = c.find_comps_with_similarity(["drama", "thriller"], k=3)
        assert comps
        for _film, sim in comps:
            assert 0.0 <= sim <= 1.0

    def test_blend_uses_jaccard_and_cosine(self) -> None:
        c = self._corpus()
        # Inject a stub index aligned to the film slugs (axis0/1/2 unit vectors).
        c._semantic_index = _fixture_index()
        c._semantic_enabled = True
        comps = dict(
            (f.slug, sim) for f, sim in c.find_comps_with_similarity(["drama", "thriller"], k=3)
        )
        # Anchor is the top-Jaccard film (axis0, jac=1.0); its blended sim folds
        # in cosine(self)=1.0 -> 0.5*1 + 0.5*1 = 1.0.
        assert comps["axis0"] == pytest.approx(1.0)
        # axis1/axis2 are orthogonal to axis0 (cos=0) so their blended sim is
        # strictly below their raw Jaccard (semantic decorrelation pressure).
        assert comps["axis1"] < 1.0

    def test_blend_degrades_when_index_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # CorpusIndex.load() returning None (no .npz) -> enable returns False,
        # find_comps stays pure Jaccard, no crash, no model import.
        c = self._corpus()
        monkeypatch.setattr(
            "pipeline.crystallize.embeddings.CorpusIndex.load",
            staticmethod(lambda *a, **k: None),
        )
        enabled = c.enable_semantic_comps()
        assert enabled is False
        comps = c.find_comps_with_similarity(["drama", "thriller"], k=3)
        assert comps and all(0.0 <= sim <= 1.0 for _f, sim in comps)
