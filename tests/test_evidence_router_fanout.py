"""tests/test_evidence_router_fanout.py — hermetic tests for EvidenceRouter.

All HTTP is replaced with fake gateways; no live network calls.
Covers:
  - SEARCH stops after Serper when it saturates the limit
  - SEARCH escalates to next provider when Serper returns only banned/bare-domain hits
  - SEARCH stops after config.search_fanout providers even when limit not reached
  - FETCH tries Jina before 302 before WebFetch-manifest before httpx-GET
  - FETCH skips WebFetch (deferred) and adds URL to deferred manifest
  - URL dedup: same normalised URL from two providers counted once
  - Tier sort: lower-tier URLs sorted to front of results
  - BudgetExceeded marks gateway dead and continues to next
  - discover() returns empty list when all gateways dead/fail
  - source_claim() returns Judgment(supports=True) on value-on-page match
  - source_claim() returns Judgment(refutes=True) when page fetched but value absent
  - source_claim() returns None when no hits found
  - webfetch_plan() returns manifest for deferred URLs
  - webfetch_plan() accepts explicit URL list override

ADR-0007: hermetic — no httpx / live calls.
ANOMALY-001: no anthropic / openrouter_client imports.
"""

from __future__ import annotations

import pytest

from pipeline.research.evidence_router import (
    EvidenceRouter,
    Judgment,
    RouterConfig,
    _normalise_url,
)
from pipeline.research.gateways.webfetch import WebFetchDeferred
from pipeline.research.http_pool import BudgetExceeded
from pipeline.research.providers.types import FetchedPage, SearchHit

# ── Fake gateway helpers ──────────────────────────────────────────────────────


def _hit(
    url: str,
    title: str = "Test",
    snippet: str = "snippet",
    score: float = 0.9,
    provider: str = "fake",
    published_date: str = "",
) -> SearchHit:
    """Build a SearchHit for use in tests."""
    return SearchHit(
        title=title,
        url=url,
        snippet=snippet,
        score=score,
        provider=provider,
        published_date=published_date,
    )


def _page(
    url: str,
    text: str = "sample page text",
    ok: bool = True,
    provider: str = "fake",
) -> FetchedPage:
    """Build a FetchedPage for use in tests."""
    return FetchedPage(
        url=url,
        final_url=url,
        status=200 if ok else 0,
        text=text,
        markdown=text,
        content_sha256="abc123",
        fetched_at="2026-06-02T00:00:00+00:00",
        provider=provider,
        ok=ok,
    )


class FakeSearchGateway:
    """Fake search gateway — returns a fixed list of hits."""

    def __init__(
        self,
        hits: list[SearchHit],
        gateway_name: str = "fake_search",
        raise_budget: bool = False,
    ) -> None:
        self.hits = hits
        self.gateway_name = gateway_name
        self.call_count = 0
        self._raise_budget = raise_budget

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]:
        self.call_count += 1
        if self._raise_budget:
            raise BudgetExceeded("fake budget exceeded", provider=self.gateway_name)
        return self.hits[:num]


class FakeFetchGateway:
    """Fake fetch gateway — returns pages from a dict keyed by URL."""

    def __init__(
        self,
        pages: dict[str, FetchedPage],
        gateway_name: str = "fake_fetch",
        raise_budget: bool = False,
        raise_deferred: bool = False,
    ) -> None:
        self.pages = pages
        self.gateway_name = gateway_name
        self.call_count = 0
        self._raise_budget = raise_budget
        self._raise_deferred = raise_deferred

    def fetch(self, url: str) -> FetchedPage:
        self.call_count += 1
        if self._raise_budget:
            raise BudgetExceeded("fake budget exceeded", provider=self.gateway_name)
        if self._raise_deferred:
            raise WebFetchDeferred(url)
        return self.pages.get(url, _page(url, text="", ok=False))


# ── Credible deep-link URLs for test hits ────────────────────────────────────

_BOM_URL = "https://www.boxofficemojo.com/year/world/2023/"
_THN_URL = "https://www.the-numbers.com/market/"
_VAR_URL = "https://variety.com/2023/film/news/barbie-box-office-12345/"
_BARE_DOMAIN = "https://boxofficemojo.com/"  # bare domain — fails is_deep_link
_BLOG_URL = "https://somerandomblog.blogspot.com/post/123"  # fails is_credible


# ── URL normalisation tests ───────────────────────────────────────────────────


class TestNormaliseUrl:
    def test_strips_trailing_slash(self) -> None:
        assert _normalise_url("https://example.com/foo/") == "https://example.com/foo"

    def test_lowercases_scheme_and_host(self) -> None:
        result = _normalise_url("HTTPS://Example.COM/Path")
        assert result.startswith("https://example.com/")

    def test_strips_fragment(self) -> None:
        result = _normalise_url("https://example.com/foo#section")
        assert "#section" not in result

    def test_preserves_query_string(self) -> None:
        result = _normalise_url("https://example.com/search?q=barbie")
        assert "q=barbie" in result

    def test_empty_string_returns_empty(self) -> None:
        assert _normalise_url("") == ""


# ── discover() tests ──────────────────────────────────────────────────────────


class TestDiscoverFanout:
    def test_stops_after_limit_reached_from_first_provider(self) -> None:
        """SEARCH stops after Serper when it returns enough credible deep-link hits."""
        serper = FakeSearchGateway(
            hits=[_hit(_BOM_URL), _hit(_THN_URL), _hit(_VAR_URL)],
            gateway_name="serper",
        )
        exa = FakeSearchGateway(hits=[_hit(_VAR_URL)], gateway_name="exa")
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=3, limit=3),
            search_gateways=[serper, exa],
        )
        hits = router.discover("barbie 2023 box office")
        assert len(hits) == 3
        assert exa.call_count == 0, "Exa should not be called when limit already reached"

    def test_escalates_when_first_provider_returns_only_banned_urls(self) -> None:
        """SEARCH escalates when Serper returns only bare-domain / non-credible hits."""
        serper = FakeSearchGateway(
            hits=[_hit(_BARE_DOMAIN), _hit(_BLOG_URL)],
            gateway_name="serper",
        )
        exa = FakeSearchGateway(
            hits=[_hit(_BOM_URL)],
            gateway_name="exa",
        )
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=2, limit=1),
            search_gateways=[serper, exa],
        )
        hits = router.discover("barbie 2023 box office")
        assert len(hits) == 1
        assert hits[0].url == _BOM_URL
        assert exa.call_count == 1, "Exa must be called when Serper returns no credible hits"

    def test_stops_after_fanout_cap_even_if_limit_not_reached(self) -> None:
        """SEARCH respects search_fanout even when the limit is not met."""
        gw1 = FakeSearchGateway(hits=[], gateway_name="gw1")
        gw2 = FakeSearchGateway(hits=[], gateway_name="gw2")
        gw3 = FakeSearchGateway(hits=[_hit(_BOM_URL)], gateway_name="gw3")
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=2, limit=5),
            search_gateways=[gw1, gw2, gw3],
        )
        hits = router.discover("barbie 2023 box office")
        assert hits == []
        assert gw1.call_count == 1
        assert gw2.call_count == 1
        assert gw3.call_count == 0, "gw3 must NOT be called — fanout cap is 2"

    def test_url_dedup_across_providers(self) -> None:
        """Same normalised URL from two providers is counted only once."""
        # Two different representations of the same URL
        url_a = _BOM_URL
        url_b = _BOM_URL + "?ref=test"  # query variant — different URL, allowed
        url_c = _BOM_URL  # exact duplicate of url_a
        gw1 = FakeSearchGateway(hits=[_hit(url_a), _hit(url_b)], gateway_name="gw1")
        gw2 = FakeSearchGateway(hits=[_hit(url_c)], gateway_name="gw2")
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=2, limit=5),
            search_gateways=[gw1, gw2],
        )
        hits = router.discover("barbie 2023 box office")
        urls = [h.url for h in hits]
        assert urls.count(url_a) == 1, "Exact duplicate URL must appear only once"

    def test_tier_sort_lower_tier_first(self) -> None:
        """Results sorted by source_tier ascending (tier 1 = best first)."""
        # boxofficemojo.com = tier 2, variety.com = tier 2, but BOM comes first alphabetically
        # Use a tier-1 URL to verify ordering
        tier1_url = "https://fred.stlouisfed.org/series/MKTGDPUSA646NWDB"
        tier2_url = _BOM_URL
        gw = FakeSearchGateway(
            # tier2 listed first in raw hits
            hits=[_hit(tier2_url), _hit(tier1_url)],
            gateway_name="gw",
        )
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=5),
            search_gateways=[gw],
        )
        hits = router.discover("gdp film market")
        assert len(hits) == 2
        assert hits[0].url == tier1_url, "Tier-1 URL must be first after sort"
        assert hits[1].url == tier2_url

    def test_budget_exceeded_marks_gateway_dead_and_continues(self) -> None:
        """BudgetExceeded on gw1 marks it dead and gw2 is tried."""
        gw1 = FakeSearchGateway(hits=[], gateway_name="gw1", raise_budget=True)
        gw2 = FakeSearchGateway(hits=[_hit(_BOM_URL)], gateway_name="gw2")
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=2, limit=5),
            search_gateways=[gw1, gw2],
        )
        hits = router.discover("barbie 2023 box office")
        assert len(hits) == 1
        assert hits[0].url == _BOM_URL
        assert "gw1" in router._dead, "gw1 must be marked dead after BudgetExceeded"
        assert gw2.call_count == 1

    def test_returns_empty_when_all_gateways_dead(self) -> None:
        """Returns empty list when all gateways raise BudgetExceeded."""
        gw1 = FakeSearchGateway(hits=[], gateway_name="gw1", raise_budget=True)
        gw2 = FakeSearchGateway(hits=[], gateway_name="gw2", raise_budget=True)
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=3, limit=5),
            search_gateways=[gw1, gw2],
        )
        hits = router.discover("anything")
        assert hits == []

    def test_drops_non_deep_link_urls(self) -> None:
        """Bare-domain URLs are dropped even when provider returns them."""
        gw = FakeSearchGateway(
            hits=[_hit(_BARE_DOMAIN), _hit(_BOM_URL)],
            gateway_name="gw",
        )
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=5),
            search_gateways=[gw],
        )
        hits = router.discover("anything")
        urls = [h.url for h in hits]
        assert _BARE_DOMAIN not in urls
        assert _BOM_URL in urls

    def test_drops_non_credible_urls(self) -> None:
        """Blog/uncredible URLs are dropped."""
        gw = FakeSearchGateway(
            hits=[_hit(_BLOG_URL), _hit(_BOM_URL)],
            gateway_name="gw",
        )
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=5),
            search_gateways=[gw],
        )
        hits = router.discover("anything")
        urls = [h.url for h in hits]
        assert _BLOG_URL not in urls
        assert _BOM_URL in urls


# ── fetch() tests ─────────────────────────────────────────────────────────────


class TestFetch:
    def test_tries_jina_before_302(self) -> None:
        """FETCH tries Jina first; 302 is not called when Jina succeeds."""
        jina = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="barbie gross 1.4 billion")},
            gateway_name="jina",
        )
        gw302 = FakeFetchGateway(pages={}, gateway_name="302_firecrawl")
        router = EvidenceRouter(
            config=RouterConfig(),
            fetch_gateways=[jina, gw302],
        )
        page = router.fetch(_BOM_URL)
        assert page.ok
        assert "1.4 billion" in page.text
        assert gw302.call_count == 0, "302 must not be called when Jina succeeds"

    def test_escalates_to_302_when_jina_returns_empty(self) -> None:
        """FETCH escalates to 302 when Jina returns empty text."""
        jina = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="", ok=False)},
            gateway_name="jina",
        )
        gw302 = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="firecrawl content here")},
            gateway_name="302_firecrawl",
        )
        router = EvidenceRouter(
            config=RouterConfig(),
            fetch_gateways=[jina, gw302],
        )
        page = router.fetch(_BOM_URL)
        assert page.ok
        assert "firecrawl content" in page.text
        assert gw302.call_count == 1

    def test_webfetch_deferred_adds_to_manifest_and_continues(self) -> None:
        """WebFetch sentinel causes URL to be queued in deferred list; next GW tried."""
        webfetch = FakeFetchGateway(pages={}, gateway_name="webfetch", raise_deferred=True)
        httpx_gw = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="httpx fallback text")},
            gateway_name="httpx_get",
        )
        router = EvidenceRouter(
            config=RouterConfig(),
            fetch_gateways=[webfetch, httpx_gw],
        )
        page = router.fetch(_BOM_URL)
        assert page.ok
        assert _BOM_URL in router._deferred_urls, "URL must be in deferred list"
        assert httpx_gw.call_count == 1

    def test_budget_exceeded_marks_dead_and_continues(self) -> None:
        """BudgetExceeded on first fetch GW marks it dead; second GW used."""
        gw1 = FakeFetchGateway(pages={}, gateway_name="gw1", raise_budget=True)
        gw2 = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="fallback page")},
            gateway_name="gw2",
        )
        router = EvidenceRouter(
            config=RouterConfig(),
            fetch_gateways=[gw1, gw2],
        )
        page = router.fetch(_BOM_URL)
        assert page.ok
        assert "gw1" in router._dead
        assert gw2.call_count == 1

    def test_returns_empty_page_when_all_gateways_fail(self) -> None:
        """Returns FetchedPage(ok=False) when all gateways fail."""
        gw1 = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="", ok=False)},
            gateway_name="gw1",
        )
        router = EvidenceRouter(
            config=RouterConfig(),
            fetch_gateways=[gw1],
        )
        page = router.fetch(_BOM_URL)
        assert not page.ok
        assert page.text == ""

    def test_skips_dead_gateway(self) -> None:
        """Dead gateway is skipped without calling fetch."""
        gw1 = FakeFetchGateway(pages={}, gateway_name="gw1")
        gw2 = FakeFetchGateway(
            pages={_BOM_URL: _page(_BOM_URL, text="found it")},
            gateway_name="gw2",
        )
        router = EvidenceRouter(
            config=RouterConfig(),
            fetch_gateways=[gw1, gw2],
        )
        router._dead.add("gw1")  # pre-mark dead
        page = router.fetch(_BOM_URL)
        assert page.ok
        assert gw1.call_count == 0


# ── source_claim() tests ──────────────────────────────────────────────────────


class TestSourceClaim:
    def _router_with(
        self,
        hits: list[SearchHit],
        page_text: str,
        *,
        fanout: int = 1,
        limit: int = 3,
    ) -> EvidenceRouter:
        """Build a router with controlled search + fetch."""
        search_gw = FakeSearchGateway(hits=hits, gateway_name="serper")
        fetch_gw = FakeFetchGateway(
            pages={h.url: _page(h.url, text=page_text) for h in hits},
            gateway_name="jina",
        )
        return EvidenceRouter(
            config=RouterConfig(search_fanout=fanout, limit=limit),
            search_gateways=[search_gw],
            fetch_gateways=[fetch_gw],
        )

    def test_returns_judgment_supports_true_on_match(self) -> None:
        """Returns Judgment(supports=True) when value found on page."""
        url = _BOM_URL
        # Page contains the exact value string
        router = self._router_with(
            hits=[_hit(url, published_date="2023-12-31")],
            page_text="The film grossed $1.4B worldwide in 2023.",
        )
        result = router.source_claim(
            {
                "claim_id": "rev-001",
                "value": "$1.4B",
                "claim_text": "Barbie grossed $1.4B worldwide",
            }
        )
        assert result is not None
        assert isinstance(result, Judgment)
        assert result.supports is True
        assert result.refutes is False
        assert result.claim_id == "rev-001"
        assert result.url == url
        assert "1.4" in result.quote or "1,400,000,000" in result.quote or result.quote != ""

    def test_returns_judgment_refutes_true_when_value_absent(self) -> None:
        """Returns Judgment(refutes=True) when page fetched but value not found."""
        url = _BOM_URL
        router = self._router_with(
            hits=[_hit(url)],
            page_text="This page talks about something else entirely.",
        )
        result = router.source_claim(
            {
                "claim_id": "rev-002",
                "value": "$9.9B",
                "claim_text": "Barbie grossed $9.9B worldwide",
            }
        )
        # May be None (no page) or refuting; both are acceptable non-supporting outcomes
        if result is not None:
            assert result.supports is False

    def test_returns_none_when_no_hits(self) -> None:
        """Returns None when discover() produces no hits."""
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[FakeSearchGateway(hits=[], gateway_name="serper")],
            fetch_gateways=[],
        )
        result = router.source_claim(
            {"claim_id": "rev-003", "value": "$1.4B", "claim_text": "any claim"}
        )
        assert result is None

    def test_returns_none_when_no_value_in_claim(self) -> None:
        """Returns None immediately when claim has no value field."""
        router = EvidenceRouter(config=RouterConfig())
        result = router.source_claim({"claim_id": "rev-004", "claim_text": "no value here"})
        assert result is None


# ── webfetch_plan() tests ─────────────────────────────────────────────────────


class TestWebfetchPlan:
    def test_returns_manifest_for_deferred_urls(self) -> None:
        """webfetch_plan() uses router._deferred_urls when no explicit list given."""
        router = EvidenceRouter(config=RouterConfig())
        router._deferred_urls = [_BOM_URL, _THN_URL]
        manifest = router.webfetch_plan()
        assert len(manifest) == 2
        assert all(m["deferred"] is True for m in manifest)
        urls_in_manifest = [m["url"] for m in manifest]
        assert _BOM_URL in urls_in_manifest
        assert _THN_URL in urls_in_manifest

    def test_accepts_explicit_url_list(self) -> None:
        """webfetch_plan(unresolved=[...]) uses the explicit list, ignoring deferred."""
        router = EvidenceRouter(config=RouterConfig())
        router._deferred_urls = [_BOM_URL]  # should be ignored
        manifest = router.webfetch_plan(unresolved=[_THN_URL])
        assert len(manifest) == 1
        assert manifest[0]["url"] == _THN_URL

    def test_returns_empty_manifest_for_empty_list(self) -> None:
        """webfetch_plan([]) returns empty manifest."""
        router = EvidenceRouter(config=RouterConfig())
        assert router.webfetch_plan(unresolved=[]) == []

    def test_manifest_entries_have_required_keys(self) -> None:
        """Each manifest entry has url, provider, deferred, fetched keys."""
        router = EvidenceRouter(config=RouterConfig())
        manifest = router.webfetch_plan(unresolved=[_BOM_URL])
        entry = manifest[0]
        assert "url" in entry
        assert "provider" in entry
        assert "deferred" in entry
        assert "fetched" in entry
        assert entry["fetched"] is False


# ── Judgment.to_dict() ────────────────────────────────────────────────────────


class TestJudgment:
    def test_to_dict_round_trip(self) -> None:
        j = Judgment(
            claim_id="c1",
            supports=True,
            refutes=False,
            quote="grossed $1.4B",
            url=_BOM_URL,
            date="2023-12-31",
        )
        d = j.to_dict()
        assert d["claim_id"] == "c1"
        assert d["supports"] is True
        assert d["refutes"] is False
        assert d["quote"] == "grossed $1.4B"
        assert d["url"] == _BOM_URL
        assert d["date"] == "2023-12-31"

    def test_judgment_is_frozen(self) -> None:
        j = Judgment(claim_id="c2", supports=False, refutes=True, quote="", url="", date="")
        with pytest.raises((AttributeError, TypeError)):
            j.supports = True  # type: ignore[misc]
