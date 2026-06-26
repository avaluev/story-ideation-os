"""RED-first tests for pipeline.crystallize.portfolio.

The portfolio module is the pure selection + comp-dedup core behind the
multi-concept investor portfolio (the v5.2 superset of the single-best-per-
format slate). It must:

  * pick the top-K DISTINCT concepts per format (no two share a world or a wound)
  * assign DISTINCT comps across the whole portfolio (fixes the cross-card
    comp-reuse defect the prior slate shipped)
  * validate demand-evidence rows against the deep-link evidence policy

No LLM / network here — every number is produced upstream by python_executed
economics; this module only ranks + dedups.
"""

from __future__ import annotations

import pytest

portfolio = pytest.importorskip("pipeline.crystallize.portfolio")

from scripts.build_portfolio import som_band  # noqa: E402


def _cand(
    score: float, world: str, wound: str | None = None, *, comps: list[str] | None = None
) -> dict:
    wound = wound or f"SW_{world}"  # distinct per world unless an explicit clash is requested
    return {
        "crystallization_score": score,
        "seed_axes": {
            "world_texture": {"id": world, "name": world},
            "sdt_wound": {"id": wound, "description": wound},
            "structural_inversion": {"id": "SI_1"},
            "moral_fault_line": {"id": "MF_1"},
        },
        "comps": [{"title": t, "worldwide_gross_usd": 1.0} for t in (comps or [])],
    }


# --------------------------------------------------------------------------- #
# dedup_axis_key
# --------------------------------------------------------------------------- #


def test_dedup_axis_key_reads_seed_axes() -> None:
    key = portfolio.dedup_axis_key(_cand(0.5, "WT_03", "SW_12"))
    assert key == ("WT_03", "SW_12", "SI_1", "MF_1")


def test_dedup_axis_key_reads_top_level_when_no_seed_axes() -> None:
    c = {"world_texture": {"id": "WT_09"}, "sdt_wound": {"id": "SW_01"}}
    key = portfolio.dedup_axis_key(c)
    assert key[0] == "WT_09"
    assert key[1] == "SW_01"


# --------------------------------------------------------------------------- #
# select_topk_distinct
# --------------------------------------------------------------------------- #


def test_select_topk_distinct_orders_by_score() -> None:
    cands = [_cand(0.3, "A"), _cand(0.9, "B"), _cand(0.6, "C")]
    out = portfolio.select_topk_distinct(cands, 3)
    assert [c["seed_axes"]["world_texture"]["id"] for c in out] == ["B", "C", "A"]


def test_select_topk_distinct_rejects_duplicate_world() -> None:
    cands = [_cand(0.9, "A"), _cand(0.8, "A"), _cand(0.7, "B")]
    out = portfolio.select_topk_distinct(cands, 3)
    worlds = [c["seed_axes"]["world_texture"]["id"] for c in out]
    assert worlds == ["A", "B"]  # the second "A" is skipped


def test_select_topk_distinct_rejects_duplicate_wound() -> None:
    cands = [_cand(0.9, "A", "SW_1"), _cand(0.8, "B", "SW_1"), _cand(0.7, "C", "SW_2")]
    out = portfolio.select_topk_distinct(cands, 3)
    worlds = [c["seed_axes"]["world_texture"]["id"] for c in out]
    assert worlds == ["A", "C"]  # B shares SW_1 with A -> skipped


def test_select_topk_distinct_respects_k() -> None:
    cands = [_cand(0.9, "A"), _cand(0.8, "B"), _cand(0.7, "C")]
    assert len(portfolio.select_topk_distinct(cands, 2)) == 2


def test_select_topk_distinct_excludes_pre_claimed_worlds() -> None:
    """A world claimed by an earlier format is HARD-excluded (cross-slate)."""
    cands = [_cand(0.9, "A"), _cand(0.8, "B"), _cand(0.7, "C")]
    out = portfolio.select_topk_distinct(cands, 3, seen={"world_texture": {"A"}})
    worlds = [c["seed_axes"]["world_texture"]["id"] for c in out]
    assert "A" not in worlds  # A is pre-claimed by another format
    assert worlds == ["B", "C"]


def test_select_topk_distinct_does_not_mutate_caller_seen() -> None:
    cands = [_cand(0.9, "A"), _cand(0.8, "B")]
    seen = {"world_texture": {"Z"}}
    portfolio.select_topk_distinct(cands, 2, seen=seen)
    assert seen == {"world_texture": {"Z"}}  # caller's set untouched


# --------------------------------------------------------------------------- #
# assign_distinct_comps
# --------------------------------------------------------------------------- #


def test_assign_distinct_comps_zero_overlap_when_pool_rich() -> None:
    concepts = [
        _cand(0.9, "A", comps=["F1", "F2", "F3", "F4", "F5", "F6"]),
        _cand(0.8, "B", comps=["F1", "F2", "F3", "F4", "F5", "F6"]),
        _cand(0.7, "C", comps=["F1", "F2", "F3", "F4", "F5", "F6"]),
    ]
    out = portfolio.assign_distinct_comps(concepts, k=2)
    titles = [[c["title"] for c in concept["comps"]] for concept in out]
    flat = [t for row in titles for t in row]
    # 6 slots, 6 distinct films available -> zero reuse
    assert len(flat) == len(set(flat))
    assert all(len(row) == 2 for row in titles)


def test_assign_distinct_comps_falls_back_to_reuse_when_pool_thin() -> None:
    concepts = [
        _cand(0.9, "A", comps=["F1", "F2"]),
        _cand(0.8, "B", comps=["F1", "F2"]),
        _cand(0.7, "C", comps=["F1", "F2"]),
    ]
    out = portfolio.assign_distinct_comps(concepts, k=2, max_reuse=2)
    # every concept still reaches k comps despite the thin shared pool
    assert all(len(c["comps"]) == 2 for c in out)


def test_assign_distinct_comps_is_immutable() -> None:
    concepts = [_cand(0.9, "A", comps=["F1", "F2", "F3"])]
    before = [c["title"] for c in concepts[0]["comps"]]
    portfolio.assign_distinct_comps(concepts, k=1)
    after = [c["title"] for c in concepts[0]["comps"]]
    assert before == after  # input pool not mutated


def test_assign_distinct_comps_preserves_similarity_order() -> None:
    concepts = [_cand(0.9, "A", comps=["F1", "F2", "F3", "F4"])]
    out = portfolio.assign_distinct_comps(concepts, k=3)
    assert [c["title"] for c in out[0]["comps"]] == ["F1", "F2", "F3"]


# --------------------------------------------------------------------------- #
# deep-link evidence policy
# --------------------------------------------------------------------------- #


def test_is_deep_path_accepts_real_path() -> None:
    assert portfolio.is_deep_path("https://www.boxofficemojo.com/title/tt1661199/")


def test_is_deep_path_rejects_bare_domain() -> None:
    assert not portfolio.is_deep_path("https://example.com")
    assert not portfolio.is_deep_path("https://example.com/")


def test_is_deep_path_rejects_bare_domain_with_query() -> None:
    """Regression: a query string must not count as path depth (the trailing
    slash before '?' previously inflated the slash count to a false-positive)."""
    assert not portfolio.is_deep_path("https://example.com/?utm_source=x")
    assert not portfolio.is_deep_path("https://example.com?ref=tw")
    # a genuine deep path that carries a query is still accepted
    assert portfolio.is_deep_path("https://variety.com/2025/film/news/a-1236#top")


def test_is_deep_path_rejects_search_engine() -> None:
    assert not portfolio.is_deep_path("https://www.google.com/search?q=film")


def test_validate_demand_evidence_accepts_well_formed_row() -> None:
    row = {
        "claim": "Microdrama app revenue hit $X in 2025.",
        "stat": "$6.6B",
        "source_url": "https://variety.com/2025/digital/news/microdrama-apps-revenue-1236521194/",
        "date": "2025",
    }
    ok, reason = portfolio.validate_demand_evidence(row)
    assert ok, reason


def test_validate_demand_evidence_rejects_bare_domain_source() -> None:
    row = {"claim": "x", "stat": "1", "source_url": "https://variety.com", "date": "2025"}
    ok, _ = portfolio.validate_demand_evidence(row)
    assert not ok


def test_validate_demand_evidence_rejects_missing_source() -> None:
    row = {"claim": "x", "stat": "1", "date": "2025"}
    ok, _ = portfolio.validate_demand_evidence(row)
    assert not ok


# --------------------------------------------------------------------------- #
# title_overlap_clusters — cross-slate distinctiveness detection (P5)
# --------------------------------------------------------------------------- #


def _titled(id_: str, title: str, *, score: float = 0.5, demand: int = 3) -> dict:
    return {
        "id": id_,
        "crystallization_score": score,
        "enrichment": {"title": title},
        "title": title,
        "demand_evidence": [
            {
                "claim": f"c{n}",
                "stat": "1",
                "source_url": f"https://variety.com/2025/news/x-{id_}-{n}/",
                "date": "2025",
            }
            for n in range(demand)
        ],
    }


def test_title_overlap_clusters_empty_when_distinct() -> None:
    cs = [_titled("a", "Weatherbound"), _titled("b", "Apex Bloom"), _titled("c", "Keepsake")]
    assert portfolio.title_overlap_clusters(cs) == []


def test_title_overlap_clusters_detects_shared_token() -> None:
    cs = [_titled("a", "The Quiet Custodian"), _titled("b", "The Quiet Wing")]
    clusters = portfolio.title_overlap_clusters(cs)
    assert clusters == [["a", "b"]]  # collide on "quiet"


def test_title_overlap_clusters_folds_plural() -> None:
    cs = [_titled("a", "The Hollowing Hours"), _titled("b", "The Lucid Hour")]
    assert portfolio.title_overlap_clusters(cs) == [["a", "b"]]  # hours == hour


def test_title_overlap_clusters_ignores_stopwords() -> None:
    cs = [_titled("a", "The Clean Room"), _titled("b", "The Apex Bloom")]
    assert portfolio.title_overlap_clusters(cs) == []  # "the" is not a collision


def test_title_overlap_clusters_reads_enrichment_title_first() -> None:
    c = {"id": "a", "title": "Old Noun Salad", "enrichment": {"title": "Weatherbound"}}
    c2 = {"id": "b", "title": "Weatherbound Two", "enrichment": {"title": "Apex Bloom"}}
    assert portfolio.title_overlap_clusters([c, c2]) == []  # uses enrichment, not raw title


# --------------------------------------------------------------------------- #
# select_titles_to_rename — greedy keep-strongest
# --------------------------------------------------------------------------- #


def test_select_titles_to_rename_empty_when_distinct() -> None:
    cs = [_titled("a", "Weatherbound"), _titled("b", "Keepsake")]
    assert portfolio.select_titles_to_rename(cs) == []


def test_select_titles_to_rename_keeps_strongest() -> None:
    cs = [
        _titled("strong", "The Quiet Custodian", score=0.9),
        _titled("weak", "The Quiet Wing", score=0.3),
    ]
    assert portfolio.select_titles_to_rename(cs) == ["weak"]


def test_select_titles_to_rename_triple_collider_counts_once() -> None:
    cs = [
        _titled("keep_q", "The Quiet Custodian", score=0.95),
        _titled("keep_h", "The Lucid Hour", score=0.90),
        _titled("keep_l", "Last Light Protocol", score=0.85),
        _titled("triple", "The Last Quiet Hour", score=0.10),  # collides on quiet+hour+last
    ]
    assert portfolio.select_titles_to_rename(cs) == ["triple"]


# --------------------------------------------------------------------------- #
# apply_review_fixes — rename / drop dead urls / drop ids (immutable)
# --------------------------------------------------------------------------- #


def test_apply_review_fixes_renames_in_both_places() -> None:
    enriched = {"concepts": [_titled("a", "Old Title", demand=3)]}
    out = portfolio.apply_review_fixes(enriched, renames={"a": "New Title"})
    c = out["concepts"][0]
    assert c["title"] == "New Title"
    assert c["enrichment"]["title"] == "New Title"
    # input untouched
    assert enriched["concepts"][0]["title"] == "Old Title"


def test_apply_review_fixes_drops_dead_urls() -> None:
    c = _titled("a", "T", demand=4)
    dead = c["demand_evidence"][0]["source_url"]
    out = portfolio.apply_review_fixes({"concepts": [c]}, dropped_urls={"a": [dead]})
    urls = [r["source_url"] for r in out["concepts"][0]["demand_evidence"]]
    assert dead not in urls
    assert len(urls) == 3


def test_apply_review_fixes_raises_below_min_demand() -> None:
    c = _titled("a", "T", demand=3)
    dead = c["demand_evidence"][0]["source_url"]
    with pytest.raises(ValueError, match="re-enrich"):
        portfolio.apply_review_fixes({"concepts": [c]}, dropped_urls={"a": [dead]})


def test_apply_review_fixes_drops_ids_and_recounts() -> None:
    enriched = {"concepts": [_titled("a", "A"), _titled("b", "B")], "concept_count": 2}
    out = portfolio.apply_review_fixes(enriched, dropped_ids=["b"])
    assert [c["id"] for c in out["concepts"]] == ["a"]
    assert out["concept_count"] == 1


# --------------------------------------------------------------------------- #
# select_top_by_som — max-credible-economics selection mode
# --------------------------------------------------------------------------- #


def _som_cand(som: float, world: str, fmt: str, wound: str | None = None) -> dict:
    c = _cand(0.5, world, wound)
    c["som_y1_usd"] = som
    c["economics_key"] = fmt
    return c


def test_select_top_by_som_ranks_by_som_desc() -> None:
    cands = [
        _som_cand(100.0, "WT_a", "feature"),
        _som_cand(800.0, "WT_b", "feature"),
        _som_cand(300.0, "WT_c", "limited_series"),
    ]
    out = portfolio.select_top_by_som(cands, 2)
    assert [c["som_y1_usd"] for c in out] == [800.0, 300.0]


def test_select_top_by_som_enforces_world_distinctness() -> None:
    cands = [
        _som_cand(900.0, "WT_dup", "feature", wound="W1"),
        _som_cand(800.0, "WT_dup", "limited_series", wound="W2"),  # same world -> skipped
        _som_cand(700.0, "WT_other", "feature", wound="W3"),
    ]
    out = portfolio.select_top_by_som(cands, 3)
    worlds = [c["seed_axes"]["world_texture"]["id"] for c in out]
    assert worlds == ["WT_dup", "WT_other"]  # the duplicate world is dropped


def test_select_top_by_som_respects_max_per_format() -> None:
    cands = [
        _som_cand(900.0, "WT_a", "feature"),
        _som_cand(800.0, "WT_b", "feature"),
        _som_cand(700.0, "WT_c", "feature"),  # 3rd feature -> capped out
        _som_cand(600.0, "WT_d", "microdrama"),
    ]
    out = portfolio.select_top_by_som(cands, 4, max_per_format=2)
    fmts = [c["economics_key"] for c in out]
    assert fmts.count("feature") == 2
    assert "microdrama" in fmts  # diversity preserved by the cap


def test_select_top_by_som_does_not_mutate_seen() -> None:
    seen = {"world_texture": {"WT_a"}}
    cands = [_som_cand(900.0, "WT_b", "feature")]
    portfolio.select_top_by_som(cands, 1, seen=seen)
    assert seen == {"world_texture": {"WT_a"}}  # caller's set untouched


# --------------------------------------------------------------------------- #
# som_band — conservative / base / upside three-point estimate
# --------------------------------------------------------------------------- #


def test_som_band_brackets_the_floor() -> None:
    # som = p50 * derate; band scales p10/p90 by the same derate.
    low, high = som_band(800.0, p10=200.0, p50=400.0, p90=900.0)
    assert low == 400.0  # 200 * (800/400)
    assert high == 1800.0  # 900 * (800/400)
    assert low <= 800.0 <= high


def test_som_band_collapses_without_distribution() -> None:
    # non-theatrical / no comp distribution -> band == point figure
    assert som_band(150.0, p10=None, p50=None, p90=None) == (150.0, 150.0)
    assert som_band(150.0, p10=10.0, p50=0.0, p90=99.0) == (150.0, 150.0)
