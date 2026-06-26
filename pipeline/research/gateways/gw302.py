"""pipeline/research/gateways/gw302.py — Multi-service 302.ai gateway.

Wraps ``pipeline.research.client_302ai.TaoAIClient`` to expose three unified
capabilities as a single gateway object:

  ``serp(query, *, num)``    — SerpApi web-search results -> list[SearchHit]
  ``fetch(url)``             — Firecrawl page-scrape       -> FetchedPage
  ``synth(model, messages)`` — Chat completion (Sonar/OpenAI) -> dict

All HTTP transport is delegated to ``TaoAIClient``; this module never calls
``http_pool.request_json`` or ``httpx`` directly — the 302 client handles
retries, key masking, semaphore, and BudgetExceeded.

Confirmed gateway shapes (from runs/research/gw_smoke_snapshot.md):

SerpApi (via TaoAIClient.serp()):
  - response["organic"][].{title, link, snippet, position}
  - response["answerBox"].{snippet, title, link}  (present on factual queries)
  - NO ``date`` field on organic results for standard web queries
  Mapping: organic[].link -> SearchHit.url, organic[].snippet -> .snippet,
           organic[].title -> .title; score uses 1.0 - (position-1)/num

Firecrawl (via TaoAIClient.crawl()):
  - returns {"url", "markdown", "html", "meta"}  (after inner.data unwrap)
  Mapping: url -> FetchedPage.url+final_url, markdown -> .markdown+.text,
           sha256(markdown) -> .content_sha256, ok = bool(markdown)

Chat/Synth (via TaoAIClient.chat()):
  - TaoAIClient already parses choices[0].message.content and strips JSON fences
  - Returns the parsed dict directly; callers use it as-is

NOTE: 302.ai's Exa endpoint returns HTTP 500 (confirmed in gw_smoke_snapshot.md).
Do NOT route Exa calls through 302.ai — use the direct ExaGateway instead.

ADR-0007: HTTP lives in client_302ai.py; this gateway is a pure adapter.
ADR-0003: TAO_AI_API_KEY masked to first 8 chars in all log output (SEC-07).
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, httpx, openrouter_client, pipeline.run
             at module level — only import TaoAIClient (which owns the HTTP).
Integration (ANOMALY-003): imported by pipeline/research/gateways/__init__.py
and transitively by pipeline/research/__init__.py.
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

from pipeline.research.client_302ai import TaoAIClient
from pipeline.research.providers.types import FetchedPage, SearchHit

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────

_PROVIDER_SERP: str = "302ai-serp"
_PROVIDER_CRAWL: str = "302ai-crawl"
_PROVIDER_SYNTH: str = "302ai-synth"

_DEFAULT_SERP_NUM: int = 10
_SNIPPET_MAX_LEN: int = 500


# ── Gateway class ─────────────────────────────────────────────────────────────


class GW302:
    """Multi-service 302.ai gateway.

    Wraps :class:`~pipeline.research.client_302ai.TaoAIClient` and exposes
    three capabilities mapped to the stable DTO types from
    :mod:`pipeline.research.providers`:

    * :meth:`serp`  — SerpApi web-search -> ``list[SearchHit]``
    * :meth:`fetch` — Firecrawl page-scrape -> ``FetchedPage``
    * :meth:`synth` — Chat completion (Sonar/OpenAI) -> ``dict``

    The 302.ai Exa endpoint returns HTTP 500 (confirmed); use the direct
    :class:`~pipeline.research.gateways.exa.ExaGateway` for Exa searches.

    Authentication: ``TAO_AI_API_KEY`` env var (Bearer).
    Key masking: first 8 chars only in all log output (SEC-07 / ADR-0003).
    Retry / BudgetExceeded: handled transparently by the wrapped TaoAIClient.

    Examples
    --------
    >>> gw = GW302.from_env()
    >>> hits = gw.serp("Barbie 2023 box office worldwide")
    >>> page = gw.fetch("https://www.boxofficemojo.com/year/world/2023/")
    >>> result = gw.synth("perplexity/sonar-pro", [{"role": "user", "content": "hi"}])
    """

    def __init__(self, client: TaoAIClient) -> None:
        """Construct from a ready :class:`TaoAIClient` instance.

        Prefer :meth:`from_env` for normal use.  This constructor is exposed
        for injection in unit tests.

        Args:
            client: A configured :class:`TaoAIClient` instance.
        """
        self._client: TaoAIClient = client
        # Derive masked key via repr() so we never access a protected attribute.
        # TaoAIClient.__repr__ returns "TaoAIClient(key=<masked>...)" — we use
        # mask_key on the raw key obtained from from_env(), but when injecting
        # a pre-built client we extract the masked prefix from its repr string.
        _repr = repr(client)
        # repr format: "TaoAIClient(key=XXXXXXXX...)"  — extract up to first ")"
        try:
            self._masked: str = _repr.split("key=")[1].rstrip(")")
        except (IndexError, ValueError):
            self._masked = "(unknown)"

    def __repr__(self) -> str:
        return f"GW302(key={self._masked})"

    @classmethod
    def from_env(cls) -> GW302:
        """Construct from the ``TAO_AI_API_KEY`` environment variable.

        Returns:
            A ready :class:`GW302` gateway.

        Raises:
            KeyError: If ``TAO_AI_API_KEY`` is absent or empty after stripping.
        """
        key = os.environ.get("TAO_AI_API_KEY", "").strip()
        if not key:
            raise KeyError("TAO_AI_API_KEY not set or empty")
        return cls(TaoAIClient(api_key=key))

    # ── serp() ────────────────────────────────────────────────────────────────

    def serp(
        self,
        query: str,
        *,
        num: int = _DEFAULT_SERP_NUM,
    ) -> list[SearchHit]:
        """Search via SerpApi (Google) through 302.ai.

        Maps ``organic[]`` results to :class:`~pipeline.research.providers.SearchHit`
        instances.  The ``answerBox.snippet`` is inserted as the first hit when
        present so callers see the direct answer at index 0.

        Score is approximated as ``1.0 - (position - 1) / num`` so the first
        organic result has score ~1.0 and the last ~0.0.

        Args:
            query: Search query string.
            num: Number of organic results to request (default 10).

        Returns:
            List of :class:`~pipeline.research.providers.SearchHit` objects,
            answerBox first (when present) followed by organic results.

        Raises:
            pipeline.research.client_302ai.BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
        """
        logger.info(
            "GW302.serp key=%s query=%.60s num=%d",
            self._masked,
            query,
            num,
        )
        raw: dict[str, Any] = self._client.serp(query, num=num)
        hits: list[SearchHit] = []

        # answerBox: insert as first hit for factual queries
        answer_box: dict[str, Any] = raw.get("answerBox") or {}
        if answer_box:
            ab_url = str(answer_box.get("link") or "")
            ab_snippet = str(
                answer_box.get("snippet") or answer_box.get("snippetHighlighted") or ""
            )
            ab_title = str(answer_box.get("title") or "")
            if ab_snippet:
                hits.append(
                    SearchHit(
                        title=ab_title,
                        url=ab_url,
                        snippet=ab_snippet,
                        score=1.0,
                        provider=_PROVIDER_SERP,
                        published_date="",
                    )
                )

        organic: list[dict[str, Any]] = raw.get("organic") or []
        for item in organic:
            position: int = int(item.get("position", len(hits) + 1))
            score: float = max(0.0, 1.0 - (position - 1) / max(num, 1))
            snippet = str(item.get("snippet") or "")[:_SNIPPET_MAX_LEN]
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("link") or ""),
                    snippet=snippet,
                    score=score,
                    provider=_PROVIDER_SERP,
                    published_date="",  # Serper web results have no date field
                )
            )

        logger.info(
            "GW302.serp key=%s returned %d hits (answer_box=%s)",
            self._masked,
            len(hits),
            bool(answer_box),
        )
        return hits

    # ── fetch() ───────────────────────────────────────────────────────────────

    def fetch(self, url: str) -> FetchedPage:
        """Scrape a URL via Firecrawl through 302.ai.

        Returns a :class:`~pipeline.research.providers.FetchedPage` with
        ``markdown`` and ``text`` populated from Firecrawl's markdown output.
        The ``content_sha256`` is the SHA-256 of the ``markdown`` field.

        Args:
            url: The URL to scrape.

        Returns:
            :class:`~pipeline.research.providers.FetchedPage` instance.
            ``ok=True`` when the page has non-empty markdown content.

        Raises:
            pipeline.research.client_302ai.BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
        """
        logger.info(
            "GW302.fetch key=%s url=%.80s",
            self._masked,
            url,
        )
        fetched_at = datetime.now(UTC).isoformat()
        raw: dict[str, Any] = self._client.crawl(url)

        final_url = str(raw.get("url") or url)
        markdown = str(raw.get("markdown") or "")
        text = markdown  # Firecrawl markdown is the canonical text representation

        content_sha256 = hashlib.sha256(markdown.encode()).hexdigest() if markdown else ""

        page = FetchedPage(
            url=url,
            final_url=final_url,
            status=200,
            text=text,
            markdown=markdown,
            content_sha256=content_sha256,
            fetched_at=fetched_at,
            provider=_PROVIDER_CRAWL,
            ok=bool(markdown),
        )
        logger.info(
            "GW302.fetch key=%s final_url=%.80s ok=%s markdown_len=%d",
            self._masked,
            final_url,
            page.ok,
            len(markdown),
        )
        return page

    # ── synth() ───────────────────────────────────────────────────────────────

    def synth(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        run_id: str | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        """Chat completion via 302.ai (Sonar, OpenAI, etc.).

        Delegates to :meth:`~pipeline.research.client_302ai.TaoAIClient.chat`.
        ``TaoAIClient`` parses ``choices[0].message.content``, strips JSON
        fences, and returns the parsed dict — no additional transformation here.

        Args:
            model: Model identifier, e.g. ``"perplexity/sonar-pro"``,
                   ``"openai/gpt-4o"``.
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            json_mode: Request JSON-only responses.  For ``perplexity/*``
                       models the ``response_format`` field is omitted
                       (Perplexity rejects it — handled inside TaoAIClient).
            max_tokens: Maximum tokens for the completion (default 2048).
            run_id: Optional run identifier for quota tracking (ADR-0008).
            phase: Optional phase label for quota tracking (ADR-0008).

        Returns:
            Parsed JSON dict from the LLM response content.

        Raises:
            pipeline.research.client_302ai.BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
            json.JSONDecodeError: If parsing fails after all retries.
        """
        logger.info(
            "GW302.synth key=%s model=%s json_mode=%s",
            self._masked,
            model,
            json_mode,
        )
        return self._client.chat(
            model=model,
            messages=messages,
            json_mode=json_mode,
            max_tokens=max_tokens,
            run_id=run_id,
            phase=phase,
        )
