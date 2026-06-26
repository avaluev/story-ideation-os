"""tests/test_research_dispatch_m2.py — M-2 RU-dispatch correctness.

Covers:
  - ``_aiml_primary`` parses AIML_PRIMARY symmetrically against ``_TRUTHY``
    (the old ad-hoc deny list treated ``"off"`` / ``"No"`` as truthy).
  - ``assert_translation_model`` pins the AIML allowlist and forbids Gemini.
  - ``build_translation_client`` is AIML-only with NO OpenRouter last resort —
    it raises loudly when AIML is unavailable.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline import research_dispatch

# ── _aiml_primary truthy-parse ────────────────────────────────────────────────


def test_aiml_primary_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIML_PRIMARY", raising=False)
    assert research_dispatch._aiml_primary() is True


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on", " on "])
def test_aiml_primary_truthy_values(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("AIML_PRIMARY", val)
    assert research_dispatch._aiml_primary() is True


@pytest.mark.parametrize("val", ["0", "", "false", "False", "no", "No", "NO", "off", "OFF", "x"])
def test_aiml_primary_falsy_values(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("AIML_PRIMARY", val)
    assert research_dispatch._aiml_primary() is False


# ── assert_translation_model ──────────────────────────────────────────────────


@pytest.mark.parametrize("model", ["openai/gpt-5-chat-latest", "openai/gpt-4.1"])
def test_assert_translation_model_allowlist(model: str) -> None:
    assert research_dispatch.assert_translation_model(model) == model


def test_assert_translation_model_strips_whitespace() -> None:
    assert research_dispatch.assert_translation_model("  openai/gpt-4.1  ") == "openai/gpt-4.1"


@pytest.mark.parametrize(
    "model",
    ["google/gemini-2.5-pro", "gemini-1.5-flash", "vertex/GEMINI-pro"],
)
def test_assert_translation_model_forbids_gemini(model: str) -> None:
    with pytest.raises(ValueError, match="Gemini is forbidden"):
        research_dispatch.assert_translation_model(model)


@pytest.mark.parametrize("model", ["openai/gpt-4o-mini", "perplexity/sonar-pro", ""])
def test_assert_translation_model_rejects_off_allowlist(model: str) -> None:
    with pytest.raises(ValueError, match="not in allowlist"):
        research_dispatch.assert_translation_model(model)


# ── build_translation_client (AIML-only; no OpenRouter last resort) ───────────


class _FakeAiml:
    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        return {"ok": True}


def test_build_translation_client_returns_aiml(monkeypatch: pytest.MonkeyPatch) -> None:
    fake: Any = _FakeAiml()
    monkeypatch.setattr(research_dispatch, "_aiml_client_or_none", lambda: fake)
    assert research_dispatch.build_translation_client() is fake


def test_build_translation_client_raises_without_aiml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_dispatch, "_aiml_client_or_none", lambda: None)
    with pytest.raises(RuntimeError, match="no OpenRouter fallback"):
        research_dispatch.build_translation_client()


def test_module_exports_translation_helpers() -> None:
    assert "assert_translation_model" in research_dispatch.__all__
    assert "build_translation_client" in research_dispatch.__all__
