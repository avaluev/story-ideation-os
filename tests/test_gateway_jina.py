"""tests/test_gateway_jina.py — hermetic unit tests for JinaGateway.

All HTTP calls are mocked against ``pipeline.research.http_pool``.
Live round-trips are gated behind ``ONLINE_JINA=1`` (mirrors the
ONLINE_302AI pattern in test_client_302ai.py).

Coverage
--------
- ``from_env()`` — keyless fallback when JINA_API_KEY absent.
- ``from_env()`` — uses key when JINA_API_KEY is set.
- ``fetch()`` — builds correct URL, passes auth header, strips sentinel,
                populates FetchedPage fields.
- ``fetch()`` keyless — omits Authorization header.
- ``fetch()`` 402 — re-raises BudgetExceeded without retry.
- ``fetch()`` 429 — propagates HTTPStatusError for tenacity.
- ``search()`` — builds correct URL+headers, maps data[] to SearchHit list.
- ``search()`` max_results — truncates to requested count.
- ``search()`` empty data — returns empty list.
- ``_strip_jina_sentinel()`` — sentinel present / absent / multi-line body.
- Key masking — Authorization header masked to first 8 chars in repr.

ADR-0003: no live key in any assertion; masked form only.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pipeline.research.gateways.jina import (
    JinaGateway,
    _strip_jina_sentinel,
)
from pipeline.research.http_pool import BudgetExceeded
from pipeline.research.providers.types import FetchedPage, SearchHit

# ── Fixtures ──────────────────────────────────────────────────────────────────

_FAKE_KEY = "jina_fake_test_key_XXXX"
_FAKE_URL = "https://www.boxofficemojo.com/year/world/2023/"

_READER_RAW = (
    "Title: Box Office Mojo 2023\n\n"
    "URL Source: https://www.boxofficemojo.com/year/world/2023/\n\n"
    "Markdown Content:\n"
    "# World Box Office 2023\n\n"
    "| Rank | Title | Gross |\n"
    "|------|-------|-------|\n"
    "| 1    | Barbie | $1.44B |\n"
)

_SEARCH_BODY: dict[str, Any] = {
    "code": 200,
    "status": 20000,
    "data": [
        {
            "title": "Box Office 2023 Overview",
            "url": "https://www.boxofficemojo.com/year/world/2023/",
            "content": "Global box office hit $8.5B in 2023.",
            "score": 0.92,
            "publishedDate": "2024-01-15",
        },
        {
            "title": "The Numbers 2023",
            "url": "https://www.the-numbers.com/market/2023/summary",
            "content": "Domestic total for 2023 reached $9.1B.",
            "score": 0.85,
            "publishedDate": "",
        },
        {
            "title": "Variety 2023 Wrap",
            "url": "https://variety.com/2024/film/news/box-office-2023-wrap/",
            "content": "Record-breaking year for global cinema.",
            "score": 0.78,
            "publishedDate": "2024-01-05",
        },
    ],
    "meta": {"total": 3},
}


# ── Helper: mock http_pool.request_text ───────────────────────────────────────


def _mock_request_text(
    status: int = 200,
    body: str = _READER_RAW,
    final_url: str = _FAKE_URL,
) -> MagicMock:
    m = MagicMock(return_value=(status, final_url, body))
    return m


def _mock_request_json(
    status: int = 200,
    body: dict[str, Any] | None = None,
    final_url: str = "https://s.jina.ai/query",
) -> MagicMock:
    m = MagicMock(return_value=(status, final_url, body or _SEARCH_BODY))
    return m


# ── _strip_jina_sentinel ──────────────────────────────────────────────────────


class TestStripJinaSentinel:
    def test_strips_header_metadata(self) -> None:
        result = _strip_jina_sentinel(_READER_RAW)
        assert result.startswith("# World Box Office 2023")
        assert "Title:" not in result
        assert "URL Source:" not in result

    def test_no_sentinel_returns_full_body(self) -> None:
        raw = "Some plain text without the sentinel."
        assert _strip_jina_sentinel(raw) == raw

    def test_sentinel_at_end_returns_empty(self) -> None:
        raw = "Header stuff\n\nMarkdown Content:\n"
        result = _strip_jina_sentinel(raw)
        assert result == ""

    def test_multiline_body_preserved(self) -> None:
        raw = "Title: X\n\nMarkdown Content:\n## H2\n\nParagraph.\n"
        result = _strip_jina_sentinel(raw)
        assert "## H2" in result
        assert "Paragraph." in result


# ── from_env ──────────────────────────────────────────────────────────────────


class TestFromEnv:
    def test_keyless_when_var_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", "")
        gw = JinaGateway.from_env()
        assert gw._key == ""

    def test_uses_key_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", _FAKE_KEY)
        gw = JinaGateway.from_env()
        assert gw._key == _FAKE_KEY

    def test_repr_masks_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", _FAKE_KEY)
        gw = JinaGateway.from_env()
        text = repr(gw)
        # Must show only the first 8 chars, not the full key
        assert _FAKE_KEY not in text
        assert _FAKE_KEY[:8] in text

    def test_repr_keyless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", "")
        gw = JinaGateway.from_env()
        assert "(keyless)" in repr(gw)


# ── fetch ─────────────────────────────────────────────────────────────────────


class TestFetch:
    def test_builds_correct_reader_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """request_text must be called with r.jina.ai/<target_url>."""
        mock = _mock_request_text()
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            gw = JinaGateway(api_key=_FAKE_KEY)
            gw.fetch(_FAKE_URL)

        called_url = mock.call_args[0][1]
        assert called_url == f"https://r.jina.ai/{_FAKE_URL}"

    def test_passes_bearer_auth_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _mock_request_text()
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            gw = JinaGateway(api_key=_FAKE_KEY)
            gw.fetch(_FAKE_URL)

        headers = mock.call_args[1]["headers"]
        assert headers.get("Authorization") == f"Bearer {_FAKE_KEY}"

    def test_keyless_omits_auth_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _mock_request_text()
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            gw = JinaGateway(api_key="")
            gw.fetch(_FAKE_URL)

        headers = mock.call_args[1]["headers"]
        assert "Authorization" not in headers

    def test_returns_fetched_page_ok_true(self) -> None:
        mock = _mock_request_text(status=200)
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

        assert isinstance(page, FetchedPage)
        assert page.ok is True
        assert page.status == 200
        assert page.provider == "jina"
        assert page.url == _FAKE_URL

    def test_sentinel_stripped_in_markdown(self) -> None:
        mock = _mock_request_text(body=_READER_RAW)
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

        assert page.markdown.startswith("# World Box Office 2023")
        assert "Title:" not in page.markdown
        assert "Markdown Content:" not in page.markdown

    def test_raw_text_in_text_field(self) -> None:
        """FetchedPage.text must hold the raw (pre-strip) body for SHA-256."""
        mock = _mock_request_text(body=_READER_RAW)
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

        assert page.text == _READER_RAW

    def test_content_sha256_matches_raw_text(self) -> None:
        mock = _mock_request_text(body=_READER_RAW)
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

        expected = hashlib.sha256(_READER_RAW.encode("utf-8")).hexdigest()
        assert page.content_sha256 == expected

    def test_fetched_at_is_iso8601(self) -> None:
        mock = _mock_request_text()
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

        # Basic ISO-8601 check: starts with year and contains T
        assert len(page.fetched_at) >= 19
        assert "T" in page.fetched_at

    def test_non_2xx_sets_ok_false(self) -> None:
        """A non-2xx status that slips through should set ok=False."""
        mock = _mock_request_text(status=404)
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

        assert page.ok is False
        assert page.status == 404

    def test_402_raises_budget_exceeded(self) -> None:
        mock = MagicMock(side_effect=BudgetExceeded("jina 402", provider="jina", status=402))
        with (
            patch("pipeline.research.gateways.jina.http_pool.request_text", mock),
            pytest.raises(BudgetExceeded),
        ):
            JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

    def test_429_propagates_http_error(self) -> None:
        mock = MagicMock(
            side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock())
        )
        with (
            patch("pipeline.research.gateways.jina.http_pool.request_text", mock),
            pytest.raises(httpx.HTTPStatusError),
        ):
            JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)

    def test_provider_tag_in_fetched_page(self) -> None:
        mock = _mock_request_text()
        with patch("pipeline.research.gateways.jina.http_pool.request_text", mock):
            page = JinaGateway(api_key=_FAKE_KEY).fetch(_FAKE_URL)
        assert page.provider == "jina"


# ── search ────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_builds_correct_search_url(self) -> None:
        """request_json must be called with s.jina.ai/<url-encoded-query>."""
        mock = _mock_request_json()
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            JinaGateway(api_key=_FAKE_KEY).search("box office 2023")

        called_url: str = mock.call_args[0][1]
        assert called_url.startswith("https://s.jina.ai/")
        # Query must be URL-encoded
        assert " " not in called_url
        assert (
            "box%20office" in called_url
            or "box+office" in called_url
            or "box%20office" in called_url
        )

    def test_passes_bearer_auth_header(self) -> None:
        mock = _mock_request_json()
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            JinaGateway(api_key=_FAKE_KEY).search("test")

        headers = mock.call_args[1]["headers"]
        assert headers.get("Authorization") == f"Bearer {_FAKE_KEY}"

    def test_accept_json_header_present(self) -> None:
        mock = _mock_request_json()
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            JinaGateway(api_key=_FAKE_KEY).search("test")

        headers = mock.call_args[1]["headers"]
        assert headers.get("Accept") == "application/json"

    def test_maps_data_to_search_hits(self) -> None:
        mock = _mock_request_json()
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            hits = JinaGateway(api_key=_FAKE_KEY).search("box office 2023")

        assert len(hits) == 3
        assert all(isinstance(h, SearchHit) for h in hits)
        assert hits[0].url == "https://www.boxofficemojo.com/year/world/2023/"
        assert hits[0].title == "Box Office 2023 Overview"
        assert "8.5B" in hits[0].snippet
        assert hits[0].score == pytest.approx(0.92)
        assert hits[0].provider == "jina"
        assert hits[0].published_date == "2024-01-15"

    def test_max_results_truncates(self) -> None:
        mock = _mock_request_json()
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            hits = JinaGateway(api_key=_FAKE_KEY).search("test", max_results=2)

        assert len(hits) == 2

    def test_empty_data_returns_empty_list(self) -> None:
        empty_body: dict[str, Any] = {"code": 200, "status": 20000, "data": [], "meta": {}}
        mock = _mock_request_json(body=empty_body)
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            hits = JinaGateway(api_key=_FAKE_KEY).search("no results query")

        assert hits == []

    def test_missing_published_date_defaults_empty_string(self) -> None:
        body: dict[str, Any] = {
            "code": 200,
            "status": 20000,
            "data": [{"title": "T", "url": "https://example.com/a", "content": "C"}],
            "meta": {},
        }
        mock = _mock_request_json(body=body)
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            hits = JinaGateway(api_key=_FAKE_KEY).search("q")

        assert hits[0].published_date == ""

    def test_402_raises_budget_exceeded(self) -> None:
        mock = MagicMock(side_effect=BudgetExceeded("jina search 402", provider="jina", status=402))
        with (
            patch("pipeline.research.gateways.jina.http_pool.request_json", mock),
            pytest.raises(BudgetExceeded),
        ):
            JinaGateway(api_key=_FAKE_KEY).search("test")

    def test_keyless_search_omits_auth_header(self) -> None:
        mock = _mock_request_json()
        with patch("pipeline.research.gateways.jina.http_pool.request_json", mock):
            JinaGateway(api_key="").search("test")

        headers = mock.call_args[1]["headers"]
        assert "Authorization" not in headers


# ── Live round-trip (ONLINE_JINA=1 only) ─────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("ONLINE_JINA") != "1",
    reason="Set ONLINE_JINA=1 to run live Jina round-trips.",
)
class TestOnlineRoundTrip:
    def test_fetch_returns_markdown(self) -> None:
        gw = JinaGateway.from_env()
        page = gw.fetch("https://www.boxofficemojo.com/year/world/2023/")
        assert page.ok
        assert len(page.markdown) > 100
        assert "Title:" not in page.markdown  # sentinel stripped
        assert page.content_sha256 != ""

    def test_search_returns_hits(self) -> None:
        gw = JinaGateway.from_env()
        hits = gw.search("global box office 2023 total gross", max_results=3)
        assert isinstance(hits, list)
        assert len(hits) > 0
        assert all(isinstance(h, SearchHit) for h in hits)
        assert all(h.url.startswith("http") for h in hits)
