"""Tests for the compound seed axes (multi-pick resonance stacks + archetype pairing).

Covers:
- frameworks/data JSON files exist and have required schema fields
- _new_axes_prompt_lines() returns empty list when all axes are empty/None
- _new_axes_prompt_lines() returns one line per present axis group
- Each axis line contains the axis's label and primary_fear text
- to_dict() serialises all axes (empty list / None / populated)
- generate() populates new axes fields in returned result dict
- Axes loaded from frameworks/data files round-trip through engine sampling
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.compound_seed import (
    CompoundScore,
    CompoundSeedEngine,
    CompoundSeedResult,
    CompoundVariables,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FW_DATA = _REPO_ROOT / "frameworks" / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_full_minimal_vars(**overrides: Any) -> CompoundVariables:
    """Return a CompoundVariables with all required fields, all optional axes empty/None."""
    defaults: dict[str, Any] = {
        "themes": [],
        "problems": [],
        "tensions": [],
        "sdt_wound": {"need": "autonomy", "deprivation_intensity": 1.5, "description": "wound"},
        "psychological_pattern": {
            "description": "psych",
            "surprise_weight": 0.8,
            "domain_tags": [],
        },
        "structural_inversion": {
            "description": "inversion",
            "surprise_weight": 0.9,
            "domain_tags": ["institution"],
        },
        "moral_fault_line": {"description": "fault about truth"},
        "compression_key": {"description": "aha", "surprise_weight": 0.85},
        "divisiveness_engine": {
            "description": "divisive",
            "score": 9.0,
            "organic_marketing_multiplier": 2.5,
        },
        "audiences": [{"id": "A", "size_M": 500, "affinity_with": []}],
        "world_texture": {"name": "cyber-noir", "domain_tags": ["technology"]},
        "civilizational_stake": None,
        "methodology_protagonist": None,
        "historical_transplant": None,
        "era_collision": [],
        # Multi-pick list fields — empty list = not sampled
        "conspiracy_engine": [],
        "reptile_trigger": [],
        "cultural_moment": [],
        # Single-dict / None fields
        "open_problem": [],
        "dark_archetype": None,
        "antagonist_archetype": None,
    }
    defaults.update(overrides)
    return CompoundVariables(**defaults)


def _fake_axis(label: str, fear: str) -> dict[str, Any]:
    return {"id": "TEST_001", "label": label, "primary_fear": fear}


# ---------------------------------------------------------------------------
# frameworks/data file existence + schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "conspiracy_engines.json",
        "reptile_triggers.json",
        "open_problems_science.json",
        "cultural_moment_2026.json",
        "dark_archetypes.json",
    ],
)
def test_framework_data_file_exists(filename: str) -> None:
    path = _FW_DATA / filename
    assert path.exists(), f"Expected frameworks/data/{filename} to exist"


@pytest.mark.parametrize(
    "filename",
    [
        "conspiracy_engines.json",
        "reptile_triggers.json",
        "open_problems_science.json",
        "cultural_moment_2026.json",
        "dark_archetypes.json",
    ],
)
def test_framework_data_is_list_with_items(filename: str) -> None:
    path = _FW_DATA / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list), f"{filename} must be a JSON array"
    assert len(data) >= 3, f"{filename} must contain at least 3 items"


@pytest.mark.parametrize(
    "filename",
    [
        "conspiracy_engines.json",
        "reptile_triggers.json",
        "open_problems_science.json",
        "cultural_moment_2026.json",
        "dark_archetypes.json",
    ],
)
def test_framework_data_items_have_required_keys(filename: str) -> None:
    path = _FW_DATA / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data:
        assert "id" in item, f"{filename}: item missing 'id': {item}"
        assert "label" in item, f"{filename}: item missing 'label': {item}"
        assert "primary_fear" in item, f"{filename}: item missing 'primary_fear': {item}"


# ---------------------------------------------------------------------------
# _new_axes_prompt_lines — unit tests
# ---------------------------------------------------------------------------


def test_new_axes_all_none_returns_empty_list() -> None:
    """When no new axes are set (empty lists / None), the helper returns an empty list."""
    v = _make_full_minimal_vars()
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    result = engine._new_axes_prompt_lines(v)
    assert result == []


def test_new_axes_conspiracy_only() -> None:
    label, fear = "JFK Assassination", "Institutions we trust are instruments of destruction."
    v = _make_full_minimal_vars(conspiracy_engine=[_fake_axis(label, fear)])
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 1
    assert label in lines[0]
    assert fear in lines[0]


def test_new_axes_reptile_trigger_only() -> None:
    label, fear = "Predator Threat", "Something is hunting you."
    v = _make_full_minimal_vars(reptile_trigger=[_fake_axis(label, fear)])
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 1
    assert label in lines[0]
    assert fear in lines[0]


def test_new_axes_open_problem_only() -> None:
    label, fear = "Consciousness: Hard Problem", "No one can explain subjective experience."
    v = _make_full_minimal_vars(open_problem=[_fake_axis(label, fear)])
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 1
    assert label in lines[0]
    assert fear in lines[0]


def test_new_axes_cultural_moment_only() -> None:
    label, fear = "AI Job Displacement", "Your skills are becoming obsolete."
    v = _make_full_minimal_vars(cultural_moment=[_fake_axis(label, fear)])
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 1
    assert label in lines[0]
    assert fear in lines[0]


def test_new_axes_dark_archetype_only() -> None:
    label, fear = "Shadow Hero", "The savior manufactures the crises they solve."
    v = _make_full_minimal_vars(dark_archetype=_fake_axis(label, fear))
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 1
    assert label in lines[0]
    assert fear in lines[0]


def test_new_axes_protagonist_antagonist_pair() -> None:
    """Protagonist + antagonist shadow each produce one line (two total)."""
    protagonist = _fake_axis("Shadow Hero", "Savior manufactures crises.")
    antagonist = _fake_axis("Corrupted Mentor", "The guide has become a weapon.")
    v = _make_full_minimal_vars(dark_archetype=protagonist, antagonist_archetype=antagonist)
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 2
    assert "Protagonist shadow" in lines[0]
    assert "Antagonist shadow" in lines[1]


def test_new_axes_multi_conspiracy_produces_one_line() -> None:
    """Multiple conspiracy picks are joined in a single line."""
    axes = [_fake_axis("JFK", "Fear A"), _fake_axis("MoonLanding", "Fear B")]
    v = _make_full_minimal_vars(conspiracy_engine=axes)
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 1
    assert "JFK" in lines[0]
    assert "MoonLanding" in lines[0]


def test_new_axes_all_five_returns_five_lines() -> None:
    """When all 5 axis groups are populated, exactly 5 lines are returned."""
    v = _make_full_minimal_vars(
        conspiracy_engine=[_fake_axis("Conspiracy A", "Fear A")],
        reptile_trigger=[_fake_axis("Reptile B", "Fear B")],
        open_problem=[_fake_axis("Problem C", "Fear C")],
        cultural_moment=[_fake_axis("Culture D", "Fear D")],
        dark_archetype=_fake_axis("Archetype E", "Fear E"),
    )
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 5


def test_new_axes_partial_two_axes() -> None:
    """Only axes that are non-empty / not-None contribute a line."""
    v = _make_full_minimal_vars(
        reptile_trigger=[_fake_axis("Reptile B", "Fear B")],
        dark_archetype=_fake_axis("Archetype E", "Fear E"),
    )
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    assert len(lines) == 2


def test_new_axes_lines_contain_no_framework_ids() -> None:
    """Prompt lines must not expose internal IDs like 'CC_001'."""
    v = _make_full_minimal_vars(
        conspiracy_engine=[
            {
                "id": "CC_001",
                "label": "JFK",
                "primary_fear": "The institution kills.",
            }
        ],
        dark_archetype={
            "id": "DA_001",
            "label": "Shadow Hero",
            "primary_fear": "Savior manufactures crises.",
        },
    )
    engine = CompoundSeedEngine.__new__(CompoundSeedEngine)
    lines = engine._new_axes_prompt_lines(v)
    combined = " ".join(lines)
    assert "CC_001" not in combined
    assert "DA_001" not in combined


# ---------------------------------------------------------------------------
# to_dict serialisation — new axes appear in output
# ---------------------------------------------------------------------------


def test_to_dict_includes_all_new_axes_empty() -> None:
    """to_dict must include all axis keys; list fields are [] and dict fields are None."""
    v = _make_full_minimal_vars()
    score = CompoundScore(
        genius_score=0.8,
        associative_distance=0.4,
        goldilocks_score=0.9,
        sdt_intensity=1.5,
        structural_surprise=0.9,
        compression_score=0.85,
        audience_overlap_M=200.0,
        divisiveness_score=9.0,
        organic_marketing_mult=2.5,
        som_floor_M=500.0,
        passes_500m_gate=True,
        passes_genius_gate=True,
        tam_M=40000.0,
        sam_M=960.0,
        thematic_anchor_score=0.6,
        emotional_universality_score=3.5,
        primary_cluster="emotional",
        cluster_coherence=0.6,
        arc_shape_6="Cinderella",
        cultural_field_alignment=0.5,
    )
    result = CompoundSeedResult(
        run_id="test_000",
        themes=[],
        problems=[],
        variables=v,
        scores=score,
        intersection_premise="test premise",
        hidden_attrs={},
    )
    d = result.to_dict()
    # Multi-pick list fields default to empty list (not None)
    for key in ("conspiracy_engine", "reptile_trigger", "cultural_moment"):
        assert key in d, f"to_dict() missing key: {key}"
        assert d[key] == [], f"Expected [] for {key}, got {d[key]!r}"
    # List fields default to empty list
    for key in ("open_problem", "era_collision"):
        assert key in d, f"to_dict() missing key: {key}"
        assert d[key] == [], f"Expected [] for {key}, got {d[key]!r}"
    # Single-dict fields default to None
    for key in ("dark_archetype", "antagonist_archetype"):
        assert key in d, f"to_dict() missing key: {key}"
        assert d[key] is None, f"Expected None for {key}, got {d[key]!r}"


def test_to_dict_includes_new_axes_when_set() -> None:
    """to_dict must carry populated axis values through correctly."""
    fake_conspiracy = _fake_axis("JFK", "Institutions kill.")
    v = _make_full_minimal_vars(conspiracy_engine=[fake_conspiracy])
    score = CompoundScore(
        genius_score=0.8,
        associative_distance=0.4,
        goldilocks_score=0.9,
        sdt_intensity=1.5,
        structural_surprise=0.9,
        compression_score=0.85,
        audience_overlap_M=200.0,
        divisiveness_score=9.0,
        organic_marketing_mult=2.5,
        som_floor_M=500.0,
        passes_500m_gate=True,
        passes_genius_gate=True,
        tam_M=40000.0,
        sam_M=960.0,
        thematic_anchor_score=0.6,
        emotional_universality_score=3.5,
        primary_cluster="emotional",
        cluster_coherence=0.6,
        arc_shape_6="Cinderella",
        cultural_field_alignment=0.5,
    )
    result = CompoundSeedResult(
        run_id="test_001",
        themes=[],
        problems=[],
        variables=v,
        scores=score,
        intersection_premise="test premise",
        hidden_attrs={},
    )
    d = result.to_dict()
    assert d["conspiracy_engine"] == [fake_conspiracy]
    assert d["reptile_trigger"] == []


# ---------------------------------------------------------------------------
# Engine integration — sampling populates new axes
# ---------------------------------------------------------------------------


def test_engine_loads_new_axes_data() -> None:
    """Engine must load all 5 framework/data JSON files without error."""
    engine = CompoundSeedEngine(rng_seed=7)
    assert len(engine._conspiracy) >= 3
    assert len(engine._reptile) >= 3
    assert len(engine._open_problems) >= 3
    assert len(engine._cultural_moments) >= 3
    assert len(engine._dark_archetypes) >= 3


def test_generate_result_dict_has_new_axis_keys() -> None:
    """generate().to_dict() must always include all axis keys including antagonist."""
    engine = CompoundSeedEngine(rng_seed=42)
    result = engine.generate(max_attempts=5)
    d = result.to_dict()
    for key in (
        "conspiracy_engine",
        "reptile_trigger",
        "open_problem",
        "cultural_moment",
        "dark_archetype",
        "antagonist_archetype",
    ):
        assert key in d, f"generate().to_dict() missing key: {key}"


def test_generate_result_hidden_attrs_has_archetype_dynamic() -> None:
    """hidden_attrs must include archetype_dynamic ('mirror' or 'contrast')."""
    engine = CompoundSeedEngine(rng_seed=42)
    result = engine.generate(max_attempts=5)
    assert "archetype_dynamic" in result.hidden_attrs
    assert result.hidden_attrs["archetype_dynamic"] in ("mirror", "contrast")


def test_generate_intersection_premise_is_substantive_when_axes_present() -> None:
    """When axes are sampled the intersection_premise must be non-trivial prose.

    Previously this test checked for literal label strings (e.g. 'Tavistock Institute
    Manipulation') in the premise text.  That worked only in template-fallback mode
    (no API key).  With a live Haiku key the LLM transforms axis labels into narrative
    prose — the raw strings never appear literally.  The correct invariant is that the
    premise is substantive (>= 40 words), not that it echo-prints the raw labels.
    """
    engine = CompoundSeedEngine(rng_seed=99)
    found = False
    for _ in range(10):
        result = engine.generate(max_attempts=3)
        v = result.variables
        has_axes = bool(
            v.conspiracy_engine
            or v.reptile_trigger
            or v.cultural_moment
            or bool(v.open_problem)
            or v.dark_archetype is not None
            or v.antagonist_archetype is not None
        )
        if has_axes:
            premise = result.intersection_premise
            word_count = len(premise.split())
            assert word_count >= 40, (
                f"Premise too short ({word_count} words) — expected >= 40. Snippet: {premise[:200]}"
            )
            found = True
            break
    assert found, "No result with a populated axis was sampled in 10 attempts"
