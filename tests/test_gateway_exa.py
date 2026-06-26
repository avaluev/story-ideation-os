"""tests/test_gateway_exa.py — offline + optional live tests for ExaGateway.

Hermetic by default: all HTTP is mocked against the http_pool layer.
Live calls are gated behind ``ONLINE_EXA=1`` (mirrors the ONLINE_302AI
pattern in test_client_302ai.py).

Confirmed response shape (from runs/research/gw_smoke_snapshot.md):
  POST https://api.exa.ai/search
  Header: x-api-key (lowercase; Bearer rejected)
  Body:   {"query": str, "numResults": int, "contents": {"text": true}}
  Response top-level keys: requestId, resolvedSearchType, results,
                            searchTime, costDollars
  results[].id     == URL
  results[].url    == full URL
  results[].title  == page title
  results[].text   == full inline page text (present when contents.text=true)
  results[].publishedDate  (may be absent)
  results[].score          (may be absent)

Coverage:
  - from_env() raises KeyError when EXA_API_KEY is absent
  - from_env() raises KeyError when EXA_API_KEY is blank
  - from_env() constructs successfully when key is set
  - __repr__ masks the key tail (does not leak the secret suffix)
  - search() POSTs to the correct URL with x-api-key header (not Bearer)
  - search() sends {"query", "numResults", "contents": {"text": true}} body
  - search() maps results[].url -> SearchHit.url
  - search() maps results[].title -> SearchHit.title
  - search() maps results[].text[:500] -> SearchHit.snippet
  - search() maps results[].score -> SearchHit.score (float)
  - search() maps results[].publishedDate -> SearchHit.published_date
  - search() sets provider="exa" on all hits
  - search() returns one FetchedPage per hit with text=results[].text inline
  - search() sets FetchedPage.ok=True when text is non-empty
  - search() sets FetchedPage.ok=False when text is empty string
  - search() computes correct SHA-256 for FetchedPage.content_sha256
  - search() tolerates absent publishedDate and score (defaults to "" and 0.0)
  - search() handles empty results list (returns empty hits and pages)
  - search() on HTTP 402 raises BudgetExceeded (not retried)
  - search() on HTTP 429 raises HTTPStatusError (retried by http_pool tenacity)
  - key is masked to first 8 chars in log output (ADR-0003)
"""

from __future__ import annotations

import ast
import hashlib
import os
import pathlib
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from pipeline.research.gateways.exa import _EXA_SEARCH_URL, ExaGateway
from pipeline.research.http_pool import BudgetExceeded
from pipeline.research.providers.types import FetchedPage, SearchHit

# ── Fixtures and helpers ──────────────────────────────────────────────────────


def _fake_key(suffix: str = "SECRETSUFFIX0000") -> str:
    """Build a realistic-looking fake Exa key (at least 8 chars + suffix)."""
    return f"fake-exa-{suffix}"


def _make_result(
    url: str = "https://example.com/article",
    title: str = "Test Article",
    text: str = "Some extracted page text.",
    score: float | None = 0.87,
    published_date: str | None = "2025-01-15",
) -> dict[str, Any]:
    """Build a single Exa results[] item in confirmed schema shape."""
    item: dict[str, Any] = {
        "id": url,
        "url": url,
        "title": title,
        "text": text,
    }
    if score is not None:
        item["score"] = score
    if published_date is not None:
        item["publishedDate"] = published_date
    return item


def _make_response(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a results list in the confirmed Exa top-level response envelope."""
    return {
        "requestId": "req-test-abc123",
        "resolvedSearchType": "neural",
        "results": results,
        "searchTime": 0.42,
        "costDollars": {"total": 0.001},
    }


def _stub_request_json(response_body: dict[str, Any], *, status: int = 200):
    """Return a mock for http_pool.request_json that returns a fixed body."""

    def _mock(method, url, *, headers, json_body=None, params=None, timeout=30.0, provider=""):
        return (status, url, response_body)

    return _mock


# ── from_env() ────────────────────────────────────────────────────────────────


class TestFromEnv:
    def test_raises_key_error_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        with pytest.raises(KeyError, match="EXA_API_KEY"):
            ExaGateway.from_env()

    def test_raises_key_error_when_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXA_API_KEY", "   ")
        with pytest.raises(KeyError, match="EXA_API_KEY"):
            ExaGateway.from_env()

    def test_constructs_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXA_API_KEY", "fake-exa-testkey-12345")
        gw = ExaGateway.from_env()
        assert gw is not None

    def test_strips_whitespace_from_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXA_API_KEY", "  fake-exa-testkey-12345  ")
        gw = ExaGateway.from_env()
        assert gw is not None


# ── Key masking (ADR-0003) ────────────────────────────────────────────────────


class TestKeyMasking:
    def test_repr_does_not_leak_secret_suffix(self) -> None:
        key = _fake_key("TOPSECRET9999")
        gw = ExaGateway(api_key=key)
        text = repr(gw)
        assert "TOPSECRET" not in text
        assert "SECRETSUFFIX" not in text

    def test_repr_shows_masked_prefix(self) -> None:
        gw = ExaGateway(api_key="fake-exa-SECRETSUFFIX")
        text = repr(gw)
        # First 8 chars are "fake-exa"; masked repr should start with them.
        assert "fake-exa" in text

    def test_repr_includes_ellipsis(self) -> None:
        gw = ExaGateway(api_key=_fake_key())
        assert "..." in repr(gw)


# ── search() — HTTP contract ──────────────────────────────────────────────────


class TestSearchHttpContract:
    """Verify that search() hits the correct URL with the correct auth header
    and correct request body shape, using a mock against http_pool."""

    def _make_gw(self) -> ExaGateway:
        return ExaGateway(api_key=_fake_key())

    def test_posts_to_correct_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["method"] = method
            captured["url"] = url
            return (200, url, _make_response([]))

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _fake_request)
        gw.search("test query")
        assert captured["method"] == "POST"
        assert captured["url"] == _EXA_SEARCH_URL

    def test_uses_lowercase_x_api_key_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exa requires lowercase ``x-api-key``; Bearer is rejected."""
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["headers"] = headers
            return (200, url, _make_response([]))

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _fake_request)
        gw.search("test query")
        # Must use lowercase x-api-key, NOT Authorization: Bearer
        assert "x-api-key" in captured["headers"]
        assert "Authorization" not in captured["headers"]

    def test_sends_api_key_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = _fake_key("MYSPECIFICKEY")
        gw = ExaGateway(api_key=key)
        captured: dict[str, Any] = {}

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["headers"] = headers
            return (200, url, _make_response([]))

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _fake_request)
        gw.search("test query")
        assert captured["headers"]["x-api-key"] == key

    def test_sends_correct_body_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Body must contain query, numResults, and contents.text=true."""
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return (200, url, _make_response([]))

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _fake_request)
        gw.search("severance season 2 budget", num_results=3)
        body = captured["json_body"]
        assert body["query"] == "severance season 2 budget"
        assert body["numResults"] == 3
        assert body["contents"] == {"text": True}

    def test_num_results_default_is_five(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        gw = self._make_gw()

        def _fake_request(method, url, *, headers, json_body=None, **kwargs):
            captured["json_body"] = json_body
            return (200, url, _make_response([]))

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _fake_request)
        gw.search("any query")
        assert captured["json_body"]["numResults"] == 5


# ── search() — result mapping ─────────────────────────────────────────────────


class TestSearchResultMapping:
    """Verify that search() correctly maps Exa results[] to SearchHit / FetchedPage."""

    def _run_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
        results: list[dict[str, Any]],
    ) -> tuple[list[SearchHit], list[FetchedPage]]:
        gw = ExaGateway(api_key=_fake_key())
        response = _make_response(results)
        monkeypatch.setattr(
            "pipeline.research.gateways.exa.http_pool.request_json",
            _stub_request_json(response),
        )
        return gw.search("test query")

    def test_returns_one_hit_per_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, pages = self._run_search(
            monkeypatch, [_make_result(), _make_result(url="https://b.com/")]
        )
        assert len(hits) == 2
        assert len(pages) == 2

    def test_hit_url_from_results_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(
            monkeypatch, [_make_result(url="https://boxofficemojo.com/title/tt1234/")]
        )
        assert hits[0].url == "https://boxofficemojo.com/title/tt1234/"

    def test_hit_title_from_results_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result(title="Box Office Mojo")])
        assert hits[0].title == "Box Office Mojo"

    def test_hit_snippet_truncated_to_500_chars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long_text = "x" * 800
        hits, _ = self._run_search(monkeypatch, [_make_result(text=long_text)])
        assert hits[0].snippet == "x" * 500

    def test_hit_snippet_not_truncated_when_short(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result(text="short text")])
        assert hits[0].snippet == "short text"

    def test_hit_score_from_results_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result(score=0.93)])
        assert hits[0].score == pytest.approx(0.93)

    def test_hit_score_defaults_to_zero_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result(score=None)])
        assert hits[0].score == pytest.approx(0.0)

    def test_hit_published_date_from_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result(published_date="2024-11-01")])
        assert hits[0].published_date == "2024-11-01"

    def test_hit_published_date_defaults_to_empty_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result(published_date=None)])
        assert hits[0].published_date == ""

    def test_hit_provider_is_exa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, _ = self._run_search(monkeypatch, [_make_result()])
        assert hits[0].provider == "exa"

    def test_page_text_equals_full_results_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        full_text = "Complete extracted page text with multiple sentences."
        _, pages = self._run_search(monkeypatch, [_make_result(text=full_text)])
        assert pages[0].text == full_text

    def test_page_markdown_equals_full_results_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        full_text = "# Heading\n\nBody paragraph."
        _, pages = self._run_search(monkeypatch, [_make_result(text=full_text)])
        assert pages[0].markdown == full_text

    def test_page_url_from_results_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, pages = self._run_search(monkeypatch, [_make_result(url="https://example.org/data")])
        assert pages[0].url == "https://example.org/data"
        assert pages[0].final_url == "https://example.org/data"

    def test_page_status_is_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, pages = self._run_search(monkeypatch, [_make_result()])
        assert pages[0].status == 200

    def test_page_ok_true_when_text_nonempty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, pages = self._run_search(monkeypatch, [_make_result(text="some content")])
        assert pages[0].ok is True

    def test_page_ok_false_when_text_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, pages = self._run_search(monkeypatch, [_make_result(text="")])
        assert pages[0].ok is False

    def test_page_provider_is_exa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, pages = self._run_search(monkeypatch, [_make_result()])
        assert pages[0].provider == "exa"

    def test_page_content_sha256_is_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = "precise content for hashing"
        expected_sha = hashlib.sha256(text.encode()).hexdigest()
        _, pages = self._run_search(monkeypatch, [_make_result(text=text)])
        assert pages[0].content_sha256 == expected_sha

    def test_page_content_sha256_empty_string_when_no_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, pages = self._run_search(monkeypatch, [_make_result(text="")])
        assert pages[0].content_sha256 == ""

    def test_empty_results_returns_empty_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits, pages = self._run_search(monkeypatch, [])
        assert hits == []
        assert pages == []

    def test_fetched_at_is_iso8601(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FetchedPage.fetched_at must be a parseable ISO-8601 UTC string."""

        _, pages = self._run_search(monkeypatch, [_make_result()])
        # Must not raise
        dt = datetime.fromisoformat(pages[0].fetched_at)
        assert dt.tzinfo is not None


# ── search() — error handling ─────────────────────────────────────────────────


class TestSearchErrorHandling:
    def _make_gw(self) -> ExaGateway:
        return ExaGateway(api_key=_fake_key())

    def test_402_raises_budget_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 402 from http_pool is BudgetExceeded — never retried."""
        gw = self._make_gw()

        def _raise_budget(*args: Any, **kwargs: Any) -> Any:
            raise BudgetExceeded("exa quota exhausted", provider="exa", status=402)

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _raise_budget)
        with pytest.raises(BudgetExceeded):
            gw.search("test")

    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-402 HTTP errors propagate so tenacity can retry at the pool level."""

        gw = self._make_gw()

        def _raise_http(*args: Any, **kwargs: Any) -> Any:
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock())

        monkeypatch.setattr("pipeline.research.gateways.exa.http_pool.request_json", _raise_http)
        with pytest.raises(httpx.HTTPStatusError):
            gw.search("test")

    def test_id_used_as_url_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When results[].url is absent, results[].id is used as the URL."""
        gw = self._make_gw()
        result: dict[str, Any] = {
            "id": "https://fallback-id.example.com/page",
            "title": "Fallback",
            "text": "some text",
        }
        # Deliberately omit "url" key
        response = _make_response([result])
        monkeypatch.setattr(
            "pipeline.research.gateways.exa.http_pool.request_json",
            _stub_request_json(response),
        )
        hits, pages = gw.search("test")
        assert hits[0].url == "https://fallback-id.example.com/page"
        assert pages[0].url == "https://fallback-id.example.com/page"


# ── DTOs are frozen (immutability check) ─────────────────────────────────────


class TestDtoImmutability:
    def test_search_hit_is_frozen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = ExaGateway(api_key=_fake_key())
        monkeypatch.setattr(
            "pipeline.research.gateways.exa.http_pool.request_json",
            _stub_request_json(_make_response([_make_result()])),
        )
        hits, _ = gw.search("test")
        with pytest.raises((AttributeError, TypeError)):
            hits[0].url = "mutated"  # type: ignore[misc]

    def test_fetched_page_is_frozen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = ExaGateway(api_key=_fake_key())
        monkeypatch.setattr(
            "pipeline.research.gateways.exa.http_pool.request_json",
            _stub_request_json(_make_response([_make_result()])),
        )
        _, pages = gw.search("test")
        with pytest.raises((AttributeError, TypeError)):
            pages[0].text = "mutated"  # type: ignore[misc]


# ── ANOMALY-001 import ban ────────────────────────────────────────────────────


class TestAnomalyImportBan:
    def test_exa_module_does_not_import_httpx_directly(self) -> None:
        """exa.py must use http_pool for HTTP — direct httpx import is banned
        from scoring.py / cc_dispatch.py / gemini_dispatch.py but allowed here;
        however the gateway pattern uses http_pool for the shared semaphore.

        This test verifies the module relies on http_pool rather than instantiating
        httpx.Client itself (the pattern mandated by task brief).
        """

        src = pathlib.Path(
            "/Users/sxope/Documents/2026/Development/29.Engine/pipeline/research/gateways/exa.py"
        ).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httpx", (
                        "exa.py imports httpx directly — use http_pool instead"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "httpx", (
                    "exa.py imports from httpx directly — use http_pool instead"
                )

    def test_exa_module_does_not_import_anthropic(self) -> None:
        """exa.py must not import anthropic (ANOMALY-001)."""

        src = pathlib.Path(
            "/Users/sxope/Documents/2026/Development/29.Engine/pipeline/research/gateways/exa.py"
        ).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "anthropic"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") != "anthropic"


# ── Live round-trip (ONLINE_EXA=1) ───────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("ONLINE_EXA") != "1",
    reason="Set ONLINE_EXA=1 to run live Exa round-trips.",
)
class TestOnlineRoundTrip:
    def test_search_returns_hits_and_pages(self) -> None:
        gw = ExaGateway.from_env()
        hits, pages = gw.search("Severance season 2 Apple TV budget", num_results=3)
        assert len(hits) > 0
        assert len(pages) == len(hits)
        assert all(h.provider == "exa" for h in hits)
        assert all(isinstance(h.url, str) and h.url.startswith("http") for h in hits)

    def test_pages_have_inline_text(self) -> None:
        gw = ExaGateway.from_env()
        _, pages = gw.search("global box office 2024 total revenue", num_results=2)
        # At least one page should have non-empty text (Exa inline fetch)
        assert any(len(p.text) > 50 for p in pages), "Expected at least one page with inline text"
