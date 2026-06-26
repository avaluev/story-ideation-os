"""Tests for pipeline.campaign_goal -- typed loader for config/campaign_goal.json.

Coverage
--------
1. Schema validity: load_campaign_goal() parses config/campaign_goal.json
   into a CampaignGoal without raising.
2. All definition_of_done thresholds present and >= baseline_to_exceed values:
   - verified_density_min >= baseline deep_link_pct (>= 0.80)
   - quote_bound_pct_min  >= baseline quote_bound_pct (>= 0.735)
   - mean_card_grade == "A"
3. Guards: no_gemini is True, exec_model == "sonnet".
4. Frozen dataclass: mutating a field raises FrozenInstanceError.
5. Helper methods return correct derived values.
6. Missing-file raises FileNotFoundError (not a silent fallback).
7. Round-trip: JSON keys survive load without data loss.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pipeline.campaign_goal import (
    CampaignGoal,
    DefinitionOfDone,
    load_campaign_goal,
)

# ---------------------------------------------------------------------------
# Path to the live config (relative to project root = cwd when pytest runs)
# ---------------------------------------------------------------------------
_CONFIG = Path("config/campaign_goal.json")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def goal() -> CampaignGoal:
    """Load the real config/campaign_goal.json once for the whole module."""
    return load_campaign_goal(_CONFIG)


@pytest.fixture()
def minimal_json(tmp_path: Path) -> Path:
    """Write a minimal valid campaign_goal.json for isolated unit tests."""
    data = {
        "campaign": "test-campaign",
        "created": "2026-06-01",
        "description": "test",
        "definition_of_done": {
            "reports": 20,
            "languages": ["EN", "RU"],
            "packaging": "per_concept_files",
            "deep_links_per_report_min": 12,
            "quote_bound_pct_min": 0.90,
            "verified_density_min": 0.85,
            "http_2xx_pct_min": 0.98,
            "mean_card_grade": "A",
            "every_dollar_has_inline_arithmetic": True,
            "fabricated_count_max": 0,
            "en_ru_parity": ["url_set", "dollar_multiset"],
        },
        "baseline_to_exceed": {
            "verified_claims": 109,
            "deep_link_pct": 0.80,
            "quote_bound_pct": 0.735,
            "mean_composite": 75,
        },
        "guards": {
            "make_test": "green",
            "make_eval": "green",
            "lint_imports": ["ANOMALY-001"],
            "webfetch_primary_forbidden": True,
            "openrouter_optional": True,
            "no_gemini": True,
        },
        "budget": {
            "research_max_concurrency": 4,
            "iso_week_cache": True,
            "opus_touch_budget": "minimal",
            "exec_model": "sonnet",
        },
        "concepts": ["01_alpha", "02_beta"],
    }
    p = tmp_path / "campaign_goal.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Schema validity
# ---------------------------------------------------------------------------


def test_load_returns_campaign_goal(goal: CampaignGoal) -> None:
    """load_campaign_goal() returns a CampaignGoal instance."""
    assert isinstance(goal, CampaignGoal)


def test_definition_of_done_is_dataclass(goal: CampaignGoal) -> None:
    assert isinstance(goal.definition_of_done, DefinitionOfDone)


def test_campaign_name_non_empty(goal: CampaignGoal) -> None:
    assert goal.campaign, "campaign field must be non-empty"


def test_concepts_non_empty(goal: CampaignGoal) -> None:
    assert len(goal.concepts) > 0, "concepts list must not be empty"


def test_concepts_count(goal: CampaignGoal) -> None:
    """The live config declares exactly 20 concepts."""
    assert len(goal.concepts) == 20


# ---------------------------------------------------------------------------
# 2. Definition-of-done thresholds >= baseline_to_exceed values
# ---------------------------------------------------------------------------


def test_deep_link_threshold_meets_baseline(goal: CampaignGoal) -> None:
    """verified_density_min >= baseline deep_link_pct (>= 0.80)."""
    assert goal.definition_of_done.verified_density_min >= 0.80, (
        f"verified_density_min={goal.definition_of_done.verified_density_min} "
        "must be >= 0.80 (ADR-0011 / campaign baseline)"
    )


def test_deep_link_threshold_exceeds_baseline_value(goal: CampaignGoal) -> None:
    """DoD deep-link target must be >= the baseline_to_exceed.deep_link_pct."""
    assert goal.definition_of_done.verified_density_min >= goal.baseline_to_exceed.deep_link_pct, (
        f"verified_density_min={goal.definition_of_done.verified_density_min} "
        f"must be >= baseline deep_link_pct={goal.baseline_to_exceed.deep_link_pct}"
    )


def test_quote_threshold_meets_baseline(goal: CampaignGoal) -> None:
    """quote_bound_pct_min >= baseline quote_bound_pct (>= 0.735)."""
    assert goal.definition_of_done.quote_bound_pct_min >= 0.735, (
        f"quote_bound_pct_min={goal.definition_of_done.quote_bound_pct_min} "
        "must be >= 0.735 (campaign baseline)"
    )


def test_quote_threshold_exceeds_baseline_value(goal: CampaignGoal) -> None:
    """DoD quote target must be >= the baseline_to_exceed.quote_bound_pct."""
    assert goal.definition_of_done.quote_bound_pct_min >= goal.baseline_to_exceed.quote_bound_pct, (
        f"quote_bound_pct_min={goal.definition_of_done.quote_bound_pct_min} "
        f"must be >= baseline quote_bound_pct={goal.baseline_to_exceed.quote_bound_pct}"
    )


def test_mean_card_grade_is_A(goal: CampaignGoal) -> None:
    """mean_card_grade must be 'A' (composite target grade)."""
    assert goal.definition_of_done.mean_card_grade == "A", (
        f"mean_card_grade={goal.definition_of_done.mean_card_grade!r} must be 'A'"
    )


def test_fabricated_count_max_is_zero(goal: CampaignGoal) -> None:
    """Zero fabricated claims are allowed."""
    assert goal.definition_of_done.fabricated_count_max == 0


def test_fabrication_not_allowed(goal: CampaignGoal) -> None:
    """Helper fabrication_allowed() returns False."""
    assert goal.fabrication_allowed() is False


def test_baseline_deep_link_is_80(goal: CampaignGoal) -> None:
    """Baseline deep_link_pct must be exactly 0.80."""
    assert goal.baseline_to_exceed.deep_link_pct == 0.80


def test_baseline_quote_is_735(goal: CampaignGoal) -> None:
    """Baseline quote_bound_pct must be exactly 0.735."""
    assert goal.baseline_to_exceed.quote_bound_pct == 0.735


def test_baseline_mean_composite_is_75(goal: CampaignGoal) -> None:
    """Baseline mean_composite must be 75."""
    assert goal.baseline_to_exceed.mean_composite == 75


# ---------------------------------------------------------------------------
# 3. Guards: no_gemini and exec_model
# ---------------------------------------------------------------------------


def test_no_gemini_guard_is_true(goal: CampaignGoal) -> None:
    """guards.no_gemini must be True."""
    assert goal.guards.no_gemini is True


def test_no_gemini_helper(goal: CampaignGoal) -> None:
    """Helper no_gemini_guard() returns True."""
    assert goal.no_gemini_guard() is True


def test_exec_model_is_sonnet(goal: CampaignGoal) -> None:
    """budget.exec_model must be 'sonnet'."""
    assert goal.budget.exec_model == "sonnet"


def test_exec_model_helper(goal: CampaignGoal) -> None:
    """Helper exec_model() returns 'sonnet'."""
    assert goal.exec_model() == "sonnet"


# ---------------------------------------------------------------------------
# 4. Frozen dataclass immutability
# ---------------------------------------------------------------------------


def test_campaign_goal_is_frozen(tmp_path: Path) -> None:
    """CampaignGoal is a frozen dataclass -- normal assignment must raise."""
    g = load_campaign_goal(_CONFIG)
    with pytest.raises((FrozenInstanceError, AttributeError)):
        g.campaign = "hacked"  # type: ignore[misc]


def test_definition_of_done_is_frozen(tmp_path: Path) -> None:
    """DefinitionOfDone is a frozen dataclass -- normal assignment must raise."""
    g = load_campaign_goal(_CONFIG)
    with pytest.raises((FrozenInstanceError, AttributeError)):
        g.definition_of_done.mean_card_grade = "B"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. Helper methods
# ---------------------------------------------------------------------------


def test_deep_link_threshold_helper(goal: CampaignGoal) -> None:
    assert goal.deep_link_threshold() == goal.definition_of_done.verified_density_min


def test_quote_threshold_helper(goal: CampaignGoal) -> None:
    assert goal.quote_threshold() == goal.definition_of_done.quote_bound_pct_min


def test_mean_grade_target_helper(goal: CampaignGoal) -> None:
    assert goal.mean_grade_target() == "A"


def test_beats_baseline_deep_link_true(goal: CampaignGoal) -> None:
    """A score of 1.0 beats the 0.80 baseline."""
    assert goal.beats_baseline_deep_link(1.0) is True


def test_beats_baseline_deep_link_false(goal: CampaignGoal) -> None:
    """A score equal to baseline does NOT beat it (strictly greater)."""
    assert goal.beats_baseline_deep_link(goal.baseline_to_exceed.deep_link_pct) is False


def test_beats_baseline_quote_true(goal: CampaignGoal) -> None:
    assert goal.beats_baseline_quote(1.0) is True


def test_beats_baseline_quote_false(goal: CampaignGoal) -> None:
    assert goal.beats_baseline_quote(goal.baseline_to_exceed.quote_bound_pct) is False


def test_beats_baseline_composite_true(goal: CampaignGoal) -> None:
    assert goal.beats_baseline_composite(76.0) is True


def test_beats_baseline_composite_false(goal: CampaignGoal) -> None:
    assert goal.beats_baseline_composite(75.0) is False


# ---------------------------------------------------------------------------
# 6. Missing-file raises, not silent fallback
# ---------------------------------------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """load_campaign_goal raises FileNotFoundError for missing path."""
    with pytest.raises(FileNotFoundError):
        load_campaign_goal(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# 7. Round-trip: all top-level keys survive load
# ---------------------------------------------------------------------------


def test_round_trip_minimal(minimal_json: Path) -> None:
    """Minimal JSON round-trips without data loss."""
    g = load_campaign_goal(minimal_json)
    assert g.campaign == "test-campaign"
    assert g.definition_of_done.reports == 20
    assert g.definition_of_done.mean_card_grade == "A"
    assert g.guards.no_gemini is True
    assert g.budget.exec_model == "sonnet"
    assert g.concepts == ("01_alpha", "02_beta")


def test_round_trip_languages(minimal_json: Path) -> None:
    g = load_campaign_goal(minimal_json)
    assert "EN" in g.definition_of_done.languages
    assert "RU" in g.definition_of_done.languages


def test_round_trip_lint_imports(minimal_json: Path) -> None:
    g = load_campaign_goal(minimal_json)
    assert "ANOMALY-001" in g.guards.lint_imports


def test_round_trip_en_ru_parity(minimal_json: Path) -> None:
    g = load_campaign_goal(minimal_json)
    assert "url_set" in g.definition_of_done.en_ru_parity
