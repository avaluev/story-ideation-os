"""tests/test_key_manager_302.py — 302.ai key diagnostics + evidence router keys.

Verifies that diagnose() PASSes on a 302.ai-only setup (since 302.ai is now the
primary provider), FAILs when no chat provider key is present, and that the
live-style diagnose_302() smoke returns True when the client round-trips.

Also tests the four new evidence-router resolver functions and confirms that
diagnose() reports masked status for EXA_API_KEY, SERPER_API_KEY, JINA_API_KEY,
and AIML_API_KEY.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from pipeline import key_manager
from pipeline.research import client_302ai

# ── Existing 302.ai diagnostics tests ────────────────────────────────────────


def test_diagnose_passes_with_only_tao(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENROUTER_KEY_PAID", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao-key-123456")

    report = key_manager.diagnose()

    assert report["overall"] == "PASS"
    chat_provider = report["CHAT_PROVIDER"]
    assert isinstance(chat_provider, dict)
    assert chat_provider["primary"] == "302.ai"


def test_diagnose_fails_with_no_chat_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENROUTER_KEY_PAID", "OPENROUTER_API_KEY", "TAO_AI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    report = key_manager.diagnose()

    assert report["overall"] == "FAIL"


def test_diagnose_302_returns_true_on_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao-key-123456")

    class _FakeClient:
        @classmethod
        def from_env(cls) -> _FakeClient:
            return cls()

        def chat(self, **kwargs: object) -> dict[str, object]:
            return {"ok": True}

    monkeypatch.setattr(client_302ai, "TaoAIClient", _FakeClient)

    assert key_manager.diagnose_302() is True


def test_diagnose_302_returns_false_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAO_AI_API_KEY", raising=False)
    assert key_manager.diagnose_302() is False


# ── Evidence-router resolver tests ───────────────────────────────────────────


def test_resolve_exa_key_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_exa_key() returns the env var value when set."""
    monkeypatch.setenv("EXA_API_KEY", "fake-exa-key-abc123")
    assert key_manager.resolve_exa_key() == "fake-exa-key-abc123"


def test_resolve_exa_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_exa_key() raises KeyError when EXA_API_KEY is not set."""
    monkeypatch.setenv("EXA_API_KEY", "")
    with pytest.raises(KeyError, match="EXA_API_KEY"):
        key_manager.resolve_exa_key()


def test_resolve_serper_key_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_serper_key() returns the env var value when set."""
    monkeypatch.setenv("SERPER_API_KEY", "fake-serper-key-xyz")
    assert key_manager.resolve_serper_key() == "fake-serper-key-xyz"


def test_resolve_serper_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_serper_key() raises KeyError when SERPER_API_KEY is not set."""
    monkeypatch.setenv("SERPER_API_KEY", "")
    with pytest.raises(KeyError, match="SERPER_API_KEY"):
        key_manager.resolve_serper_key()


def test_resolve_jina_key_tolerant(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_jina_key() returns '' when JINA_API_KEY is absent (tolerant)."""
    monkeypatch.setenv("JINA_API_KEY", "")
    assert key_manager.resolve_jina_key() == ""


def test_resolve_jina_key_returns_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_jina_key() returns the key when JINA_API_KEY is set."""
    monkeypatch.setenv("JINA_API_KEY", "fake-jina-key-abc")
    assert key_manager.resolve_jina_key() == "fake-jina-key-abc"


def test_resolve_aiml_key_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_aiml_key() returns the env var value when set."""
    monkeypatch.setenv("AIML_API_KEY", "fake-aiml-key-xyz")
    assert key_manager.resolve_aiml_key() == "fake-aiml-key-xyz"


def test_resolve_aiml_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_aiml_key() raises KeyError when AIML_API_KEY is not set."""
    monkeypatch.setenv("AIML_API_KEY", "")
    with pytest.raises(KeyError, match="AIML_API_KEY"):
        key_manager.resolve_aiml_key()


# ── diagnose() reports masked status for all four new keys ────────────────────


def test_diagnose_reports_evidence_router_keys_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """diagnose() includes EXA, SERPER, JINA, AIML in its report when all are set."""
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao-key-123456")
    monkeypatch.setenv("EXA_API_KEY", "fake-exa-key-abcdef")
    monkeypatch.setenv("SERPER_API_KEY", "fake-serper-keyxyz")
    monkeypatch.setenv("JINA_API_KEY", "fake-jina-key-12345")
    monkeypatch.setenv("AIML_API_KEY", "fake-aiml-key-67890")

    report = key_manager.diagnose()

    for key_name in ("EXA_API_KEY", "SERPER_API_KEY", "JINA_API_KEY", "AIML_API_KEY"):
        assert key_name in report, f"diagnose() report missing entry for {key_name}"
        entry = report[key_name]
        assert isinstance(entry, dict), f"{key_name} entry must be a dict"
        assert entry["found"] is True, f"{key_name} should be found=True when set"
        assert entry["via"] == key_name, f"{key_name} must be found via its own var name"


def test_diagnose_reports_evidence_router_keys_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """diagnose() includes EXA, SERPER, JINA, AIML with found=False when unset."""
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao-key-123456")
    for key_name in ("EXA_API_KEY", "SERPER_API_KEY", "JINA_API_KEY", "AIML_API_KEY"):
        monkeypatch.setenv(key_name, "")

    report = key_manager.diagnose()

    # Overall still PASS because 302.ai is present; evidence keys are optional.
    assert report["overall"] == "PASS"
    for key_name in ("EXA_API_KEY", "SERPER_API_KEY", "JINA_API_KEY", "AIML_API_KEY"):
        assert key_name in report, f"diagnose() report missing entry for {key_name}"
        entry = report[key_name]
        assert isinstance(entry, dict), f"{key_name} entry must be a dict"
        assert entry["found"] is False, f"{key_name} should be found=False when empty"


# ── generate_env_example() includes the 5 new Evidence Router vars ────────────


def test_generate_env_example_includes_evidence_router_vars() -> None:
    """generate_env_example() output must contain all 5 new Evidence Router vars.

    The 5 required names: EXA_API_KEY, SERPER_API_KEY, JINA_API_KEY,
    AIML_API_KEY, AIML_PRIMARY (as a key-or-commented mention), and
    RESEARCH_MAX_CONCURRENCY.
    """
    with tempfile.NamedTemporaryFile(suffix=".env.example", delete=False) as tf:
        tmp_path = tf.name

    try:
        key_manager.generate_env_example(tmp_path)
        content = pathlib.Path(tmp_path).read_text()
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)

    expected_vars = [
        "EXA_API_KEY",
        "SERPER_API_KEY",
        "JINA_API_KEY",
        "AIML_API_KEY",
        "AIML_PRIMARY",
        "RESEARCH_MAX_CONCURRENCY",
    ]
    for var in expected_vars:
        assert var in content, (
            f"generate_env_example() output is missing '{var}'.\n"
            "Add it to the 'Evidence Router providers' block in key_manager.py."
        )
