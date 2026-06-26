"""Shared pytest fixtures for Anomaly Engine v3.0 tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _hermetic_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank LLM provider keys for every test so ``pipeline.llm_client.build_chat_client``
    never makes a real 302.ai / OpenRouter call from a populated ``.env``.

    Without this, a live ``TAO_AI_API_KEY`` in ``.env`` makes any test that triggers a
    generation/research LLM call hit the network (slow 503 retry storms, non-deterministic).
    Tests that genuinely need a key set it via ``monkeypatch.setenv`` in the test body,
    which runs after this autouse fixture and therefore wins.
    """
    for var in (
        "TAO_AI_API_KEY",
        "TAO_AI_PRIMARY",
        "TAO_AI_MODEL_OVERRIDES",
        "OPENROUTER_API_KEY",
        "OPENROUTER_KEY_PAID",
        "OPENROUTER_KEY_FREE_1",
        "OPENROUTER_KEY_FREE_2",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _isolate_axis_frequency_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect the ADR-0012 frequency log to a per-test tmp file so the suite
    never writes to the live, gitignored ``data/axis_frequency.jsonl``.

    Without this, every evolve/one_shot test that records survivor axes appends
    degenerate single-run rows to the real log; the R1 raw-sampler ceiling gate
    (``tests/test_anti_overfit_ceiling.py``) would then trip on test noise
    instead of a deliberate batch. The gate is meant to audit a real
    ``run_format_slate`` / evolve batch (run OUTSIDE pytest), so the live log
    stays cold-start during ``make test`` and the gate correctly SKIPS.

    Tests that pass an explicit ``path=`` still win (the wrapper only supplies a
    default). Only ``pipeline.evolve.one_shot`` reaches the no-path default.
    """
    from pipeline import diversity  # noqa: PLC0415

    real_record = diversity.record_sample
    tmp_log = tmp_path / "axis_frequency.jsonl"

    def _redirected(axis: str, value_id: str, run_id: str, *, path: Path | str = tmp_log) -> None:
        real_record(axis, value_id, run_id, path=path)

    monkeypatch.setattr(diversity, "record_sample", _redirected)


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Yield a clean .planning/state/ skeleton in tmp_path.

    Creates the standard subdirectories (sessions/, handoffs/) and a stub RESUME.md.
    Callers can write files into this dir without polluting the real state.
    """
    state_dir = tmp_path / ".planning" / "state"
    sessions_dir = state_dir / "sessions"
    handoffs_dir = state_dir / "handoffs"
    sessions_dir.mkdir(parents=True)
    handoffs_dir.mkdir(parents=True)

    # Seed a minimal RESUME.md with required YAML frontmatter
    resume = state_dir / "RESUME.md"
    resume.write_text(
        "---\n"
        'schema_version: "1.0"\n'
        'last_updated: "2026-05-06T20:00:00Z"\n'
        'current_phase: "P0"\n'
        'current_plan: "00-02"\n'
        'last_session_id: "test-session"\n'
        'last_commit_sha: "abc1234"\n'
        "open_questions: []\n"
        "blockers: []\n"
        'next_agent: "builder-engine"\n'
        'next_action: "Run tests."\n'
        "---\n\n"
        "# Resume Bridge — Test Fixture\n"
    )

    yield state_dir


@pytest.fixture
def mock_pipeline_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Patch pipeline.state module functions to write into tmp_path.

    Returns tmp_path so tests can read back written files.
    This fixture is a forward-compatible stub — plan 00-04 creates pipeline/state.py;
    until then, this patches the not-yet-existent module.
    """
    state_dir = tmp_path / ".planning" / "state"
    state_dir.mkdir(parents=True)

    try:
        import pipeline.state as _state_mod  # noqa: F401, PLC0415

        monkeypatch.setattr(
            "pipeline.state.safe_write",
            lambda path, content: Path(tmp_path / Path(path).name).write_bytes(
                content if isinstance(content, bytes) else content.encode()
            ),
        )
        monkeypatch.setattr(
            "pipeline.state.append_jsonl",
            lambda path, row: None,
        )
    except ImportError:
        # pipeline.state not yet created (lands in plan 00-04); this fixture is a stub
        pass

    return tmp_path
