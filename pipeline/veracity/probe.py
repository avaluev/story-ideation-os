"""Deterministic URL probe for the veracity subsystem (deep-link evidence policy).

One request per URL. Classifies a cited source into a probe verdict that
:func:`pipeline.veracity.verdict.decide` consumes:

  * ``BANNED``  — a search-engine host (never acceptable evidence).
  * ``NOT_DEEP`` — a bare domain with no real path.
  * ``PASS``    — a deep-link URL returning 2xx (YouTube validated via oEmbed).
  * ``BOT_BLOCK`` — 401/403 from an allow-listed legitimate source.
  * ``FAIL``    — a deep-link URL returning any other non-2xx.
  * ``ERROR``   — the request raised (DNS, TLS, timeout, connection).
  * ``SKIPPED_OFFLINE`` — offline mode; no network was touched.

Reuses :func:`pipeline.crystallize.portfolio.is_deep_path` so the deep-link rule
has a single definition across the codebase (the audit hardened it once).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from pipeline.crystallize.portfolio import is_deep_path

_REQUEST_TIMEOUT: float = float(os.environ.get("VERACITY_PROBE_TIMEOUT", "12.0"))
_USER_AGENT: str = "AnomalyEngine/5.0 veracity-probe"
_HTTP_2XX_MIN: int = 200
_HTTP_2XX_MAX: int = 300
_BOT_BLOCK_STATUSES: frozenset[int] = frozenset({401, 403})
_MAX_SHA_BYTES: int = 2 * 1024 * 1024  # cap payload read for the content fingerprint

#: Hosts that legitimately return 401/403 to bots but are real primary sources.
#: Superset of ``evidence_gate._ALLOW_LISTED`` plus the FilmIntel allow-list.
ALLOW_LISTED_BOT_BLOCK_HOSTS: frozenset[str] = frozenset(
    {
        "variety.com",
        "hollywoodreporter.com",
        "deadline.com",
        "the-numbers.com",
        "boxofficemojo.com",
        "imdb.com",
        "themoviedb.org",
        "letterboxd.com",
        "kinopoisk.ru",
        "flixpatrol.com",
        "reelgood.com",
        "sec.gov",
        "census.gov",
        "film.ca.gov",
        "gov.br",
        "papers.ssrn.com",
        "nber.org",
        "arxiv.org",
        "wsj.com",
        "ft.com",
        "nytimes.com",
        "economist.com",
        "bloomberg.com",
        "parrotanalytics.com",
        "nielsen.com",
        "deloitte.com",
        "statista.com",
    }
)

_YOUTUBE_HOSTS: frozenset[str] = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
)

#: Search-engine hosts that are never valid evidence. Mirrors
#: ``pipeline.crystallize.portfolio._BANNED_HOSTS`` (kept local to avoid a
#: private cross-module import); used only to label BANNED vs NOT_DEEP.
_SEARCH_ENGINE_HOSTS: frozenset[str] = frozenset(
    {"google.com", "bing.com", "duckduckgo.com", "search.brave.com", "yandex.com", "yahoo.com"}
)


@dataclass(frozen=True)
class ProbeResult:
    """The deterministic outcome of probing one URL."""

    url: str
    final_url: str
    status: int | None
    verdict: str
    host: str
    is_deep: bool
    allow_listed: bool
    content_sha256: str | None
    fetched_at: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bare_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _result(
    url: str,
    *,
    verdict: str,
    status: int | None = None,
    final_url: str = "",
    sha: str | None = None,
    error: str | None = None,
) -> ProbeResult:
    host = _bare_host(url)
    return ProbeResult(
        url=url,
        final_url=final_url or url,
        status=status,
        verdict=verdict,
        host=host,
        is_deep=is_deep_path(url),
        allow_listed=host in ALLOW_LISTED_BOT_BLOCK_HOSTS,
        content_sha256=sha,
        fetched_at=_now_iso(),
        error=error,
    )


def probe_url(
    url: str,
    *,
    client: httpx.Client | None = None,
    offline: bool = False,
) -> ProbeResult:
    """Probe one URL and classify it. Never raises — failures become verdicts."""
    if not url or not url.startswith("http"):
        return _result(url, verdict="NOT_DEEP", error="empty or non-http url")

    bare = _bare_host(url)
    # 1. Search-engine hosts are banned outright (handled by is_deep_path too).
    if not is_deep_path(url) and bare not in _YOUTUBE_HOSTS:
        # is_deep_path returns False for banned hosts and for bare domains alike;
        # distinguish so the verdict is actionable.
        verdict = "BANNED" if bare in _SEARCH_ENGINE_HOSTS else "NOT_DEEP"
        return _result(url, verdict=verdict)

    if offline:
        return _result(url, verdict="SKIPPED_OFFLINE")

    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": _USER_AGENT},
        timeout=_REQUEST_TIMEOUT,
        follow_redirects=True,
    )
    try:
        if bare in _YOUTUBE_HOSTS:
            return _probe_youtube(client, url)
        return _probe_http(client, url)
    finally:
        if owns_client:
            client.close()


def _classify_status(url: str, status: int, final_url: str, sha: str | None) -> ProbeResult:
    bare = _bare_host(url)
    if _HTTP_2XX_MIN <= status < _HTTP_2XX_MAX:
        return _result(url, verdict="PASS", status=status, final_url=final_url, sha=sha)
    if status in _BOT_BLOCK_STATUSES and bare in ALLOW_LISTED_BOT_BLOCK_HOSTS:
        return _result(url, verdict="BOT_BLOCK", status=status, final_url=final_url, sha=sha)
    return _result(url, verdict="FAIL", status=status, final_url=final_url, sha=sha)


def _probe_http(client: httpx.Client, url: str) -> ProbeResult:
    try:
        with client.stream("GET", url) as resp:
            status = resp.status_code
            final_url = str(resp.url)
            hasher = hashlib.sha256()
            read = 0
            for chunk in resp.iter_bytes():
                hasher.update(chunk)
                read += len(chunk)
                if read >= _MAX_SHA_BYTES:
                    break
            sha = hasher.hexdigest() if read else None
    except httpx.HTTPError as exc:
        return _result(url, verdict="ERROR", error=type(exc).__name__)
    return _classify_status(url, status, final_url, sha)


def _probe_youtube(client: httpx.Client, url: str) -> ProbeResult:
    """YouTube /watch URLs return 200 even for removed videos — validate via oEmbed."""
    oembed = f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
    try:
        resp = client.get(oembed)
        status = resp.status_code
    except httpx.HTTPError as exc:
        return _result(url, verdict="ERROR", error=type(exc).__name__)
    if _HTTP_2XX_MIN <= status < _HTTP_2XX_MAX:
        return _result(url, verdict="PASS", status=status, final_url=url)
    return _result(url, verdict="FAIL", status=status, final_url=url)
