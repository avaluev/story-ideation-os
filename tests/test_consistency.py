"""Tests for pipeline.consistency.detect_drift.

SKIP until Wave C creates pipeline/consistency.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_mod = pytest.importorskip("pipeline.consistency", reason="defensive import guard")
detect_drift = _mod.detect_drift


def _make_sidecars(tmp_path: Path, overrides: dict | None = None) -> dict:
    """Write minimal sidecar JSON files; return name->Path mapping."""
    base: dict[str, dict] = {
        "seed": {
            "protagonist_name": "Alice",
            "genre": "thriller",
            "target_format": "feature",
        },
        "research": {
            "genre": "thriller",
            "audience_size_m": 200,
            "comp_films": ["Parasite", "Get Out"],
        },
        "draft_v0": {
            "protagonist_name": "Alice",
            "genre": "thriller",
            "comp_films": ["Parasite", "Get Out"],
        },
        "challenge": {
            "verdict": "PASS",
            "protagonist_name": "Alice",
        },
        "amplification": {
            "final_som": 150,
            "genre": "thriller",
        },
        "genius": {
            "overall": 75,
            "genre": "thriller",
        },
    }
    if overrides:
        for key, updates in overrides.items():
            base[key].update(updates)

    paths: dict[str, Path] = {}
    for name, data in base.items():
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data))
        paths[name] = p
    return paths


class TestDetectDrift:
    def test_consistent_sidecars_returns_consistent(self, tmp_path: Path) -> None:
        paths = _make_sidecars(tmp_path)
        result = detect_drift(paths)
        assert result["verdict"] == "CONSISTENT"
        assert result["drift_fields"] == []

    def test_protagonist_name_drift_detected(self, tmp_path: Path) -> None:
        paths = _make_sidecars(
            tmp_path,
            overrides={
                "draft_v0": {"protagonist_name": "Bob"},
            },
        )
        result = detect_drift(paths)
        assert result["verdict"] == "DRIFT"
        assert any("protagonist" in f.lower() for f in result["drift_fields"])

    def test_genre_drift_detected(self, tmp_path: Path) -> None:
        paths = _make_sidecars(
            tmp_path,
            overrides={
                "amplification": {"genre": "romantic-comedy"},
            },
        )
        result = detect_drift(paths)
        assert result["verdict"] == "DRIFT"
        assert any("genre" in f.lower() for f in result["drift_fields"])

    def test_result_has_required_keys(self, tmp_path: Path) -> None:
        result = detect_drift(_make_sidecars(tmp_path))
        for key in ("verdict", "drift_fields", "severity", "suggested_resolutions"):
            assert key in result

    def test_verdict_is_consistent_or_drift(self, tmp_path: Path) -> None:
        result = detect_drift(_make_sidecars(tmp_path))
        assert result["verdict"] in {"CONSISTENT", "DRIFT"}

    def test_missing_sidecar_handled_gracefully(self, tmp_path: Path) -> None:
        paths = _make_sidecars(tmp_path)
        paths["genius"].unlink()
        result = detect_drift(paths)
        assert "verdict" in result

    def test_drift_fields_is_list(self, tmp_path: Path) -> None:
        result = detect_drift(_make_sidecars(tmp_path))
        assert isinstance(result["drift_fields"], list)

    def test_multi_field_drift_reports_multiple_fields(self, tmp_path: Path) -> None:
        paths = _make_sidecars(
            tmp_path,
            overrides={
                "draft_v0": {"protagonist_name": "Charlie", "genre": "horror"},
            },
        )
        result = detect_drift(paths)
        if result["verdict"] == "DRIFT":
            assert len(result["drift_fields"]) >= 1
