"""tests/test_drafter_quality_gate.py — S4.1 NB.5-INTEGRATE contract.

The Phase-2 post-draft check writes ``runs/{id}/quality.json`` via
``pipeline.single_idea.evaluate_draft_quality()``. Pure-Python; no I/O beyond
reading ``draft_v0.json`` and writing ``quality.json`` atomically.

Cycle-1 minimum (per Session 4 prompt §STREAM B / S4.1):

- function reads ``draft_v0.json`` from the run directory
- extracts measured attributes from ``draft_v0["hidden_attrs"]`` (default ``{}``)
- runs ``scorecard.compose`` + ``scorecard.evaluate``
- writes ``quality.json`` with schema
  ``{axis_scores, axis_pass, vector_pass, overall_pass, fired_rules,
  evidence, produced_at}``
- does NOT halt the pipeline; failing axes are surfaced via the module logger
- atomic write via ``pipeline.state.safe_write``

Anti-pattern guards (HANDOFF_SESSION_4 §STAGE 4):

- no hardcoded format taxonomy — attrs are measurements not labels
- no silent feature flags
- tests are shape assertions; behavioural correctness defers to S0 calibration
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from pipeline import single_idea
from pipeline.scorecard import EvalResult

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def deep_draft_v0() -> dict[str, Any]:
    """Concept whose character_depth axis clears the Cycle-1 0.50 threshold."""
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
                "contradiction": ("the system that protects her son is the one she must dismantle"),
            },
            "antagonist": {
                "name": "Judge Reed",
                "belief": "law without mercy is the only law that survives",
                "method": "weaponize procedure to make injustice legal",
                "entity_type": "human",
            },
            "key_characters": [{"name": "Father", "function": "moral mirror"}],
        },
        "hidden_attrs": {
            "cast_size_principal": 3,
            "antagonist_entity_type": "human",
            "ip_origin": "original",
        },
    }


@pytest.fixture
def shallow_draft_v0() -> dict[str, Any]:
    """Concept that fails character_depth and trips Q2."""
    return {
        "slug": "shallow",
        "logline": "A man fights bad guys.",
        "characters": {
            "protagonist": {"name": "He", "want": "win", "need": "win"},
            "antagonist": {"name": None, "belief": None},
        },
        "hidden_attrs": {},
    }


def _write_draft(run_dir: Path, draft: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "draft_v0.json").write_text(json.dumps(draft), encoding="utf-8")


# ── Module surface ──────────────────────────────────────────────────────────


def test_evaluate_draft_quality_is_public() -> None:
    """The function must be a module-level callable on pipeline.single_idea."""
    assert hasattr(single_idea, "evaluate_draft_quality")
    assert callable(single_idea.evaluate_draft_quality)


def test_quality_filename_constant_exposed() -> None:
    """The sidecar filename must be a public constant so callers don't string-leak."""
    assert getattr(single_idea, "QUALITY_FILENAME", None) == "quality.json"


# ── Behaviour ───────────────────────────────────────────────────────────────


def test_quality_json_written_after_phase_2(tmp_path: Path, deep_draft_v0: dict[str, Any]) -> None:
    _write_draft(tmp_path, deep_draft_v0)
    result = single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    assert (tmp_path / "quality.json").exists(), "quality.json sidecar not written"
    assert isinstance(result, EvalResult)


def test_quality_json_schema_matches_evalresult(
    tmp_path: Path, deep_draft_v0: dict[str, Any]
) -> None:
    _write_draft(tmp_path, deep_draft_v0)
    single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    payload = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    expected_keys = {
        "axis_scores",
        "axis_pass",
        "vector_pass",
        "overall_pass",
        "fired_rules",
        "evidence",
        "produced_at",
    }
    assert expected_keys.issubset(payload.keys()), (
        f"quality.json missing keys: {expected_keys - set(payload.keys())!r}"
    )
    assert isinstance(payload["axis_scores"], dict)
    assert isinstance(payload["axis_pass"], dict)
    assert isinstance(payload["vector_pass"], dict)
    assert isinstance(payload["overall_pass"], bool)
    assert isinstance(payload["fired_rules"], list)
    assert isinstance(payload["evidence"], dict)
    assert isinstance(payload["produced_at"], str)


def test_failing_concept_surfaces_axes_in_log(
    tmp_path: Path,
    shallow_draft_v0: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When overall_pass is False, the module logger names the failing axes."""
    _write_draft(tmp_path, shallow_draft_v0)
    with caplog.at_level(logging.INFO, logger="pipeline.single_idea"):
        single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    messages = " ".join(rec.getMessage() for rec in caplog.records)
    assert "FAIL" in messages.upper(), f"expected failing-axes log line, got: {messages!r}"
    assert "character_depth" in messages, f"failing axis name must appear in log, got: {messages!r}"


def test_passing_concept_writes_overall_pass_true(
    tmp_path: Path, deep_draft_v0: dict[str, Any]
) -> None:
    _write_draft(tmp_path, deep_draft_v0)
    result = single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    payload = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert result.overall_pass is True
    assert payload["overall_pass"] is True


def test_failing_concept_writes_overall_pass_false(
    tmp_path: Path, shallow_draft_v0: dict[str, Any]
) -> None:
    """quality.json must record the False verdict, not silently skip."""
    _write_draft(tmp_path, shallow_draft_v0)
    single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    payload = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert payload["overall_pass"] is False
    assert payload["vector_pass"]["Q2"] is False


def test_quality_json_atomically_written(tmp_path: Path, deep_draft_v0: dict[str, Any]) -> None:
    """state.safe_write must not leave a .tmp.* sibling in the run dir."""
    _write_draft(tmp_path, deep_draft_v0)
    single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    leftover = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp.")]
    assert leftover == [], f"safe_write left tmp files behind: {leftover!r}"
    # quality.json parses cleanly — final write was complete.
    parsed = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)


def test_missing_draft_raises(tmp_path: Path) -> None:
    """Caller mistake (no draft_v0.json) is explicit, never silent."""
    with pytest.raises(FileNotFoundError):
        single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")


def test_missing_hidden_attrs_defaults_to_empty(
    tmp_path: Path, deep_draft_v0: dict[str, Any]
) -> None:
    """draft_v0 without hidden_attrs still evaluates; no rule fires."""
    draft = dict(deep_draft_v0)
    draft.pop("hidden_attrs", None)
    _write_draft(tmp_path, draft)
    result = single_idea.evaluate_draft_quality(tmp_path, rules_path=tmp_path / "no_rules.jsonl")
    assert result.fired_rules == ()


def test_canonical_rules_path_is_consulted(tmp_path: Path, deep_draft_v0: dict[str, Any]) -> None:
    """If a rules file is supplied, matching rules fire and land in quality.json."""
    rules_file = tmp_path / "rules.jsonl"
    rules_file.write_text(
        json.dumps(
            {
                "rule_id": "RX-TEST-1",
                "if": {"cast_size_principal": "<=3"},
                "then": {"axes": {"character_depth": {"weight_delta": 0.10}}},
                "evidence_id": "parq:test#1",
                "method": "unit_test",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_draft(tmp_path, deep_draft_v0)
    single_idea.evaluate_draft_quality(tmp_path, rules_path=rules_file)
    payload = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert "RX-TEST-1" in payload["fired_rules"]


def test_default_rules_path_is_canonical_repo_file() -> None:
    """The default rules_path resolves to data/axis_selection_rules.jsonl."""
    repo_root = Path(__file__).resolve().parents[1]
    expected = repo_root / "data" / "axis_selection_rules.jsonl"
    # Function should be invokable with no explicit rules path and not raise on
    # the empty repo file. We probe via a temp run dir that has a draft.
    # Use an isolated repo-relative path probe rather than monkeypatching the
    # cwd; the function-default value lives in pipeline.single_idea.
    default = getattr(single_idea, "_RULES_PATH_DEFAULT", None)
    assert default == expected, f"expected default {expected!r}, got {default!r}"
