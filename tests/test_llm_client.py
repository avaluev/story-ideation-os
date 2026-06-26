"""tests/test_llm_client.py — shared chat-client factory (302.ai-primary policy).

Covers provider selection (302.ai primary when flag set OR no OpenRouter key;
OpenRouter primary otherwise) and the BudgetExceeded -> secondary fallback.
No real keys or network: the underlying client makers are monkeypatched to
sentinels so only the routing logic is exercised.
"""

from __future__ import annotations

import pytest

from pipeline import llm_client
from pipeline.research.client_302ai import BudgetExceeded


class _Sentinel:
    """A stand-in chat client tagged with the provider name it represents."""

    def __init__(self, name: str) -> None:
        self.name = name

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        return {"provider": self.name}


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TAO_AI_PRIMARY",
        "OPENROUTER_KEY_PAID",
        "OPENROUTER_API_KEY",
        "TAO_AI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_tao_primary_requested_reads_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAO_AI_PRIMARY", "1")
    assert llm_client.tao_primary_requested() is True
    monkeypatch.setenv("TAO_AI_PRIMARY", "TRUE")
    assert llm_client.tao_primary_requested() is True
    monkeypatch.setenv("TAO_AI_PRIMARY", "off")
    assert llm_client.tao_primary_requested() is False


def test_tao_primary_flag_routes_to_302_even_with_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAO_AI_PRIMARY", "1")
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    monkeypatch.setattr(llm_client, "_make_tao", lambda: _Sentinel("tao"))
    monkeypatch.setattr(llm_client, "_make_openrouter", lambda: _Sentinel("openrouter"))

    client = llm_client.build_chat_client()
    assert client.chat("m", []) == {"provider": "tao"}


def test_no_openrouter_key_auto_routes_to_302(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao")
    monkeypatch.setattr(llm_client, "_make_tao", lambda: _Sentinel("tao"))

    client = llm_client.build_chat_client()
    assert client.chat("m", []) == {"provider": "tao"}


def test_openrouter_primary_by_default_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    monkeypatch.setenv("TAO_AI_API_KEY", "fake-tao")
    monkeypatch.setattr(llm_client, "_make_openrouter", lambda: _Sentinel("openrouter"))
    monkeypatch.setattr(llm_client, "_make_tao", lambda: _Sentinel("tao"))

    client = llm_client.build_chat_client()
    assert client.chat("m", []) == {"provider": "openrouter"}


def test_fallback_on_budget_exceeded() -> None:
    class _Boom:
        def chat(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise BudgetExceeded("402 — quota exhausted")

    fallback = llm_client.FallbackClient(_Boom(), make_secondary=lambda: _Sentinel("secondary"))
    assert fallback.chat("m", []) == {"provider": "secondary"}


def test_fallback_reraises_when_no_secondary() -> None:
    class _Boom:
        def chat(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise BudgetExceeded("402 — quota exhausted")

    fallback = llm_client.FallbackClient(_Boom(), make_secondary=None)
    with pytest.raises(BudgetExceeded):
        fallback.chat("m", [])
