"""Shared frozen dataclasses for research provider results.

All provider wrappers (302.ai, OpenRouter, etc.) return instances of these
types so callers depend on a stable, provider-agnostic interface.

ADR-0007: this module is pure data — no HTTP, no LLM clients.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, httpx, openrouter_client, or pipeline.run.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchHit:
    """A single result returned by a search provider (Exa, SerpApi, etc.).

    Attributes
    ----------
    title:
        Page or article title as returned by the provider.
    url:
        Canonical URL of the result.
    snippet:
        Short excerpt or description surface by the provider.
    score:
        Provider relevance score (0.0-1.0 or raw provider float).
    provider:
        Slug identifying the originating provider, e.g. ``"exa"``,
        ``"serpapi"``, ``"perplexity"``.
    published_date:
        ISO-8601 date string when available; empty string otherwise.
    """

    title: str
    url: str
    snippet: str
    score: float
    provider: str
    published_date: str = field(default="")


@dataclass(frozen=True)
class FetchedPage:
    """The result of fetching and extracting a single URL.

    Attributes
    ----------
    url:
        The URL that was originally requested.
    final_url:
        The URL after any redirects.
    status:
        HTTP status code of the final response.
    text:
        Raw response body text (may be empty if extraction failed).
    markdown:
        Markdown-converted page content (e.g. via Firecrawl / Jina).
    content_sha256:
        Hex-encoded SHA-256 of *text* for provenance tracking (ADR-0001).
    fetched_at:
        ISO-8601 UTC timestamp of when the fetch completed.
    provider:
        Slug identifying the fetch provider, e.g. ``"firecrawl"``,
        ``"jina"``, ``"httpx"``.
    ok:
        ``True`` when the fetch succeeded and usable content is present.
    """

    url: str
    final_url: str
    status: int
    text: str
    markdown: str
    content_sha256: str
    fetched_at: str
    provider: str
    ok: bool
