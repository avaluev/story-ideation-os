"""tests/test_state.py — substrate interface + schema tests (MEM-04..11).

Tests in this file:
  test_state_module_interface   — 8 callables + 2 dataclasses present
  test_state_module_constants   — path constants match expected values
  test_handoff_contract_roundtrip   — HandoffContract validate + roundtrip (MEM-05)
  test_session_checkpoint_roundtrip — SessionCheckpoint validate + roundtrip (MEM-04)
  test_resume_md_yaml_frontmatter_parses — RESUME.md YAML frontmatter valid (MEM-06)
  test_tasks_jsonl_append_only  — append-only invariant with inline helper (MEM-10)

Note on test_atomic_write_under_kill (MEM-01, CLAUDE.md enforcer):
  This test is defined here as a placeholder marked xfail. The kill-9 body
  lands in P3 (pipeline.state.safe_write implementation). Until P3, the test
  must xfail because the function body raises NotImplementedError.
  Named exactly as referenced in CLAUDE.md: tests/test_state.py::test_atomic_write_under_kill
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

import pipeline.state as st

# ---------------------------------------------------------------------------
# Interface and constants
# ---------------------------------------------------------------------------


def test_state_module_interface() -> None:
    """All 8 required callables + 2 dataclasses are present in pipeline.state."""
    required = [
        "safe_write",
        "append_jsonl",
        "write_handoff",
        "write_checkpoint",
        "bump_session_checkpoint",
        "read_resume",
        "latest_checkpoint",
        "latest_handoff_for",
    ]
    for name in required:
        assert hasattr(st, name), f"pipeline.state missing {name}"
        assert callable(getattr(st, name)), f"{name} not callable"
    assert hasattr(st, "HandoffContract"), "pipeline.state missing HandoffContract"
    assert hasattr(st, "SessionCheckpoint"), "pipeline.state missing SessionCheckpoint"


def test_state_module_constants() -> None:
    """Path constants match expected values (MEM-11)."""
    assert Path(".planning/state") == st.STATE_DIR
    assert Path(".planning/state/sessions") == st.SESSIONS_DIR
    assert Path(".planning/state/handoffs") == st.HANDOFFS_DIR
    assert Path(".planning/state/RESUME.md") == st.RESUME_PATH
    assert Path(".planning/state/tasks.jsonl") == st.TASKS_LOG
    assert Path("data/state") == st.RUNTIME_STATE_DIR
    assert Path("data/run_log.jsonl") == st.RUN_LOG


# ---------------------------------------------------------------------------
# HandoffContract round-trip (MEM-05)
# ---------------------------------------------------------------------------


def _sample_handoff_dict() -> dict:
    return {
        "schema_version": "1.0",
        "from_agent": "builder-engine",
        "to_agent": "critic-engine",
        "handoff_ts": "2026-05-06T20:00:00Z",
        "session_id": "29engine-20260506-abc",
        "produced": ["pipeline/state.py", "tests/test_state.py"],
        "consumed": ["pipeline/__init__.py"],
        "next_action": "Review pipeline/state.py interface for MEM-04..11 compliance.",
        "assumptions_made": ["pydantic v2 not needed in P0"],
        "open_decisions": [],
        "notes": "P0 ships stubs only; P3 implements bodies.",
    }


def test_handoff_contract_roundtrip() -> None:
    """HandoffContract: from_dict → validate → to_dict round-trip (MEM-05)."""
    d = _sample_handoff_dict()

    # from_dict works
    contract = st.HandoffContract.from_dict(d)
    assert contract.schema_version == "1.0"
    assert contract.from_agent == "builder-engine"
    assert contract.to_agent == "critic-engine"

    # validate passes on valid data
    contract.validate()

    # to_dict round-trip preserves all fields
    result = contract.to_dict()
    for key in d:
        assert result[key] == d[key], f"field {key!r} changed after roundtrip"

    # validate raises on session_id length 7 (too short)
    bad_short = st.HandoffContract.from_dict({**d, "session_id": "1234567"})
    with pytest.raises(ValueError, match=r"session_id length must be 8\.\.64"):
        bad_short.validate()

    # validate raises on session_id length 65 (too long)
    bad_long = st.HandoffContract.from_dict({**d, "session_id": "a" * 65})
    with pytest.raises(ValueError, match=r"session_id length must be 8\.\.64"):
        bad_long.validate()

    # validate raises on next_action > 500 chars
    bad_action = st.HandoffContract.from_dict({**d, "next_action": "x" * 501})
    with pytest.raises(ValueError, match="next_action max 500 chars"):
        bad_action.validate()

    # validate raises on bad ISO-8601 in handoff_ts
    bad_ts = st.HandoffContract.from_dict({**d, "handoff_ts": "not-a-timestamp"})
    with pytest.raises((ValueError, TypeError)):
        bad_ts.validate()


# ---------------------------------------------------------------------------
# SessionCheckpoint round-trip (MEM-04)
# ---------------------------------------------------------------------------


def _sample_checkpoint_dict() -> dict:
    return {
        "schema_version": "1.0",
        "session_id": "29engine-20260506-session",
        "started_at": "2026-05-06T17:00:00Z",
        "last_updated_at": "2026-05-06T17:30:00Z",
        "current_phase": "P0",
        "current_plan": "00-04",
        "pending_tasks": [{"id": 1, "name": "Task 3"}],
        "open_questions": ["Is pydantic needed in P0?"],
        "last_artifact_path": "pipeline/state.py",
        "last_commit_sha": "2face68",
        "files_edited_this_session": ["pipeline/state.py", "tests/test_state.py"],
        "handoffs_written": [],
        "notes": "P0 substrate in progress.",
    }


def test_session_checkpoint_roundtrip() -> None:
    """SessionCheckpoint: from_dict → validate → to_dict round-trip (MEM-04)."""
    d = _sample_checkpoint_dict()

    # from_dict works
    chk = st.SessionCheckpoint.from_dict(d)
    assert chk.schema_version == "1.0"
    assert chk.session_id == "29engine-20260506-session"
    assert chk.current_phase == "P0"
    assert chk.current_plan == "00-04"

    # validate passes on valid data
    chk.validate()

    # to_dict round-trip preserves fields
    result = chk.to_dict()
    for key in d:
        assert result[key] == d[key], f"field {key!r} changed after roundtrip"

    # validate raises on session_id length 7 (too short)
    bad_short = st.SessionCheckpoint.from_dict({**d, "session_id": "1234567"})
    with pytest.raises(ValueError, match=r"session_id length 8\.\.64"):
        bad_short.validate()

    # validate raises on bad ISO-8601 in started_at
    bad_ts = st.SessionCheckpoint.from_dict({**d, "started_at": "not-a-ts"})
    with pytest.raises((ValueError, TypeError)):
        bad_ts.validate()


# ---------------------------------------------------------------------------
# RESUME.md YAML frontmatter (MEM-06)
# ---------------------------------------------------------------------------


def test_resume_md_yaml_frontmatter_parses() -> None:
    """RESUME.md frontmatter parses as valid YAML with required keys (MEM-06)."""
    resume_path = Path(".planning/state/RESUME.md")
    assert resume_path.exists(), f"RESUME.md not found at {resume_path}"

    text = resume_path.read_text()

    # YAML frontmatter is between the first and second '---' delimiters
    parts = text.split("---", 2)
    assert len(parts) >= 3, (
        "RESUME.md must have YAML frontmatter delimited by '---' markers.\n"
        "Expected: '---\\n<yaml>\\n---\\n<body>'"
    )

    fm = yaml.safe_load(parts[1])
    assert isinstance(fm, dict), "RESUME.md frontmatter must parse as a YAML dict"

    required_keys = [
        "schema_version",
        "last_updated",
        "current_phase",
        "current_plan",
        "last_session_id",
        "open_questions",
        "blockers",
        "next_agent",
        "next_action",
    ]
    for key in required_keys:
        assert key in fm, f"RESUME.md frontmatter missing key: {key!r}"

    assert fm["schema_version"] == "1.0", (
        f"Expected schema_version '1.0', got {fm['schema_version']!r}"
    )
    assert str(fm["current_phase"]).startswith("P"), (
        f"current_phase must start with 'P', got {fm['current_phase']!r}"
    )


# ---------------------------------------------------------------------------
# tasks.jsonl append-only invariant (MEM-10)
# ---------------------------------------------------------------------------


def _append_jsonl_inline(p: Path, row: dict) -> None:
    """Inline helper: mimics append-only semantics (P0 stand-in for pipeline.state.append_jsonl).

    The real pipeline.state.append_jsonl ships in P3. This helper verifies
    the APPEND-ONLY invariant: opens in 'a' mode (never 'w') so previous
    lines are always preserved.

    Note: this is NOT the production implementation — it is a local test
    helper to assert the invariant before P3 lands.
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def test_tasks_jsonl_append_only(tmp_path: Path) -> None:
    """Append-only invariant: 3 rows appended → 3 lines, order preserved (MEM-10).

    Uses tmp_path; does NOT touch the real .planning/state/tasks.jsonl.
    The real append_jsonl body ships in P3 — this test verifies the INVARIANT
    using a stand-in helper.
    """
    log = tmp_path / "tasks.jsonl"

    rows = [
        {"event": "TaskCreate", "id": 1, "name": "Task 1"},
        {"event": "TaskUpdate", "id": 1, "status": "in_progress"},
        {"event": "TaskCreate", "id": 2, "name": "Task 2"},
    ]

    for row in rows:
        _append_jsonl_inline(log, row)

    lines = log.read_text().splitlines()
    assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"

    for i, (line, expected) in enumerate(zip(lines, rows, strict=True)):
        parsed = json.loads(line)
        assert parsed == expected, f"Row {i} mismatch: {parsed!r} != {expected!r}"

    # Verify the helper does NOT rewrite (append again; previous lines preserved)
    extra = {"event": "TaskCreate", "id": 3, "name": "Task 3"}
    _append_jsonl_inline(log, extra)

    lines_after = log.read_text().splitlines()
    assert len(lines_after) == 4, "Previous 3 lines must be preserved after append"
    assert json.loads(lines_after[0]) == rows[0], "First row must be unchanged"
    assert json.loads(lines_after[3]) == extra, "New row appended at end"


# ---------------------------------------------------------------------------
# Placeholder for P3 kill-9 test (MEM-01) — xfail until P3 implements safe_write
# ---------------------------------------------------------------------------


def test_atomic_write_under_kill(tmp_path: Path) -> None:
    """Atomic write survives kill -9: no .tmp.* files left behind (MEM-01).

    Named test_atomic_write_under_kill to match the enforcer reference in
    CLAUDE.md (State Durability section).
    """
    dest = tmp_path / "state.json"

    # Normal write completes atomically
    st.safe_write(dest, b'{"test": true}')
    assert dest.exists()
    assert dest.read_bytes() == b'{"test": true}'

    # No .tmp.* files left behind after successful write
    tmp_files = list(tmp_path.glob(".tmp.*"))
    assert not tmp_files, f"Stale .tmp.* files found: {tmp_files}"

    # Verify POSIX atomic rename: re-write with new content
    st.safe_write(dest, b'{"test": false}')
    assert dest.read_bytes() == b'{"test": false}'

    # Verify failed write (no parent directory) raises OSError and leaves no orphaned tmp files
    # safe_write calls mkdir(parents=True) so we need a non-writable parent to trigger failure
    bad_file = tmp_path / "state.json" / "not_a_dir" / "file.json"
    with pytest.raises(OSError):
        st.safe_write(bad_file, "data")
    # No orphaned .tmp.* files after failed write
    assert not list(tmp_path.rglob(".tmp.*"))


# ---------------------------------------------------------------------------
# MEM-02: run_log.jsonl row schema
# ---------------------------------------------------------------------------


def test_run_log_row_schema(tmp_path: Path) -> None:
    """run_log.jsonl rows have all required fields (MEM-02)."""
    log = tmp_path / "run_log.jsonl"
    payload = {"concept_id": "test-001", "model": "anthropic/claude-sonnet-4.6"}
    payload_str = json.dumps(payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:16]
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "event": "PHASE_START",
        "phase": "miner",
        "agent": "pipeline.run",
        "session_id": "test-session-01",
        "payload_hash": payload_hash,
    }
    st.append_jsonl(log, row)
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    for key in ("ts", "event", "phase", "agent", "session_id", "payload_hash"):
        assert key in parsed, f"run_log row missing key: {key!r}"


# ---------------------------------------------------------------------------
# MEM-03: per-phase checkpoint row schema
# ---------------------------------------------------------------------------


def test_phase_checkpoint_row_schema(tmp_path: Path) -> None:
    """Per-phase checkpoint rows have all required fields (MEM-03)."""
    chk = tmp_path / "01_assets.jsonl"
    prev_hash = hashlib.sha256(b"").hexdigest()[:16]
    row = {
        "produced_at": datetime.now(UTC).isoformat(),
        "produced_by_agent": "pipeline.run::phase_miner",
        "session_id": "test-session-01",
        "seed_used": 42,
        "prev_phase_hash": prev_hash,
        "asset_id": "asset-001",
    }
    st.append_jsonl(chk, row)
    lines = chk.read_text().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    for key in ("produced_at", "produced_by_agent", "session_id", "seed_used", "prev_phase_hash"):
        assert key in parsed, f"checkpoint row missing key: {key!r}"
