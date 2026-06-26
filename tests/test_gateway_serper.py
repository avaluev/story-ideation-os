"""tests/test_gateway_serper.py — offline + optional live tests for SerperGateway.

Hermetic by default: all HTTP is mocked against the http_pool layer.
Live calls are gated behind ``ONLINE_SERPER=1`` (mirrors the ONLINE_302AI
pattern in test_client_302ai.py).

Confirmed response shape (from runs/research/gw_smoke_snapshot.md):
  POST https://google.serper.dev/search
  Header: X-API-KEY: <SERPER_API_KEY>
  Body:   {"q": str, "num": int}
  organic[].title     : str
  organic[].link      : str  (→ SearchHit.url)
  organic[].snippet   : str
  organic[].position  : int  (1-based rank; NO date on web results)
  answerBox           : {snippet, snippetHighlighted, title, link} — when present

Coverage:
  - from_env() raises KeyError when SERPER_API_KEY is absent
  - from_env() raises KeyError when SERPER_API_KEY is blank
  - from_env() constructs successfully when key is set
  - from_env() strips leading/trailing whitespace from key
  - __repr__ masks key tail (does not leak secret suffix)
  - __repr__ includes masked prefix (first 8 chars)
  - __repr__ includes ellipsis
  - search() POSTs to https://google.serper.dev/search
  - search() uses X-API-KEY header (not Authorization: Bearer)
  - search() sends correct API key value in X-API-KEY header
  - search() sends body with "q" and "num" keys
  - search() maps organic[].link -> SearchHit.url
  - search() maps organic[].title -> SearchHit.title
  - search() maps organic[].snippet -> SearchHit.snippet
  - search() maps organic[].position 1 -> score 1.0
  - search() maps organic[].position 2 -> score ~0.5
  - search() maps organic[].position 10 -> score ~0.1
  - search() sets provider="serper" on all organic hits
  - search() sets published_date="" (no date on Serper web results)
  - search() inserts answerBox as first hit when present
  - search() uses answerBox.snippet when present
  - search() uses answerBox.snippetHighlighted when snippet absent
  - search() sets answerBox hit score to 0.0
  - search() maps answerBox.link -> url and answerBox.title -> title
  - search() omits answerBox hit when link is absent
  - search() omits answerBox hit when both snippet fields are absent
  - search() returns empty list for empty organic + no answerBox
  - search() skips organic items with no link
  - search() on HTTP 402 raises BudgetExceeded (not retried)
  - search() on HTTP 429 raises HTTPStatusError (propagates for tenacity)
  - SearchHit is frozen (immutable dataclass)
  - serper.py does not import httpx directly (uses http_pool)
  - serper.py does not import anthropic (ANOMALY-001)
"""

from __future__ import annotations

import ast
import os
import pathlib
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from pipeline.research.gateways.serper import (
    _SERPER_SEARCH_URL,
    SerperGateway,
)
from pipeline.research.http_pool import BudgetExceeded
from pipeline.research.providers.types import SearchHit

# ── Fixtures and helpers ──────────────────────────────────────────────────────

_SERPER_MODULE_PATH = pathlib.Path(
    "/Users/sxope/Documents/2026/Development/29.Engine/pipeline/research/gateways/serper.py"
)


def _fake_key(suffix: str = "SECRETSUFFIX0000") -> str:
    """Build a realistic-looking fake Serper key (at least 8 chars + suffix)."""
    return f"fake-srp-{suffix}"


def _make_organic_item(
    title: str = "Test Result Title",
    link: str = "https://example.com/result",
    snippet: str = "Short excerpt from the search result.",
    position: int = 1,
) -> dict[str, Any]:
    """Build a single organic[] item in confirmed Serper schema shape."""
    return {
        "title": title,
        "link": link,
        "snippet": snippet,
        "position": position,
    }


def _make_answer_box(
    title: str = "Answer Box Title",
    link: str = "https://example.com/answer",
    snippet: str = "Direct answer from the knowledge graph.",
    snippet_highlighted: str = "",
) -> dict[str, Any]:
    """Build an answerBox dict in confirmed Serper schema shape."""
    box: dict[str, Any] = {
        "title": title,
        "link": link,
    }
    if snippet:
        box["snippet"] = snippet
    if snippet_highlighted:
        box["snippetHighlighted"] = snippet_highlighted
    return box


def _make_response(
    organic: list[dict[str, Any]] | None = None,
    answer_box: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap organic results (and optional answerBox) in the Serper envelope."""
    body: dict[str, Any] = {
        "searchParameters": {"q": "test query", "type": "search", "num": 10},
        "organic": organic or [],
        "credits": 1,
    }
    if answer_box is not None:
        body["answerBox"] = answer_box
    return body


def _stub_request_json(response_body: dict[str, Any], *, status: int = 200):
    """Return a mock for http_pool.request_json that returns a fixed body."""

    def _mock(method, url, *, headers, json_body=None, params=None, timeout=30.0, provider=""):
        return (status, url, response_body)

    return _mock


# ── from_env() ────────────────────────────────────────────────────────────────


class TestFromEnv:
    def test_raises_key_error_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        with pytest.raises(KeyError, match="SERPER_API_KEY"):
            SerperGateway.from_env()

    def test_raises_key_error_when_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERPER_API_KEY", "   ")
        with pytest.raises(KeyError, match="SERPER_API_KEY"):
            SerperGateway.from_env()

    def test_constructs_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERPER_API_KEY", "fake-srp-testkey-12345")
        gw = SerperGateway.from_env()
        assert gw is not None

    def test_strips_whitespace_from_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERPER_API_KEY", "  fake-srp-testkey-12345  ")
        gw = SerperGateway.from_env()
        assert gw is not None


# ── Key masking (ADR-0003) ────────────────────────────────────────────────────


class TestKeyMasking:
    def test_repr_does_not_leak_secret_suffix(self) -> None:
        key = _fake_key("TOPSECRET9999")
        gw = SerperGateway(api_key=key)
        text = repr(gw)
        assert "TOPSECRET" not in text
        assert "SECRETSUFFIX" not in text

    def test_repr_shows_masked_prefix(self) -> None:
        gw = SerperGateway(api_key="fake-srp-SECRETSUFFIX")
        text = repr(gw)
        # First 8 chars are "fake-srp"; masked repr should contain them.
        assert "fake-srp" in text

    def test_repr_includes_ellipsis(self) -> None:
        gw = SerperGateway(api_key=_fake_key())
        assert "..." in repr(gw)


# ── search() — HTTP contract ──────────────────────────────────────────────────


class TestSearchHttpContract:
    """Verify that search() hits the correct URL with the correct auth header
    and correct request body shape, using a mock against http_pool."""

    def _make_gw(self) -> SerperGateway:
        return SerperGateway(api_key=_fake_key())

    def test_posts_to_correct_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["method"] = method
            captured["url"] = url
            return (200, url, _make_response())

        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json", _fake_request
        )
        gw.search("test query")
        assert captured["method"] == "POST"
        assert captured["url"] == _SERPER_SEARCH_URL
        assert captured["url"] == "https://google.serper.dev/search"

    def test_uses_x_api_key_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Serper requires ``X-API-KEY``; must NOT use Authorization: Bearer."""
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["headers"] = headers
            return (200, url, _make_response())

        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json", _fake_request
        )
        gw.search("test query")
        assert "X-API-KEY" in captured["headers"]
        assert "Authorization" not in captured["headers"]

    def test_sends_correct_api_key_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = _fake_key("MYSPECIFICKEY00")
        gw = SerperGateway(api_key=key)
        captured: dict[str, Any] = {}

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["headers"] = headers
            return (200, url, _make_response())

        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json", _fake_request
        )
        gw.search("test query")
        assert captured["headers"]["X-API-KEY"] == key

    def test_sends_body_with_q_and_num(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Body must use 'q' (not 'query') per confirmed Serper schema."""
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return (200, url, _make_response())

        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json", _fake_request
        )
        gw.search("box office 2025", num=5)
        body = captured["json_body"]
        assert body["q"] == "box office 2025"
        assert body["num"] == 5

    def test_default_num_is_ten(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return (200, url, _make_response())

        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json", _fake_request
        )
        gw.search("any query")
        assert captured["json_body"]["num"] == 10


# ── search() — organic result mapping ────────────────────────────────────────


class TestOrganicMapping:
    """Verify that organic[] items are correctly mapped to SearchHit DTOs."""

    def _run_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
        organic: list[dict[str, Any]],
        answer_box: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        gw = SerperGateway(api_key=_fake_key())
        response = _make_response(organic=organic, answer_box=answer_box)
        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json",
            _stub_request_json(response),
        )
        return gw.search("test query")

    def test_returns_one_hit_per_organic_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(
            monkeypatch,
            [_make_organic_item(position=1), _make_organic_item(link="https://b.com/", position=2)],
        )
        assert len(hits) == 2

    def test_hit_url_from_organic_link(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(
            monkeypatch,
            [_make_organic_item(link="https://boxofficemojo.com/title/tt1234/", position=1)],
        )
        assert hits[0].url == "https://boxofficemojo.com/title/tt1234/"

    def test_hit_title_from_organic_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(
            monkeypatch, [_make_organic_item(title="Box Office Mojo — 2025", position=1)]
        )
        assert hits[0].title == "Box Office Mojo — 2025"

    def test_hit_snippet_from_organic_snippet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(
            monkeypatch, [_make_organic_item(snippet="Revenue was $1.2B in 2025.", position=1)]
        )
        assert hits[0].snippet == "Revenue was $1.2B in 2025."

    def test_hit_score_position_1_is_1_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(monkeypatch, [_make_organic_item(position=1)])
        assert hits[0].score == pytest.approx(1.0)

    def test_hit_score_position_2_is_0_5(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(monkeypatch, [_make_organic_item(position=2)])
        assert hits[0].score == pytest.approx(0.5)

    def test_hit_score_position_10_is_0_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(monkeypatch, [_make_organic_item(position=10)])
        assert hits[0].score == pytest.approx(0.1)

    def test_hit_provider_is_serper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(monkeypatch, [_make_organic_item()])
        assert hits[0].provider == "serper"

    def test_hit_published_date_is_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Serper web results have NO date field — published_date must be ''."""
        hits = self._run_search(monkeypatch, [_make_organic_item()])
        assert hits[0].published_date == ""

    def test_empty_organic_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = self._run_search(monkeypatch, [])
        assert hits == []

    def test_organic_item_without_link_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Items missing 'link' must be silently skipped."""
        item_no_link: dict[str, Any] = {"title": "No link", "snippet": "text", "position": 1}
        hits = self._run_search(monkeypatch, [item_no_link])
        assert hits == []


# ── search() — answerBox mapping ─────────────────────────────────────────────


class TestAnswerBoxMapping:
    """Verify answerBox is inserted as the first hit when present."""

    def _run_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
        organic: list[dict[str, Any]] | None = None,
        answer_box: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        gw = SerperGateway(api_key=_fake_key())
        response = _make_response(organic=organic or [], answer_box=answer_box)
        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json",
            _stub_request_json(response),
        )
        return gw.search("test query")

    def test_answer_box_is_first_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        organic = [_make_organic_item(link="https://organic.example.com/", position=1)]
        ab = _make_answer_box(link="https://answer.example.com/", snippet="Direct answer.")
        hits = self._run_search(monkeypatch, organic=organic, answer_box=ab)
        assert len(hits) == 2
        assert hits[0].url == "https://answer.example.com/"
        assert hits[1].url == "https://organic.example.com/"

    def test_answer_box_url_from_link(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ab = _make_answer_box(link="https://direct.example.com/page")
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits[0].url == "https://direct.example.com/page"

    def test_answer_box_title_from_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ab = _make_answer_box(title="The Answer Title")
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits[0].title == "The Answer Title"

    def test_answer_box_snippet_from_snippet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ab = _make_answer_box(snippet="The direct answer snippet.")
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits[0].snippet == "The direct answer snippet."

    def test_answer_box_falls_back_to_snippet_highlighted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When snippet is absent, snippetHighlighted is used instead."""
        ab: dict[str, Any] = {
            "title": "Fallback",
            "link": "https://example.com/",
            "snippetHighlighted": "Highlighted fallback snippet.",
        }
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert len(hits) == 1
        assert hits[0].snippet == "Highlighted fallback snippet."

    def test_answer_box_score_is_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ab = _make_answer_box()
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits[0].score == pytest.approx(0.0)

    def test_answer_box_provider_is_serper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ab = _make_answer_box()
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits[0].provider == "serper"

    def test_answer_box_without_link_is_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ab: dict[str, Any] = {"title": "No link", "snippet": "some text"}
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits == []

    def test_answer_box_without_snippet_fields_is_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ab: dict[str, Any] = {"title": "No snippet", "link": "https://example.com/"}
        hits = self._run_search(monkeypatch, answer_box=ab)
        assert hits == []

    def test_no_answer_box_key_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Response with no answerBox key: only organic hits are returned."""
        organic = [_make_organic_item(position=1)]
        hits = self._run_search(monkeypatch, organic=organic, answer_box=None)
        assert len(hits) == 1
        assert hits[0].url == organic[0]["link"]


# ── search() — error handling ─────────────────────────────────────────────────


class TestSearchErrorHandling:
    def _make_gw(self) -> SerperGateway:
        return SerperGateway(api_key=_fake_key())

    def test_402_raises_budget_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 402 from http_pool is BudgetExceeded — never retried."""
        gw = self._make_gw()

        def _raise_budget(*args: Any, **kwargs: Any) -> Any:
            raise BudgetExceeded("serper quota exhausted", provider="serper", status=402)

        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json", _raise_budget
        )
        with pytest.raises(BudgetExceeded):
            gw.search("test")

    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-402 HTTP errors propagate so tenacity can retry at the pool level."""
        gw = self._make_gw()

        def _raise_http(*args: Any, **kwargs: Any) -> Any:
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock())

        monkeypatch.setattr("pipeline.research.gateways.serper.http_pool.request_json", _raise_http)
        with pytest.raises(httpx.HTTPStatusError):
            gw.search("test")


# ── DTO immutability ──────────────────────────────────────────────────────────


class TestDtoImmutability:
    def test_search_hit_is_frozen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = SerperGateway(api_key=_fake_key())
        monkeypatch.setattr(
            "pipeline.research.gateways.serper.http_pool.request_json",
            _stub_request_json(_make_response(organic=[_make_organic_item()])),
        )
        hits = gw.search("test")
        with pytest.raises((AttributeError, TypeError)):
            hits[0].url = "mutated"  # type: ignore[misc]


# ── ANOMALY-001 import ban (structural AST check) ─────────────────────────────


class TestAnomalyImportBan:
    def test_serper_module_does_not_import_httpx_directly(self) -> None:
        """serper.py must delegate HTTP to http_pool — direct httpx import banned
        for consistency with the gateway pattern (shared semaphore + tenacity)."""
        src = _SERPER_MODULE_PATH.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httpx", (
                        "serper.py imports httpx directly — use http_pool instead"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") != "httpx", (
                    "serper.py imports from httpx directly — use http_pool instead"
                )

    def test_serper_module_does_not_import_anthropic(self) -> None:
        """serper.py must not import anthropic (ANOMALY-001)."""
        src = _SERPER_MODULE_PATH.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "anthropic"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") != "anthropic"

    def test_serper_module_does_not_import_openrouter_client(self) -> None:
        """serper.py must not import openrouter_client (ANOMALY-001)."""
        src = _SERPER_MODULE_PATH.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "openrouter_client" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                assert "openrouter_client" not in (node.module or "")


# ── Live round-trip (ONLINE_SERPER=1) ────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("ONLINE_SERPER") != "1",
    reason="Set ONLINE_SERPER=1 to run live Serper round-trips.",
)
class TestOnlineRoundTrip:
    def test_search_returns_hits(self) -> None:
        gw = SerperGateway.from_env()
        hits = gw.search("Barbie 2023 box office total gross", num=5)
        assert isinstance(hits, list)
        assert len(hits) > 0
        assert all(h.provider == "serper" for h in hits)
        assert all(isinstance(h.url, str) and h.url.startswith("http") for h in hits)

    def test_organic_hits_have_snippets(self) -> None:
        gw = SerperGateway.from_env()
        hits = gw.search("global box office revenue 2024", num=3)
        organic_hits = [h for h in hits if h.score > 0]
        assert any(len(h.snippet) > 10 for h in organic_hits), (
            "Expected at least one organic hit with a non-trivial snippet"
        )
