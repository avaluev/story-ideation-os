"""Tests for pipeline.single_idea.SingleIdeaOrchestrator (mocked, no LLM).

SKIP until Wave C creates pipeline/single_idea.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_mod = pytest.importorskip("pipeline.single_idea", reason="defensive import guard")
SingleIdeaOrchestrator = _mod.SingleIdeaOrchestrator


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "runs" / "2026-05-12-000000-test-theme"
    d.mkdir(parents=True)
    return d


class TestSingleIdeaOrchestratorInit:
    def test_instantiation(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch is not None

    def test_run_dir_stored_as_path(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert isinstance(orch.run_dir, Path)

    def test_theme_stored(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="station tolerance")
        assert orch.theme == "station tolerance"

    def test_current_phase_starts_at_zero(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.current_phase == 0

    def test_is_halted_false_initially(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.is_halted is False


class TestPhaseDefinitions:
    def test_ten_phases_defined(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert len(orch.phase_names) == 10

    def test_phase_0_is_seed_capture(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.phase_names[0] == "seed_capture"

    def test_phase_1_is_research(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.phase_names[1] == "research"

    def test_phase_2_is_draft_v0(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.phase_names[2] == "draft_v0"

    def test_phase_7_is_investor_narrator(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.phase_names[7] == "investor_narrator"

    def test_phase_8_is_eval_gate(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.phase_names[8] == "eval_gate"

    def test_phase_9_is_lessons_capture(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert orch.phase_names[9] == "lessons_capture"


class TestSidecarPaths:
    def test_seed_sidecar_defined(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert "seed" in orch.sidecar_paths

    def test_research_sidecar_defined(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert "research" in orch.sidecar_paths

    def test_challenge_sidecar_defined(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        assert "challenge" in orch.sidecar_paths

    def test_all_sidecar_paths_under_run_dir(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        for path in orch.sidecar_paths.values():
            assert str(run_dir) in str(path)


class TestResumeLogic:
    def test_resume_skips_completed_phases(self, run_dir: Path) -> None:
        (run_dir / "seed.json").write_text(json.dumps({"theme": "test"}))
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme", resume=True)
        assert orch.current_phase >= 1

    def test_no_resume_starts_from_zero(self, run_dir: Path) -> None:
        (run_dir / "seed.json").write_text(json.dumps({"theme": "test"}))
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme", resume=False)
        assert orch.current_phase == 0


class TestHaltBehavior:
    def test_halt_sets_is_halted_true(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        orch.halt(reason="test halt")
        assert orch.is_halted is True

    def test_halt_stores_reason(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        orch.halt(reason="SOM below gate")
        assert orch.halt_reason == "SOM below gate"


class TestPhaseAdvancement:
    def test_mark_phase_complete_advances_counter(self, run_dir: Path) -> None:
        orch = SingleIdeaOrchestrator(run_dir=run_dir, theme="test theme")
        (run_dir / "seed.json").write_text(json.dumps({"theme": "test"}))
        orch._mark_phase_complete(0)
        assert orch.current_phase == 1
