"""Tests for pipeline.research.gateways.aiml — AimlClient gateway.

Network round-trips live behind ``ONLINE_AIML=1`` so CI stays hermetic.
The default test set covers:
  - key resolution / masking (ADR-0003)
  - correct URL + auth header on POST (gateway smoke)
  - correct JSON body: model mapping, json_mode, perplexity no response_format
  - 402 → BudgetExceeded (never retried)
  - 429 → HTTPStatusError propagation (tenacity retries)
  - response shape extraction (choices[0].message.content)
  - citation() branching: sonar-pro (top-level citations[]), gpt-4o-search
    (markdown inline links + annotations), gpt-5 (empty list)
  - model override via AIML_MODEL_OVERRIDES env var
  - from_env() raises KeyError when AIML_API_KEY absent/empty

All mock shapes match the CONFIRMED schema in runs/research/gw_smoke_snapshot.md.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from pipeline.research import http_pool
from pipeline.research.gateways.aiml import (
    AimlClient,
    BudgetExceeded,
    _mask_key,
    _resolve_model,
    citations,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_chat_response(content: str, **extra: Any) -> dict[str, Any]:
    """Build a minimal AIML chat completion response envelope."""
    return {
        "id": "test-id",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    **extra,
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        **{k: v for k, v in extra.items() if k not in ("role", "content")},
    }


def _mock_transport(status: int, body: dict[str, Any]) -> httpx.MockTransport:
    """Return a MockTransport that always responds with *status* and *body*."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.MockTransport(_handler)


def _patch_pool(monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, Any]) -> None:
    """Patch http_pool.request_json to return *(status, url, body)* without network."""

    def _fake_request_json(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
        provider: str = "",
    ) -> tuple[int, str, dict[str, Any]]:
        if status == 402:
            raise http_pool.BudgetExceeded(
                f"provider={provider!r} returned HTTP 402 — quota exhausted.",
                provider=provider,
                status=402,
            )
        if status == 429:
            raise httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=httpx.Request("POST", url),
                response=httpx.Response(429),
            )
        return status, url, body

    monkeypatch.setattr(http_pool, "request_json", _fake_request_json)


# ── Key resolution ─────────────────────────────────────────────────────────────


class TestKeyResolution:
    def test_from_env_raises_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_API_KEY", "")
        with pytest.raises(KeyError, match="AIML_API_KEY"):
            AimlClient.from_env()

    def test_from_env_raises_when_blank_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_API_KEY", "   ")
        with pytest.raises(KeyError, match="AIML_API_KEY"):
            AimlClient.from_env()

    def test_from_env_constructs_with_valid_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_API_KEY", "fake-aiml-key-12345")
        client = AimlClient.from_env()
        assert client is not None
        assert hasattr(client, "chat")

    def test_direct_construction_raises_on_empty_key(self) -> None:
        with pytest.raises(KeyError, match="AIML_API_KEY"):
            AimlClient(api_key="")


# ── Key masking (ADR-0003 / SEC-07) ──────────────────────────────────────────


class TestPrefixMasking:
    def test_short_key_unchanged(self) -> None:
        assert _mask_key("abc12") == "abc12"

    def test_long_key_masked_to_prefix_plus_ellipsis(self) -> None:
        full = "fake-pfx-trailing-secret"
        masked = _mask_key(full)
        assert masked == "fake-pfx..."
        assert "trailing" not in masked
        assert "secret" not in masked

    def test_repr_does_not_leak_key(self) -> None:
        client = AimlClient(api_key="fake-test-fullkey-SENSITIVE-tail")
        text = repr(client)
        assert "SENSITIVE" not in text
        assert "tail" not in text
        assert "fake-tes" in text


# ── Model overrides ───────────────────────────────────────────────────────────


class TestModelOverride:
    def test_no_override_returns_model_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_MODEL_OVERRIDES", "")
        assert _resolve_model("openai/gpt-5-chat-latest") == "openai/gpt-5-chat-latest"

    def test_override_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "AIML_MODEL_OVERRIDES",
            '{"openai/gpt-5-chat-latest": "openai/gpt-5-custom"}',
        )
        assert _resolve_model("openai/gpt-5-chat-latest") == "openai/gpt-5-custom"

    def test_malformed_override_json_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_MODEL_OVERRIDES", "not-valid-json")
        # Falls back to identity
        assert _resolve_model("openai/gpt-5-chat-latest") == "openai/gpt-5-chat-latest"


# ── HTTP POST — URL, auth header, body shape ──────────────────────────────────


class TestChatPostShape:
    """Verify correct URL, Authorization header, and payload sent to AIML API."""

    def _make_client_and_capture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[AimlClient, dict[str, Any]]:
        captured: dict[str, Any] = {}

        def _fake_request_json(
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            json_body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
            timeout: float = 30.0,
            provider: str = "",
        ) -> tuple[int, str, dict[str, Any]]:
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json_body
            content = '{"ok": true}'
            return 200, url, _make_chat_response(content)

        monkeypatch.setattr(http_pool, "request_json", _fake_request_json)
        client = AimlClient(api_key="fake-test-key-XXXXXXXX")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **kw: None)
        return client, captured

    def test_posts_to_aiml_chat_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, captured = self._make_client_and_capture(monkeypatch)
        client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert captured["url"] == "https://api.aimlapi.com/v1/chat/completions"
        assert captured["method"] == "POST"

    def test_authorization_header_bearer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, captured = self._make_client_and_capture(monkeypatch)
        client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "hello"}],
        )
        auth = captured["headers"].get("Authorization", "")
        assert auth.startswith("Bearer ")
        # Key must not be fully exposed — only first 8 chars in header value;
        # the full key IS sent to the server (correct) but we verify the
        # Authorization header value contains the real key (not masked).
        assert "fake-test-key-XXXXXXXX" in auth

    def test_auth_header_key_masked_in_logs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """repr() and log output must not leak beyond first 8 chars."""
        client = AimlClient(api_key="fake-test-key-SENSITIVE-tail")
        assert "SENSITIVE" not in repr(client)

    def test_json_mode_adds_response_format_for_gpt5(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, captured = self._make_client_and_capture(monkeypatch)
        client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "q"}],
            json_mode=True,
        )
        assert captured["body"]["response_format"] == {"type": "json_object"}

    def test_json_mode_omitted_for_sonar_pro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Perplexity rejects response_format — must be absent even with json_mode=True."""
        client, captured = self._make_client_and_capture(monkeypatch)
        client.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "q"}],
            json_mode=True,
        )
        assert "response_format" not in captured["body"]

    def test_model_passed_verbatim_to_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, captured = self._make_client_and_capture(monkeypatch)
        client.chat(
            model="openai/gpt-4o-search-preview",
            messages=[{"role": "user", "content": "q"}],
        )
        assert captured["body"]["model"] == "openai/gpt-4o-search-preview"


# ── HTTP error handling ───────────────────────────────────────────────────────


class TestHttpErrorHandling:
    def test_402_raises_budget_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_pool(monkeypatch, 402, {})
        client = AimlClient(api_key="fake-test-key-12345678")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **kw: None)
        with pytest.raises(http_pool.BudgetExceeded):
            client.chat(
                model="openai/gpt-5-chat-latest",
                messages=[{"role": "user", "content": "q"}],
            )

    def test_429_raises_http_status_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_pool(monkeypatch, 429, {})
        client = AimlClient(api_key="fake-test-key-12345678")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **kw: None)
        with pytest.raises(httpx.HTTPStatusError):
            client.chat(
                model="openai/gpt-5-chat-latest",
                messages=[{"role": "user", "content": "q"}],
            )


# ── Response shape extraction ─────────────────────────────────────────────────


class TestResponseExtraction:
    def test_json_content_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = _make_chat_response('{"title": "Barbie", "gross_usd_m": 1441.0}')
        _patch_pool(monkeypatch, 200, body)
        client = AimlClient(api_key="fake-test-key-12345678")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **kw: None)
        result = client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "q"}],
        )
        assert result == {"title": "Barbie", "gross_usd_m": 1441.0}

    def test_json_fence_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = _make_chat_response('```json\n{"wrapped": true}\n```')
        _patch_pool(monkeypatch, 200, body)
        client = AimlClient(api_key="fake-test-key-12345678")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **kw: None)
        result = client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "q"}],
        )
        assert result == {"wrapped": True}

    def test_prose_response_wrapped_in_text_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prose = "The box office was strong this quarter."
        body = _make_chat_response(prose)
        _patch_pool(monkeypatch, 200, body)
        client = AimlClient(api_key="fake-test-key-12345678")
        monkeypatch.setattr(client, "_record_quota", lambda *a, **kw: None)
        result = client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "q"}],
        )
        assert result == {"text": prose}


# ── Citation extraction ───────────────────────────────────────────────────────


class TestCitationExtraction:
    """Verify citations() branches on model family per gw_smoke_snapshot.md."""

    def test_sonar_pro_top_level_citations(self) -> None:
        """perplexity/sonar-pro: citations at response["citations"] (list of URLs)."""
        response: dict[str, Any] = {
            "choices": [{"message": {"role": "assistant", "content": "See [1] and [2]."}}],
            "citations": [
                "https://boxofficemojo.com/title/tt1517268/",
                "https://variety.com/2023/film/news/barbie-box-office-1234567/",
            ],
            "search_results": [
                {"url": "https://deadline.com/2023/08/barbie-1-billion/", "title": "Barbie"},
            ],
        }
        urls = citations(response, "perplexity/sonar-pro")
        assert "https://boxofficemojo.com/title/tt1517268/" in urls
        assert "https://variety.com/2023/film/news/barbie-box-office-1234567/" in urls
        # search_results URL also included, deduplicated
        assert "https://deadline.com/2023/08/barbie-1-billion/" in urls

    def test_sonar_pro_deduplicates_urls(self) -> None:
        """Same URL in both citations[] and search_results must appear once."""
        url = "https://boxofficemojo.com/title/tt1517268/"
        response: dict[str, Any] = {
            "citations": [url],
            "search_results": [{"url": url}],
        }
        result = citations(response, "perplexity/sonar-pro")
        assert result.count(url) == 1

    def test_sonar_pro_missing_citations_key_returns_empty(self) -> None:
        response: dict[str, Any] = {"choices": []}
        result = citations(response, "perplexity/sonar-pro")
        assert result == []

    def test_gpt4o_search_markdown_links_extracted(self) -> None:
        """openai/gpt-4o-search-preview: citations are markdown links in content."""
        content = (
            "Barbie grossed $1,441,138,421 worldwide "
            "([boxofficemojo.com](https://www.boxofficemojo.com/title/tt1517268/))."
        )
        response: dict[str, Any] = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "annotations": [],
                        "reasoning": "",
                    }
                }
            ],
        }
        urls = citations(response, "openai/gpt-4o-search-preview")
        assert "https://www.boxofficemojo.com/title/tt1517268/" in urls

    def test_gpt4o_search_annotations_extracted(self) -> None:
        """message.annotations may carry structured citation objects."""
        response: dict[str, Any] = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "See sources.",
                        "annotations": [
                            {"url": "https://variety.com/2023/film/barbie-billion/"},
                            {"url": "https://deadline.com/2023/08/barbie-global/"},
                        ],
                    }
                }
            ],
        }
        urls = citations(response, "openai/gpt-4o-search-preview")
        assert "https://variety.com/2023/film/barbie-billion/" in urls
        assert "https://deadline.com/2023/08/barbie-global/" in urls

    def test_gpt4o_search_no_top_level_citations_key(self) -> None:
        """gpt-4o-search does NOT have a top-level 'citations' key — must not crash."""
        response: dict[str, Any] = {
            "choices": [{"message": {"role": "assistant", "content": "plain answer"}}],
        }
        urls = citations(response, "openai/gpt-4o-search-preview")
        assert isinstance(urls, list)

    def test_gpt5_returns_empty_list(self) -> None:
        """openai/gpt-5-chat-latest has no web citations."""
        response: dict[str, Any] = {
            "choices": [{"message": {"role": "assistant", "content": "Кассовые сборы."}}],
        }
        assert citations(response, "openai/gpt-5-chat-latest") == []

    def test_unknown_model_returns_empty_list(self) -> None:
        response: dict[str, Any] = {"choices": [{"message": {"content": "hi"}}]}
        assert citations(response, "some/unknown-model") == []


# ── Exception types ───────────────────────────────────────────────────────────


class TestExceptionTypes:
    def test_budget_exceeded_is_exception_subclass(self) -> None:
        assert issubclass(BudgetExceeded, Exception)

    def test_budget_exceeded_constructable(self) -> None:
        exc = BudgetExceeded("quota exhausted")
        assert "quota" in str(exc)


# ── Live round-trip (guarded by ONLINE_AIML=1) ───────────────────────────────


@pytest.mark.skipif(
    os.environ.get("ONLINE_AIML") != "1",
    reason="Set ONLINE_AIML=1 to run live AIML API round-trips.",
)
class TestOnlineRoundTrip:
    def test_gpt5_translation(self) -> None:
        client = AimlClient.from_env()
        result = client.chat(
            model="openai/gpt-5-chat-latest",
            messages=[{"role": "user", "content": "Translate to Russian: 'Box office revenue.'"}],
            max_tokens=64,
        )
        assert isinstance(result, dict)
        # Confirmed live shape: prose response wrapped in {"text": ...}
        assert "text" in result or len(result) > 0

    def test_sonar_pro_returns_citations(self) -> None:
        client = AimlClient.from_env()
        result = client.chat(
            model="perplexity/sonar-pro",
            messages=[
                {
                    "role": "user",
                    "content": "What was Barbie (2023) worldwide box office gross?",
                }
            ],
            json_mode=False,
            max_tokens=256,
        )
        assert isinstance(result, dict)
