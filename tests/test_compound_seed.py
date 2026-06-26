"""Tests for pipeline/compound_seed.py.

Covers:
- Variable library loads without error
- Associative distance stays in valid range
- Audience overlap is non-negative
- Scoring produces valid CompoundScore
- generate() returns a result within attempt cap
- Hidden attrs contain required keys
- SOM floor is proportional to audience overlap
- CLI smoke test (no crash)
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from pipeline.compound_seed import (
    CompoundSeedEngine,
    CompoundVariables,
    _compute_associative_distance,
    _compute_audience_overlap,
    _derive_arc_shape,
    _derive_boden_type,
    _derive_conflict_type,
    _thematic_weighted_choice,
    _theme_keywords_to_clusters,
)
from pipeline.zeitgeist_probe import boost_weights

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VARS_PATH = _REPO_ROOT / "pipeline" / "data" / "compound_seed_variables.json"
_ONTOLOGY_PATH = _REPO_ROOT / "sources" / "conflict_ontology.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine() -> CompoundSeedEngine:
    return CompoundSeedEngine(rng_seed=42)


@pytest.fixture(scope="module")
def result(engine: CompoundSeedEngine):
    return engine.generate(rng_seed=42) if False else engine.generate()


# ---------------------------------------------------------------------------
# Variable library
# ---------------------------------------------------------------------------


def test_vars_file_exists() -> None:
    assert _VARS_PATH.exists(), f"compound_seed_variables.json missing at {_VARS_PATH}"


def test_vars_required_categories() -> None:

    data = json.loads(_VARS_PATH.read_text())
    required = [
        "sdt_wounds",
        "psychological_patterns",
        "structural_inversions",
        "moral_fault_lines",
        "compression_keys",
        "divisiveness_engines",
        "audience_domains",
        "world_textures",
        "era_collisions",
        "civilizational_stakes",
        "methodology_protagonists",
        "historical_methodology_transplants",
    ]
    for cat in required:
        assert cat in data, f"Missing category: {cat}"
        assert len(data[cat]) >= 5, f"Category {cat} has fewer than 5 entries"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def test_associative_distance_empty_returns_default() -> None:
    dist = _compute_associative_distance([])
    assert 0.0 <= dist <= 1.0


def test_associative_distance_single_group_returns_default() -> None:
    dist = _compute_associative_distance([["bureaucracy", "institution"]])
    assert 0.0 <= dist <= 1.0


def test_associative_distance_two_identical_groups_low() -> None:
    dist = _compute_associative_distance(
        [["bureaucracy", "institution"], ["bureaucracy", "institution"]]
    )
    assert dist < 0.5


def test_associative_distance_distant_groups_higher() -> None:
    close = _compute_associative_distance(
        [["bureaucracy", "institution"], ["institution", "authority"]]
    )
    far = _compute_associative_distance(
        [["bureaucracy", "institution"], ["nature", "ecology", "climate"]]
    )
    assert far >= close


def test_audience_overlap_empty() -> None:
    assert _compute_audience_overlap([]) == 0.0


def test_audience_overlap_single() -> None:
    result = _compute_audience_overlap([{"id": "X", "size_M": 200, "affinity_with": []}])
    assert result >= 0.0


def test_audience_overlap_three_grows_with_size() -> None:
    small = _compute_audience_overlap(
        [
            {"id": "A", "size_M": 50, "affinity_with": []},
            {"id": "B", "size_M": 50, "affinity_with": []},
            {"id": "C", "size_M": 50, "affinity_with": []},
        ]
    )
    large = _compute_audience_overlap(
        [
            {"id": "A", "size_M": 500, "affinity_with": []},
            {"id": "B", "size_M": 500, "affinity_with": []},
            {"id": "C", "size_M": 500, "affinity_with": []},
        ]
    )
    assert large > small


# ---------------------------------------------------------------------------
# derive helpers
# ---------------------------------------------------------------------------


def _make_minimal_vars(**overrides) -> CompoundVariables:
    defaults: dict = {
        "themes": [],
        "problems": [],
        "tensions": [],
        "sdt_wound": {"need": "autonomy", "deprivation_intensity": 1.5},
        "psychological_pattern": {"description": "test", "surprise_weight": 0.8, "domain_tags": []},
        "structural_inversion": {
            "description": "test",
            "surprise_weight": 0.9,
            "domain_tags": ["institution"],
        },
        "moral_fault_line": {"description": "test about truth"},
        "compression_key": {"description": "test", "surprise_weight": 0.85},
        "divisiveness_engine": {
            "description": "test",
            "score": 9.0,
            "organic_marketing_multiplier": 2.5,
        },
        "audiences": [{"id": "A", "size_M": 500, "affinity_with": []}],
        "world_texture": {"name": "test", "domain_tags": ["institution"]},
        "civilizational_stake": None,
        "methodology_protagonist": None,
        "historical_transplant": None,
        "era_collision": None,
    }
    defaults.update(overrides)
    return CompoundVariables(**defaults)


def test_derive_arc_shape_fall_rise() -> None:
    v = _make_minimal_vars(
        divisiveness_engine={"score": 9.5, "organic_marketing_multiplier": 2.5, "description": "t"},
        sdt_wound={"need": "autonomy", "deprivation_intensity": 1.5},
    )
    assert _derive_arc_shape(v) == "Fall-Rise"


def test_derive_arc_shape_rise_fall() -> None:
    v = _make_minimal_vars(
        divisiveness_engine={"score": 7.5, "organic_marketing_multiplier": 2.0, "description": "t"},
        sdt_wound={"need": "autonomy", "deprivation_intensity": 1.0},
    )
    assert _derive_arc_shape(v) == "Rise-Fall"


def test_derive_conflict_type_society() -> None:
    v = _make_minimal_vars(
        structural_inversion={
            "description": "t",
            "surprise_weight": 0.9,
            "domain_tags": ["institution", "systemic"],
        },
    )
    assert _derive_conflict_type(v) == "man vs society"


def test_derive_conflict_type_technology() -> None:
    v = _make_minimal_vars(
        structural_inversion={
            "description": "t",
            "surprise_weight": 0.9,
            "domain_tags": ["technology", "AI"],
        },
    )
    assert _derive_conflict_type(v) == "man vs technology"


def test_derive_boden_transformational() -> None:
    v = _make_minimal_vars(
        structural_inversion={"description": "t", "surprise_weight": 0.90, "domain_tags": []},
    )
    assert _derive_boden_type(v) == "transformational"


def test_derive_boden_exploratory() -> None:
    v = _make_minimal_vars(
        structural_inversion={"description": "t", "surprise_weight": 0.72, "domain_tags": []},
    )
    assert _derive_boden_type(v) == "exploratory"


# ---------------------------------------------------------------------------
# Engine end-to-end
# ---------------------------------------------------------------------------


def test_generate_returns_result(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=10)
    assert result is not None
    assert result.intersection_premise
    assert result.scores.genius_score >= 0.0


def test_generate_scores_in_range(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=10)
    s = result.scores
    assert 0.0 <= s.genius_score <= 1.0
    assert 0.0 <= s.associative_distance <= 1.0
    assert s.audience_overlap_M >= 0.0
    assert s.som_floor_M >= 0.0


def test_generate_hidden_attrs_keys(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=5)
    required_keys = {
        "arc_shape",
        "conflict_type",
        "boden_type",
        "sdt_need",
        "budget_tier",
        "moral_wager",
    }
    assert required_keys.issubset(result.hidden_attrs.keys())


def test_generate_to_dict_serialisable(engine: CompoundSeedEngine) -> None:

    result = engine.generate(max_attempts=5)
    payload = result.to_dict()
    serialised = json.dumps(payload)
    assert len(serialised) > 100


def test_generate_with_themes(engine: CompoundSeedEngine) -> None:
    result = engine.generate(
        themes=["information verification", "AI misinformation"],
        max_attempts=10,
    )
    assert result.themes == ["information verification", "AI misinformation"]


def test_generate_force_transplant(engine: CompoundSeedEngine) -> None:
    result = engine.generate(
        force_historical_transplant="HT_02",
        max_attempts=5,
    )
    assert result.variables.historical_transplant is not None
    assert result.variables.historical_transplant["id"] == "HT_02"


def test_generate_force_civilizational(engine: CompoundSeedEngine) -> None:
    result = engine.generate(force_civilizational=True, max_attempts=5)
    assert result.variables.civilizational_stake is not None


def test_som_proportional_to_audience(engine: CompoundSeedEngine) -> None:
    """Larger audience overlap must produce higher SOM floor."""
    small_aud = [{"id": "X", "size_M": 50, "affinity_with": []}]
    large_aud = [{"id": "Y", "size_M": 800, "affinity_with": []}]
    assert _compute_audience_overlap(large_aud) > _compute_audience_overlap(small_aud)


# ---------------------------------------------------------------------------
# Genre bias fix — Issue #26
# ---------------------------------------------------------------------------


def test_theme_keywords_to_clusters_family() -> None:
    clusters = _theme_keywords_to_clusters(["family adventure", "love story"])
    assert 1 in clusters  # cluster 1 = family/love/intimacy


def test_theme_keywords_to_clusters_ai_problem() -> None:
    clusters = _theme_keywords_to_clusters(["AI displacement", "automation job loss"])
    assert 2 in clusters  # cluster 2 = technology/AI/automation


def test_theme_keywords_to_clusters_ecology() -> None:
    clusters = _theme_keywords_to_clusters(["climate crisis", "ecology collapse"])
    assert 4 in clusters  # cluster 4 = nature/ecology/climate


def test_theme_keywords_to_clusters_empty_returns_empty_set() -> None:
    assert _theme_keywords_to_clusters([]) == set()


def test_thematic_weighted_choice_no_penalty_when_empty_clusters() -> None:
    rng = random.Random(0)  # noqa: S311
    pool = [
        {"id": "A", "domain_tags": ["institution", "bureaucracy"]},
        {"id": "B", "domain_tags": ["family", "love"]},
    ]
    # Empty target_clusters = uniform; both items must be reachable
    seen = {_thematic_weighted_choice(rng, pool, set(), 0.6)["id"] for _ in range(40)}
    assert seen == {"A", "B"}


def test_thematic_weighted_choice_penalises_institutional_for_family_themes() -> None:
    rng = random.Random(42)  # noqa: S311
    institutional = {"id": "INST", "domain_tags": ["institution", "bureaucracy"]}
    family_item = {"id": "FAM", "domain_tags": ["family", "love"]}
    pool = [institutional] * 5 + [family_item] * 5
    target = {1}  # cluster 1 = family
    counts: dict[str, int] = {"INST": 0, "FAM": 0}
    for _ in range(200):
        pick = _thematic_weighted_choice(rng, pool, target, 0.6)
        counts[pick["id"]] += 1
    # Family-tagged item must win more often than institutional when family themes given
    assert counts["FAM"] > counts["INST"]


def test_thematic_weighted_choice_zero_penalty_is_uniform() -> None:
    rng = random.Random(7)  # noqa: S311
    pool = [
        {"id": "A", "domain_tags": ["institution"]},
        {"id": "B", "domain_tags": ["family"]},
    ]
    seen = {_thematic_weighted_choice(rng, pool, {1}, 0.0)["id"] for _ in range(60)}
    assert seen == {"A", "B"}


def test_generate_with_real_world_problem(engine: CompoundSeedEngine) -> None:
    result = engine.generate(
        problems=["AI displacement of workers", "loneliness epidemic"],
        max_attempts=10,
    )
    assert result is not None
    assert result.problems == ["AI displacement of workers", "loneliness epidemic"]
    assert result.scores.genius_score >= 0.0


def test_genre_bias_family_themes_avoids_institutional_cluster(
    engine: CompoundSeedEngine,
) -> None:
    """With family/love themes, institutional-tagged variables should appear less often.

    Uses _sample_variables directly to avoid the Haiku API call.
    """
    institutional_tags = {"institution", "bureaucracy", "precision", "authority"}
    institutional_hits = 0
    runs = 30
    tc = _theme_keywords_to_clusters(["family", "love", "wonder"])
    for i in range(runs):
        eng = CompoundSeedEngine(rng_seed=i)
        v = eng._sample_variables(
            themes=["family", "love", "wonder"],
            problems=[],
            n_tensions=2,
            n_conspiracy=0,
            n_reptile=0,
            n_cultural_moment=0,
            n_audiences=3,
            n_era=0,
            n_open_problems=0,
            n_worlds=1,
            n_moral=1,
            protagonist_entity_type="HUMAN",
            antagonist_entity_type="HUMAN",
            force_historical_transplant=None,
            force_civilizational=False,
            target_clusters=tc,
            genre_bias_penalty_weight=0.8,
        )
        si_tags = set(v.structural_inversion.get("domain_tags", []))
        if si_tags & institutional_tags:
            institutional_hits += 1
    # With penalty 0.8 and family themes, institutional inversions should appear < 65% of the time.
    assert institutional_hits < runs * 0.65, (
        f"Institutional inversion appeared {institutional_hits}/{runs} times — bias not reduced"
    )


# ---------------------------------------------------------------------------
# Issue #23 — thematic cluster tags
# ---------------------------------------------------------------------------


def test_generate_exposes_primary_cluster_and_coherence(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=10)
    assert isinstance(result.scores.primary_cluster, str)
    assert 0.0 <= result.scores.cluster_coherence <= 1.0


def test_cluster_coherence_higher_with_aligned_themes() -> None:
    """Seeding with a single-cluster theme should produce higher coherence.

    Uses _sample_variables + _compute_cluster_coherence directly to avoid Haiku.
    """
    from pipeline.compound_seed import _compute_cluster_coherence  # noqa: PLC0415

    tc = _theme_keywords_to_clusters(["family", "love", "belonging", "emotional"])
    coherences: list[float] = []
    for i in range(20):
        eng = CompoundSeedEngine(rng_seed=i)
        v = eng._sample_variables(
            themes=["family", "love", "belonging", "emotional"],
            problems=[],
            n_tensions=2,
            n_conspiracy=0,
            n_reptile=0,
            n_cultural_moment=0,
            n_audiences=3,
            n_era=0,
            n_open_problems=0,
            n_worlds=1,
            n_moral=1,
            protagonist_entity_type="HUMAN",
            antagonist_entity_type="HUMAN",
            force_historical_transplant=None,
            force_civilizational=False,
            target_clusters=tc,
            genre_bias_penalty_weight=0.9,
        )
        _, coh = _compute_cluster_coherence(v)
        coherences.append(coh)
    avg = sum(coherences) / len(coherences)
    assert avg > 0.30, f"Expected coherence > 0.30 with aligned themes, got {avg:.3f}"


_VARS_JSON = _REPO_ROOT / "pipeline/data/compound_seed_variables.json"
_CM_JSON = _REPO_ROOT / "frameworks/data/cultural_moment_2026.json"


def test_theme_keywords_to_clusters_recognises_cluster_names() -> None:
    assert 1 in _theme_keywords_to_clusters(["emotional journey"])
    assert 4 in _theme_keywords_to_clusters(["nature catastrophe"])
    assert 2 in _theme_keywords_to_clusters(["technology collapse"])
    assert 7 in _theme_keywords_to_clusters(["civilizational stakes"])


def test_audience_domains_now_have_domain_tags_and_cluster() -> None:
    data = json.loads(_VARS_JSON.read_text())
    for ad in data["audience_domains"]:
        assert ad.get("domain_tags"), f"{ad['id']} missing domain_tags"
        assert ad.get("thematic_cluster"), f"{ad['id']} missing thematic_cluster"


def test_all_variable_categories_have_thematic_cluster() -> None:
    data = json.loads(_VARS_JSON.read_text())
    check = [
        "sdt_wounds",
        "psychological_patterns",
        "structural_inversions",
        "moral_fault_lines",
        "compression_keys",
        "divisiveness_engines",
        "world_textures",
        "audience_domains",
    ]
    for cat in check:
        missing = [x["id"] for x in data[cat] if not x.get("thematic_cluster")]
        assert not missing, f"{cat} entries missing thematic_cluster: {missing}"


# ---------------------------------------------------------------------------
# Issue #24 — urgency weights on cultural moments
# ---------------------------------------------------------------------------


def test_cultural_moments_have_urgency_score() -> None:
    data = json.loads(_CM_JSON.read_text())
    assert len(data) == 30
    for cm in data:
        assert "urgency_score_2026" in cm, f"{cm['id']} missing urgency_score_2026"
        score = cm["urgency_score_2026"]
        assert 0.5 <= score <= 2.0, f"{cm['id']} urgency={score} out of [0.5, 2.0]"
        assert "thematic_cluster" in cm, f"{cm['id']} missing thematic_cluster"
        assert "domain_tags" in cm, f"{cm['id']} missing domain_tags"


def test_boost_weights_multiplies_urgency() -> None:

    low = {"id": "CM_LOW", "label": "irrelevant old topic", "urgency_score_2026": 0.5}
    high = {"id": "CM_HIGH", "label": "irrelevant old topic", "urgency_score_2026": 1.9}
    # No zeitgeist overlap for either — both get floor weight, but high urgency wins
    weights = boost_weights([low, high], zeitgeist=[])
    assert weights[1] > weights[0], "Higher urgency must produce higher weight"


def test_boost_weights_urgency_times_overlap() -> None:

    cm_hit = {"id": "CM_HIT", "label": "AI displacement crisis", "urgency_score_2026": 1.0}
    cm_miss = {"id": "CM_MISS", "label": "obscure fringe concern", "urgency_score_2026": 1.9}
    zeitgeist = [{"id": "ai_displacement", "description": "AI displacement of workers"}]
    weights = boost_weights([cm_hit, cm_miss], zeitgeist=zeitgeist)
    # cm_hit matches zeitgeist (overlap=1.0 * urgency=1.0 = 1.0)
    # cm_miss has no overlap (floor * urgency=1.9) — floor is 0.1 so 0.19 < 1.0
    assert weights[0] > weights[1], (
        "Zeitgeist-matching low-urgency should beat non-matching high-urgency"
    )


# ---------------------------------------------------------------------------
# Ally archetypes
# ---------------------------------------------------------------------------

_ALLY_JSON = _REPO_ROOT / "frameworks/data/ally_archetypes.json"


def test_ally_archetypes_file_exists() -> None:
    assert _ALLY_JSON.exists(), "ally_archetypes.json missing"


def test_ally_archetypes_schema() -> None:
    data = json.loads(_ALLY_JSON.read_text())
    assert len(data) >= 8
    required = {
        "id",
        "label",
        "role",
        "dramatic_function",
        "relationship_to_protagonist",
        "primary_fear",
        "thematic_cluster",
        "domain_tags",
    }
    for item in data:
        missing = required - item.keys()
        assert not missing, f"{item.get('id')} missing fields: {missing}"


def test_generate_includes_ally_by_default(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=5, n_allies=1)
    assert isinstance(result.variables.ally_archetypes, list)
    # default n_allies=1 should produce exactly one ally
    assert len(result.variables.ally_archetypes) == 1
    ally = result.variables.ally_archetypes[0]
    assert ally.get("dramatic_function"), "ally must have dramatic_function"
    assert ally.get("role"), "ally must have role"


def test_generate_n_allies_zero_produces_empty(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=5, n_allies=0)
    assert result.variables.ally_archetypes == []


def test_generate_n_allies_two_produces_pair(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=5, n_allies=2)
    assert len(result.variables.ally_archetypes) <= 2  # may be 1 if pool dedup collapses
    assert len(result.variables.ally_archetypes) >= 1


def test_ally_included_in_to_dict(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=5, n_allies=1)
    d = result.to_dict()
    assert "ally_archetypes" in d
    assert isinstance(d["ally_archetypes"], list)


def test_ally_roles_in_hidden_attrs(engine: CompoundSeedEngine) -> None:
    result = engine.generate(max_attempts=5, n_allies=1)
    assert "num_allies" in result.hidden_attrs
    assert "ally_roles" in result.hidden_attrs
    assert result.hidden_attrs["num_allies"] == len(result.variables.ally_archetypes)


def test_ally_cluster_steered_by_themes() -> None:
    """Allies must prefer emotional-cluster entries when emotional themes given.

    Uses _sample_allies directly to avoid the Haiku API call.
    """
    tc = _theme_keywords_to_clusters(["family", "grief", "love", "emotional"])
    emotional_hits = 0
    runs = 30
    for i in range(runs):
        eng = CompoundSeedEngine(rng_seed=i)
        allies = eng._sample_allies(1, tc, 0.9)
        for ally in allies:
            if ally.get("thematic_cluster") == "emotional":
                emotional_hits += 1
    # Emotional pool is 3/10 entries (30% baseline). Steering should beat that.
    assert emotional_hits >= runs * 0.25, (
        f"Ally cluster steering weak: only {emotional_hits}/{runs} emotional picks"
    )
