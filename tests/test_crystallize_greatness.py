"""Tests for pipeline/crystallize/greatness.py — C001-C007 rubric scorer.

Covers:
- load_checklist() reads version + 7 criteria with weights summing to 1.0.
- load_checklist() returns empty Checklist gracefully when file is missing.
- greatness_subscores() emits all 7 C-keys ∈ [0, 1].
- weighted_total matches the manual sum.
- kill_switch_failed correctly populates only for sub-scores < 0.4
  on the 4 kill-switch criteria (C001, C003, C005, C006).
- lore-density proxy responds to decorative list counts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.crystallize.greatness import (
    _KILL_SWITCH_THRESHOLD,
    Checklist,
    Criterion,
    _clamp01,
    _lore_density_proxy,
    greatness_subscores,
    load_checklist,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_CHECKLIST = _REPO_ROOT / "Inputs" / "GeniusFilm" / "GREATNESS_CHECKLIST.json"

_checklist_missing = pytest.mark.skipif(
    not _REAL_CHECKLIST.exists(),
    reason="GREATNESS_CHECKLIST.json not present on disk",
)


# ---------------------------------------------------------------------------
# _clamp01
# ---------------------------------------------------------------------------


def test_clamp01_in_range() -> None:
    assert _clamp01(0.5) == pytest.approx(0.5)


def test_clamp01_below_zero() -> None:
    assert _clamp01(-1.0) == pytest.approx(0.0)


def test_clamp01_above_one() -> None:
    assert _clamp01(99.0) == pytest.approx(1.0)


def test_clamp01_handles_nan() -> None:
    assert _clamp01(float("nan")) == pytest.approx(0.0)


def test_clamp01_handles_non_numeric() -> None:
    # Type-ignore: function intentionally accepts garbage to be defensive
    assert _clamp01("not a number") == pytest.approx(0.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# load_checklist()
# ---------------------------------------------------------------------------


@_checklist_missing
def test_load_checklist_real_file() -> None:
    cl = load_checklist()
    assert cl.version == "1.0"
    assert len(cl.criteria) == 7
    ids = {c.id for c in cl.criteria}
    assert ids == {"C001", "C002", "C003", "C004", "C005", "C006", "C007"}


@_checklist_missing
def test_load_checklist_weights_sum_to_one() -> None:
    cl = load_checklist()
    total = sum(c.weight_default for c in cl.criteria)
    assert total == pytest.approx(1.0)


@_checklist_missing
def test_load_checklist_kill_switches() -> None:
    cl = load_checklist()
    kill_ids = {c.id for c in cl.criteria if c.kill_switch}
    assert kill_ids == {"C001", "C003", "C005", "C006"}


def test_load_checklist_missing_file_returns_empty(tmp_path: Path) -> None:
    cl = load_checklist(tmp_path / "no_such.json")
    assert cl.version == "0.0"
    assert cl.criteria == ()


def test_load_checklist_malformed_criteria(tmp_path: Path) -> None:
    """Non-dict entries in the criteria list are skipped silently."""
    p = tmp_path / "checklist.json"
    p.write_text(
        json.dumps(
            {"version": "test", "criteria": ["not a dict", {"id": "C001", "weight_default": 1.0}]}
        ),
        encoding="utf-8",
    )
    cl = load_checklist(p)
    assert cl.version == "test"
    assert len(cl.criteria) == 1
    assert cl.criteria[0].id == "C001"


# ---------------------------------------------------------------------------
# Checklist.weight() and is_kill_switch()
# ---------------------------------------------------------------------------


def test_checklist_weight_unknown_criterion_returns_zero() -> None:
    cl = Checklist(version="t", criteria=(Criterion("C001", "n", "d", "q", 0.5, True),))
    assert cl.weight("C999") == 0.0


def test_checklist_is_kill_switch_unknown_returns_false() -> None:
    cl = Checklist(version="t", criteria=(Criterion("C001", "n", "d", "q", 0.5, True),))
    assert cl.is_kill_switch("C999") is False


# ---------------------------------------------------------------------------
# _lore_density_proxy
# ---------------------------------------------------------------------------


def test_lore_density_empty_seed() -> None:
    assert _lore_density_proxy({}) == pytest.approx(0.0)


def test_lore_density_partial() -> None:
    # 2 items in conspiracy_engine + 1 in era_collision = 3 total → 3/5 = 0.6.
    seed: dict[str, Any] = {
        "conspiracy_engine": [{}, {}],
        "era_collision": [{}],
    }
    assert _lore_density_proxy(seed) == pytest.approx(0.6)


def test_lore_density_caps_at_one() -> None:
    seed: dict[str, Any] = {
        "conspiracy_engine": [{}] * 10,
        "era_collision": [{}] * 10,
    }
    assert _lore_density_proxy(seed) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# greatness_subscores
# ---------------------------------------------------------------------------


def _build_full_seed(
    goldilocks: float = 0.5,
    emo: float = 2.5,
    anchor: float = 0.5,
    cultural: float = 0.5,
    compression: float = 0.5,
    decorative_count: int = 2,
) -> dict[str, Any]:
    return {
        "scores": {
            "goldilocks_score": goldilocks,
            "emotional_universality_score": emo,
            "thematic_anchor_score": anchor,
            "cultural_field_alignment": cultural,
            "compression_score": compression,
        },
        "era_collision": [{}] * decorative_count,
        "conspiracy_engine": [],
        "reptile_trigger": [],
        "open_problem": [],
        "cultural_moment": [],
        "additional_world_textures": [],
        "additional_moral_fault_lines": [],
    }


def test_greatness_subscores_all_keys_present() -> None:
    g = greatness_subscores(_build_full_seed(), derivative_distance=0.6)
    for k in ("C001", "C002", "C003", "C004", "C005", "C006", "C007"):
        assert k in g
        assert 0.0 <= g[k] <= 1.0
    assert "weighted_total" in g
    assert "kill_switch_failed" in g


def test_greatness_subscores_uses_derivative_distance_as_c001() -> None:
    g = greatness_subscores(_build_full_seed(), derivative_distance=0.42)
    assert g["C001"] == pytest.approx(0.42)


def test_greatness_subscores_emo_scaled_by_five() -> None:
    g = greatness_subscores(_build_full_seed(emo=5.0), derivative_distance=1.0)
    assert g["C003"] == pytest.approx(1.0)
    g_low = greatness_subscores(_build_full_seed(emo=0.0), derivative_distance=1.0)
    assert g_low["C003"] == pytest.approx(0.0)


@_checklist_missing
def test_greatness_subscores_weighted_total_matches_manual_sum() -> None:
    cl = load_checklist()
    seed = _build_full_seed(
        goldilocks=0.85,
        emo=4.0,
        anchor=0.7,
        cultural=0.6,
        compression=0.9,
        decorative_count=2,
    )
    g = greatness_subscores(seed, derivative_distance=0.78, checklist=cl)
    expected = (
        cl.weight("C001") * g["C001"]
        + cl.weight("C002") * g["C002"]
        + cl.weight("C003") * g["C003"]
        + cl.weight("C004") * g["C004"]
        + cl.weight("C005") * g["C005"]
        + cl.weight("C006") * g["C006"]
        + cl.weight("C007") * g["C007"]
    )
    assert g["weighted_total"] == pytest.approx(min(1.0, expected))


@_checklist_missing
def test_greatness_kill_switch_failed_populates_correctly() -> None:
    # Make C001 (kill-switch) sub-score drop below threshold by passing a tiny
    # derivative_distance.
    g = greatness_subscores(_build_full_seed(), derivative_distance=0.1)
    assert "C001" in g["kill_switch_failed"]
    # C002 is NOT a kill switch even though sub-score may be low.
    assert "C002" not in g["kill_switch_failed"]


@_checklist_missing
def test_greatness_kill_switch_threshold_is_strict() -> None:
    # A value exactly at threshold (0.4) must NOT be flagged (strict <).
    cl = load_checklist()
    seed = _build_full_seed(emo=_KILL_SWITCH_THRESHOLD * 5.0)
    g = greatness_subscores(seed, derivative_distance=1.0, checklist=cl)
    # C003 sub-score = emo/5 = 0.4 — exactly at threshold, NOT failed.
    assert g["C003"] == pytest.approx(_KILL_SWITCH_THRESHOLD)
    assert "C003" not in g["kill_switch_failed"]


def test_greatness_subscores_empty_seed_dict() -> None:
    """No scores at all → everything 0 except C001 from derivative_distance."""
    g = greatness_subscores({}, derivative_distance=0.9)
    assert g["C001"] == pytest.approx(0.9)
    # C002..C007 all default to 0 because the underlying score fields are missing.
    for k in ("C002", "C003", "C004", "C005", "C007"):
        assert g[k] == pytest.approx(0.0)
    # C006 = 1 - lore_density; with no decorative lists at all, lore=0, C006=1.
    assert g["C006"] == pytest.approx(1.0)
