"""tests/test_evidence_router_m1.py — M-1: no double-fetch on the refute path.

Before M-1, ``EvidenceRouter._source_claim_inner`` fetched ``hits[0]`` a SECOND
time to build the refute-by-default judgment after the main loop had already
fetched it. These tests pin the fix: ``hits[0]`` is fetched exactly once and the
refute judgment is byte-identical (supports=False, refutes=True, url=hits[0].url).

ADR-0007: hermetic — fake gateways, no live network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pipeline.research.evidence_router import EvidenceRouter, Judgment, RouterConfig
from pipeline.research.providers.types import FetchedPage, SearchHit

_BOM = "https://www.boxofficemojo.com/year/world/2023/"
_THN = "https://www.the-numbers.com/movie/Barbie"


@pytest.fixture(autouse=True)
def _bypass_research_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``source_claim`` to always run the live inner path so fetch
    call-counts are deterministic (mirrors tests/test_router_resilience.py)."""
    from pipeline.research import research_cache  # noqa: PLC0415

    def _passthrough(
        key_parts: tuple[str, str, str],
        payload: object,
        miss_fn: Callable[[], dict[str, Any]],
        *,
        iso_week: str | None = None,
    ) -> dict[str, Any]:
        return miss_fn()

    monkeypatch.setattr(research_cache, "cached_call", _passthrough)


def _hit(url: str, date: str = "2023-12-31") -> SearchHit:
    return SearchHit(
        title="t", url=url, snippet="s", score=1.0, provider="serper", published_date=date
    )


def _page(url: str, text: str) -> FetchedPage:
    return FetchedPage(
        url=url,
        final_url=url,
        status=200,
        text=text,
        markdown=text,
        content_sha256="sha",
        fetched_at="2026-06-05T00:00:00+00:00",
        provider="jina",
        ok=True,
    )


class _CountingSearch:
    gateway_name = "serper"

    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]:
        return self.hits[:num]


class _CountingFetch:
    gateway_name = "jina"

    def __init__(self, pages: dict[str, FetchedPage]) -> None:
        self.pages = pages
        self.call_count = 0

    def fetch(self, url: str) -> FetchedPage:
        self.call_count += 1
        return self.pages.get(url, _page(url, ""))


def _router(hits: list[SearchHit], fetch: _CountingFetch) -> EvidenceRouter:
    return EvidenceRouter(
        config=RouterConfig(search_fanout=1, limit=5),
        search_gateways=[_CountingSearch(hits)],
        fetch_gateways=[fetch],
    )


def test_refute_path_fetches_first_hit_once_single_hit() -> None:
    """One hit, value absent -> refute judgment; hits[0] fetched exactly once."""
    fetch = _CountingFetch({_BOM: _page(_BOM, "this page is about a different film entirely")})
    router = _router([_hit(_BOM)], fetch)
    result = router.source_claim(
        {"claim_id": "c1", "value": "$9.9B", "claim_text": "grossed $9.9B"}
    )
    assert result == Judgment(
        claim_id="c1", supports=False, refutes=True, quote="", url=_BOM, date="2023-12-31"
    )
    assert fetch.call_count == 1, "hits[0] must be fetched once, not twice (M-1)"


def test_refute_path_no_extra_fetch_two_hits() -> None:
    """Two hits, neither matches -> 2 fetches total (one per hit), not 3."""
    pages = {
        _BOM: _page(_BOM, "nothing relevant here"),
        _THN: _page(_THN, "also nothing relevant"),
    }
    fetch = _CountingFetch(pages)
    router = _router([_hit(_BOM), _hit(_THN)], fetch)
    result = router.source_claim(
        {"claim_id": "c2", "value": "$9.9B", "claim_text": "grossed $9.9B"}
    )
    assert result is not None
    assert result.refutes is True
    assert result.url == _BOM, "refute judgment uses hits[0] url"
    assert fetch.call_count == 2, "2 hits -> 2 fetches; the old code made 3 (refetch of hits[0])"


def test_supports_path_still_returns_first_match() -> None:
    """Value present on hits[0] -> supports judgment, fetched once."""
    fetch = _CountingFetch({_BOM: _page(_BOM, "Barbie grossed $1.4B worldwide in 2023.")})
    router = _router([_hit(_BOM)], fetch)
    result = router.source_claim(
        {"claim_id": "c3", "value": "$1.4B", "claim_text": "grossed $1.4B"}
    )
    assert result is not None
    assert result.supports is True
    assert result.url == _BOM
    assert fetch.call_count == 1


def test_empty_first_page_yields_no_judgment_one_fetch() -> None:
    """hits[0] fetches empty text -> no judgment (None); still a single fetch."""
    fetch = _CountingFetch({})  # every fetch returns empty text
    router = _router([_hit(_BOM)], fetch)
    result = router.source_claim(
        {"claim_id": "c4", "value": "$9.9B", "claim_text": "grossed $9.9B"}
    )
    assert result is None
    assert fetch.call_count == 1, "empty hits[0] must not be re-fetched (M-1)"
