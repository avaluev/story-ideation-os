"""Tests for pipeline/schema.py — Pydantic v2 phase output models.

Covers PIPE-01: total_score guard, source_quote word-count validator,
ISO2 country pattern, round-trip serialization for all 5 phase models.

TDD: these tests are written before schema.py exists (RED phase).
They go GREEN in Task 3 when pipeline/schema.py is created.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

# Allow test file to be collected even before schema.py exists.
# After schema.py lands in Task 3, all tests must pass (GREEN).
pipeline_schema = pytest.importorskip("pipeline.schema")

Phase1Assets = pipeline_schema.Phase1Assets
Phase2JTBD = pipeline_schema.Phase2JTBD
Phase3Audience = pipeline_schema.Phase3Audience
Phase4Concept = pipeline_schema.Phase4Concept
Phase5Critique = pipeline_schema.Phase5Critique


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_valid_critique() -> dict:
    """Return a valid Phase5Critique dict with total_score=None (valid LLM output)."""
    return {
        "concept_id": "test-concept-001",
        "novelty_score": 20,
        "jtbd_score": 18,
        "contradiction_score": 19,
        "specificity_score": 17,
        "cap_at_70_triggered": False,
        "ten_school_self_check": [True] * 10,
        "stabilization_pattern_to_add_to_anti_slop": None,
        "total_score": None,  # MUST be None in LLM output
    }


def _make_valid_assets() -> dict:
    """Return a valid Phase1Assets dict."""
    return {
        "asset_id": "asset-001",
        "asset_name": "Al-Bukhari Hadith Collection",
        "domain": "religious-scholarship",
        "theme": "knowledge-preservation",
        "source_url": "https://example.com/source",
        "source_quote": "Memory of scholars must survive",  # 6 words — ≤14
        "untapped_check_passed": True,
        "produced_at": "2026-05-07T08:00:00Z",
        "session_id": "session-001",
    }


def _make_valid_jtbd() -> dict:
    """Return a valid Phase2JTBD dict."""
    return {
        "asset_id": "asset-001",
        "job_statement": "When I fear knowledge will be lost, I want to preserve it",
        "primary_need": "autonomy",
        "primary_strength": 0.85,
        "secondary_need": "relatedness",
        "secondary_strength": 0.6,
        "deprivation_amplifier_active": True,
        "jtbd_notes": "",
    }


def _make_valid_audience() -> dict:
    """Return a valid Phase3Audience dict."""
    return {
        "asset_id": "asset-001",
        "target_countries": ["US", "GB", "RU"],
        "cited_audience": 250_000_000,
        "sources_per_claim": 2,
        "trend_direction": "rising",
        "primary_jtbd_strength": 0.85,
        "source_quote": "Growing interest in Islamic history",  # 5 words — ≤14
        "produced_at": "2026-05-07T08:00:00Z",
        "session_id": "session-001",
    }


def _make_valid_concept() -> dict:
    """Return a valid Phase4Concept dict."""
    return {
        "concept_id": "concept-001",
        "title": "The Last Compiler",
        "logline": "A disgraced archivist must decode a dying scholar's encrypted memories",
        "polti_id": 12,
        "tobias_id": 7,
        "seed_used": 42,
        "seed_increments": 0,
        "forge_meta": {"model": "anthropic/claude-sonnet-4.6", "k": 3},
        "produced_at": "2026-05-07T08:00:00Z",
        "session_id": "session-001",
    }


# ── Test 1: total_score=96 in LLM output raises ValueError ───────────────────


def test_phase5_critique_raises_on_nonzero_total_score() -> None:
    """Phase5Critique with total_score=96 in LLM output must raise ValueError."""
    data = _make_valid_critique()
    data["total_score"] = 96  # LLM populating total_score is a violation

    with pytest.raises(Exception) as exc_info:
        Phase5Critique.model_validate(data)

    assert "total_score" in str(exc_info.value).lower()


# ── Test 2: total_score=0 in LLM output also raises ValueError ───────────────


def test_phase5_critique_raises_on_zero_total_score() -> None:
    """Phase5Critique with total_score=0 in LLM output must also raise.

    0 is non-None — any non-None value from an LLM is wrong.
    """
    data = _make_valid_critique()
    data["total_score"] = 0  # 0 is non-None, still a violation

    with pytest.raises(Exception) as exc_info:
        Phase5Critique.model_validate(data)

    assert "total_score" in str(exc_info.value).lower()


# ── Test 3: model_copy bypass succeeds ───────────────────────────────────────


def test_phase5_critique_model_copy_sets_total_score() -> None:
    """model_copy(update={'total_score': 96.0}) bypasses validator — this is the
    only safe setter path for scoring.py (ADR-0002 + Pydantic v2 design).
    """
    critique = Phase5Critique.model_validate(_make_valid_critique())
    assert critique.total_score is None  # starts None

    scored = critique.model_copy(update={"total_score": 96.0})

    assert scored.total_score == 96.0
    assert critique.total_score is None  # original unchanged (immutable)


# ── Test 4: source_quote word-count validator ─────────────────────────────────


def test_source_quote_length_validator() -> None:
    """source_quote with 15 words raises ValueError; 14 words passes."""
    # 15 words — should FAIL
    fifteen_words = (
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    )
    assert len(fifteen_words.split()) == 15

    data_bad = _make_valid_assets()
    data_bad["source_quote"] = fifteen_words

    with pytest.raises(ValueError):
        Phase1Assets.model_validate(data_bad)

    # 14 words — should PASS
    fourteen_words = (
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    )
    assert len(fourteen_words.split()) == 14

    data_good = _make_valid_assets()
    data_good["source_quote"] = fourteen_words

    asset = Phase1Assets.model_validate(data_good)
    assert asset.source_quote == fourteen_words


# ── Test 5: ISO2 country code validator ──────────────────────────────────────


def test_iso2_country_code_validator_passes_valid_codes() -> None:
    """Phase3Audience target_countries=["US", "GB", "RU"] passes validation."""
    audience = Phase3Audience.model_validate(_make_valid_audience())
    assert audience.target_countries == ["US", "GB", "RU"]


def test_iso2_country_code_validator_rejects_invalid_code() -> None:
    """Phase3Audience target_countries=["USA"] raises ValueError (3-letter code)."""
    data = _make_valid_audience()
    data["target_countries"] = ["USA"]  # 3 letters — not ISO2

    with pytest.raises(Exception) as exc_info:
        Phase3Audience.model_validate(data)

    assert (
        "usa" in str(exc_info.value).lower()
        or "iso" in str(exc_info.value).lower()
        or "target_countries" in str(exc_info.value).lower()
    )


# ── Test 6: Round-trip JSON serialization for all 5 phase models ──────────────


@pytest.mark.parametrize(
    "model_cls, valid_data_fn",
    [
        (Phase1Assets, _make_valid_assets),
        (Phase2JTBD, _make_valid_jtbd),
        (Phase3Audience, _make_valid_audience),
        (Phase4Concept, _make_valid_concept),
        (Phase5Critique, _make_valid_critique),
    ],
    ids=["Phase1Assets", "Phase2JTBD", "Phase3Audience", "Phase4Concept", "Phase5Critique"],
)
def test_round_trip_serialization(model_cls: type, valid_data_fn: object) -> None:
    """Round-trip: dict → validate → model_dump → json.dumps → json.loads → validate."""
    original_data = valid_data_fn()  # type: ignore[operator]
    model = model_cls.model_validate(original_data)

    # Serialize to JSON string and back
    json_str = model.model_dump_json()
    parsed = json.loads(json_str)

    # Re-validate from JSON round-trip
    model2 = model_cls.model_validate(parsed)

    # The second model should have the same total_score state
    assert model2.model_dump() == model.model_dump()


# ── Test 7: Phase1Assets required fields ──────────────────────────────────────


def test_phase1_assets_required_fields() -> None:
    """Phase1Assets requires at least: asset_id (str), asset_name (str), domain (str)."""
    data = _make_valid_assets()
    asset = Phase1Assets.model_validate(data)

    assert isinstance(asset.asset_id, str)
    assert isinstance(asset.asset_name, str)
    assert isinstance(asset.domain, str)
    assert asset.asset_id == "asset-001"
    assert asset.asset_name == "Al-Bukhari Hadith Collection"
    assert asset.domain == "religious-scholarship"


def test_phase1_assets_missing_required_field_raises() -> None:
    """Phase1Assets raises ValidationError when asset_id is missing."""

    data = _make_valid_assets()
    del data["asset_id"]

    with pytest.raises(ValidationError):
        Phase1Assets.model_validate(data)


# ── Test 8: Phase2JTBD required fields ───────────────────────────────────────


def test_phase2_jtbd_required_fields() -> None:
    """Phase2JTBD requires: job_statement, primary_need, primary_strength (0.0-1.0)."""
    data = _make_valid_jtbd()
    jtbd = Phase2JTBD.model_validate(data)

    assert isinstance(jtbd.job_statement, str)
    assert jtbd.primary_need in ("autonomy", "competence", "relatedness")
    assert 0.0 <= jtbd.primary_strength <= 1.0


def test_phase2_jtbd_primary_strength_out_of_range_raises() -> None:
    """Phase2JTBD raises ValidationError when primary_strength > 1.0."""

    data = _make_valid_jtbd()
    data["primary_strength"] = 1.5  # out of range

    with pytest.raises(ValidationError):
        Phase2JTBD.model_validate(data)


def test_phase2_jtbd_invalid_primary_need_raises() -> None:
    """Phase2JTBD raises ValidationError when primary_need is not a valid Literal."""

    data = _make_valid_jtbd()
    data["primary_need"] = "dominance"  # not in Literal

    with pytest.raises(ValidationError):
        Phase2JTBD.model_validate(data)


# ── V4A-003e — Phase4Concept v4 fields (mutation_provenance + closing_image) ──


def test_phase4_concept_both_v4_fields_null_is_v3_backward_compat() -> None:
    """V4A-003e backward-compat: a Phase4Concept with mutation_provenance=None
    AND closing_image=None must validate cleanly (the 1067 v3.1 outputs all
    leave both fields null and continue producing 12-section A4 docs)."""
    data = _make_valid_concept()
    # Both v4 fields default to None — do not set them.
    concept = Phase4Concept.model_validate(data)
    assert concept.mutation_provenance is None
    assert concept.closing_image is None


def test_phase4_concept_v4_mutation_provenance_canonical_op_passes() -> None:
    """A valid mutation_provenance dict with canonical op + non-empty parents
    list must pass validation."""
    data = _make_valid_concept()
    data["mutation_provenance"] = {
        "op": "SWAP",
        "parents": ["c-parent-1", "c-parent-2"],
    }
    concept = Phase4Concept.model_validate(data)
    assert concept.mutation_provenance is not None
    assert concept.mutation_provenance["op"] == "SWAP"


def test_phase4_concept_v4_mutation_provenance_invalid_op_raises() -> None:
    """mutation_provenance.op outside the 6-op canonical set must raise."""
    data = _make_valid_concept()
    data["mutation_provenance"] = {
        "op": "NOT_A_REAL_OP",
        "parents": ["c-parent-1"],
    }
    with pytest.raises(ValidationError) as exc_info:
        Phase4Concept.model_validate(data)
    assert "must be in" in str(exc_info.value)


def test_phase4_concept_v4_mutation_provenance_empty_parents_raises() -> None:
    """mutation_provenance.parents MUST be a non-empty list/tuple."""
    data = _make_valid_concept()
    data["mutation_provenance"] = {"op": "INVERT", "parents": []}
    with pytest.raises(ValidationError) as exc_info:
        Phase4Concept.model_validate(data)
    assert "non-empty" in str(exc_info.value)


def test_phase4_concept_v4_closing_image_under_30_words_passes() -> None:
    """closing_image at the 30-word ceiling must validate (boundary case)."""
    data = _make_valid_concept()
    data["closing_image"] = " ".join(["word"] * 30)
    concept = Phase4Concept.model_validate(data)
    assert concept.closing_image is not None


def test_phase4_concept_v4_closing_image_over_30_words_raises() -> None:
    """closing_image with 31 words MUST raise; v4 spec caps at 30."""
    data = _make_valid_concept()
    data["closing_image"] = " ".join(["word"] * 31)
    with pytest.raises(ValidationError) as exc_info:
        Phase4Concept.model_validate(data)
    assert "≤30 words" in str(exc_info.value) or "<=30" in str(exc_info.value)
