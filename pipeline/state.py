"""State substrate for the Anomaly Engine.

ADR-0001: State lives on disk (not in agent context). This module is the
single entry-point for all durability I/O.

REQ-IDs: MEM-04, MEM-05, MEM-06, MEM-07, MEM-08, MEM-10, MEM-11.

**Implemented I/O (P3+):** safe_write (atomic tmp+fsync+rename), append_jsonl
(O_APPEND), write_handoff, write_checkpoint, bump_session_checkpoint,
read_resume, latest_checkpoint, latest_handoff_for. Dataclass schemas carry
working validators. The kill-9 recovery path is exercised end-to-end by
evals/test_resume.py against the runtime pipeline.

**MUST NOT import:** anthropic, httpx, openai, or any LLM client.
Enforced by: ANOMALY-001 in scripts/lint_imports.py.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants (MEM-11)
# ---------------------------------------------------------------------------

STATE_DIR = Path(".planning/state")
SESSIONS_DIR = STATE_DIR / "sessions"
HANDOFFS_DIR = STATE_DIR / "handoffs"
RESUME_PATH = STATE_DIR / "RESUME.md"
TASKS_LOG = STATE_DIR / "tasks.jsonl"
RUNTIME_STATE_DIR = Path("data/state")
RUN_LOG = Path("data/run_log.jsonl")

# ---------------------------------------------------------------------------
# Schema constants (used by HandoffContract.validate and SessionCheckpoint.validate)
# ---------------------------------------------------------------------------

_SESSION_ID_MIN = 8
_SESSION_ID_MAX = 64
_NEXT_ACTION_MAX = 500
_NOTES_MAX = 5000
_AGENT_NAME_MIN = 2
_FRONTMATTER_PARTS = 3  # split("---", 2) yields [before, yaml, body]

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema dataclasses (functional in P0; used directly by round-trip tests)
# ---------------------------------------------------------------------------


@dataclass
class HandoffContract:
    """Per-agent handoff contract (MEM-05).

    When agent A returns, A writes one of these to
    ``.planning/state/handoffs/<from>_to_<to>_<ts>.json``.
    Agent B's first action is to read the latest such file.

    Shape documented in 00-RESEARCH.md §5.2.
    """

    schema_version: str
    from_agent: str
    to_agent: str
    handoff_ts: str  # ISO-8601 UTC
    session_id: str  # 8..64 chars
    produced: list[str] = field(default_factory=lambda: [])
    consumed: list[str] = field(default_factory=lambda: [])
    next_action: str = ""  # ≤500 chars
    assumptions_made: list[str] = field(default_factory=lambda: [])
    open_decisions: list[str] = field(default_factory=lambda: [])
    notes: str = ""  # ≤5000 chars

    def validate(self) -> None:
        """Raise ValueError if the contract violates invariants."""
        if not (_SESSION_ID_MIN <= len(self.session_id) <= _SESSION_ID_MAX):
            raise ValueError(f"session_id length must be 8..64, got {len(self.session_id)}")
        if len(self.next_action) > _NEXT_ACTION_MAX:
            raise ValueError("next_action max 500 chars")
        if len(self.notes) > _NOTES_MAX:
            raise ValueError("notes max 5000 chars")
        if len(self.from_agent) < _AGENT_NAME_MIN or len(self.to_agent) < _AGENT_NAME_MIN:
            raise ValueError("agent names must be >= 2 chars")
        # ISO-8601 sanity check
        datetime.fromisoformat(self.handoff_ts.replace("Z", "+00:00"))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HandoffContract:
        """Construct from a plain dict (e.g. parsed JSON)."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for json.dumps."""
        return asdict(self)


@dataclass
class SessionCheckpoint:
    """Per-session checkpoint snapshot (MEM-04).

    Written before any context-eating operation (PreCompact hook) and after
    each PostToolUse(Write|Edit) via bump_session_checkpoint.

    Stored at ``.planning/state/sessions/<session_id>/checkpoint.json``.
    Shape documented in 00-RESEARCH.md §6.2.
    """

    schema_version: str
    session_id: str  # 8..64 chars
    started_at: str  # ISO-8601
    last_updated_at: str  # ISO-8601
    current_phase: str
    current_plan: str | None = None
    pending_tasks: list[dict[str, Any]] = field(default_factory=lambda: [])
    open_questions: list[str] = field(default_factory=lambda: [])
    last_artifact_path: str | None = None
    last_commit_sha: str | None = None
    files_edited_this_session: list[str] = field(default_factory=lambda: [])
    handoffs_written: list[str] = field(default_factory=lambda: [])
    notes: str = ""

    def validate(self) -> None:
        """Raise ValueError if the checkpoint violates invariants."""
        if not (_SESSION_ID_MIN <= len(self.session_id) <= _SESSION_ID_MAX):
            raise ValueError("session_id length 8..64")
        datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        datetime.fromisoformat(self.last_updated_at.replace("Z", "+00:00"))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionCheckpoint:
        """Construct from a plain dict (e.g. parsed JSON)."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for json.dumps."""
        return asdict(self)


# ---------------------------------------------------------------------------
# I/O interface stubs (P0 — bodies raise NotImplementedError; P3 implements)
# ---------------------------------------------------------------------------


def safe_write(path: Path | str, content: str | bytes) -> None:
    """Atomic write via tmp + fsync + rename.

    POSIX rename(2) is atomic on the same filesystem.
    No partial writes are ever observable at the target path.

    See ADR-0001.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".tmp." + path.name)
    try:
        mode = "wb" if isinstance(content, bytes) else "w"
        encoding: str | None = None if isinstance(content, bytes) else "utf-8"
        with open(tmp, mode, encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def append_jsonl(path: Path | str, row: dict[str, Any]) -> None:
    """Append one JSON object as a newline-delimited record.

    Uses O_APPEND for atomic per-line semantics.
    Never rewrites or compacts the log.

    See ADR-0001.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def write_handoff(from_agent: str, to_agent: str, payload: dict[str, Any]) -> Path:
    """Write a HandoffContract JSON file via safe_write.

    Returns the Path written. Filename convention:
    ``<from>_to_<to>_<ts>.json`` under HANDOFFS_DIR.

    See MEM-05.
    """
    ts_str = datetime.now(UTC).isoformat()
    contract = HandoffContract.from_dict(
        {
            "schema_version": "1.0",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "handoff_ts": ts_str,
            **payload,
        }
    )
    contract.validate()
    ts_filename = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{from_agent}_to_{to_agent}_{ts_filename}.json"
    dest = HANDOFFS_DIR / filename
    safe_write(dest, json.dumps(contract.to_dict(), indent=2))
    return dest


def write_checkpoint(session_id: str, snapshot: dict[str, Any]) -> Path:
    """Write a SessionCheckpoint JSON file via safe_write.

    Returns the Path written. Stored at
    ``SESSIONS_DIR/<session_id>/checkpoint.json``.

    See MEM-04.
    """
    chk = SessionCheckpoint.from_dict({"session_id": session_id, **snapshot})
    chk.validate()
    dest = SESSIONS_DIR / session_id / "checkpoint.json"
    safe_write(dest, json.dumps(chk.to_dict(), indent=2))
    return dest


def bump_session_checkpoint(file_edited: str) -> None:
    """PostToolUse(Write|Edit) hook entry point.

    Called after every file write/edit to update the current session's
    checkpoint with the latest edited-file list and timestamp.

    See MEM-07.
    """
    chk_data = latest_checkpoint(my_agent="")
    if chk_data is None:
        return
    session_id = chk_data.get("session_id", "")
    if not session_id:
        return
    edited: list[str] = chk_data.get("files_edited_this_session", [])
    if file_edited not in edited:
        edited = [*edited, file_edited]
    updated = {
        **chk_data,
        "files_edited_this_session": edited,
        "last_updated_at": datetime.now(UTC).isoformat(),
    }
    write_checkpoint(session_id, updated)


def read_resume() -> dict[str, Any]:
    """Parse RESUME.md YAML frontmatter and return as a dict.

    Returns the frontmatter only (not the human-readable body).

    See MEM-06.
    """

    text = RESUME_PATH.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < _FRONTMATTER_PARTS:
        return {}
    result: dict[str, Any] = yaml.safe_load(parts[1]) or {}
    return result


def latest_checkpoint(my_agent: str) -> dict[str, Any] | None:
    """Return the most recent session checkpoint dict, or None if none exists.

    Scans SESSIONS_DIR for all checkpoint.json files and returns the one
    with the newest last_updated_at timestamp.

    See MEM-04.
    """
    best: dict[str, Any] | None = None
    best_ts = ""
    if not SESSIONS_DIR.exists():
        return None
    for chk_file in SESSIONS_DIR.glob("*/checkpoint.json"):
        try:
            data: dict[str, Any] = json.loads(chk_file.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("Skipping unreadable checkpoint %s: %s", chk_file, exc)
            continue
        ts = str(data.get("last_updated_at", ""))
        if ts > best_ts:
            best_ts = ts
            best = data
    return best


def latest_handoff_for(my_agent: str) -> dict[str, Any] | None:
    """Return the most recent handoff dict targeted at my_agent, or None.

    Scans HANDOFFS_DIR for ``*_to_<my_agent>_*.json`` and returns the
    most recently written one.

    See MEM-05.
    """
    if not HANDOFFS_DIR.exists():
        return None
    pattern = f"*_to_{my_agent}_*.json"
    candidates = sorted(HANDOFFS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None
    try:
        result: dict[str, Any] = json.loads(candidates[-1].read_text(encoding="utf-8"))
        return result
    except Exception:
        return None
