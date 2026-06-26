"""tests/test_e2e_smoke.py — end-to-end smoke test for --phase miner (PIPE-07, PIPE-08).

Verifies that the Typer CLI wires up correctly and that --phase miner runs
end-to-end with mocked HTTP and state calls without exiting non-zero.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from pipeline.run import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2026, 5, 7, 12, 0, 0, tzinfo=datetime.UTC).isoformat()

# A minimal valid Phase1Assets payload (matches schema fields exactly)
_MOCK_ASSET = {
    "asset_id": "SMOKE-001",
    "asset_name": "The Iron Atlas",
    "domain": "legal",
    "theme": "test",
    "source_url": "https://example.com/test-asset",
    "source_quote": "A short source quote here max words",
    "untapped_check_passed": True,
    "produced_at": _NOW,
    "session_id": "smoke-test-session",
    "total_score": None,
}


def _make_mock_client(asset: dict[str, Any] | None = None) -> MagicMock:
    """Return a MagicMock configured to stand in for OpenRouterClient.

    chat() returns a dict with 'assets' key so _run_miner processes it.
    """
    mock_client = MagicMock()
    payload = asset or _MOCK_ASSET
    mock_client.chat.return_value = {"assets": [payload]}
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_smoke_phase_miner_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--phase miner runs end-to-end with mocked client and state (PIPE-07).

    Uses tmp_path to isolate data/ writes; monkeypatches the working-dir
    path constants in pipeline.run so files land under tmp_path.
    """
    runner = CliRunner()

    # Redirect data/ writes to tmp_path
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    # Provide required env vars so OpenRouterClient.__init__ doesn't raise
    monkeypatch.setenv("OPENROUTER_KEY_PAID", "sk-or-v1-smoketest-fake-key-for-tests")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_1", "")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_2", "")

    # frameworks/ and prompts/ must be resolvable by load_framework — use the
    # real directories from the project root (read-only; never mutated here).
    project_root = Path(__file__).parent.parent
    frameworks_src = project_root / "frameworks"
    prompts_src = project_root / "prompts"
    (tmp_path / "frameworks").symlink_to(frameworks_src)
    (tmp_path / "prompts").symlink_to(prompts_src)

    mock_client = _make_mock_client()

    with (
        patch("pipeline.run.OpenRouterClient", return_value=mock_client),
        patch("pipeline.run.append_jsonl") as mock_append,
        patch("pipeline.run.safe_write"),
    ):
        mock_append.return_value = None
        result = runner.invoke(
            app,
            ["--phase", "miner", "--theme", "test", "--n", "1", "--seed", "42"],
        )

    assert result.exit_code == 0, f"Smoke test exited {result.exit_code}:\n{result.output}"


def test_smoke_phase_miner_calls_chat_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Miner phase calls client.chat() exactly once when --n 1 (PIPE-07)."""
    runner = CliRunner()

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("OPENROUTER_KEY_PAID", "sk-or-v1-smoketest-fake-key-for-tests")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_1", "")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_2", "")

    project_root = Path(__file__).parent.parent
    (tmp_path / "frameworks").symlink_to(project_root / "frameworks")
    (tmp_path / "prompts").symlink_to(project_root / "prompts")

    mock_client = _make_mock_client()

    with (
        patch("pipeline.run.OpenRouterClient", return_value=mock_client),
        patch("pipeline.run.append_jsonl"),
        patch("pipeline.run.safe_write"),
    ):
        runner.invoke(
            app,
            ["--phase", "miner", "--theme", "test", "--n", "1", "--seed", "42"],
        )

    mock_client.chat.assert_called_once()


def test_smoke_unknown_phase_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown --phase value exits with code 1 (PIPE-07 CLI validation)."""
    runner = CliRunner()
    monkeypatch.setenv("OPENROUTER_KEY_PAID", "sk-or-v1-smoketest-fake-key-for-tests")

    with patch("pipeline.run.OpenRouterClient"):
        result = runner.invoke(app, ["--phase", "nonexistent_phase"])

    assert result.exit_code == 1, f"Expected exit 1 for bad phase; got {result.exit_code}"


def test_smoke_miner_requires_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--phase miner without --theme exits with code 1 (PIPE-07 guard)."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("OPENROUTER_KEY_PAID", "sk-or-v1-smoketest-fake-key-for-tests")

    project_root = Path(__file__).parent.parent
    (tmp_path / "frameworks").symlink_to(project_root / "frameworks")
    (tmp_path / "prompts").symlink_to(project_root / "prompts")

    mock_client = _make_mock_client()

    with (
        patch("pipeline.run.OpenRouterClient", return_value=mock_client),
        patch("pipeline.run.append_jsonl"),
        patch("pipeline.run.safe_write"),
    ):
        result = runner.invoke(app, ["--phase", "miner"])

    assert result.exit_code == 1, f"Expected exit 1 when --theme missing; got {result.exit_code}"


def test_smoke_multi_phase_mapper_after_miner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase mapper runs after miner and reads 01_assets.jsonl (TEST-05 multi-phase)."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("OPENROUTER_KEY_PAID", "sk-or-v1-smoketest-fake-key-for-tests")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_1", "")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_2", "")

    project_root = Path(__file__).parent.parent
    (tmp_path / "frameworks").symlink_to(project_root / "frameworks")
    (tmp_path / "prompts").symlink_to(project_root / "prompts")

    # Seed 01_assets.jsonl so mapper has input to read

    asset_row = {**_MOCK_ASSET}
    (tmp_path / "data" / "01_assets.jsonl").write_text(json.dumps(asset_row) + "\n")

    # mapper returns a Phase2JTBD-compatible dict
    mock_jtbd_response = {
        "asset_id": "SMOKE-001",
        "job_statement": "When I seek identity I want validation",
        "primary_need": "relatedness",
        "primary_strength": 0.80,
        "secondary_need": "competence",
        "secondary_strength": 0.50,
        "deprivation_amplifier_active": True,
        "jtbd_notes": "smoke test",
        "total_score": None,
    }
    mock_client = MagicMock()
    mock_client.chat.return_value = mock_jtbd_response

    with (
        patch("pipeline.run.OpenRouterClient", return_value=mock_client),
        patch("pipeline.run.append_jsonl") as mock_append,
        patch("pipeline.run.safe_write"),
    ):
        mock_append.return_value = None
        result = runner.invoke(app, ["--phase", "mapper"])

    assert result.exit_code == 0, f"mapper phase failed:\n{result.output}"


def test_smoke_run_log_entries_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Miner phase writes START and DONE events to run_log.jsonl (TEST-05 log check)."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("OPENROUTER_KEY_PAID", "sk-or-v1-smoketest-fake-key-for-tests")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_1", "")
    monkeypatch.setenv("OPENROUTER_KEY_FREE_2", "")

    project_root = Path(__file__).parent.parent
    (tmp_path / "frameworks").symlink_to(project_root / "frameworks")
    (tmp_path / "prompts").symlink_to(project_root / "prompts")

    # Capture actual append_jsonl calls
    log_rows: list[dict] = []

    def _capture_append(path: object, row: object) -> None:
        if "run_log" in str(path):
            log_rows.append(row)  # type: ignore[arg-type]

    mock_client = _make_mock_client()

    with (
        patch("pipeline.run.OpenRouterClient", return_value=mock_client),
        patch("pipeline.run.append_jsonl", side_effect=_capture_append),
        patch("pipeline.run.safe_write"),
    ):
        result = runner.invoke(
            app,
            ["--phase", "miner", "--theme", "test", "--n", "1", "--seed", "42"],
        )

    assert result.exit_code == 0, f"Smoke test failed:\n{result.output}"
    events = [r.get("event") for r in log_rows if isinstance(r, dict)]
    assert "START" in events, f"Expected START event in run_log; got: {events}"
    assert "DONE" in events, f"Expected DONE event in run_log; got: {events}"
