"""pipeline/research/gateways/exa.py — Exa SEARCH+FETCH gateway.

Direct Exa API (not via 302.ai proxy). A single POST to
``https://api.exa.ai/search`` with ``contents.text=true`` returns search
hits with full page text inline — no second ``/contents`` round-trip needed.

Confirmed schema (from runs/research/gw_smoke_snapshot.md):
  - Endpoint:  POST https://api.exa.ai/search
  - Auth:      ``x-api-key: <EXA_API_KEY>``  (lowercase; Bearer rejected)
  - Request:   {"query": str, "numResults": int, "contents": {"text": true}}
  - Response top-level keys: requestId, resolvedSearchType, results,
                              searchTime, costDollars
  - results[].id          == URL (canonical identity key)
  - results[].url         == full URL (use this)
  - results[].title       == page title
  - results[].text        == full extracted page text (inline when text=true)
  - results[].publishedDate  (may be absent)
  - results[].score          (may be absent)

Mapping:
  - SearchHit: url=results[].url, title=results[].title,
               snippet=results[].text[:500], score=results[].score or 0.0,
               provider="exa", published_date=results[].publishedDate or ""
  - FetchedPage: url=results[].url, final_url=results[].url,
                 status=200, text=results[].text, markdown=results[].text,
                 content_sha256=sha256(text), fetched_at=<now UTC>,
                 provider="exa", ok=bool(text)

Error handling:
  - HTTP 402 -> ``http_pool.BudgetExceeded`` (never retried)
  - HTTP 429 -> retried by tenacity via ``http_pool.request_json``
  - All other 4xx/5xx -> retried by tenacity

ADR-0007: HTTP lives in pipeline/research/ — NOT on ANOMALY-001 ban list.
ADR-0003: EXA_API_KEY masked to first 8 chars in all log output.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, openrouter_client, or pipeline.run.

Integration (ANOMALY-003): exported by pipeline.research.gateways.__init__
and imported by pipeline.research.__init__ so the orphan gate stays green.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import UTC, datetime
from typing import Any

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:
    pass

from pipeline.research import http_pool
from pipeline.research.providers.types import FetchedPage, SearchHit

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────

_EXA_SEARCH_URL: str = "https://api.exa.ai/search"
_EXA_PROVIDER_SLUG: str = "exa"
_DEFAULT_NUM_RESULTS: int = 5
_SNIPPET_MAX_LEN: int = 500


# ── Gateway class ─────────────────────────────────────────────────────────────


class ExaGateway:
    """Exa SEARCH+FETCH gateway.

    A single ``search()`` call returns both :class:`SearchHit` objects and
    :class:`FetchedPage` objects because Exa returns inline page text when
    ``contents.text=true`` is passed — no separate fetch round-trip needed.

    Authentication: ``EXA_API_KEY`` env var (lowercase ``x-api-key`` header).
    Key masking: first 8 chars only in all log output (SEC-07 / ADR-0003).
    Rate-limiting: delegated to :mod:`pipeline.research.http_pool`.

    Examples
    --------
    >>> gw = ExaGateway.from_env()
    >>> hits, pages = gw.search("Severance season 2 budget", num_results=3)
    >>> hits[0].provider
    'exa'
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise KeyError("EXA_API_KEY not set")
        self._key: str = api_key
        self._masked: str = http_pool.mask_key(api_key)

    def __repr__(self) -> str:
        return f"ExaGateway(key={self._masked})"

    @classmethod
    def from_env(cls) -> ExaGateway:
        """Construct from ``EXA_API_KEY`` environment variable.

        Raises
        ------
        KeyError
            If ``EXA_API_KEY`` is absent or empty after stripping whitespace.
        """
        raw = os.environ.get("EXA_API_KEY", "").strip()
        if not raw:
            raise KeyError("EXA_API_KEY not set or empty")
        return cls(api_key=raw)

    # ── Public search+fetch ───────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        num_results: int = _DEFAULT_NUM_RESULTS,
    ) -> tuple[list[SearchHit], list[FetchedPage]]:
        """Search Exa and return both hits and pre-fetched pages.

        Exa returns full page text inline when ``contents.text=true`` is sent,
        so one POST gives both search rankings and page content with no
        second round-trip.

        Parameters
        ----------
        query:
            Search query string.
        num_results:
            Number of results to request (default 5).

        Returns
        -------
        (hits, pages):
            ``hits`` — list of :class:`SearchHit` (ranked by Exa relevance).
            ``pages`` — list of :class:`FetchedPage` (one per hit, inline text).

        Raises
        ------
        http_pool.BudgetExceeded
            If Exa returns HTTP 402.
        httpx.HTTPError
            If all retry attempts fail.
        """
        logger.info(
            "ExaGateway.search key=%s query=%.60s num_results=%d",
            self._masked,
            query,
            num_results,
        )
        headers = self._auth_headers()
        body: dict[str, Any] = {
            "query": query,
            "numResults": num_results,
            "contents": {"text": True},
        }

        _status, _final_url, data = http_pool.request_json(
            "POST",
            _EXA_SEARCH_URL,
            headers=headers,
            json_body=body,
            provider=_EXA_PROVIDER_SLUG,
        )

        results_raw: list[dict[str, Any]] = data.get("results", [])
        fetched_at = datetime.now(UTC).isoformat()

        hits: list[SearchHit] = []
        pages: list[FetchedPage] = []

        for item in results_raw:
            url = item.get("url") or item.get("id", "")
            title = item.get("title", "")
            text = item.get("text", "")
            score = float(item.get("score", 0.0)) if item.get("score") is not None else 0.0
            published_date = item.get("publishedDate", "") or ""

            snippet = text[:_SNIPPET_MAX_LEN] if text else ""

            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=snippet,
                    score=score,
                    provider=_EXA_PROVIDER_SLUG,
                    published_date=published_date,
                )
            )

            content_sha256 = hashlib.sha256(text.encode()).hexdigest() if text else ""
            pages.append(
                FetchedPage(
                    url=url,
                    final_url=url,
                    status=200,
                    text=text,
                    markdown=text,
                    content_sha256=content_sha256,
                    fetched_at=fetched_at,
                    provider=_EXA_PROVIDER_SLUG,
                    ok=bool(text),
                )
            )

        logger.info(
            "ExaGateway.search key=%s returned %d results cost_dollars=%s",
            self._masked,
            len(hits),
            data.get("costDollars", "n/a"),
        )
        return hits, pages

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Return Exa auth headers.

        Exa uses lowercase ``x-api-key`` (Bearer is rejected per smoke test).
        """
        return {
            "x-api-key": self._key,
            "Content-Type": "application/json",
        }
