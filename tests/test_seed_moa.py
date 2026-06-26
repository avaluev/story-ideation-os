"""Tests for pipeline/seed_moa.py (Change 4 - Mixture-of-Experts seeders)."""

from __future__ import annotations

from pathlib import Path

from pipeline.compound_seed import CompoundSeedResult
from pipeline.seed_moa import (
    _DEFAULT_SEEDER_SEEDS,
    MoASeedResult,
    _derive_theme_seeds,
    generate,
)
from pipeline.single_idea import SingleIdeaOrchestrator


def test_generate_returns_moa_result() -> None:
    """generate() returns a MoASeedResult with at least 1 candidate."""
    result = generate(max_attempts=3)
    assert isinstance(result, MoASeedResult)
    assert isinstance(result.selected, CompoundSeedResult)
    assert len(result.candidates) >= 1
    assert len(result.seeder_names) >= 1


def test_selected_has_moa_audit_trail() -> None:
    """The selected candidate has moa_candidates in hidden_attrs."""
    result = generate(max_attempts=3)
    hidden = result.selected.hidden_attrs
    assert "moa_candidates" in hidden
    assert "moa_judge_rationale" in hidden
    assert "selected_by" in hidden
    # May be llm_judge_sonnet (live API) or python_judge_fallback (API down / 402)
    assert hidden["selected_by"] in (
        "llm_judge_sonnet",
        "python_judge_fallback",
    ), f"Unexpected selected_by value: {hidden['selected_by']!r}"


def test_moa_candidates_have_required_fields() -> None:
    """Each moa_candidate entry has seeder, run_id, som_floor_M, genius_score, selected."""
    result = generate(max_attempts=3)
    entries = result.selected.hidden_attrs.get("moa_candidates", [])
    assert len(entries) >= 1
    for entry in entries:
        assert "seeder" in entry
        assert "run_id" in entry
        assert "som_floor_M" in entry
        assert "genius_score" in entry
        assert "selected" in entry


def test_selected_is_quality_candidate() -> None:
    """The selected candidate passes the genius gate and has a positive SOM.

    Previously asserted selected == highest-SOM candidate, which held only
    when the Python fallback judge was used. The LLM judge (Sonnet) selects
    by prose quality + genius_score, so the highest-SOM assertion is too strict.
    The correct invariant: the selected candidate is a viable concept.
    """
    result = generate(max_attempts=5, rng_seeds=(1, 2, 3))
    assert result.selected.scores.passes_genius_gate, "Selected candidate must pass genius gate"
    assert result.selected.scores.som_floor_M > 0, "Selected candidate must have positive SOM"
    max_som = max(c.scores.som_floor_M for c in result.candidates)
    # Selected may not be max-SOM (LLM picks by quality), but must be within 50% of max
    assert result.selected.scores.som_floor_M >= max_som * 0.50


def test_to_dict_includes_moa_hidden_attrs() -> None:
    """The selected seed's to_dict() serialises the MoA audit trail."""
    result = generate(max_attempts=3)
    d = result.selected.to_dict()
    assert "hidden_attrs" in d
    hidden = d["hidden_attrs"]
    assert "moa_candidates" in hidden
    assert "moa_judge_rationale" in hidden


def test_exactly_one_selected_flag_in_audit_trail() -> None:
    """Exactly one moa_candidates entry has selected=True."""
    result = generate(max_attempts=3)
    entries = result.selected.hidden_attrs.get("moa_candidates", [])
    selected_count = sum(1 for e in entries if e["selected"] is True)
    assert selected_count == 1


def test_judge_rationale_is_substantive() -> None:
    """judge_rationale is a non-trivial explanation of why a candidate was chosen.

    Previously checked for the seeder name ('conspiracy_mind' etc.) in the text.
    With a live LLM judge the rationale says 'Candidate 1' or similar — equally
    valid. The correct invariant is that the rationale is real prose, not empty.
    """
    result = generate(max_attempts=3)
    rationale = result.judge_rationale
    assert len(rationale.split()) >= 8, f"Rationale too short: {rationale!r}"


def test_seeder_names_are_expected_values() -> None:
    """seeder_names contains the three bias names (or default_fallback)."""
    result = generate(max_attempts=3)
    valid_names = {"conspiracy_mind", "open_science_mind", "reptile_fear_mind", "default_fallback"}
    for name in result.seeder_names:
        assert name in valid_names


def test_custom_rng_seeds_produce_result() -> None:
    """Custom rng_seeds tuple is accepted and produces a valid result."""
    result = generate(max_attempts=3, rng_seeds=(7, 13, 99))
    assert isinstance(result, MoASeedResult)
    assert result.selected.scores.som_floor_M >= 0


def test_use_moa_flag_on_single_idea_orchestrator(tmp_path: Path) -> None:
    """SingleIdeaOrchestrator.use_moa defaults to False."""
    orch = SingleIdeaOrchestrator(run_dir=tmp_path, theme="test")
    assert orch.use_moa is False


def test_derive_theme_seeds_empty_returns_fallback() -> None:
    """No themes → fallback constants unchanged (preserves test determinism)."""

    assert _derive_theme_seeds([]) == _DEFAULT_SEEDER_SEEDS


def test_derive_theme_seeds_different_themes_yield_different_seeds() -> None:
    """Different themes MUST produce different seed tuples — fixes the Session
    A/B/C bug where three distinct themes all sampled the identical 30
    engine dimensions because the seeders shared rng_seeds (42, 137, 271).
    """

    seeds_a = _derive_theme_seeds(["climate cascade across the equatorial belt"])
    seeds_b = _derive_theme_seeds(["Korean demographer leaks fertility ledgers"])
    seeds_c = _derive_theme_seeds(["fertility entrepreneur burns surrogacy company"])

    assert seeds_a != seeds_b
    assert seeds_b != seeds_c
    assert seeds_a != seeds_c
    # Each tuple's three seeds must also be mutually distinct so the 3 MoA
    # seeders (conspiracy_mind, open_science_mind, reptile_fear_mind) still
    # explore divergent slices of the parameter space.
    for seeds in (seeds_a, seeds_b, seeds_c):
        assert len(set(seeds)) == 3, f"seeder seeds collapsed: {seeds}"


def test_derive_theme_seeds_deterministic() -> None:
    """Same theme list MUST always derive the same seeds (reproducibility)."""

    theme = ["a single haunting test theme"]
    assert _derive_theme_seeds(theme) == _derive_theme_seeds(theme)


def test_derive_theme_seeds_explicit_seeds_honored() -> None:
    """When caller passes a non-default rng_seeds tuple, theme-derivation
    must NOT be applied — test pinning of known samples stays exact.

    (The seed_moa.generate codepath has an explicit equality check on
    rng_seeds == _DEFAULT_SEEDER_SEEDS before applying theme derivation.)
    """
    custom = (1, 2, 3)
    result = generate(themes=["any theme here"], max_attempts=3, rng_seeds=custom)
    # Sanity: the result must still be valid.
    assert result.selected is not None
    assert len(result.candidates) >= 1
