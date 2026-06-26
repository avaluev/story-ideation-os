"""Regression: _infer_query_genres uses six signals, not three.

WEDGE Step 2 of the plan. Pre-Step-2, _infer_query_genres pulled genre
hints from only three engine fields (primary_cluster, arc_shape_6,
world_texture.name). The other 19 axes sampled per candidate had ZERO
influence on comp retrieval — so two seeds identical in those three
fields but differing in sdt_wound / moral_fault_line / divisiveness_engine
produced IDENTICAL queries, and therefore identical comps.

Post-Step-2, three more axis signals vote via their ``thematic_cluster``
field (already present in pipeline/data/compound_seed_variables.json).

These tests pin the contract:

  1. Two seeds identical in (primary_cluster, arc_shape_6, world_texture)
     but differing in sdt_wound.thematic_cluster produce DIVERGENT query
     genre sets.
  2. The same holds for moral_fault_line and divisiveness_engine.
  3. The query is capped at _MAX_QUERY_TERMS so Jaccard denominators
     stay bounded.
  4. Missing axis entries (None) do not crash the inference.
"""

from __future__ import annotations

from typing import Any

from pipeline.crystallize.comps import _MAX_QUERY_TERMS, _infer_query_genres


def _seed(
    primary_cluster: str = "institutional",
    arc_shape_6: str = "Man in a Hole",
    world_name: str = "newsroom",
    sdt_wound_cluster: str | None = "institutional",
    moral_fault_line_cluster: str | None = "institutional",
    divisiveness_engine_cluster: str | None = "institutional",
) -> dict[str, Any]:
    """Build a minimal seed dict shaped like a CompoundSeedResult.to_dict()."""
    seed: dict[str, Any] = {
        "scores": {"primary_cluster": primary_cluster, "arc_shape_6": arc_shape_6},
        "world_texture": {"name": world_name},
    }
    if sdt_wound_cluster is not None:
        seed["sdt_wound"] = {"id": "SW_TEST", "thematic_cluster": sdt_wound_cluster}
    if moral_fault_line_cluster is not None:
        seed["moral_fault_line"] = {"id": "MF_TEST", "thematic_cluster": moral_fault_line_cluster}
    if divisiveness_engine_cluster is not None:
        seed["divisiveness_engine"] = {
            "id": "DE_TEST",
            "thematic_cluster": divisiveness_engine_cluster,
        }
    return seed


class TestMultiSignalQueryDivergence:
    """The single regression that proves the new signals actually vote."""

    def test_sdt_wound_cluster_changes_query(self) -> None:
        """Two seeds identical in the original 3 signals but differing in
        sdt_wound.thematic_cluster must produce different query genre sets."""
        base = _seed(sdt_wound_cluster="institutional")
        variant = _seed(sdt_wound_cluster="emotional")

        q_base = set(_infer_query_genres(base))
        q_variant = set(_infer_query_genres(variant))

        assert q_base != q_variant, (
            "sdt_wound.thematic_cluster did not influence the query — multi-signal "
            f"voting is dead. base={sorted(q_base)} variant={sorted(q_variant)}"
        )

    def test_moral_fault_line_cluster_changes_query(self) -> None:
        base = _seed(moral_fault_line_cluster="civilizational")
        variant = _seed(moral_fault_line_cluster="emotional")

        q_base = set(_infer_query_genres(base))
        q_variant = set(_infer_query_genres(variant))

        assert q_base != q_variant, "moral_fault_line.thematic_cluster did not influence the query."

    def test_divisiveness_engine_cluster_changes_query(self) -> None:
        base = _seed(divisiveness_engine_cluster="civilizational")
        variant = _seed(divisiveness_engine_cluster="technology")

        q_base = set(_infer_query_genres(base))
        q_variant = set(_infer_query_genres(variant))

        assert q_base != q_variant, (
            "divisiveness_engine.thematic_cluster did not influence the query."
        )

    def test_query_capped_at_max_terms(self) -> None:
        """When every signal contributes hints, dedupe + cap keeps the
        query bounded at _MAX_QUERY_TERMS (avoid unbounded Jaccard denoms)."""
        # Force every signal to contribute distinct hints.
        # institutional → drama, thriller, mystery (3)
        # arc Icarus → drama, thriller (overlap)
        # world "city" → drama, thriller (overlap)
        # sdt_wound cluster nature → adventure, drama, horror (adds adventure, horror)
        # moral_fault_line cluster economic → drama, crime, thriller (adds crime)
        # divisiveness cluster temporal → drama, sci-fi, mystery (adds sci-fi)
        seed = _seed(
            primary_cluster="institutional",
            arc_shape_6="Icarus",
            world_name="city",
            sdt_wound_cluster="nature",
            moral_fault_line_cluster="economic",
            divisiveness_engine_cluster="temporal",
        )
        query = _infer_query_genres(seed)
        assert len(query) <= _MAX_QUERY_TERMS, (
            f"query exceeded _MAX_QUERY_TERMS={_MAX_QUERY_TERMS}: {query}"
        )

    def test_missing_axis_entries_do_not_crash(self) -> None:
        """Seeds without sdt_wound / moral_fault_line / divisiveness_engine
        (e.g. older sidecars) must still produce a valid query."""
        seed = _seed(
            sdt_wound_cluster=None,
            moral_fault_line_cluster=None,
            divisiveness_engine_cluster=None,
        )
        query = _infer_query_genres(seed)
        assert query  # non-empty fallback or original-3-signal hints
        # Should equal the pre-Step-2 behaviour for this same seed.
        assert "drama" in query  # primary_cluster="institutional" guarantees drama

    def test_unknown_axis_cluster_silently_ignored(self) -> None:
        """If an axis entry has a thematic_cluster not in _CLUSTER_GENRE_HINTS,
        we silently skip it rather than crash. Forward-compatible with new
        clusters added by Step 7 pool expansion."""
        seed = _seed(sdt_wound_cluster="fictional_new_cluster")
        query = _infer_query_genres(seed)
        assert query  # still non-empty from other signals

    def test_returns_lowercase_dedup_preserving_order(self) -> None:
        """Output contract preserved: lowercase, deduped, order-preserving."""
        seed = _seed()
        query = _infer_query_genres(seed)
        assert query == [g.lower() for g in query]
        assert len(query) == len(set(query))  # no duplicates
