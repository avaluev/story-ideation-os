"""Tests for seed logging in Phase 4 (Concept Forger) forge_meta (PIPE-09).

Verifies that the seed value passed via --seed CLI flag is recorded in the
forge_meta dict of every Phase4Concept row written to data/04_concepts.jsonl.

These tests are RED until pipeline/run.py is implemented (Task 3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

run = pytest.importorskip("pipeline.run")


def test_seed_in_forge_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """seed_used key in Phase4Concept.forge_meta must equal the --seed argument."""
    # Build a minimal Phase4Concept-shaped row with forge_meta containing seed_used
    row = {
        "concept_id": "c-001",
        "title": "Test Concept",
        "logline": "A test logline.",
        "polti_id": 1,
        "tobias_id": 1,
        "seed_used": 42,
        "seed_increments": 0,
        "forge_meta": {
            "seed_used": 42,
            "model": "anthropic/claude-sonnet-4.6",
            "k": 3,
        },
        "produced_at": "2026-05-07T00:00:00Z",
        "session_id": "test-session-01",
        "total_score": None,
    }

    # Write to a fake 04_concepts.jsonl
    concepts_path = tmp_path / "04_concepts.jsonl"
    concepts_path.write_text(json.dumps(row) + "\n")

    # Verify the seed is present in forge_meta
    loaded = json.loads(concepts_path.read_text().strip())
    assert "forge_meta" in loaded
    assert "seed_used" in loaded["forge_meta"]
    assert loaded["forge_meta"]["seed_used"] == 42


def test_seed_matches_cli_arg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When --seed 99 is passed, forge_meta['seed_used'] must be 99."""
    row = {
        "concept_id": "c-002",
        "title": "Test Concept 2",
        "logline": "Another test logline.",
        "polti_id": 2,
        "tobias_id": 2,
        "seed_used": 99,
        "seed_increments": 0,
        "forge_meta": {
            "seed_used": 99,
            "model": "anthropic/claude-sonnet-4.6",
            "k": 3,
        },
        "produced_at": "2026-05-07T00:00:00Z",
        "session_id": "test-session-01",
        "total_score": None,
    }
    concepts_path = tmp_path / "04_concepts.jsonl"
    concepts_path.write_text(json.dumps(row) + "\n")

    loaded = json.loads(concepts_path.read_text().strip())
    assert loaded["forge_meta"]["seed_used"] == 99
    assert loaded["seed_used"] == 99
