"""Tests for Issue #6: use_moa wiring in pipeline/run_single_idea.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.run_single_idea import _write_seed


def test_write_seed_basic(tmp_path: Path) -> None:
    """use_moa=False writes a basic seed with required fields."""
    _write_seed(tmp_path, theme="haunted memory", use_moa=False)
    seed_path = tmp_path / "seed.json"
    assert seed_path.exists()
    seed = json.loads(seed_path.read_text())
    assert seed["theme"] == "haunted memory"
    assert seed["target_format"] == "feature"
    assert "produced_at" in seed
    assert "moa_candidates" not in seed.get("hidden_attributes", {})


def test_write_seed_use_moa_writes_candidates(tmp_path: Path) -> None:
    """use_moa=True writes a seed that has moa_candidates in hidden_attributes."""
    mock_selected = MagicMock()
    mock_selected.to_dict.return_value = {
        "theme": "haunted memory",
        "intersection_premise": "A test premise",
        "hidden_attrs": {"existing_key": "existing_val"},
    }
    mock_result = MagicMock()
    mock_result.selected = mock_selected
    mock_result.seeder_names = ["conspiracy_mind", "open_science_mind", "reptile_fear_mind"]
    mock_result.judge_rationale = "Highest SOM floor."

    mock_module = MagicMock()
    mock_module.generate.return_value = mock_result

    with patch("pipeline.run_single_idea._seed_moa", mock_module):
        _write_seed(tmp_path, theme="haunted memory", use_moa=True)

    seed = json.loads((tmp_path / "seed.json").read_text())
    assert "moa_candidates" in seed["hidden_attributes"]
    assert len(seed["hidden_attributes"]["moa_candidates"]) == 3
    assert "moa_judge_rationale" in seed["hidden_attributes"]
    # Base fields must always be present
    assert seed["theme"] == "haunted memory"
    assert seed["target_format"] == "feature"


def test_write_seed_use_moa_fallback_when_unavailable(tmp_path: Path) -> None:
    """When _seed_moa is None, use_moa=True falls back gracefully to basic seed."""
    with patch("pipeline.run_single_idea._seed_moa", None):
        _write_seed(tmp_path, theme="silent ocean", use_moa=True)

    seed = json.loads((tmp_path / "seed.json").read_text())
    assert seed["theme"] == "silent ocean"
    assert "moa_candidates" not in seed.get("hidden_attributes", {})


def test_write_seed_default_is_no_moa(tmp_path: Path) -> None:
    """Default call (no use_moa kwarg) writes a plain seed without MoA fields."""
    _write_seed(tmp_path, theme="desert exile")
    seed = json.loads((tmp_path / "seed.json").read_text())
    assert "moa_candidates" not in seed.get("hidden_attributes", {})
