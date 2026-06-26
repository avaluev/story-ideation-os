"""Tests for the `python -m pipeline.goal` front door (G2).

Pins the contract that makes config/goal.json safe to edit:
  * `set` loads the LIVE config first, so a new goal_history row carries the
    active lineage (investor_v1 -> investor_v2), NOT the stale default_v5;
  * a non-unit weight sum WARNs loudly then auto-normalises (never silently, and
    never a hard reject -- matching Goal.load's forward-compat contract);
  * a negative weight is rejected loudly;
  * an unchanged scoring contract dedupes (no history row, no version bump);
  * Goal.sha is weight-only (name/timestamp do not change it).
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.goal import Goal, main


@pytest.fixture
def live_config(tmp_path: Path) -> tuple[Path, Path]:
    """A temp config seeded with an investor_v1-shaped goal + empty history."""
    gp = tmp_path / "goal.json"
    hp = tmp_path / "goal_history.jsonl"
    seed = replace(Goal.default(), goal_id="investor_v1")
    gp.write_text(json.dumps(seed.to_dict(), indent=2), encoding="utf-8")
    return gp, hp


def _history(hp: Path) -> list[dict[str, object]]:
    if not hp.exists():
        return []
    return [json.loads(line) for line in hp.read_text().splitlines() if line.strip()]


def test_set_preserves_lineage_not_default_v5(live_config: tuple[Path, Path]) -> None:
    gp, hp = live_config
    rc = main(["--config", str(gp), "--history", str(hp), "set", "som_y1=0.30", "genius=0.18"])
    assert rc == 0
    reloaded = Goal.load(gp)
    assert reloaded.goal_id == "investor_v2"  # bumped from the LIVE investor_v1
    rows = _history(hp)
    assert len(rows) == 1
    assert rows[0]["goal_id"] == "investor_v2"  # NOT default_v5
    assert rows[0]["sha"] == reloaded.sha


def test_set_dedupes_unchanged_contract(live_config: tuple[Path, Path]) -> None:
    gp, hp = live_config
    before = Goal.load(gp)
    # Re-assert the already-live value -> contract unchanged -> no write.
    rc = main(
        [
            "--config",
            str(gp),
            "--history",
            str(hp),
            "set",
            f"genius={before.facet_weights['genius']}",
        ]
    )
    assert rc == 0
    assert Goal.load(gp).goal_id == before.goal_id  # no version bump
    assert _history(hp) == []  # no history row


def test_set_rejects_negative_weight(live_config: tuple[Path, Path]) -> None:
    gp, hp = live_config
    before = gp.read_text()
    rc = main(["--config", str(gp), "--history", str(hp), "set", "genius=-0.1"])
    assert rc == 1
    assert gp.read_text() == before  # nothing written
    assert _history(hp) == []


def test_set_warns_then_normalises_nonunit_sum(
    live_config: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    gp, hp = live_config
    with caplog.at_level(logging.WARNING, logger="pipeline.goal"):
        rc = main(["--config", str(gp), "--history", str(hp), "set", "som_y1=0.5"])
    assert rc == 0
    assert any("auto-normalising" in r.message for r in caplog.records)
    assert sum(Goal.load(gp).facet_weights.values()) == pytest.approx(1.0)


def test_set_floor_override(live_config: tuple[Path, Path]) -> None:
    gp, hp = live_config
    rc = main(["--config", str(gp), "--history", str(hp), "set", "revenue_floor_usd=250000000"])
    assert rc == 0
    assert Goal.load(gp).revenue_floor_usd == pytest.approx(250_000_000.0)


def test_set_gate_override_is_int_normalised(live_config: tuple[Path, Path]) -> None:
    gp, hp = live_config
    rc = main(["--config", str(gp), "--history", str(hp), "set", "som_y1_usd_min=175000000"])
    assert rc == 0
    gates = Goal.load(gp).gates
    assert gates["som_y1_usd_min"] == 175_000_000
    assert isinstance(gates["som_y1_usd_min"], int)  # whole gate values stay int


def test_validate_warns_on_nonunit(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    gp = tmp_path / "goal.json"
    gp.write_text(json.dumps({"goal_id": "x", "facet_weights": {"genius": 0.6, "som_y1": 0.6}}))
    with caplog.at_level(logging.WARNING, logger="pipeline.goal"):
        rc = main(["--config", str(gp), "validate"])
    assert rc == 0
    assert any("auto-normalised" in r.message for r in caplog.records)


def test_sha_is_weight_only(tmp_path: Path) -> None:
    a = replace(Goal.default(), goal_id="name_a", created_at="2026-01-01T00:00:00Z")
    b = replace(Goal.default(), goal_id="name_b", created_at="2030-12-31T00:00:00Z")
    assert a.sha == b.sha  # name + timestamp excluded
    c = replace(a, facet_weights={**a.facet_weights, "som_y1": 0.5})
    assert a.sha != c.sha  # a weight change DOES move the sha
