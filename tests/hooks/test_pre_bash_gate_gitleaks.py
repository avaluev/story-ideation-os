"""Pin the fail-CLOSED gitleaks contract in pre_bash_gate.py (SEC-04).

The hook used to fail OPEN: when gitleaks was absent it warned and ALLOWED the
push. Combined with the cwd-relative-hook deadlock, a wedged hook could let
plaintext keys reach the remote. It now fails CLOSED -- a missing scanner BLOCKS
the push unless the operator consciously sets the override env var. These tests
make that contract a regression gate (the .sh battery only covers the
gitleaks-present path).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "pre_bash_gate.py"
_spec = importlib.util.spec_from_file_location("pre_bash_gate_under_test", _HOOK)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_gitleaks_missing_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(gate._ALLOW_NO_GITLEAKS_ENV, raising=False)
    msg = gate._gitleaks_missing()
    assert msg is not None
    assert "BLOCKED" in msg


def test_gitleaks_missing_override_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gate._ALLOW_NO_GITLEAKS_ENV, "1")
    assert gate._gitleaks_missing() is None


def test_run_gitleaks_ignores_non_push() -> None:
    assert gate._run_gitleaks("git status") is None
    assert gate._run_gitleaks("uv run pytest tests/") is None


def test_project_root_prefers_claude_project_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "/srv/project-root-sentinel"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", sentinel)
    assert gate._project_root() == sentinel
