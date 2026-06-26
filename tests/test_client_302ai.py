"""Smoke + key-management tests for ``pipeline.research.client_302ai``.

Network round-trips live behind ``ONLINE_302AI=1`` so CI stays hermetic.
The default test set covers key resolution, prefix masking, exception
import, and ``research_dispatch`` fallback wiring (ADR-0003 + ADR-0007).
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from pipeline.research import client_302ai
from pipeline.research.client_302ai import (
    BudgetExceeded,
    TaoAIClient,
    _mask_key,
    map_model,
)


class TestKeyResolution:
    def test_from_env_raises_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Import key_manager FIRST so its module-level load_dotenv() runs *before*
        # we clear the env. Otherwise from_env()'s deferred `import pipeline.key_manager`
        # would trigger load_dotenv() mid-test and repopulate TAO_AI_API_KEY from .env,
        # making this assertion order-dependent (the load_dotenv-repopulation footgun).
        import pipeline.key_manager  # noqa: F401,PLC0415

        monkeypatch.delenv("TAO_AI_API_KEY", raising=False)
        with pytest.raises(KeyError, match="TAO_AI_API_KEY"):
            TaoAIClient.from_env()

    def test_from_env_raises_on_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", "   ")
        with pytest.raises(KeyError, match="TAO_AI_API_KEY"):
            TaoAIClient.from_env()

    def test_from_env_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", "  fake-test-key-12345  ")
        client = TaoAIClient.from_env()
        # do not expose `client._api_key` in any assertion message
        assert client is not None


class TestPrefixMasking:
    """ADR-0003: API key prefixes masked to first 8 chars in all logs."""

    def test_mask_short_key_unchanged(self) -> None:
        # Real keys are always > 8 chars; short input passes through.
        masked = _mask_key("abc12")
        assert masked == "abc12"

    def test_mask_long_key_keeps_only_prefix(self) -> None:
        full = "fake-pfx-trailing-fake-test-value"
        masked = _mask_key(full)
        assert "trailing" not in masked
        assert masked.startswith("fake-pfx")
        assert "..." in masked

    def test_repr_does_not_leak_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", "fake-test-fullkey-AAAAAAAA-tail")
        client = TaoAIClient.from_env()
        text = repr(client)
        assert "tail" not in text


class TestExceptionImport:
    def test_budget_exceeded_is_subclass_of_exception(self) -> None:
        assert issubclass(BudgetExceeded, Exception)

    def test_budget_exceeded_constructable(self) -> None:
        exc = BudgetExceeded("ran out of credits")
        assert "credits" in str(exc)


class TestResearchDispatchFallback:
    """When OpenRouter is missing, research_dispatch should pick TaoAIClient."""

    def test_build_client_falls_back_when_no_openrouter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Hide OpenRouter keys, leave TAO_AI_API_KEY in place.
        for var in (
            "OPENROUTER_API_KEY",
            "OPENROUTER_KEY_PAID",
            "OPENROUTER_KEY_FREE_1",
            "OPENROUTER_KEY_FREE_2",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("TAO_AI_API_KEY", "fake-test-fallback-key")
        from pipeline import research_dispatch  # noqa: PLC0415

        client = research_dispatch._build_client()
        # The fallback returns either a TaoAIClient or a _FallbackClient that
        # wraps it -- both should be non-None and have a chat() attribute.
        assert client is not None
        assert hasattr(client, "chat")


@pytest.mark.skipif(
    os.environ.get("ONLINE_302AI") != "1",
    reason="Set ONLINE_302AI=1 to run live 302.ai round-trips.",
)
class TestOnlineRoundTrip:
    def test_search_returns_results(self) -> None:
        client = TaoAIClient.from_env()
        results = client.search("Severance season 2 budget", max_results=3)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all("url" in r for r in results)


class TestModelMap:
    """302.ai expects BARE model ids; OpenRouter-style ids must be translated."""

    def test_perplexity_pro_maps_to_bare(self) -> None:
        assert map_model("perplexity/sonar-pro") == "sonar-pro"

    def test_perplexity_deep_research_maps(self) -> None:
        assert map_model("perplexity/sonar-deep-research") == "sonar-deep-research"

    def test_anthropic_prefix_stripped(self) -> None:
        assert map_model("anthropic/claude-haiku-4.5") == "claude-haiku-4.5"

    def test_bare_and_unknown_pass_through(self) -> None:
        assert map_model("sonar-pro") == "sonar-pro"
        assert map_model("gpt-4o") == "gpt-4o"

    def test_env_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_MODEL_OVERRIDES", '{"perplexity/sonar-pro": "pplx-custom"}')
        assert map_model("perplexity/sonar-pro") == "pplx-custom"

    def test_malformed_override_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_MODEL_OVERRIDES", "not-json")
        assert map_model("perplexity/sonar-pro") == "sonar-pro"


class TestChatModelMapping:
    """chat() must POST the MAPPED model id to the 302.ai chat endpoint (offline)."""

    def test_chat_sends_mapped_model_to_chat_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["model"] = json.loads(request.content)["model"]
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

        transport = httpx.MockTransport(handler)
        real_client_cls = httpx.Client

        def fake_client(*, timeout: float | None = None, **_: object) -> httpx.Client:
            return real_client_cls(transport=transport, timeout=timeout)

        monkeypatch.setattr(client_302ai.httpx, "Client", fake_client)

        client = TaoAIClient(api_key="fake-test-key-123456")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **k: None)
        result = client.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "hi"}],
            json_mode=True,
            max_tokens=64,
        )

        assert result == {"ok": True}
        assert captured["model"] == "sonar-pro"
        assert captured["url"] == client_302ai._TAO_CHAT_URL
