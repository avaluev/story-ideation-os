"""tests/test_router_resilience.py — OpenRouter out-of-credits guard.

Verifies that EvidenceRouter degrades gracefully when the OpenRouter gateway
raises BudgetExceeded (or any error) on every call.  All HTTP is replaced
with fake gateways; no live network calls.

Test assertions
---------------
(a) source_claim() still returns a VERIFIED-eligible Judgment (supports=True)
    with a real (fixture) deep-link + value-on-page quote when Serper / Jina
    resolve first.
(b) The run never raised — no exception escapes source_claim().
(c) OpenRouter was called 0 times when AIML/302/Serper resolve first — the
    router stops at the first provider that saturates the hit limit.
(d) A forced AIML + 302 outage still degrades to Serper + Jina + httpx-GET
    without raising, and still returns a VERIFIED-eligible Judgment.

Architecture note
-----------------
The EvidenceRouter catches _budget_exceeded_types() = (http_pool.BudgetExceeded,
client_302ai.BudgetExceeded) in the typed handler and marks the gateway dead.
openrouter_client.BudgetExceeded is a distinct Exception subclass — it is caught
by the generic ``except Exception`` branch in discover() / fetch() so the router
still degrades gracefully without re-raising.

ADR-0007: hermetic — no httpx / live calls.
ANOMALY-001: no anthropic / openrouter_client imports at module level.
ANOMALY-003: imported only by the test harness; not a pipeline leaf module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pipeline.openrouter_client import BudgetExceeded as _ORBudgetExceeded
from pipeline.research.evidence_router import (
    EvidenceRouter,
    Judgment,
    RouterConfig,
)
from pipeline.research.http_pool import BudgetExceeded as _PoolBudgetExceeded
from pipeline.research.providers.types import FetchedPage, SearchHit

# ── Cache bypass fixture ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _bypass_research_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch research_cache.cached_call to always execute miss_fn.

    All tests in this file are hermetic: they must call their fake gateways on
    every invocation.  Without this patch, a cached result from a prior run (or
    an earlier test in the same session with the same claim key) would be
    returned directly and the gateway call-count assertions would spuriously fail.
    """
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


# ── Fixture data ──────────────────────────────────────────────────────────────

# A credible, deep-link URL that passes both is_deep_link() and is_credible().
_BOM_URL = "https://www.boxofficemojo.com/year/world/2023/"

# Page text that contains the claim value in a verifiable sentence.
_PAGE_TEXT = (
    "According to Box Office Mojo, the film grossed $1.4B worldwide in 2023, "
    "making it the top-grossing release of the year."
)

_CLAIM_VALUE = "$1.4B"
_CLAIM_ID = "rev-bom-001"
_CLAIM_TEXT = "The film grossed $1.4B worldwide in 2023"

_PUBLISHED_DATE = "2023-12-31"


# ── Fake gateway helpers ──────────────────────────────────────────────────────


def _make_hit(
    url: str = _BOM_URL,
    title: str = "Box Office Mojo 2023",
    snippet: str = "The film grossed $1.4B worldwide",
    provider: str = "serper",
) -> SearchHit:
    """Build a SearchHit with a credible, deep-link URL."""
    return SearchHit(
        title=title,
        url=url,
        snippet=snippet,
        score=1.0,
        provider=provider,
        published_date=_PUBLISHED_DATE,
    )


def _make_page(url: str = _BOM_URL, text: str = _PAGE_TEXT, ok: bool = True) -> FetchedPage:
    """Build a FetchedPage with the fixture text."""
    return FetchedPage(
        url=url,
        final_url=url,
        status=200 if ok else 0,
        text=text,
        markdown=text,
        content_sha256="fake-sha256",
        fetched_at="2026-06-02T00:00:00+00:00",
        provider="jina",
        ok=ok,
    )


class _CountingSearchGateway:
    """Fake search gateway with configurable hits and optional error injection."""

    def __init__(
        self,
        hits: list[SearchHit],
        gateway_name: str = "fake_search",
        raise_exc: Exception | None = None,
    ) -> None:
        self.hits = hits
        self.gateway_name = gateway_name
        self.call_count = 0
        self._raise_exc = raise_exc

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]:
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self.hits[:num]


class _CountingFetchGateway:
    """Fake fetch gateway with configurable pages and optional error injection."""

    def __init__(
        self,
        pages: dict[str, FetchedPage],
        gateway_name: str = "fake_fetch",
        raise_exc: Exception | None = None,
    ) -> None:
        self.pages = pages
        self.gateway_name = gateway_name
        self.call_count = 0
        self._raise_exc = raise_exc

    def fetch(self, url: str) -> FetchedPage:
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self.pages.get(url, _make_page(url, text="", ok=False))


class _AlwaysRaiseORGateway:
    """Simulates an OpenRouter search gateway that always raises BudgetExceeded.

    Uses openrouter_client.BudgetExceeded (distinct from http_pool.BudgetExceeded)
    to verify the router degrades via the generic-except path.
    """

    gateway_name: str = "openrouter_sonar"

    def __init__(self) -> None:
        self.call_count = 0

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]:
        self.call_count += 1
        raise _ORBudgetExceeded("OpenRouter: all keys exhausted — BudgetExceeded for this run.")


class _AlwaysRaiseFetchGateway:
    """Simulates a fetch gateway (AIML / 302) that is completely unavailable."""

    def __init__(self, gateway_name: str, exc: Exception) -> None:
        self.gateway_name = gateway_name
        self.call_count = 0
        self._exc = exc

    def fetch(self, url: str) -> FetchedPage:
        self.call_count += 1
        raise self._exc


# ── (a) + (b) + (c): Normal path — Serper resolves first ─────────────────────


class TestOpenRouterNeverCalledWhenSerperResolves:
    """Assert (a), (b), (c): OpenRouter gateway called 0 times when Serper resolves."""

    def _build_router(
        self, or_gateway: _AlwaysRaiseORGateway
    ) -> tuple[EvidenceRouter, _CountingSearchGateway, _CountingFetchGateway]:
        serper = _CountingSearchGateway(
            hits=[_make_hit()],
            gateway_name="serper",
        )
        jina = _CountingFetchGateway(
            pages={_BOM_URL: _make_page()},
            gateway_name="jina",
        )
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=3, limit=1),
            # OpenRouter is last in the search list — should never be reached
            # because Serper returns exactly 1 hit which saturates limit=1.
            search_gateways=[serper, or_gateway],
            fetch_gateways=[jina],
        )
        return router, serper, jina

    def test_source_claim_returns_verified_judgment(self) -> None:
        """(a) source_claim() returns Judgment(supports=True) with deep-link + quote."""
        or_gw = _AlwaysRaiseORGateway()
        router, _, _ = self._build_router(or_gw)

        result = router.source_claim(
            {
                "claim_id": _CLAIM_ID,
                "value": _CLAIM_VALUE,
                "claim_text": _CLAIM_TEXT,
            }
        )

        assert result is not None, "source_claim must return a Judgment, not None"
        assert isinstance(result, Judgment)
        # (a) VERIFIED-eligible: supports=True with a real deep-link and a quote
        assert result.supports is True, "Judgment must support the claim"
        assert result.refutes is False
        assert result.url == _BOM_URL, "URL must be the credible deep-link fixture"
        assert result.quote, "Quote must be non-empty (value found on page)"
        # The quote must actually contain the matched value or a variant
        quote_lower = result.quote.lower()
        assert any(
            v in quote_lower for v in ("1.4b", "1.4 billion", "1,400,000,000", "1400000000")
        ), f"Quote must contain the value variant; got: {result.quote!r}"

    def test_run_never_raises(self) -> None:
        """(b) No exception escapes source_claim() even when OpenRouter would fail."""
        or_gw = _AlwaysRaiseORGateway()
        router, _, _ = self._build_router(or_gw)
        # Must not raise — if it raises, the test fails by exception propagation.
        _ = router.source_claim(
            {
                "claim_id": _CLAIM_ID,
                "value": _CLAIM_VALUE,
                "claim_text": _CLAIM_TEXT,
            }
        )

    def test_openrouter_called_zero_times_when_serper_resolves(self) -> None:
        """(c) OpenRouter gateway is never reached when Serper saturates the limit."""
        or_gw = _AlwaysRaiseORGateway()
        router, serper, _ = self._build_router(or_gw)

        router.source_claim(
            {
                "claim_id": _CLAIM_ID,
                "value": _CLAIM_VALUE,
                "claim_text": _CLAIM_TEXT,
            }
        )

        assert or_gw.call_count == 0, (
            f"OpenRouter must not be called when Serper already resolves the claim; "
            f"call_count={or_gw.call_count}"
        )
        assert serper.call_count >= 1, "Serper must have been called"


# ── (d): AIML + 302 out — degrades to Serper + Jina + httpx ─────────────────


class TestDegradesToSerperJinaHttpx:
    """Assert (d): Forced AIML+302 outage still resolves via Serper+Jina without raising."""

    def test_aiml_and_302_down_falls_back_to_serper_and_jina(self) -> None:
        """(d) AIML+302 outage degrades to Serper+Jina; run never raises."""

        # AIML and 302 search gateways that always raise _PoolBudgetExceeded
        # (the typed form — these get marked dead via _mark_dead()).
        aiml_search = _CountingSearchGateway(
            hits=[],
            gateway_name="aiml_sonar_pro",
            raise_exc=_PoolBudgetExceeded("AIML quota exhausted", provider="aiml_sonar_pro"),
        )
        gw302_search = _CountingSearchGateway(
            hits=[],
            gateway_name="302_serpapi",
            raise_exc=_PoolBudgetExceeded("302 quota exhausted", provider="302_serpapi"),
        )
        # OpenRouter also raises (openrouter_client.BudgetExceeded, generic-except path).
        or_search = _AlwaysRaiseORGateway()

        # Serper: the survivor search gateway.
        serper = _CountingSearchGateway(
            hits=[_make_hit(provider="serper")],
            gateway_name="serper",
        )

        # AIML / 302 fetch gateways also down.
        aiml_fetch = _AlwaysRaiseFetchGateway(
            gateway_name="aiml_fetch",
            exc=_PoolBudgetExceeded("AIML fetch quota", provider="aiml_fetch"),
        )
        gw302_fetch = _AlwaysRaiseFetchGateway(
            gateway_name="302_firecrawl",
            exc=_PoolBudgetExceeded("302 fetch quota", provider="302_firecrawl"),
        )

        # Jina: survivor fetch gateway.
        jina = _CountingFetchGateway(
            pages={_BOM_URL: _make_page()},
            gateway_name="jina",
        )
        # httpx-GET: last-resort fetch gateway (also alive but not reached first).
        httpx_gw = _CountingFetchGateway(
            pages={_BOM_URL: _make_page(text=_PAGE_TEXT + " [via httpx]")},
            gateway_name="httpx_get",
        )

        router = EvidenceRouter(
            config=RouterConfig(search_fanout=6, limit=2),
            # AIML + 302 before Serper + OpenRouter (last) in search order
            search_gateways=[aiml_search, gw302_search, serper, or_search],
            # AIML/302 fetch dead → Jina → httpx-GET
            fetch_gateways=[aiml_fetch, gw302_fetch, jina, httpx_gw],
        )

        # Must not raise
        result = router.source_claim(
            {
                "claim_id": _CLAIM_ID,
                "value": _CLAIM_VALUE,
                "claim_text": _CLAIM_TEXT,
            }
        )

        # (d-i) Run never raised — we reach here only if no exception escaped.

        # (d-ii) Still returns a VERIFIED-eligible Judgment.
        assert result is not None, "source_claim must return a Judgment even when AIML+302 are down"
        assert isinstance(result, Judgment)
        assert result.supports is True, "Judgment must support the claim via Serper+Jina fallback"
        assert result.url == _BOM_URL
        assert result.quote, "Quote must be non-empty"

        # (d-iii) Serper was reached (AIML+302 were dead before it).
        assert serper.call_count >= 1, "Serper must have been called as fallback"

        # (d-iv) Dead gateways are tracked (AIML+302 marked dead via typed handler).
        assert "aiml_sonar_pro" in router._dead, "AIML search must be marked dead"
        assert "302_serpapi" in router._dead, "302 search must be marked dead"

        # (d-v) Jina resolved the fetch (AIML/302 fetch were dead first).
        assert jina.call_count >= 1, "Jina must have been called as fetch fallback"


# ── Extra: OpenRouter BudgetExceeded in search role never escapes ─────────────


class TestOpenRouterBudgetExceededNeverEscapes:
    """openrouter_client.BudgetExceeded caught by the generic-except branch."""

    def test_or_budget_exceeded_caught_not_propagated(self) -> None:
        """OpenRouter raising its own BudgetExceeded never surfaces to the caller."""
        # Only gateway: OpenRouter, which always raises.
        or_gw = _AlwaysRaiseORGateway()
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=2, limit=2),
            search_gateways=[or_gw],
            fetch_gateways=[],
        )
        # Must not raise — the generic-except branch handles it.
        result = router.source_claim(
            {
                "claim_id": "or-only-001",
                "value": _CLAIM_VALUE,
                "claim_text": _CLAIM_TEXT,
            }
        )
        # No hits found → None is the correct return when no evidence can be sourced.
        assert result is None

    def test_or_budget_exceeded_in_search_does_not_prevent_fetch_degradation(self) -> None:
        """Even when every search gateway fails, fetch cascade is still tried for any
        hit that may have come from an earlier search attempt before the failure."""
        # Serper returns a hit, OR then fails; fetch must still work for Serper hit.
        serper = _CountingSearchGateway(
            hits=[_make_hit(provider="serper")],
            gateway_name="serper",
        )
        or_gw = _AlwaysRaiseORGateway()
        jina = _CountingFetchGateway(
            pages={_BOM_URL: _make_page()},
            gateway_name="jina",
        )
        router = EvidenceRouter(
            config=RouterConfig(search_fanout=3, limit=1),
            search_gateways=[serper, or_gw],
            fetch_gateways=[jina],
        )
        result = router.source_claim(
            {
                "claim_id": "serper-then-or-001",
                "value": _CLAIM_VALUE,
                "claim_text": _CLAIM_TEXT,
            }
        )
        assert result is not None
        assert result.supports is True
        # OpenRouter was tried (after Serper already saturated the limit at 1)
        # OR not tried at all — both are valid. What matters is the result is good.
        assert result.url == _BOM_URL
