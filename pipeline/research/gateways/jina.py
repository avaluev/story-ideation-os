"""pipeline/research/gateways/jina.py — Jina Reader + Search gateway.

Provides:
  - ``JinaGateway.fetch(url)``   -> ``FetchedPage``   (via r.jina.ai/<url>)
  - ``JinaGateway.search(query)`` -> ``list[SearchHit]`` (via s.jina.ai/<query>)

Both methods use ``pipeline.research.http_pool`` for rate-limited HTTP with
4-attempt tenacity retry, concurrency semaphore, and 402/429 handling.

Auth: optional ``Authorization: Bearer <JINA_API_KEY>`` — Jina works without
a key (rate-limited). When the env var is absent, the header is omitted.

Response parsing
----------------
Reader (r.jina.ai):
  Content-Type is ``text/plain`` even though the body is structured markdown.
  Strip lines up to and including the ``Markdown Content:`` sentinel to return
  clean markdown in ``FetchedPage.markdown``.  ``FetchedPage.text`` holds the
  raw (pre-strip) body for provenance SHA-256.

Search (s.jina.ai):
  JSON envelope ``{code, status, data[], meta}``.  Map ``data[].url`` ->
  ``SearchHit.url``, ``data[].content`` -> ``SearchHit.snippet``,
  ``data[].title`` -> ``SearchHit.title``.

Error handling
--------------
HTTP 402 -> ``BudgetExceeded`` (re-raised, not retried).
HTTP 429 -> ``httpx.HTTPStatusError`` -> tenacity retries via http_pool.
Non-2xx -> ``httpx.HTTPStatusError`` -> tenacity retries via http_pool.

ADR-0007: HTTP is allowed in pipeline/research/ — not on the ANOMALY-001 ban list.
ADR-0003: API key masked to first 8 chars in all log output (SEC-07).
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, openrouter_client, or pipeline.run.
ANOMALY-003: imported by pipeline/research/gateways/__init__.py and
             pipeline/research/__init__.py — orphan gate stays green.
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from pipeline.research import http_pool
from pipeline.research.providers.types import FetchedPage, SearchHit

logger = logging.getLogger(__name__)

# ── Named constants ────────────────────────────────────────────────────────────

_READER_BASE: str = "https://r.jina.ai/"
_SEARCH_BASE: str = "https://s.jina.ai/"
_PROVIDER: str = "jina"

_MARKDOWN_SENTINEL: str = "Markdown Content:"
"""Lines before (and including) this sentinel are header metadata, not content."""

_DEFAULT_TIMEOUT: float = 45.0
"""Jina can be slow on large pages — use a slightly longer timeout than the pool default."""

_HTTP_OK_MIN: int = 200
_HTTP_OK_MAX: int = 300
"""A 2xx status (``_HTTP_OK_MIN <= status < _HTTP_OK_MAX``) marks a fetched page OK."""


# ── Key helpers ────────────────────────────────────────────────────────────────


def _load_key() -> str:
    """Return the raw JINA_API_KEY value, or '' if unset/blank."""
    return os.environ.get("JINA_API_KEY", "").strip()


def _auth_headers(key: str) -> dict[str, str]:
    """Build request headers, omitting Authorization when key is absent."""
    if key:
        return {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }
    return {"Accept": "application/json"}


def _reader_headers(key: str) -> dict[str, str]:
    """Reader uses text/plain Accept (Jina ignores Accept but Accept JSON breaks reader)."""
    if key:
        return {"Authorization": f"Bearer {key}"}
    return {}


# ── Markdown sentinel stripper ─────────────────────────────────────────────────


def _strip_jina_sentinel(raw: str) -> str:
    """Return only the content after ``Markdown Content:`` sentinel.

    If the sentinel is absent, return the full body unchanged (graceful
    fallback for future Jina API changes).

    Args:
        raw: Full response body text from r.jina.ai.

    Returns:
        Clean markdown string with header metadata removed.
    """
    idx = raw.find(_MARKDOWN_SENTINEL)
    if idx == -1:
        return raw
    after = raw[idx + len(_MARKDOWN_SENTINEL) :]
    # Skip the newline(s) immediately after the sentinel line.
    return after.lstrip("\n")


# ── SHA-256 helper ─────────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    """Return hex-encoded SHA-256 of *text* (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── ISO-8601 UTC timestamp ─────────────────────────────────────────────────────


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


# ── Gateway class ──────────────────────────────────────────────────────────────


class JinaGateway:
    """Jina Reader + Search gateway.

    Wraps ``r.jina.ai`` (fetch) and ``s.jina.ai`` (search) behind the
    ``http_pool`` layer.  Returns provider-agnostic DTOs from
    ``pipeline.research.providers.types``.

    Args:
        api_key: JINA_API_KEY value.  Pass ``""`` to use keyless (rate-limited)
                 mode.  Prefer ``from_env()`` for normal usage.

    Example::

        gateway = JinaGateway.from_env()
        page = gateway.fetch("https://www.boxofficemojo.com/year/world/2023/")
        hits = gateway.search("global box office 2023 total revenue")
    """

    def __init__(self, api_key: str = "") -> None:
        self._key = api_key
        self._masked = http_pool.mask_key(api_key) if api_key else "(keyless)"

    def __repr__(self) -> str:
        return f"JinaGateway(key={self._masked})"

    @classmethod
    def from_env(cls) -> JinaGateway:
        """Construct from the ``JINA_API_KEY`` environment variable.

        Unlike most gateways, Jina works without a key (rate-limited).
        ``from_env()`` returns a keyless gateway if the variable is absent
        rather than raising ``KeyError``.

        Raises:
            KeyError: Never raised — keyless mode is intentionally supported.

        Returns:
            A ``JinaGateway`` instance (may be keyless).
        """
        key = _load_key()
        if not key:
            logger.info(
                "JinaGateway.from_env: JINA_API_KEY not set — using keyless (rate-limited) mode"
            )
        return cls(api_key=key)

    # ── fetch ──────────────────────────────────────────────────────────────────

    def fetch(self, url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> FetchedPage:
        """Fetch a URL via Jina Reader and return a ``FetchedPage``.

        Calls ``GET https://r.jina.ai/<url>`` and strips the Jina header
        sentinel (``Markdown Content:`` block) to return clean markdown.

        Args:
            url:     Target URL to fetch.  Must be absolute (``https://...``).
            timeout: HTTP timeout in seconds (default 45s — Jina is slow on
                     large pages).

        Returns:
            ``FetchedPage`` with ``ok=True`` on success.  ``ok=False`` when
            the response is non-2xx (after all retries).

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all 4 retry attempts fail.
        """
        reader_url = _READER_BASE + url
        headers = _reader_headers(self._key)

        logger.info(
            "JinaGateway.fetch key=%s url=%.80s",
            self._masked,
            url,
        )

        status, final_url, raw_text = http_pool.request_text(
            "GET",
            reader_url,
            headers=headers,
            timeout=timeout,
            provider=_PROVIDER,
        )

        markdown = _strip_jina_sentinel(raw_text)
        fetched_at = _now_iso()

        return FetchedPage(
            url=url,
            final_url=final_url,
            status=status,
            text=raw_text,
            markdown=markdown,
            content_sha256=_sha256(raw_text),
            fetched_at=fetched_at,
            provider=_PROVIDER,
            ok=(_HTTP_OK_MIN <= status < _HTTP_OK_MAX),
        )

    # ── search ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> list[SearchHit]:
        """Search via Jina Search and return a list of ``SearchHit`` objects.

        Calls ``GET https://s.jina.ai/<url-encoded-query>`` with
        ``Accept: application/json``.  Maps ``data[].{url,title,content}``
        to ``SearchHit`` fields.

        Args:
            query:       Search query string.
            max_results: Maximum number of hits to return (slices ``data[]``).
            timeout:     HTTP timeout in seconds (default 45s).

        Returns:
            List of ``SearchHit`` objects (may be empty on no results).

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all 4 retry attempts fail.
        """
        encoded_query = urllib.parse.quote(query, safe="")
        search_url = _SEARCH_BASE + encoded_query
        headers = _auth_headers(self._key)

        logger.info(
            "JinaGateway.search key=%s query=%.60s",
            self._masked,
            query,
        )

        _status, _final_url, body = http_pool.request_json(
            "GET",
            search_url,
            headers=headers,
            timeout=timeout,
            provider=_PROVIDER,
        )

        data: list[dict[str, Any]] = body.get("data", [])
        hits: list[SearchHit] = []
        for item in data[:max_results]:
            hits.append(
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    provider=_PROVIDER,
                    published_date=item.get("publishedDate", ""),
                )
            )

        logger.info(
            "JinaGateway.search: returned %d hits for query=%.40s",
            len(hits),
            query,
        )
        return hits
