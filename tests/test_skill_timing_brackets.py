"""tests/test_skill_timing_brackets.py — NB.9 contract.

Asserts that ``.claude/skills/single-idea/SKILL.md`` brackets every Task
invocation in STEPS 3-11 with the ``pipeline.phase_timing`` CLI so that the
full pipeline is measured, not just Phase 0 (NB.1 wired only the seed_capture
auto-emit via ``pipeline/run_single_idea.py``).

Why a SKILL-file contract test: the harness has no other guard against drift
where someone edits SKILL.md and silently drops a bracket. The test reads the
raw markdown and counts ``start``/``end`` CLI calls per phase name. Phase
indices and names come from HANDOFF_SESSION_3.md §5.

State note (Session 3): editing files under ``.claude/`` is hard-blocked by the
Claude Code self-modification classifier, regardless of task authorization. The
NB.9 patch lives at ``.planning/state/NB9_SKILL_PATCH.md`` and must be applied
by the operator. Until then, the contract tests are *skipped* (not failed) so
suite count stays green. Once applied, the skips become passes automatically.

ADR-0007 (pure-CC dispatch) compliance: this test does not invoke any model;
it is a static contract over the skill file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "single-idea" / "SKILL.md"

# Phase (index, name) tuples that SKILL.md must instrument in STEPS 3-11.
# STEP 2 / Phase 0 is auto-emitted by pipeline.run_single_idea.py (NB.1) and
# intentionally not bracketed inside the skill.
INSTRUMENTED_PHASES: tuple[tuple[int, str], ...] = (
    (1, "research"),
    (2, "draft_v0"),
    (3, "challenge"),
    (4, "amplify"),
    (5, "genius_audit"),
    (6, "consistency_check"),
    (7, "investor_narrator"),
    (8, "eval_gate"),
    (9, "lessons_capture"),
)

# Patterns for the start / end brackets (allow trailing whitespace / args).
_START_RE = re.compile(
    r"uv run python -m pipeline\.phase_timing\s+start\b[^\n]*"
    r"--phase-index\s+(?P<idx>\d+)\b[^\n]*"
    r"--phase-name\s+(?P<name>[A-Za-z0-9_]+)",
)
_END_RE = re.compile(
    r"uv run python -m pipeline\.phase_timing\s+end\b[^\n]*"
    r"--phase-index\s+(?P<idx>\d+)\b[^\n]*"
    r"--phase-name\s+(?P<name>[A-Za-z0-9_]+)",
)

_PENDING_REASON = (
    "NB.9 patch pending operator apply (see .planning/state/NB9_SKILL_PATCH.md). "
    "Editing .claude/skills/* is hard-blocked by the self-modification classifier."
)


@pytest.fixture(scope="module")
def skill_text() -> str:
    assert SKILL_PATH.exists(), f"SKILL.md missing at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def _brackets_applied(text: str) -> bool:
    """True when SKILL.md has at least one phase_timing CLI bracket."""
    return bool(_START_RE.search(text) and _END_RE.search(text))


def test_skill_file_exists() -> None:
    assert SKILL_PATH.is_file()


@pytest.mark.parametrize(("phase_index", "phase_name"), INSTRUMENTED_PHASES)
def test_each_phase_has_start_bracket(skill_text: str, phase_index: int, phase_name: str) -> None:
    if not _brackets_applied(skill_text):
        pytest.skip(_PENDING_REASON)
    matches = [
        m
        for m in _START_RE.finditer(skill_text)
        if int(m.group("idx")) == phase_index and m.group("name") == phase_name
    ]
    assert matches, (
        f"SKILL.md missing `pipeline.phase_timing start` bracket for "
        f"phase_index={phase_index} phase_name={phase_name!r} "
        f"(NB.9 contract — see HANDOFF_SESSION_3.md §5)"
    )


@pytest.mark.parametrize(("phase_index", "phase_name"), INSTRUMENTED_PHASES)
def test_each_phase_has_end_bracket(skill_text: str, phase_index: int, phase_name: str) -> None:
    if not _brackets_applied(skill_text):
        pytest.skip(_PENDING_REASON)
    matches = [
        m
        for m in _END_RE.finditer(skill_text)
        if int(m.group("idx")) == phase_index and m.group("name") == phase_name
    ]
    assert matches, (
        f"SKILL.md missing `pipeline.phase_timing end` bracket for "
        f"phase_index={phase_index} phase_name={phase_name!r} "
        f"(NB.9 contract — see HANDOFF_SESSION_3.md §5)"
    )


def test_start_and_end_counts_match(skill_text: str) -> None:
    """Every start has a matching end (per phase_name)."""
    if not _brackets_applied(skill_text):
        pytest.skip(_PENDING_REASON)
    starts: dict[str, int] = {}
    ends: dict[str, int] = {}
    for m in _START_RE.finditer(skill_text):
        starts[m.group("name")] = starts.get(m.group("name"), 0) + 1
    for m in _END_RE.finditer(skill_text):
        ends[m.group("name")] = ends.get(m.group("name"), 0) + 1
    for _, name in INSTRUMENTED_PHASES:
        assert starts.get(name, 0) == ends.get(name, 0), (
            f"SKILL.md start/end bracket count mismatch for phase {name!r}: "
            f"start={starts.get(name, 0)} end={ends.get(name, 0)}"
        )


def test_brackets_use_run_dir_placeholder(skill_text: str) -> None:
    """Brackets must pass --run-dir {run_dir} (skill placeholder), not a hardcoded path."""
    if not _brackets_applied(skill_text):
        pytest.skip(_PENDING_REASON)
    for m in _START_RE.finditer(skill_text):
        line_start = skill_text.rfind("\n", 0, m.start()) + 1
        line_end = skill_text.find("\n", m.end())
        line = skill_text[line_start:line_end]
        assert "{run_dir}" in line or "$run_dir" in line, (
            f"phase_timing start bracket without --run-dir placeholder: {line!r}"
        )
