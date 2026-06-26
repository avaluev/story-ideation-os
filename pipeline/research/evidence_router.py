"""pipeline/research/evidence_router.py — Multi-gateway claim-source router.

EvidenceRouter orchestrates SEARCH → FETCH → value_on_page to source a numeric
claim from real pages.  All gateway implementations are injected (dependency
injection), so tests pass fake gateways without any network.

Design principles
-----------------
* **SEARCH route**: walk providers in order (Serper → Exa → … per routes.py),
  dedup by normalised URL, drop non-deep / banned URLs, stop when
  ``config.search_fanout`` providers have been tried OR ``limit`` credible
  deep-link hits are accumulated.
* **FETCH route**: walk providers in order (Jina → 302/firecrawl → WebFetch
  manifest → httpx-GET), stop at first page whose ``.text`` is non-empty.
* **source_claim**: FIND → FETCH → value_on_page; returns a merge-agent
  judgment dict when a value-on-page match is found, else ``None``.
* **BudgetExceeded**: caught per gateway; gateway is marked dead-for-run via
  :func:`~pipeline.research.health.mark_dead`, router continues to next
  provider.
* **Caching**: all source_claim results are persisted via
  :func:`~pipeline.research.research_cache.cached_call` (ISO-week TTL).

Gateway protocol (structural/duck-typed)
-----------------------------------------
Search gateways must implement:
    search(query: str, *, num: int = 10) -> list[SearchHit]

Fetch gateways must implement:
    fetch(url: str) -> FetchedPage

Synth gateways: not used by this module (reserved for callers that pass synth
gateways to future synth() capabilities).

The ``webfetch`` gateway raises :class:`WebFetchDeferred` from ``fetch()`` to
signal that the URL must be resolved by the Claude Code workflow layer; the
router catches this, adds the URL to the deferred manifest, and continues.

ADR-0007: HTTP lives in pipeline/research/ — this module is allowed here.
ADR-0001: cross-run state written via pipeline.state.safe_write (via research_cache).
ADR-0003: API keys never logged directly; gateway reprs mask to first 8 chars.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, httpx, openrouter_client, or pipeline.run.
ANOMALY-003: imported by pipeline.research.__init__ — orphan gate stays green.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

from pipeline.research import http_pool
from pipeline.research.client_302ai import BudgetExceeded as _TaoBudgetExceeded
from pipeline.research.gateways.webfetch import WebFetchDeferred, webfetch_manifest
from pipeline.research.http_pool import BudgetExceeded as _PoolBudgetExceeded
from pipeline.research.providers.types import FetchedPage, SearchHit
from pipeline.research.value_on_page import is_credible, is_deep_link, source_tier, value_on_page

logger = logging.getLogger(__name__)


# ── Named constants ────────────────────────────────────────────────────────────

_DEFAULT_LIMIT: int = 8
_DEFAULT_SEARCH_FANOUT: int = 3
_DEFAULT_FETCH_TIMEOUT: float = 45.0
_URL_NORM_MAX: int = 2048  # Truncate URLs at this length for dedup keys
_HTTP_OK_MIN: int = 200
_HTTP_OK_MAX: int = 300  # exclusive upper bound for 2xx range


# ── Protocols (structural duck-typing) ────────────────────────────────────────


@runtime_checkable
class SearchGateway(Protocol):
    """Structural protocol for search gateways.

    Any object with ``search(query, *, num) -> list[SearchHit]`` satisfies this.
    """

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]: ...


@runtime_checkable
class FetchGateway(Protocol):
    """Structural protocol for fetch gateways.

    Any object with ``fetch(url) -> FetchedPage`` satisfies this.
    The WebFetch gateway raises WebFetchDeferred instead of returning.
    """

    def fetch(self, url: str) -> FetchedPage: ...


@runtime_checkable
class SynthGateway(Protocol):
    """Structural protocol for synthesis / LLM gateways.

    Reserved for future synth() support; not used by current router methods.
    """

    def synth(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]: ...


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouterConfig:
    """Immutable configuration for :class:`EvidenceRouter`.

    Attributes
    ----------
    search_fanout:
        Maximum number of search providers to try before stopping even if
        *limit* credible deep-link hits have not been accumulated yet.
    limit:
        Target number of credible deep-link hits at which to stop searching.
    fetch_timeout:
        Seconds to allow each fetch provider before timeout.
    """

    search_fanout: int = _DEFAULT_SEARCH_FANOUT
    limit: int = _DEFAULT_LIMIT
    fetch_timeout: float = _DEFAULT_FETCH_TIMEOUT


# ── Judgment type (merge-agent output shape) ──────────────────────────────────


@dataclass(frozen=True)
class Judgment:
    """The output of :meth:`EvidenceRouter.source_claim`.

    Matches the merge-agent shape used by the veracity pipeline:
    ``{claim_id, supports, refutes, quote, url, date}``.

    ``supports`` is ``True`` ONLY when a real literal value-on-page match was
    found.  ``refutes`` is ``True`` when a page was fetched but the value was
    absent (refute-by-default).  Both are ``False`` when no page could be
    fetched.

    Attributes
    ----------
    claim_id:  Opaque identifier passed in by the caller.
    supports:  True when value_on_page confirms the claim on the fetched page.
    refutes:   True when the page was fetched but the value was NOT found.
    quote:     The verbatim sentence fragment containing the value (or ``""``).
    url:       The URL of the fetched evidence page.
    date:      ISO-8601 date string from the search hit, or ``""`` if absent.
    """

    claim_id: str
    supports: bool
    refutes: bool
    quote: str
    url: str
    date: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "claim_id": self.claim_id,
            "supports": self.supports,
            "refutes": self.refutes,
            "quote": self.quote,
            "url": self.url,
            "date": self.date,
        }


# ── URL normalisation for dedup ────────────────────────────────────────────────


def _normalise_url(url: str) -> str:
    """Return a canonical lower-case URL string for dedup purposes.

    Strips the fragment, lowercases the scheme and host, and strips a trailing
    slash from the path so ``/foo/`` and ``/foo`` hash to the same key.

    Args:
        url: Raw URL string from a search result.

    Returns:
        Normalised string (may be empty for malformed inputs).
    """
    if not url:
        return ""
    try:
        p = urlparse(url[:_URL_NORM_MAX])
    except ValueError:
        return url.lower()[:_URL_NORM_MAX]
    norm_path = p.path.rstrip("/")
    return f"{p.scheme.lower()}://{p.netloc.lower()}{norm_path}{('?' + p.query) if p.query else ''}"


# ── WebFetch manifest accumulator ─────────────────────────────────────────────


def _webfetch_plan(unresolved: list[str]) -> list[dict[str, Any]]:
    """Build a WebFetch manifest for URLs that no fetch gateway could resolve.

    Args:
        unresolved: List of URL strings that need Claude Code WebFetch handling.

    Returns:
        List of manifest dicts (format defined by
        :func:`~pipeline.research.gateways.webfetch.webfetch_manifest`).
    """
    return webfetch_manifest(unresolved)


# ── EvidenceRouter ─────────────────────────────────────────────────────────────


class EvidenceRouter:
    """Multi-gateway orchestrator: SEARCH → FETCH → value_on_page.

    Instantiate with lists of search, fetch, and (optionally) synth gateways.
    The router walks each list in order, uses health.mark_dead to skip gateways
    that raised BudgetExceeded, and stops as early as possible to minimise cost.

    Dependency injection makes unit-testing hermetic: pass fake gateways instead
    of real ones.  All production callers should construct via
    :meth:`from_defaults` which picks up live gateways from environment variables.

    Args:
        config:          :class:`RouterConfig` (defaults applied when ``None``).
        search_gateways: Ordered list of search providers (duck-typed).
        fetch_gateways:  Ordered list of fetch providers (duck-typed).
        synth_gateways:  Ordered list of synth providers (reserved; unused now).

    Example (production)::

        router = EvidenceRouter.from_defaults()
        hits = router.discover("Barbie 2023 worldwide box office gross")
        page = router.fetch("https://www.boxofficemojo.com/year/world/2023/")
        judgment = router.source_claim({
            "claim_id": "rev-001",
            "value": "$1.4B",
            "claim_text": "Barbie grossed $1.4B worldwide",
        })

    Example (test)::

        router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[FakeSerper(hits=[...])],
            fetch_gateways=[FakeJina(pages={url: page})],
        )
    """

    def __init__(
        self,
        config: RouterConfig | None = None,
        search_gateways: list[Any] | None = None,
        fetch_gateways: list[Any] | None = None,
        synth_gateways: list[Any] | None = None,
    ) -> None:
        self._config: RouterConfig = config or RouterConfig()
        self._search_gateways: list[Any] = search_gateways or []
        self._fetch_gateways: list[Any] = fetch_gateways or []
        self._synth_gateways: list[Any] = synth_gateways or []
        # Tracks dead gateway names for this router instance.
        self._dead: set[str] = set()
        # Deferred URLs for which no fetch gateway succeeded.
        self._deferred_urls: list[str] = []

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_defaults(cls) -> EvidenceRouter:
        """Construct a production router with all available gateways.

        Gateways that cannot be constructed (missing env keys) are silently
        skipped.  The router is still usable with whatever gateways are
        available.

        Returns:
            A configured :class:`EvidenceRouter` ready for production use.
        """
        from pipeline.research.gateways.exa import ExaGateway  # noqa: PLC0415
        from pipeline.research.gateways.gw302 import GW302  # noqa: PLC0415
        from pipeline.research.gateways.jina import JinaGateway  # noqa: PLC0415
        from pipeline.research.gateways.serper import SerperGateway  # noqa: PLC0415
        from pipeline.research.gateways.webfetch import WebFetchGateway  # noqa: PLC0415

        search_gws: list[Any] = []
        fetch_gws: list[Any] = []

        # SEARCH route: Serper → Exa → GW302-serp (fallback)
        for factory, label in [
            (SerperGateway.from_env, "SerperGateway"),
            (ExaGateway.from_env, "ExaGateway"),
        ]:
            try:
                gw = factory()  # type: ignore[call-arg]
                search_gws.append(gw)
            except (KeyError, Exception) as exc:
                logger.debug("EvidenceRouter.from_defaults: skip %s — %s", label, exc)

        # GW302 supports both serp (search) and fetch (firecrawl).
        gw302: Any = None
        try:
            gw302 = GW302.from_env()
            search_gws.append(_GW302SearchAdapter(gw302))
        except (KeyError, Exception) as exc:
            logger.debug("EvidenceRouter.from_defaults: skip GW302 search — %s", exc)

        # FETCH route: Jina → 302/firecrawl → WebFetch (manifest) → httpx-GET
        try:
            fetch_gws.append(JinaGateway.from_env())
        except Exception as exc:
            logger.debug("EvidenceRouter.from_defaults: skip JinaGateway — %s", exc)

        if gw302 is not None:
            fetch_gws.append(_GW302FetchAdapter(gw302))

        # WebFetch plan-only (always available — raises WebFetchDeferred)
        fetch_gws.append(WebFetchGateway())

        # httpx-GET last resort
        fetch_gws.append(_HttpxFetchGateway())

        return cls(
            config=RouterConfig(),
            search_gateways=search_gws,
            fetch_gateways=fetch_gws,
        )

    # ── Gateway name helper ────────────────────────────────────────────────────

    @staticmethod
    def _gw_name(gw: object) -> str:
        """Return a stable string name for a gateway (used for dead-set tracking).

        Falls back to the type name when the gateway has no ``gateway_name``
        attribute.

        Args:
            gw: Any gateway object.

        Returns:
            A non-empty string key.
        """
        name: str = getattr(gw, "gateway_name", "") or type(gw).__name__
        return name

    # ── Dead-gateway tracking (per-instance) ─────────────────────────────────

    def _mark_dead(self, gw: object) -> None:
        """Mark *gw* dead for this router instance and call health.mark_dead.

        Args:
            gw: The gateway that raised BudgetExceeded.
        """
        name = self._gw_name(gw)
        self._dead.add(name)
        try:
            from pipeline.research import health  # noqa: PLC0415

            health.mark_dead(name)
        except Exception as exc:
            logger.debug("_mark_dead: health.mark_dead unavailable — %s", exc)

    def _is_dead(self, gw: object) -> bool:
        """Return True if *gw* has been marked dead this session.

        Args:
            gw: Gateway object.

        Returns:
            True when the gateway name is in the dead set.
        """
        return self._gw_name(gw) in self._dead

    # ── discover() ────────────────────────────────────────────────────────────

    def discover(
        self,
        query: str,
        *,
        claim_type: str = "",
        limit: int | None = None,
    ) -> list[SearchHit]:
        """Fan-out search to accumulate credible deep-link hits.

        Walk :attr:`_search_gateways` in order:
        1. Skip dead gateways.
        2. Call ``gw.search(query, num=limit)`` — catch BudgetExceeded and mark
           gateway dead, then continue.
        3. Dedup by normalised URL (seen set).
        4. Drop hits that fail :func:`~pipeline.research.value_on_page.is_deep_link`
           or :func:`~pipeline.research.value_on_page.is_credible`.
        5. Stop when ``config.search_fanout`` providers have been tried OR
           ``limit`` credible deep-link hits are accumulated.
        6. Sort survivors by ``source_tier(url)`` ascending (tier 1 = best first).

        Args:
            query:      Search query string.
            claim_type: Optional claim-type hint forwarded to
                        :func:`~pipeline.research.value_on_page.is_credible`.
            limit:      Override :attr:`RouterConfig.limit`.

        Returns:
            Ordered list of :class:`~pipeline.research.providers.types.SearchHit`
            (tier-sorted, credible deep-link URLs only).
        """
        effective_limit: int = limit if limit is not None else self._config.limit
        hits: list[SearchHit] = []
        seen: set[str] = set()
        providers_tried: int = 0

        for gw in self._search_gateways:
            if providers_tried >= self._config.search_fanout:
                logger.debug("discover: fanout cap %d reached", self._config.search_fanout)
                break
            if len(hits) >= effective_limit:
                logger.debug(
                    "discover: limit %d reached after %d providers",
                    effective_limit,
                    providers_tried,
                )
                break
            if self._is_dead(gw):
                continue

            gw_name = self._gw_name(gw)
            try:
                raw_hits: list[SearchHit] = gw.search(query, num=effective_limit)
                providers_tried += 1
                logger.debug("discover: %s returned %d raw hits", gw_name, len(raw_hits))
            except _budget_exceeded_types() as exc:
                logger.warning("discover: BudgetExceeded on %s — %s", gw_name, exc)
                self._mark_dead(gw)
                continue
            except Exception as exc:
                logger.warning("discover: %s raised %s — skipping", gw_name, exc)
                providers_tried += 1
                continue

            for hit in raw_hits:
                if len(hits) >= effective_limit:
                    break
                norm = _normalise_url(hit.url)
                if not norm or norm in seen:
                    continue
                if not is_deep_link(hit.url):
                    logger.debug("discover: drop non-deep-link url=%s", hit.url[:80])
                    continue
                if not is_credible(hit.url, claim_type):
                    logger.debug("discover: drop non-credible url=%s", hit.url[:80])
                    continue
                seen.add(norm)
                hits.append(hit)

        # Sort by source_tier ascending (tier 1 = most authoritative first).
        hits.sort(key=lambda h: source_tier(h.url))
        logger.info(
            "discover: query=%.60s providers_tried=%d hits=%d",
            query,
            providers_tried,
            len(hits),
        )
        return hits

    # ── fetch() ───────────────────────────────────────────────────────────────

    def fetch(self, url: str) -> FetchedPage:
        """Fetch *url* via the fetch gateway cascade, returning the first success.

        Cascade order: Jina → 302/firecrawl → WebFetch-manifest-entry → httpx-GET.
        Stops at the first gateway that returns a page with non-empty ``.text``.
        When the WebFetch gateway raises :class:`WebFetchDeferred`, the URL is
        added to :attr:`_deferred_urls` and the next gateway is tried.

        Args:
            url: Absolute URL to fetch.

        Returns:
            :class:`~pipeline.research.providers.types.FetchedPage` — always
            returns an object; ``ok=False`` when no gateway succeeded.
        """
        for gw in self._fetch_gateways:
            if self._is_dead(gw):
                continue
            gw_name = self._gw_name(gw)
            try:
                page: FetchedPage = gw.fetch(url)
                if page.text:
                    logger.debug(
                        "fetch: %s succeeded url=%.80s text_len=%d", gw_name, url, len(page.text)
                    )
                    return page
                logger.debug(
                    "fetch: %s returned empty text for url=%.80s — trying next", gw_name, url
                )
            except WebFetchDeferred:
                logger.debug("fetch: WebFetchDeferred for url=%.80s — queued for manifest", url)
                self._deferred_urls.append(url)
                continue
            except _budget_exceeded_types() as exc:
                logger.warning("fetch: BudgetExceeded on %s — %s", gw_name, exc)
                self._mark_dead(gw)
                continue
            except Exception as exc:
                logger.warning(
                    "fetch: %s raised %s for url=%.80s — trying next", gw_name, exc, url[:80]
                )
                continue

        # All gateways failed — return an empty page
        logger.warning("fetch: all gateways exhausted for url=%.80s", url[:80])
        return FetchedPage(
            url=url,
            final_url=url,
            status=0,
            text="",
            markdown="",
            content_sha256="",
            fetched_at="",
            provider="none",
            ok=False,
        )

    # ── source_claim() ────────────────────────────────────────────────────────

    def source_claim(self, claim: dict[str, Any]) -> Judgment | None:
        """Discover, fetch, and verify a single numeric claim.

        Pipeline:
        1. Build a search query from *claim* (``claim_text`` or ``value`` + ``claim_id``).
        2. Call :meth:`discover` to get credible deep-link hits.
        3. For each hit, :meth:`fetch` the page.
        4. Run :func:`~pipeline.research.value_on_page.value_on_page` to verify
           the claim value on the page text.
        5. Return a :class:`Judgment` on first positive match, or ``None`` when
           no hit can be verified.

        Results are cached via
        :func:`~pipeline.research.research_cache.cached_call` (ISO-week TTL).
        Cache key: ``("source_claim", "router", claim_id + "|" + value)``.

        Args:
            claim: Dict with at minimum:
                - ``claim_id`` (str)  — opaque identifier.
                - ``value`` (str)     — numeric value to verify, e.g. ``"$1.4B"``.
                Optional: ``claim_text`` (str) — full sentence for query building.
                Optional: ``claim_type`` (str) — forwarded to :meth:`discover`.

        Returns:
            :class:`Judgment` on match, or ``None`` when no supporting evidence
            is found.  Returns ``None`` (not a refuting Judgment) when no page
            could be fetched at all.
        """
        claim_id: str = str(claim.get("claim_id", ""))
        value: str = str(claim.get("value", ""))
        claim_text: str = str(claim.get("claim_text", ""))
        claim_type: str = str(claim.get("claim_type", ""))

        if not value:
            logger.debug("source_claim: skip — no value in claim %s", claim_id)
            return None

        query = claim_text if claim_text else f"{value} {claim_id}"

        # Cache wrapper
        cache_key_suffix = f"{claim_id}|{value}|{claim_type}"
        cache_payload = {"q": query, "v": value, "ct": claim_type}

        def _do_source() -> dict[str, Any]:
            return self._source_claim_inner(
                claim_id=claim_id,
                value=value,
                query=query,
                claim_type=claim_type,
            )

        try:
            from pipeline.research import research_cache  # noqa: PLC0415

            cached: dict[str, Any] = research_cache.cached_call(
                ("source_claim", "router", cache_key_suffix),
                cache_payload,
                _do_source,
            )
            if not cached:
                return None
            return _judgment_from_dict(cached)
        except Exception as exc:
            logger.debug("source_claim: cache unavailable (%s) — running live", exc)
            result = _do_source()
            if not result:
                return None
            return _judgment_from_dict(result)

    def _source_claim_inner(
        self,
        *,
        claim_id: str,
        value: str,
        query: str,
        claim_type: str,
    ) -> dict[str, Any]:
        """Execute the discover→fetch→verify pipeline (no caching).

        Returns:
            Dict matching :class:`Judgment` field names, or ``{}`` on failure.
        """
        hits = self.discover(query, claim_type=claim_type)
        if not hits:
            logger.debug("source_claim inner: no hits for claim_id=%s", claim_id)
            return {}

        # M-1: capture hits[0]'s fetched page on the first loop iteration so the
        # refute-by-default branch below can reuse it instead of re-fetching the
        # same URL. The old code fetched hits[0] a SECOND time for every claim
        # whose value was not found on any page — a wasted fetch on the hottest
        # failure path (the one the refuter exercises most).
        first_page: FetchedPage | None = None
        for idx, hit in enumerate(hits):
            page = self.fetch(hit.url)
            if idx == 0:
                first_page = page
            if not page.text:
                continue
            match = value_on_page(value, page.text)
            if match.matched:
                return {
                    "claim_id": claim_id,
                    "supports": True,
                    "refutes": False,
                    "quote": match.quote,
                    "url": hit.url,
                    "date": hit.published_date,
                }
            # Page fetched but value absent → refute-by-default (keep searching)
            logger.debug(
                "source_claim inner: value not on page claim_id=%s url=%.80s",
                claim_id,
                hit.url,
            )

        # No supporting page found — refute-by-default using hits[0]'s page,
        # already fetched in the loop above (M-1: no second fetch). url/date are
        # hits[0]'s, identical to the pre-M-1 behaviour.
        if first_page is not None and first_page.text:
            return {
                "claim_id": claim_id,
                "supports": False,
                "refutes": True,
                "quote": "",
                "url": hits[0].url,
                "date": hits[0].published_date,
            }

        return {}

    # ── webfetch_plan() ───────────────────────────────────────────────────────

    def webfetch_plan(self, unresolved: list[str] | None = None) -> list[dict[str, Any]]:
        """Return a WebFetch manifest for unresolved URLs.

        Uses *unresolved* when provided; otherwise uses the internally
        accumulated :attr:`_deferred_urls` list (populated by :meth:`fetch`
        when a WebFetchGateway raises :class:`WebFetchDeferred`).

        Args:
            unresolved: Optional explicit list of URLs to manifest.  When
                        ``None``, the router's own deferred list is used.

        Returns:
            List of manifest dicts (see
            :func:`~pipeline.research.gateways.webfetch.webfetch_manifest`).
        """
        urls = unresolved if unresolved is not None else self._deferred_urls
        return _webfetch_plan(urls)


# ── Helper: BudgetExceeded catch tuple ────────────────────────────────────────


def _budget_exceeded_types() -> tuple[type[Exception], ...]:
    """Return a tuple of BudgetExceeded exception classes for use in ``except``.

    Both ``http_pool.BudgetExceeded`` and ``client_302ai.BudgetExceeded`` are
    included (both imported at module scope) so the router catches both variants.

    Returns:
        Tuple of exception classes.
    """
    return (_PoolBudgetExceeded, _TaoBudgetExceeded)


# ── Judgment deserialization ───────────────────────────────────────────────────


def _judgment_from_dict(d: dict[str, Any]) -> Judgment | None:
    """Build a :class:`Judgment` from a cached dict, or ``None`` if empty/invalid.

    Args:
        d: Dict produced by :meth:`EvidenceRouter._source_claim_inner`.

    Returns:
        :class:`Judgment` instance, or ``None`` when ``d`` is empty.
    """
    if not d:
        return None
    return Judgment(
        claim_id=str(d.get("claim_id", "")),
        supports=bool(d.get("supports", False)),
        refutes=bool(d.get("refutes", False)),
        quote=str(d.get("quote", "")),
        url=str(d.get("url", "")),
        date=str(d.get("date", "")),
    )


# ── Internal adapter classes for from_defaults() ─────────────────────────────


class _GW302SearchAdapter:
    """Adapts GW302.serp() to the SearchGateway protocol."""

    gateway_name: str = "302_serpapi"

    def __init__(self, gw302: object) -> None:
        self._gw = gw302

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]:
        return self._gw.serp(query, num=num)  # type: ignore[union-attr]


class _GW302FetchAdapter:
    """Adapts GW302.fetch() to the FetchGateway protocol."""

    gateway_name: str = "302_firecrawl"

    def __init__(self, gw302: object) -> None:
        self._gw = gw302

    def fetch(self, url: str) -> FetchedPage:
        return self._gw.fetch(url)  # type: ignore[union-attr]


class _HttpxFetchGateway:
    """Last-resort direct httpx GET fetch (no auth, no retry beyond http_pool)."""

    gateway_name: str = "httpx_get"

    def fetch(self, url: str) -> FetchedPage:
        """Fetch *url* via ``pipeline.research.http_pool.request_text``.

        Args:
            url: URL to fetch.

        Returns:
            :class:`FetchedPage` instance.
        """

        fetched_at = datetime.now(UTC).isoformat()
        try:
            status, final_url, text = http_pool.request_text(
                "GET",
                url,
                headers={},
                provider=self.gateway_name,
            )
            return FetchedPage(
                url=url,
                final_url=final_url,
                status=status,
                text=text,
                markdown=text,
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                fetched_at=fetched_at,
                provider=self.gateway_name,
                ok=(_HTTP_OK_MIN <= status < _HTTP_OK_MAX and bool(text)),
            )
        except Exception as exc:
            logger.warning("_HttpxFetchGateway: failed url=%.80s — %s", url[:80], exc)
            return FetchedPage(
                url=url,
                final_url=url,
                status=0,
                text="",
                markdown="",
                content_sha256="",
                fetched_at=fetched_at,
                provider=self.gateway_name,
                ok=False,
            )


__all__ = [
    "EvidenceRouter",
    "FetchGateway",
    "Judgment",
    "RouterConfig",
    "SearchGateway",
    "SynthGateway",
    "_normalise_url",
    "_webfetch_plan",
]
