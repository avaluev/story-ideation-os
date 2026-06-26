"""tests/test_stabilization_queue.py — Unit tests for STAB-03 queue append behavior.

Tests the _maybe_queue_stab_pattern() helper in pipeline.run that appends
critic-flagged anti-slop patterns to data/stabilization_queue.jsonl.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.run import _maybe_queue_stab_pattern
from pipeline.schema import Phase5Critique


@pytest.fixture(autouse=True)
def _isolate_run_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect pipeline.state.RUN_LOG to a tmp file so _log_event doesn't pollute
    the real data/run_log.jsonl during these unit tests. Without this, every
    `make test` invocation would re-touch run_log.jsonl and the Stop hook's
    RESUME.md freshness check would always fail."""
    fake_log = tmp_path / "test_run_log.jsonl"
    monkeypatch.setattr("pipeline.state.RUN_LOG", fake_log)
    monkeypatch.setattr("pipeline.run.RUN_LOG", fake_log)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_critique(pattern: str | None) -> Phase5Critique:
    """Build a minimal Phase5Critique with the given stabilization pattern."""
    return Phase5Critique(
        concept_id="test-concept-001",
        novelty_score=25,  # max 30
        jtbd_score=20,  # max 25
        contradiction_score=20,  # max 25
        specificity_score=15,  # max 20
        cap_at_70_triggered=False,
        ten_school_self_check=[True] * 10,
        stabilization_pattern_to_add_to_anti_slop=pattern,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_stab_queue_appends_when_pattern_non_null(tmp_path: Path) -> None:
    """STAB-03: when stabilization_pattern_to_add_to_anti_slop is non-null,
    an entry appears in the stabilization_queue.jsonl file."""
    queue_path = tmp_path / "stabilization_queue.jsonl"
    critique = _make_critique("Avoid generic 'redemption arc' clichés in 3-act structure")

    _maybe_queue_stab_pattern(critique, session_id="sess-001", stab_queue_path=queue_path)

    assert queue_path.exists(), "Queue file should be created"
    lines = [ln for ln in queue_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1, f"Expected 1 row, got {len(lines)}"
    row = json.loads(lines[0])
    assert row["concept_id"] == "test-concept-001"
    assert row["pattern"] == "Avoid generic 'redemption arc' clichés in 3-act structure"
    assert "queued_at" in row


def test_stab_queue_skips_when_pattern_null(tmp_path: Path) -> None:
    """STAB-03: when stabilization_pattern_to_add_to_anti_slop is None,
    the queue file must NOT be created or appended to."""
    queue_path = tmp_path / "stabilization_queue.jsonl"
    critique = _make_critique(None)

    _maybe_queue_stab_pattern(critique, session_id="sess-002", stab_queue_path=queue_path)

    assert not queue_path.exists(), "Queue file should NOT be created when pattern is None"


def test_stab_queue_entry_schema(tmp_path: Path) -> None:
    """Queue row must have exactly the required keys: concept_id, pattern, queued_at."""
    queue_path = tmp_path / "stabilization_queue.jsonl"
    critique = _make_critique("No 'chosen one' narratives without subverting the trope")

    _maybe_queue_stab_pattern(critique, session_id="sess-003", stab_queue_path=queue_path)

    lines = [ln for ln in queue_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    # Must have all three required keys
    assert "concept_id" in row, "Missing key: concept_id"
    assert "pattern" in row, "Missing key: pattern"
    assert "queued_at" in row, "Missing key: queued_at"
    # concept_id and pattern are strings
    assert isinstance(row["concept_id"], str)
    assert isinstance(row["pattern"], str)
    # queued_at is ISO-8601 (starts with YYYY-)
    assert isinstance(row["queued_at"], str)
    assert len(row["queued_at"]) >= 10
    assert row["queued_at"][4] == "-", "queued_at should be ISO-8601 format"


def test_stab_queue_multiple_appends(tmp_path: Path) -> None:
    """Multiple calls with non-null patterns each append a new row."""
    queue_path = tmp_path / "stabilization_queue.jsonl"

    for i in range(3):
        critique = Phase5Critique(
            concept_id=f"concept-{i:03d}",
            novelty_score=20,  # max 30
            jtbd_score=20,  # max 25
            contradiction_score=20,  # max 25
            specificity_score=15,  # max 20
            cap_at_70_triggered=False,
            ten_school_self_check=[True] * 10,
            stabilization_pattern_to_add_to_anti_slop=f"Pattern {i}",
        )
        _maybe_queue_stab_pattern(critique, session_id="sess-multi", stab_queue_path=queue_path)

    lines = [ln for ln in queue_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3, f"Expected 3 rows, got {len(lines)}"
    for i, line in enumerate(lines):
        row = json.loads(line)
        assert row["concept_id"] == f"concept-{i:03d}"
        assert row["pattern"] == f"Pattern {i}"
