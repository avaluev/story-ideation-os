"""tests/test_axis_character_depth.py — NB.4 heuristic character-depth axis.

Cycle 1 baseline (no parquet dependency). Quantifies #19/#20/#21/#22/#25/#27.
Replaced by Tier-1-parquet-driven version once S4 lands.
"""

from __future__ import annotations

from typing import Any

import pytest
from pipeline.axes import character_depth


@pytest.fixture
def shallow_concept() -> dict[str, Any]:
    return {
        "slug": "shallow",
        "logline": "A man fights bad guys.",
        "characters": {
            "protagonist": {"name": "He", "want": "win", "need": "win"},
            "antagonist": {"name": None, "belief": None},
        },
    }


@pytest.fixture
def deep_concept() -> dict[str, Any]:
    return {
        "slug": "deep",
        "logline": (
            "A whistleblower public defender named Maya forces a corrupt judge to choose "
            "between her son's freedom and the truth she swore to defend."
        ),
        "characters": {
            "protagonist": {
                "name": "Maya",
                "want": "expose the judge",
                "need": "forgive her father's silence",
                "contradiction": "the system that protects her son is the one she must dismantle",
            },
            "antagonist": {
                "name": "Judge Reed",
                "belief": "law without mercy is the only law that survives",
                "method": "weaponize procedure to make injustice legal",
                "entity_type": "human",
            },
            "key_characters": [{"name": "Father", "function": "moral mirror"}],
        },
    }


def test_module_interface() -> None:
    for name in ("score", "SIGNALS"):
        assert hasattr(character_depth, name)


def test_score_returns_float_in_unit_interval(deep_concept: dict[str, Any]) -> None:
    s, _ = character_depth.score(deep_concept)
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


def test_deep_concept_scores_higher_than_shallow(
    deep_concept: dict[str, Any], shallow_concept: dict[str, Any]
) -> None:
    s_deep, _ = character_depth.score(deep_concept)
    s_shallow, _ = character_depth.score(shallow_concept)
    assert s_deep > s_shallow + 0.3


def test_evidence_lists_named_signals(deep_concept: dict[str, Any]) -> None:
    _, ev = character_depth.score(deep_concept)
    assert "signals" in ev
    expected_signals = {
        "protagonist_named",
        "protagonist_contradiction_present",
        "antagonist_named",
        "antagonist_belief_present",
        "antagonist_method_distinct_from_protagonist_want",
        "key_characters_with_function",
    }
    fired = set(ev["signals"])
    assert expected_signals.issubset(fired), f"missing fired signals: {expected_signals - fired}"


def test_unnamed_antagonist_drops_score(deep_concept: dict[str, Any]) -> None:
    no_name = dict(deep_concept)
    no_name["characters"] = dict(deep_concept["characters"])
    no_name["characters"]["antagonist"] = dict(deep_concept["characters"]["antagonist"])
    no_name["characters"]["antagonist"]["name"] = None
    s_named, _ = character_depth.score(deep_concept)
    s_unnamed, _ = character_depth.score(no_name)
    assert s_unnamed < s_named


def test_non_human_antagonist_recognized() -> None:
    """Issue #25 — entity_type institution/environment/abstract/tech is a valid antagonist."""
    concept = {
        "slug": "the-quota",
        "logline": ("A public defender battles an algorithm that decides who gets representation."),
        "characters": {
            "protagonist": {
                "name": "Sarah",
                "want": "save clients",
                "need": "trust the system again",
            },
            "antagonist": {
                "name": "The Quota Algorithm",
                "belief": "efficiency optimizes justice",
                "entity_type": "technology",
            },
        },
    }
    s, ev = character_depth.score(concept)
    assert s > 0.5
    assert "antagonist_entity_type_non_human" in ev["signals"]


def test_logline_word_count_contributes(deep_concept: dict[str, Any]) -> None:
    """Specificity in logline (named protag, specific stakes) contributes."""
    bland = dict(deep_concept)
    bland["logline"] = "A person does a thing."
    s_specific, _ = character_depth.score(deep_concept)
    s_bland, _ = character_depth.score(bland)
    assert s_specific > s_bland


def test_empty_concept_scores_zero() -> None:
    """Empty input scores 0.0 with no signals fired."""
    s, ev = character_depth.score({})
    assert s == 0.0
    assert ev["signals"] == []


def test_score_is_deterministic(deep_concept: dict[str, Any]) -> None:
    """Two calls return identical scores."""
    s1, ev1 = character_depth.score(deep_concept)
    s2, ev2 = character_depth.score(deep_concept)
    assert s1 == s2
    assert ev1 == ev2
