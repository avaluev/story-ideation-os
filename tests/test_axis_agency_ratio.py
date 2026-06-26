"""tests/test_axis_agency_ratio.py — S4.3 NB-AXIS-AGENCY contract.

The agency-ratio axis is the second Q2 Critical Merit measurement (after
character_depth). It implements the CIE Agency Ratio constraint
(``Active/Passive > 2.0`` → axis pass) by counting curated active verbs vs
copula-based passive constructions in:

- ``concept["logline"]``
- ``concept["characters"]["protagonist"]["want" | "need" | "contradiction"]``

Score formula (per Session 4 prompt §STREAM B / S4.3):
``score = min(1.0, active_count / max(1, passive_count) / 2.0)``

A ratio of 2.0 maps to 1.0; the Cycle-1 threshold (0.50) thus requires a
ratio of at least 1.0. With both Q2 axes wired, ``vector_pass["Q2"]`` is the
``min`` of the two ``axis_pass`` booleans.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline.axes import agency_ratio


@pytest.fixture
def deep_concept() -> dict[str, Any]:
    """Concept whose protagonist drives the action verbs explicitly."""
    return {
        "logline": (
            "A public defender named Maya forces a corrupt judge to choose "
            "between her son's freedom and the truth she swore to defend."
        ),
        "characters": {
            "protagonist": {
                "name": "Maya",
                "want": "expose the judge",
                "need": "forgive her father's silence",
                "contradiction": ("the system that protects her son is the one she must dismantle"),
            },
        },
    }


@pytest.fixture
def shallow_concept() -> dict[str, Any]:
    """Concept whose protagonist is a pronoun chasing a vague verb."""
    return {
        "logline": "A man fights bad guys.",
        "characters": {
            "protagonist": {"name": "He", "want": "win", "need": "win"},
        },
    }


# ── Module surface ──────────────────────────────────────────────────────────


def test_module_interface() -> None:
    assert callable(agency_ratio.score)


# ── Scoring behaviour ───────────────────────────────────────────────────────


def test_active_protagonist_scores_high(deep_concept: dict[str, Any]) -> None:
    """Multiple curated active verbs over the four-text-source span score ≥ 0.7."""
    s, ev = agency_ratio.score(deep_concept)
    assert s >= 0.7, f"deep concept scored {s}; evidence={ev!r}"


def test_passive_protagonist_scores_low(shallow_concept: dict[str, Any]) -> None:
    """Zero curated verbs + zero passive → score 0.0 (CIE Agency Ratio fails)."""
    s, ev = agency_ratio.score(shallow_concept)
    assert s <= 0.3, f"shallow concept scored {s}; evidence={ev!r}"


def test_evidence_lists_verb_categories(deep_concept: dict[str, Any]) -> None:
    """Evidence dict exposes the verb breakdown and ratio for forensic review."""
    _, ev = agency_ratio.score(deep_concept)
    for key in (
        "active_verbs",
        "passive_constructions",
        "active_count",
        "passive_count",
        "ratio",
    ):
        assert key in ev, f"evidence missing key {key!r}; got {ev!r}"
    assert isinstance(ev["active_verbs"], list)
    assert isinstance(ev["passive_constructions"], list)
    assert isinstance(ev["active_count"], int)
    assert isinstance(ev["passive_count"], int)
    assert isinstance(ev["ratio"], float)
    # Verbs found in deep_concept (verified by hand): forces, choose, defend,
    # expose, dismantle — at least 4 of the 9 base verbs must appear.
    assert ev["active_count"] >= 4, (
        f"expected ≥4 curated verbs in deep_concept, found {ev['active_count']}: "
        f"{ev['active_verbs']!r}"
    )


def test_score_is_bounded_zero_to_one() -> None:
    """For any concept, score ∈ [0, 1] even under verb spam."""
    concept = {
        "logline": "force force force force force force force",
        "characters": {"protagonist": {"want": "force force force"}},
    }
    s, _ = agency_ratio.score(concept)
    assert 0.0 <= s <= 1.0


def test_handles_empty_concept() -> None:
    """Empty concept yields score 0.0; never raises."""
    s, ev = agency_ratio.score({})
    assert s == 0.0
    assert ev["active_count"] == 0
    assert ev["passive_count"] == 0


def test_handles_missing_characters_block() -> None:
    """concept without characters block still scores via logline only."""
    s, _ = agency_ratio.score({"logline": "Maya forces the judge to choose."})
    assert s >= 0.5  # 2 active verbs + 0 passive = ratio 2.0 → 1.0 capped


def test_passive_construction_lowers_score() -> None:
    """'Maya is forced to confront' scores lower than 'Maya forces and confronts'."""
    active = {
        "logline": "Maya forces the judge.",
        "characters": {"protagonist": {"name": "Maya", "want": "expose"}},
    }
    passive = {
        "logline": "Maya is forced to confront the judge.",
        "characters": {"protagonist": {"name": "Maya", "want": "win"}},
    }
    s_active, _ = agency_ratio.score(active)
    s_passive, _ = agency_ratio.score(passive)
    assert s_active > s_passive


def test_integrates_into_scorecard_q2(deep_concept: dict[str, Any]) -> None:
    """The scorecard composer must dispatch agency_ratio when evaluating concepts."""
    from pipeline import scorecard as sc  # noqa: PLC0415

    card = sc.compose({}, [])
    result = sc.evaluate(deep_concept, card)
    assert "agency_ratio" in result.axis_scores, (
        f"scorecard.evaluate didn't run agency_ratio axis; "
        f"axes scored: {list(result.axis_scores.keys())!r}"
    )
    assert "agency_ratio" in result.axis_pass
