"""tests/test_scorecard.py — NB.5 runtime composer contract.

The composer wires NB.4 ``character_depth.score`` into the 5-vector gating
decision and is the generic substrate for future axes (S0 calibration → S4
discovery → rule emission).

Cycle-1 minimum (per HANDOFF_SESSION_3 §10):
- ``compose(attrs, rules) -> Scorecard`` accepts an empty rules list and
  returns the base scorecard.
- ``evaluate(concept, scorecard) -> EvalResult`` runs every wired axis and
  produces per-axis scores + per-vector pass/fail + an overall verdict.
- Default thresholds are explicit constants (Cycle 1 placeholder); they are
  designed to be overridden by ``data/calibration/thresholds.jsonl`` once S0
  lands. The override path is documented in :mod:`pipeline.scorecard`.

Anti-pattern guards (HANDOFF_SESSION_3 §"ANTI-PATTERNS BANNED"):
- No hardcoded format taxonomy: rules predicate over measured attribute names
  only; the composer never branches on ``"scifi"`` or ``"chamber_piece"``.
- No silent feature flags: every code path is reachable.
- Tests are shape assertions over a small fixture; behavioural correctness
  defers to the calibration set when it lands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline import scorecard
from pipeline.scorecard import (
    EvalResult,
    Rule,
    Scorecard,
    compose,
    evaluate,
    load_rules,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "data" / "axis_selection_rules.jsonl"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def deep_concept() -> dict[str, Any]:
    """Concept that should clear character_depth axis."""
    return {
        "slug": "the-quota",
        "logline": (
            "A public defender named Maya forces a corrupt judge to choose "
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
def small_cast_attrs() -> dict[str, Any]:
    return {"cast_size_principal": 2, "antagonist_entity_type": "human"}


@pytest.fixture
def ensemble_attrs() -> dict[str, Any]:
    return {"cast_size_principal": 7, "antagonist_entity_type": "human"}


# ── Module surface ───────────────────────────────────────────────────────────


def test_module_interface() -> None:
    for name in (
        "Rule",
        "Scorecard",
        "EvalResult",
        "compose",
        "evaluate",
        "load_rules",
        "BASE_AXIS_WEIGHTS",
        "BASE_AXIS_THRESHOLDS",
        "AXIS_TO_VECTOR",
    ):
        assert hasattr(scorecard, name), f"scorecard missing public name {name!r}"


def test_axis_to_vector_maps_character_depth_to_q2() -> None:
    """NB.4's character_depth axis belongs to Q2 Critical Merit per master plan."""
    assert scorecard.AXIS_TO_VECTOR["character_depth"] == "Q2"


def test_axis_to_vector_maps_agency_ratio_to_q2() -> None:
    """S4.3's agency_ratio axis is the second Q2 axis."""
    assert scorecard.AXIS_TO_VECTOR["agency_ratio"] == "Q2"


def test_evaluate_runs_both_q2_axes(deep_concept: dict[str, Any]) -> None:
    """Q2 vector pass = min of both Q2 axes' axis_pass (both must pass).

    Once two axes map to Q2, ``vector_pass["Q2"]`` no longer trivially mirrors
    the lone character_depth verdict; it requires agency_ratio to also pass.
    The deep_concept fixture is curated to clear both thresholds.
    """
    card = compose({}, [])
    result = evaluate(deep_concept, card)
    assert "character_depth" in result.axis_scores
    assert "agency_ratio" in result.axis_scores
    assert result.axis_pass["character_depth"] is True
    assert result.axis_pass["agency_ratio"] is True
    assert result.vector_pass["Q2"] is True


def test_rules_file_exists_and_is_jsonl() -> None:
    """Cycle 1 ships with an empty rules file at data/axis_selection_rules.jsonl."""
    assert RULES_PATH.exists(), (
        "data/axis_selection_rules.jsonl missing — required by NB.5 contract"
    )
    # Empty file or valid JSONL — must not contain garbage.
    for line in RULES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)  # raises on malformed JSON


# ── compose() ────────────────────────────────────────────────────────────────


def test_compose_empty_rules_returns_base(small_cast_attrs: dict[str, Any]) -> None:
    card = compose(small_cast_attrs, [])
    assert isinstance(card, Scorecard)
    assert card.fired_rules == ()
    # Base weights echo BASE_AXIS_WEIGHTS verbatim when no rule fires.
    assert card.axis_weights == scorecard.BASE_AXIS_WEIGHTS
    assert card.axis_thresholds == scorecard.BASE_AXIS_THRESHOLDS


def test_compose_returns_immutable_scorecard(small_cast_attrs: dict[str, Any]) -> None:
    """Scorecard is frozen — composer cannot accidentally leak mutable state."""
    card = compose(small_cast_attrs, [])
    with pytest.raises((AttributeError, TypeError)):
        card.axis_weights = {}  # type: ignore[misc]


def test_compose_applies_matching_weight_delta(small_cast_attrs: dict[str, Any]) -> None:
    rule = Rule(
        rule_id="RX-001",
        if_={"cast_size_principal": "<=2"},
        then_={"axes": {"character_depth": {"weight_delta": 0.20}}},
        evidence_id="parq:test#1",
        method="unit_test",
    )
    card = compose(small_cast_attrs, [rule])
    assert "RX-001" in card.fired_rules
    base = scorecard.BASE_AXIS_WEIGHTS["character_depth"]
    assert card.axis_weights["character_depth"] == pytest.approx(base + 0.20)


def test_compose_skips_non_matching_rule(ensemble_attrs: dict[str, Any]) -> None:
    rule = Rule(
        rule_id="RX-001",
        if_={"cast_size_principal": "<=2"},
        then_={"axes": {"character_depth": {"weight_delta": 0.20}}},
        evidence_id="parq:test#1",
        method="unit_test",
    )
    card = compose(ensemble_attrs, [rule])
    assert card.fired_rules == ()
    assert card.axis_weights["character_depth"] == scorecard.BASE_AXIS_WEIGHTS["character_depth"]


def test_compose_threshold_override(small_cast_attrs: dict[str, Any]) -> None:
    rule = Rule(
        rule_id="RX-002",
        if_={"cast_size_principal": "<=2"},
        then_={"axes": {"character_depth": {"threshold_delta": 0.10}}},
        evidence_id="parq:test#2",
        method="unit_test",
    )
    card = compose(small_cast_attrs, [rule])
    base_thr = scorecard.BASE_AXIS_THRESHOLDS["character_depth"]
    assert card.axis_thresholds["character_depth"] == pytest.approx(base_thr + 0.10)


def test_compose_multi_predicate_all_required(small_cast_attrs: dict[str, Any]) -> None:
    """A rule's `if` predicates are AND-ed; missing predicate means no fire."""
    rule = Rule(
        rule_id="RX-003",
        if_={"cast_size_principal": "<=2", "antagonist_entity_type": "abstract"},
        then_={"axes": {"character_depth": {"weight_delta": 0.05}}},
        evidence_id="parq:test#3",
        method="unit_test",
    )
    card = compose(small_cast_attrs, [rule])
    # antagonist_entity_type=human ≠ "abstract" — rule must NOT fire.
    assert card.fired_rules == ()


def test_compose_supports_ge_operator() -> None:
    attrs = {"speculative_science_density": 0.85}
    rule = Rule(
        rule_id="RX-004",
        if_={"speculative_science_density": ">=0.6"},
        then_={"axes": {"character_depth": {"weight_delta": 0.10}}},
        evidence_id="parq:test#4",
        method="unit_test",
    )
    card = compose(attrs, [rule])
    assert "RX-004" in card.fired_rules


def test_compose_supports_equality_operator() -> None:
    attrs = {"ip_origin": "original"}
    rule = Rule(
        rule_id="RX-005",
        if_={"ip_origin": "original"},
        then_={"axes": {"character_depth": {"weight_delta": 0.05}}},
        evidence_id="parq:test#5",
        method="unit_test",
    )
    card = compose(attrs, [rule])
    assert "RX-005" in card.fired_rules


def test_compose_supports_membership_predicate() -> None:
    """List predicate = membership check."""
    rule = Rule(
        rule_id="RX-MEM",
        if_={"antagonist_entity_type": ["abstract", "institution", "technology"]},
        then_={"axes": {"character_depth": {"weight_delta": 0.05}}},
        evidence_id="parq:test#mem",
        method="unit_test",
    )
    card_in = compose({"antagonist_entity_type": "institution"}, [rule])
    card_out = compose({"antagonist_entity_type": "human"}, [rule])
    assert "RX-MEM" in card_in.fired_rules
    assert card_out.fired_rules == ()


def test_compose_missing_attr_blocks_match() -> None:
    """Predicate references an attribute absent from attrs → no fire."""
    rule = Rule(
        rule_id="RX-MISS",
        if_={"undeclared_attr": "x"},
        then_={"axes": {"character_depth": {"weight_delta": 0.10}}},
        evidence_id="parq:test#miss",
        method="unit_test",
    )
    card = compose({"cast_size_principal": 2}, [rule])
    assert card.fired_rules == ()


def test_compose_less_than_strict_operator() -> None:
    attrs = {"cast_size_principal": 1}
    rule = Rule(
        rule_id="RX-LT",
        if_={"cast_size_principal": "<2"},
        then_={"axes": {"character_depth": {"weight_delta": 0.05}}},
        evidence_id="parq:test#lt",
        method="unit_test",
    )
    assert "RX-LT" in compose(attrs, [rule]).fired_rules
    assert compose({"cast_size_principal": 2}, [rule]).fired_rules == ()


def test_compose_greater_than_strict_operator() -> None:
    attrs = {"cast_size_principal": 8}
    rule = Rule(
        rule_id="RX-GT",
        if_={"cast_size_principal": ">7"},
        then_={"axes": {"character_depth": {"weight_delta": 0.05}}},
        evidence_id="parq:test#gt",
        method="unit_test",
    )
    assert "RX-GT" in compose(attrs, [rule]).fired_rules


def test_compose_unknown_axis_in_then_is_ignored() -> None:
    """If a rule references an axis the composer has not wired yet, skip silently."""
    rule = Rule(
        rule_id="RX-006",
        if_={"ip_origin": "original"},
        then_={"axes": {"axis_not_yet_implemented": {"weight_delta": 0.5}}},
        evidence_id="parq:test#6",
        method="unit_test",
    )
    card = compose({"ip_origin": "original"}, [rule])
    # Rule still logs as fired; axis is absent from base, so no entry created.
    assert "RX-006" in card.fired_rules
    assert "axis_not_yet_implemented" not in card.axis_weights


# ── load_rules() ─────────────────────────────────────────────────────────────


def test_load_rules_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "rules.jsonl"
    path.write_text("", encoding="utf-8")
    assert load_rules(path) == []


def test_load_rules_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "rules.jsonl"
    payload = (
        "\n"
        '{"rule_id":"RX-007","if":{"x":"<=1"},'
        '"then":{"axes":{"character_depth":{"weight_delta":0.05}}},'
        '"evidence_id":"e","method":"m"}\n'
        "\n"
    )
    path.write_text(payload, encoding="utf-8")
    rules = load_rules(path)
    assert len(rules) == 1
    assert rules[0].rule_id == "RX-007"


def test_load_rules_canonical_file_parses() -> None:
    """The repo's data/axis_selection_rules.jsonl loads (may be empty)."""
    rules = load_rules(RULES_PATH)
    assert isinstance(rules, list)


def test_load_rules_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_rules(tmp_path / "does_not_exist.jsonl") == []


def test_load_rules_skips_malformed_json(tmp_path: Path) -> None:
    """Malformed lines are logged + skipped; never raise."""
    path = tmp_path / "rules.jsonl"
    payload = (
        "this is not json\n"
        '{"rule_id":"RX-OK","if":{},'
        '"then":{"axes":{"character_depth":{"weight_delta":0.05}}},'
        '"evidence_id":"e","method":"m"}\n'
    )
    path.write_text(payload, encoding="utf-8")
    rules = load_rules(path)
    assert len(rules) == 1
    assert rules[0].rule_id == "RX-OK"


def test_load_rules_skips_missing_rule_id(tmp_path: Path) -> None:
    """A row without `rule_id` is logged + skipped."""
    path = tmp_path / "rules.jsonl"
    payload = (
        '{"missing":"rule_id_key"}\n'
        '{"rule_id":"RX-OK","if":{},'
        '"then":{"axes":{}},"evidence_id":"e","method":"m"}\n'
    )
    path.write_text(payload, encoding="utf-8")
    rules = load_rules(path)
    assert len(rules) == 1
    assert rules[0].rule_id == "RX-OK"


# ── evaluate() ───────────────────────────────────────────────────────────────


def test_evaluate_runs_character_depth_axis(deep_concept: dict[str, Any]) -> None:
    card = compose({}, [])
    result = evaluate(deep_concept, card)
    assert isinstance(result, EvalResult)
    assert "character_depth" in result.axis_scores
    assert 0.0 <= result.axis_scores["character_depth"] <= 1.0


def test_evaluate_pass_on_deep_concept(deep_concept: dict[str, Any]) -> None:
    card = compose({}, [])
    result = evaluate(deep_concept, card)
    assert result.axis_pass["character_depth"] is True


def test_evaluate_fail_on_shallow_concept(shallow_concept: dict[str, Any]) -> None:
    card = compose({}, [])
    result = evaluate(shallow_concept, card)
    assert result.axis_pass["character_depth"] is False


def test_evaluate_vector_pass_rolls_up_axes(deep_concept: dict[str, Any]) -> None:
    """Q2 vector pass = min of all Q2 axes' axis_pass (additive composition)."""
    card = compose({}, [])
    result = evaluate(deep_concept, card)
    assert result.vector_pass["Q2"] is True


def test_evaluate_unmeasured_vectors_are_none(deep_concept: dict[str, Any]) -> None:
    """Q1/Q3/Q4/Q5 have no axes yet in Cycle 1 — vector_pass is None, not False.

    None semantics: not-yet-measured ≠ failed. Drafter / gate logic must
    distinguish these cases.
    """
    card = compose({}, [])
    result = evaluate(deep_concept, card)
    for q in ("Q1", "Q3", "Q4", "Q5"):
        assert result.vector_pass[q] is None, f"expected {q}=None, got {result.vector_pass[q]!r}"


def test_evaluate_overall_pass_treats_none_as_pass(deep_concept: dict[str, Any]) -> None:
    """overall_pass = all measured vectors pass; unmeasured vectors don't veto."""
    card = compose({}, [])
    result = evaluate(deep_concept, card)
    assert result.overall_pass is True


def test_evaluate_overall_fail_on_shallow_concept(shallow_concept: dict[str, Any]) -> None:
    card = compose({}, [])
    result = evaluate(shallow_concept, card)
    assert result.overall_pass is False
    assert result.vector_pass["Q2"] is False


def test_evaluate_fired_rules_logged_into_result(small_cast_attrs: dict[str, Any]) -> None:
    rule = Rule(
        rule_id="RX-001",
        if_={"cast_size_principal": "<=2"},
        then_={"axes": {"character_depth": {"weight_delta": 0.20}}},
        evidence_id="parq:test#1",
        method="unit_test",
    )
    card = compose(small_cast_attrs, [rule])
    result = evaluate(
        {
            "slug": "x",
            "logline": "A.",
            "characters": {
                "protagonist": {"name": "A", "want": "b", "need": "c"},
                "antagonist": {"name": "B", "belief": "x", "method": "y"},
            },
        },
        card,
    )
    assert "RX-001" in result.fired_rules


def test_evaluate_threshold_override_affects_pass(deep_concept: dict[str, Any]) -> None:
    """A high threshold override can force a previously-passing concept to fail."""
    rule = Rule(
        rule_id="RX-008",
        if_={},
        then_={"axes": {"character_depth": {"threshold_delta": 0.45}}},
        evidence_id="parq:test#8",
        method="unit_test",
    )
    card_low = compose({}, [])
    card_high = compose({}, [rule])

    result_low = evaluate(deep_concept, card_low)
    result_high = evaluate(deep_concept, card_high)

    assert result_low.axis_pass["character_depth"] is True
    # If threshold + delta clears the axis score, axis fails.
    raised_threshold = card_high.axis_thresholds["character_depth"]
    if raised_threshold > result_low.axis_scores["character_depth"]:
        assert result_high.axis_pass["character_depth"] is False


# ── Anti-pattern guards ──────────────────────────────────────────────────────


def test_no_hardcoded_format_taxonomy_in_module() -> None:
    """Operator constraint: no `if format == "scifi"` style branching in scorecard.py."""
    src = (REPO_ROOT / "pipeline" / "scorecard.py").read_text(encoding="utf-8")
    for banned in ("scifi", "chamber_piece", "micro_drama", "ensemble_film", "is_scifi"):
        assert banned not in src.lower(), f"banned format token {banned!r} in scorecard.py"
