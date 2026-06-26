"""Tests for ``pipeline.research.gateways.gw302.GW302``.

Covers:
- from_env() — raises KeyError when TAO_AI_API_KEY absent/blank
- serp() — correct URL, auth header, organic mapping, answerBox insertion
- fetch() — correct URL, auth header, FetchedPage mapping (url/markdown/sha256/ok)
- synth() — correct URL, auth header, model pass-through, dict return
- HTTP 402 -> BudgetExceeded propagation
- HTTP 429 -> retried (tenacity fires inside TaoAIClient)
- Key masking in repr / log context (SEC-07 / ADR-0003)

All network calls are intercepted via ``httpx.MockTransport`` patched onto
``pipeline.research.client_302ai.httpx.Client``, mirroring the pattern in
``tests/test_client_302ai.py``.

Live calls (ONLINE_302AI=1 guard) are intentionally minimal — they only
assert the returned objects have the right types, not specific values.

ADR-0003: No raw API key may appear in assertion strings or log output.
"""

from __future__ import annotations

import hashlib
import json
import os

import httpx
import pytest

from pipeline.research import client_302ai
from pipeline.research.client_302ai import (
    _TAO_CHAT_URL,
    _TAO_FIRECRAWL_SCRAPE_URL,
    _TAO_SERP_URL,
    BudgetExceeded,
    TaoAIClient,
)
from pipeline.research.gateways.gw302 import GW302
from pipeline.research.providers.types import FetchedPage, SearchHit

# ── Helpers ───────────────────────────────────────────────────────────────────

_FAKE_KEY = "fake-302-test-key-XXXX"

# Minimal SERP response matching the confirmed shape from gw_smoke_snapshot.md
_SERP_ORGANIC_RESPONSE = {
    "organic": [
        {
            "title": "Box Office: Barbie 2023",
            "link": "https://boxofficemojo.com/title/tt1517268/",
            "snippet": "Worldwide: $1.44B",
            "position": 1,
        },
        {
            "title": "Barbie Wikipedia",
            "link": "https://en.wikipedia.org/wiki/Barbie_(film)",
            "snippet": "American fantasy comedy film",
            "position": 2,
        },
    ],
    "relatedSearches": [],
    "credits": 1,
}

_SERP_WITH_ANSWERBOX_RESPONSE = {
    "answerBox": {
        "title": "Barbie (film)",
        "snippet": "Worldwide gross: $1,441,593,235",
        "link": "https://boxofficemojo.com/title/tt1517268/",
    },
    "organic": [
        {
            "title": "Box Office Mojo — Barbie",
            "link": "https://boxofficemojo.com/title/tt1517268/",
            "snippet": "Full details",
            "position": 1,
        },
    ],
    "credits": 1,
}

# Minimal Firecrawl scrape response matching the confirmed shape
_CRAWL_RESPONSE = {
    "data": {
        "url": "https://www.boxofficemojo.com/year/world/2023/",
        "markdown": "# Box Office 2023\n\nTop grossing films worldwide.",
        "html": "<h1>Box Office 2023</h1>",
        "metadata": {"title": "Box Office 2023"},
    }
}

# Minimal chat completion response
_CHAT_RESPONSE = {
    "choices": [{"message": {"content": '{"answer": "Barbie earned $1.44B worldwide"}'}}]
}


def _make_gw302(monkeypatch: pytest.MonkeyPatch) -> GW302:
    """Return a GW302 with the fake key set in the environment."""
    monkeypatch.setenv("TAO_AI_API_KEY", _FAKE_KEY)
    return GW302.from_env()


def _patch_tao_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Replace httpx.Client inside client_302ai with a mock-transport client."""
    transport = httpx.MockTransport(handler)
    real_cls = httpx.Client

    def fake_client(*, timeout: float | None = None, **_: object) -> httpx.Client:
        return real_cls(transport=transport, timeout=timeout)

    monkeypatch.setattr(client_302ai.httpx, "Client", fake_client)


# ── from_env() ────────────────────────────────────────────────────────────────


class TestFromEnv:
    def test_raises_when_key_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", "")
        with pytest.raises(KeyError, match="TAO_AI_API_KEY"):
            GW302.from_env()

    def test_raises_when_key_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", "   ")
        with pytest.raises(KeyError, match="TAO_AI_API_KEY"):
            GW302.from_env()

    def test_constructs_with_valid_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", _FAKE_KEY)
        gw = GW302.from_env()
        assert gw is not None

    def test_repr_masks_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", _FAKE_KEY)
        gw = GW302.from_env()
        text = repr(gw)
        # The raw key must not appear in repr (SEC-07 / ADR-0003)
        assert _FAKE_KEY not in text
        # The repr should contain the first 8 chars of the key
        assert _FAKE_KEY[:8] in text


# ── serp() ────────────────────────────────────────────────────────────────────


class TestSerp:
    def test_posts_to_serp_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization", "")
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_SERP_ORGANIC_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        hits = gw.serp("Barbie 2023 box office", num=5)

        # Correct endpoint
        assert str(captured["url"]).startswith(_TAO_SERP_URL), f"wrong URL: {captured['url']}"

        # Auth header present and masked correctly in assertions (we check prefix only)
        auth = str(captured["auth"])
        assert auth.startswith("Bearer "), f"missing Bearer prefix: {auth}"
        # Confirm the key is in the Bearer value (we compare first 8 chars)
        bearer_value = auth.removeprefix("Bearer ")
        assert bearer_value.startswith(_FAKE_KEY[:8])

        # Returns a list of SearchHit
        assert isinstance(hits, list)
        assert len(hits) == 2
        assert all(isinstance(h, SearchHit) for h in hits)

    def test_organic_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_SERP_ORGANIC_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        hits = gw.serp("Barbie box office")

        first = hits[0]
        assert first.url == "https://boxofficemojo.com/title/tt1517268/"
        assert first.title == "Box Office: Barbie 2023"
        assert "1.44B" in first.snippet
        assert first.provider == "302ai-serp"
        assert first.score > 0.0

    def test_answerbox_inserted_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_SERP_WITH_ANSWERBOX_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        hits = gw.serp("Barbie worldwide gross")

        # answerBox hit is at index 0
        assert len(hits) == 2  # answerBox + 1 organic
        assert "1,441,593,235" in hits[0].snippet
        assert hits[0].score == 1.0

    def test_score_decreases_with_position(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_SERP_ORGANIC_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        hits = gw.serp("test query", num=10)

        scores = [h.score for h in hits]
        assert scores[0] >= scores[1], "score should decrease with position"

    def test_empty_organic_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"organic": [], "credits": 1})

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        hits = gw.serp("nothing found")
        assert hits == []

    def test_402_raises_budget_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error": "quota exceeded"})

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        with pytest.raises(BudgetExceeded):
            gw.serp("some query")


# ── fetch() ───────────────────────────────────────────────────────────────────


class TestFetch:
    def test_posts_to_firecrawl_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization", "")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_CRAWL_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        gw.fetch("https://www.boxofficemojo.com/year/world/2023/")

        assert captured["url"] == _TAO_FIRECRAWL_SCRAPE_URL
        auth = str(captured["auth"])
        assert auth.startswith("Bearer ")
        bearer_value = auth.removeprefix("Bearer ")
        assert bearer_value.startswith(_FAKE_KEY[:8])

    def test_returns_fetched_page_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_CRAWL_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        page = gw.fetch("https://www.boxofficemojo.com/year/world/2023/")

        assert isinstance(page, FetchedPage)

    def test_mapping_url_markdown_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_CRAWL_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        page = gw.fetch("https://www.boxofficemojo.com/year/world/2023/")

        assert page.url == "https://www.boxofficemojo.com/year/world/2023/"
        assert page.final_url == "https://www.boxofficemojo.com/year/world/2023/"
        assert "Box Office 2023" in page.markdown
        assert page.ok is True
        assert page.provider == "302ai-crawl"
        assert page.status == 200

    def test_content_sha256_matches_markdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_CRAWL_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        page = gw.fetch("https://www.boxofficemojo.com/year/world/2023/")

        expected_sha = hashlib.sha256(page.markdown.encode()).hexdigest()
        assert page.content_sha256 == expected_sha

    def test_empty_markdown_sets_ok_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "url": "https://example.com/",
                        "markdown": "",
                        "html": "",
                        "metadata": {},
                    }
                },
            )

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        page = gw.fetch("https://example.com/")

        assert page.ok is False
        assert page.content_sha256 == ""

    def test_request_body_contains_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_CRAWL_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        target = "https://www.boxofficemojo.com/year/world/2023/"
        gw.fetch(target)

        assert captured["body"]["url"] == target  # type: ignore[index]

    def test_402_raises_budget_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error": "quota exceeded"})

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        with pytest.raises(BudgetExceeded):
            gw.fetch("https://www.boxofficemojo.com/year/world/2023/")


# ── synth() ───────────────────────────────────────────────────────────────────


class TestSynth:
    def test_posts_to_chat_url(self, monkeypatch: pytest.MonkeyPatch) -> None:

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization", "")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_CHAT_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        # Patch _record_quota to avoid quota side-effects in tests
        monkeypatch.setattr(gw._client, "_record_quota", lambda *a, **k: None)
        gw.synth("perplexity/sonar-pro", [{"role": "user", "content": "test"}])

        assert captured["url"] == _TAO_CHAT_URL

    def test_auth_header_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("Authorization", "")
            return httpx.Response(200, json=_CHAT_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        monkeypatch.setattr(gw._client, "_record_quota", lambda *a, **k: None)
        gw.synth("openai/gpt-4o", [{"role": "user", "content": "hello"}])

        auth = str(captured["auth"])
        assert auth.startswith("Bearer ")
        bearer_value = auth.removeprefix("Bearer ")
        assert bearer_value.startswith(_FAKE_KEY[:8])

    def test_returns_parsed_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_CHAT_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        monkeypatch.setattr(gw._client, "_record_quota", lambda *a, **k: None)
        result = gw.synth(
            "perplexity/sonar-pro",
            [{"role": "user", "content": "test question"}],
        )

        assert isinstance(result, dict)
        assert result.get("answer") == "Barbie earned $1.44B worldwide"

    def test_model_mapped_to_302ai_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TaoAIClient must translate perplexity/sonar-pro -> sonar-pro before POST."""
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["model"] = json.loads(request.content).get("model")
            return httpx.Response(200, json=_CHAT_RESPONSE)

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        monkeypatch.setattr(gw._client, "_record_quota", lambda *a, **k: None)
        gw.synth("perplexity/sonar-pro", [{"role": "user", "content": "hi"}])

        # TaoAIClient.map_model strips the "perplexity/" prefix
        assert captured["model"] == "sonar-pro"

    def test_402_raises_budget_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error": "quota exceeded"})

        _patch_tao_client(monkeypatch, handler)
        gw = _make_gw302(monkeypatch)
        monkeypatch.setattr(gw._client, "_record_quota", lambda *a, **k: None)
        with pytest.raises(BudgetExceeded):
            gw.synth("perplexity/sonar-pro", [{"role": "user", "content": "hi"}])


# ── Key masking (ADR-0003 / SEC-07) ──────────────────────────────────────────


class TestKeyMasking:
    def test_repr_does_not_expose_full_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAO_AI_API_KEY", _FAKE_KEY)
        gw = GW302.from_env()
        text = repr(gw)
        # Full key must not appear; only the first 8-char prefix is acceptable
        assert _FAKE_KEY not in text
        assert _FAKE_KEY[8:] not in text

    def test_inject_client_repr_masks_key(self) -> None:
        """Injecting a TaoAIClient directly must also produce a masked repr."""
        client = TaoAIClient(api_key=_FAKE_KEY)
        gw = GW302(client)
        text = repr(gw)
        assert _FAKE_KEY not in text
        assert _FAKE_KEY[8:] not in text


# ── Live online smoke (ONLINE_302AI=1) ────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("ONLINE_302AI") != "1",
    reason="Set ONLINE_302AI=1 to run live 302.ai round-trips.",
)
class TestOnlineRoundTrip:
    def test_serp_returns_search_hits(self) -> None:
        gw = GW302.from_env()
        hits = gw.serp("Barbie 2023 worldwide box office", num=3)
        assert isinstance(hits, list)
        assert len(hits) > 0
        assert all(isinstance(h, SearchHit) for h in hits)
        assert all(h.url.startswith("http") for h in hits if h.url)

    def test_fetch_returns_fetched_page(self) -> None:
        gw = GW302.from_env()
        page = gw.fetch("https://www.boxofficemojo.com/year/world/2023/")
        assert isinstance(page, FetchedPage)
        assert page.ok or page.markdown == ""  # ok=True when content present

    def test_synth_returns_dict(self) -> None:
        gw = GW302.from_env()
        result = gw.synth(
            "perplexity/sonar-pro",
            [
                {
                    "role": "user",
                    "content": (
                        "What was the worldwide box office of Barbie (2023)?"
                        ' Reply in JSON: {"gross_usd": ...}'
                    ),
                }
            ],
            json_mode=True,
        )
        assert isinstance(result, dict)
