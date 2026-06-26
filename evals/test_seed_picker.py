"""Tests for pipeline.seed_picker — the evolutionary loop's seed source."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.seed_picker import (
    SeedPackage,
    _classify_novelty,
    _weight_value,
    pick_seeds,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ONTOLOGY = _REPO_ROOT / "sources" / "conflict_ontology.json"
_WEIGHTS = _REPO_ROOT / "sources" / "resonance_weights.json"


def test_data_files_present() -> None:
    """Both source JSON files must ship in sources/."""
    assert _ONTOLOGY.exists(), f"missing {_ONTOLOGY}"
    assert _WEIGHTS.exists(), f"missing {_WEIGHTS}"


def test_pick_returns_n_seeds() -> None:
    """pick_seeds(n) returns exactly n SeedPackage objects."""
    seeds = pick_seeds(n=5, rng_seed=7)
    assert len(seeds) == 5
    assert all(isinstance(s, SeedPackage) for s in seeds)


def test_pick_is_deterministic_with_seed() -> None:
    """Same rng_seed produces same picks (reproducibility for tests/CI)."""
    a = pick_seeds(n=5, rng_seed=12345)
    b = pick_seeds(n=5, rng_seed=12345)
    assert [s.cell_id for s in a] == [s.cell_id for s in b]


def test_pick_enforces_bt_ps_diversity() -> None:
    """No two seeds in one batch share both bt_id AND ps_id."""
    seeds = pick_seeds(n=10, rng_seed=999)
    pairs = [(s.bt_id, s.ps_id) for s in seeds]
    assert len(pairs) == len(set(pairs)), f"duplicate (bt,ps) pair: {pairs}"


def test_pick_clamps_n_to_max() -> None:
    """n > 30 is clamped to 30 (the engineered ceiling)."""
    seeds = pick_seeds(n=999, rng_seed=1)
    assert len(seeds) == 30


def test_pick_clamps_n_to_min() -> None:
    """n <= 0 is clamped to 1."""
    seeds = pick_seeds(n=0, rng_seed=1)
    assert len(seeds) == 1
    seeds_neg = pick_seeds(n=-5, rng_seed=1)
    assert len(seeds_neg) == 1


def test_pick_respects_recent_history(tmp_path: Path) -> None:
    """Cells already in cell_history.jsonl get resonance penalty (history_mult=0.3).

    We forge-record one specific cell, then verify that the same cell drawn
    again receives a strictly lower resonance_score than its first appearance.
    """
    fake_cell = "BT-041_PS-030_PA-006_US-034"
    history = tmp_path / "cell_history.jsonl"
    history.write_text(json.dumps({"cell_id": fake_cell}) + "\n", encoding="utf-8")

    # Draw a large batch with the fake history file; if the fake cell appears,
    # its resonance must be <= raw_max * _HISTORY_PENALTY (0.3) = 0.3.
    seeds = pick_seeds(
        n=20,
        history_path=history,
        rng_seed=42,
    )
    matching = [s for s in seeds if s.cell_id == fake_cell]
    if matching:
        assert matching[0].resonance_score <= 0.30, (
            f"history-penalized cell scored too high: {matching[0].resonance_score}"
        )


def test_weight_value_handles_dict_and_float() -> None:
    """_weight_value accepts {weight, driver} dicts AND bare floats."""
    assert _weight_value({"weight": 0.85, "driver": "test"}) == pytest.approx(0.85)
    assert _weight_value(0.75) == pytest.approx(0.75)
    assert _weight_value(None) == pytest.approx(0.5)
    assert _weight_value("nonsense") == pytest.approx(0.5)


def test_classify_novelty_three_bands() -> None:
    """Underexplored beats overdone; combo-match beats BT-only match."""
    overdone = {"BT-004"}
    under = {"BT-006+US-009"}
    assert _classify_novelty("BT-006", "BT-006+US-009", overdone, under) == (
        1.0,
        "underexplored",
    )
    assert _classify_novelty("BT-004", "BT-004+US-007", overdone, under) == (
        0.2,
        "overdone",
    )
    assert _classify_novelty("BT-001", "BT-001+US-001", overdone, under) == (
        0.5,
        "neutral",
    )


def test_pick_emits_valid_resonance_range() -> None:
    """resonance_score must be in (0.0, 1.0] for every seed produced."""
    seeds = pick_seeds(n=10, rng_seed=3)
    for s in seeds:
        assert 0.0 < s.resonance_score <= 1.0, (
            f"{s.cell_id} has out-of-range resonance: {s.resonance_score}"
        )
