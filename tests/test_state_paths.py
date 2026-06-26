"""tests/test_state_paths.py — assert .planning/state/ git-tracked, data/state/ ignored (MEM-11).

MEM-11: data/state/ (gitignored) holds runtime state;
        .planning/state/ (git-tracked) holds planning state.

Tests:
  test_planning_state_tracked     — git ls-files shows all 4 planning-state files
  test_data_state_ignored         — git check-ignore: data/state/ + data/run_log.jsonl ignored
  test_planning_state_NOT_in_data — .planning/state/ NOT ignored; data/state/ IS ignored
  test_runtime_paths_in_module_constants — RUNTIME_STATE_DIR + RUN_LOG match MEM-11 spec
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import pipeline.state as st


def _in_git_repo() -> bool:
    """Return True if CWD is inside a git repository."""
    r = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode == 0


def test_planning_state_tracked() -> None:
    """All 4 .planning/state files are git-tracked (MEM-11)."""
    if not _in_git_repo():
        pytest.skip("Not inside a git repo")

    r = subprocess.run(
        ["git", "ls-files", ".planning/state/"],
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = r.stdout.strip().splitlines()

    expected = [
        ".planning/state/RESUME.md",
        ".planning/state/handoffs/.gitkeep",
        ".planning/state/sessions/.gitkeep",
        ".planning/state/tasks.jsonl",
    ]
    for path in expected:
        assert path in tracked, (
            f"{path!r} is NOT git-tracked.\n"
            f"Currently tracked: {tracked}\n"
            f"MEM-11 requires .planning/state/ to be git-tracked."
        )


def test_data_state_ignored() -> None:
    """data/state/ and data/run_log.jsonl are gitignored (MEM-11)."""
    if not _in_git_repo():
        pytest.skip("Not inside a git repo")

    # git check-ignore returns 0 if path is ignored, 1 if NOT ignored, 128 on error
    r_state = subprocess.run(
        ["git", "check-ignore", "-v", "data/state/foo.jsonl"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_state.returncode == 0, (
        "data/state/foo.jsonl is NOT gitignored.\n"
        f"git check-ignore output: {r_state.stdout!r} {r_state.stderr!r}\n"
        "MEM-11 requires data/state/ to be gitignored."
    )

    r_log = subprocess.run(
        ["git", "check-ignore", "-v", "data/run_log.jsonl"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_log.returncode == 0, (
        "data/run_log.jsonl is NOT gitignored.\n"
        f"git check-ignore output: {r_log.stdout!r} {r_log.stderr!r}\n"
        "MEM-11 requires data/run_log.jsonl to be gitignored."
    )


def test_planning_state_NOT_in_data() -> None:
    """.planning/state/ is NOT gitignored; data/state/ IS gitignored (MEM-11)."""
    if not _in_git_repo():
        pytest.skip("Not inside a git repo")

    # .planning/state/RESUME.md must NOT be ignored (returncode 1 = not ignored)
    r_planning = subprocess.run(
        ["git", "check-ignore", "-v", ".planning/state/RESUME.md"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_planning.returncode != 0, (
        ".planning/state/RESUME.md IS gitignored — it should NOT be.\n"
        f"git check-ignore output: {r_planning.stdout!r}\n"
        "MEM-11 requires .planning/state/ to be git-tracked, not ignored."
    )

    # data/state/ must be ignored (returncode 0 = ignored)
    r_data = subprocess.run(
        ["git", "check-ignore", "-v", "data/state/"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_data.returncode == 0, (
        "data/state/ is NOT gitignored — it should be.\n"
        f"git check-ignore output: {r_data.stdout!r}\n"
        "MEM-11 requires data/state/ to be gitignored."
    )


def test_runtime_paths_in_module_constants() -> None:
    """RUNTIME_STATE_DIR and RUN_LOG constants in pipeline.state match MEM-11 spec."""
    assert Path("data/state") == st.RUNTIME_STATE_DIR, (
        f"RUNTIME_STATE_DIR is {st.RUNTIME_STATE_DIR!r}, expected Path('data/state').\n"
        "MEM-11: runtime state lives in data/state/ (gitignored)."
    )
    assert Path("data/run_log.jsonl") == st.RUN_LOG, (
        f"RUN_LOG is {st.RUN_LOG!r}, expected Path('data/run_log.jsonl').\n"
        "MEM-11: run log lives in data/run_log.jsonl (gitignored)."
    )
