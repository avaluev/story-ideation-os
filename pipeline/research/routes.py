"""pipeline/research/routes.py — Capability-to-gateway routing table.

Defines which gateway to try for each high-level capability (SEARCH, FETCH,
SYNTH, TRANSLATE) and in what order.  The ``health`` module marks gateways
dead-for-run on 402/BudgetExceeded; ``next_gateway`` skips dead entries so
callers always get the next live option without re-implementing fallback logic.

Route orders (from task spec):

  SEARCH:    Serper -> Exa -> AIML(sonar-pro) -> AIML(gpt-4o-search-preview)
             -> 302(serpapi) -> 302(sonar) -> OpenRouter(sonar)
  FETCH:     Jina -> 302(firecrawl) -> WebFetch(plan-only) -> httpx-GET(http_pool)
  SYNTH:     AIML(gpt-5-chat-latest) -> AIML(sonar-pro) -> 302 -> OpenRouter
  TRANSLATE: AIML(gpt-5-chat-latest) -> AIML(gpt-4.1) -> 302(gpt-5-chat)

Design notes
------------
- ``AIML_PRIMARY`` (env, default ``"1"``) keeps AIML ahead of OpenRouter in
  SEARCH and SYNTH.  Set to ``""`` or ``"0"`` to swap the order.
- ``WebFetch`` is the last real gateway in FETCH — after it comes
  ``httpx-GET(http_pool)`` which is a raw direct fetch, not the deferred
  WebFetch tool.  WebFetch (plan-only) is never last in FETCH; the httpx-GET
  entry serves that role.
- OpenRouter is always last in SEARCH and SYNTH (never the first choice).
- This module is import-time-safe: it does NOT construct any gateway instance.
  Instances are built lazily via ``pipeline.research.health.build_gateway``.

ADR-0007: HTTP lives in the gateway modules — this module is pure data.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import httpx, anthropic, openrouter_client, pipeline.run.
ANOMALY-003: imported by pipeline.research.__init__ — orphan gate stays green.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

# ── Capability enum ────────────────────────────────────────────────────────────


class Capability(StrEnum):
    """High-level research capability categories.

    Each capability maps to an ordered list of :class:`Route` entries.
    """

    SEARCH = "SEARCH"
    FETCH = "FETCH"
    SYNTH = "SYNTH"
    TRANSLATE = "TRANSLATE"


# ── Cost tier ─────────────────────────────────────────────────────────────────


class CostTier(StrEnum):
    """Relative cost classification for a gateway route.

    Used by the health cache to prefer cheaper options when multiple gateways
    are live and a budget-aware caller wants cost-ordered selection.
    """

    FREE = "free"
    CHEAP = "cheap"
    MEDIUM = "medium"
    EXPENSIVE = "expensive"


# ── Route dataclass ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Route:
    """A single entry in a capability's route table.

    Attributes
    ----------
    capability:
        The high-level capability this route serves.
    gateway_name:
        Identifier string matching the keys in
        :data:`~pipeline.research.health.GATEWAY_REGISTRY`.
        Examples: ``"serper"``, ``"exa"``, ``"aiml_sonar_pro"``,
        ``"302_serpapi"``, ``"webfetch"``, ``"httpx_get"``.
    model:
        Optional model ID forwarded to chat-capable gateways.
        ``""`` for non-chat gateways (Jina, Serper, httpx-GET, etc.).
    cost_tier:
        Relative cost classification; informational, not enforced.
    """

    capability: Capability
    gateway_name: str
    model: str = ""
    cost_tier: CostTier = CostTier.MEDIUM


# ── Route table ────────────────────────────────────────────────────────────────


def aiml_primary() -> bool:
    """Return True when AIML should be ordered before OpenRouter.

    Reads ``AIML_PRIMARY`` env var; default ``"1"`` (AIML first). Parsed
    symmetrically (case-insensitive truthy set) so it agrees with
    ``research_dispatch._aiml_primary`` on every value, including ``"off"`` /
    ``"No"`` (both falsy) — the two used to disagree. Exposed for callers that
    want to inspect the ordering preference; :func:`default_route_table` itself
    builds AIML-first unconditionally.
    """
    return os.environ.get("AIML_PRIMARY", "1").strip().lower() in {"1", "true", "yes", "on"}


def _build_search_routes() -> list[Route]:
    """Construct SEARCH route list.

    SEARCH order:
      Serper -> Exa -> AIML(sonar-pro) -> AIML(gpt-4o-search-preview)
      -> 302(serpapi) -> 302(sonar) -> OpenRouter(sonar)
    """
    return [
        Route(
            capability=Capability.SEARCH,
            gateway_name="serper",
            model="",
            cost_tier=CostTier.CHEAP,
        ),
        Route(
            capability=Capability.SEARCH,
            gateway_name="exa",
            model="",
            cost_tier=CostTier.CHEAP,
        ),
        Route(
            capability=Capability.SEARCH,
            gateway_name="aiml_sonar_pro",
            model="perplexity/sonar-pro",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SEARCH,
            gateway_name="aiml_gpt4o_search",
            model="openai/gpt-4o-search-preview",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SEARCH,
            gateway_name="302_serpapi",
            model="",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SEARCH,
            gateway_name="302_sonar",
            model="perplexity/sonar-pro",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SEARCH,
            gateway_name="openrouter_sonar",
            model="perplexity/sonar-pro",
            cost_tier=CostTier.EXPENSIVE,
        ),
    ]


def _build_fetch_routes() -> list[Route]:
    """Construct FETCH route list.

    FETCH order:
      Jina -> 302(firecrawl) -> WebFetch(plan-only) -> httpx-GET(http_pool)

    WebFetch is always second-to-last; httpx-GET is always last.
    """
    return [
        Route(
            capability=Capability.FETCH,
            gateway_name="jina",
            model="",
            cost_tier=CostTier.FREE,
        ),
        Route(
            capability=Capability.FETCH,
            gateway_name="302_firecrawl",
            model="",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.FETCH,
            gateway_name="webfetch",
            model="",
            cost_tier=CostTier.FREE,
        ),
        Route(
            capability=Capability.FETCH,
            gateway_name="httpx_get",
            model="",
            cost_tier=CostTier.FREE,
        ),
    ]


def _build_synth_routes() -> list[Route]:
    """Construct SYNTH route list.

    SYNTH order (AIML_PRIMARY=1, default):
      AIML(gpt-5-chat-latest) -> AIML(sonar-pro) -> 302 -> OpenRouter
    """
    return [
        Route(
            capability=Capability.SYNTH,
            gateway_name="aiml_gpt5",
            model="openai/gpt-5-chat-latest",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SYNTH,
            gateway_name="aiml_sonar_pro",
            model="perplexity/sonar-pro",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SYNTH,
            gateway_name="302_synth",
            model="perplexity/sonar-pro",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.SYNTH,
            gateway_name="openrouter_synth",
            model="perplexity/sonar-pro",
            cost_tier=CostTier.EXPENSIVE,
        ),
    ]


def _build_translate_routes() -> list[Route]:
    """Construct TRANSLATE route list.

    TRANSLATE order:
      AIML(gpt-5-chat-latest) -> AIML(gpt-4.1) -> 302(gpt-5-chat)
    """
    return [
        Route(
            capability=Capability.TRANSLATE,
            gateway_name="aiml_gpt5",
            model="openai/gpt-5-chat-latest",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.TRANSLATE,
            gateway_name="aiml_gpt41",
            model="openai/gpt-4.1",
            cost_tier=CostTier.MEDIUM,
        ),
        Route(
            capability=Capability.TRANSLATE,
            gateway_name="302_gpt5_chat",
            model="openai/gpt-5-chat-latest",
            cost_tier=CostTier.MEDIUM,
        ),
    ]


def _empty_route_dict() -> dict[Capability, list[Route]]:
    """Return a typed empty dict for use as :class:`RouteTable` default factory."""
    return {}


@dataclass
class RouteTable:
    """Per-capability ordered list of :class:`Route` entries.

    Access via :func:`default_route_table` or construct directly for tests.

    Attributes
    ----------
    routes:
        Mapping from :class:`Capability` to an ordered list of :class:`Route`.
    """

    routes: dict[Capability, list[Route]] = field(default_factory=_empty_route_dict)

    def for_capability(self, capability: Capability) -> list[Route]:
        """Return the ordered route list for *capability*.

        Args:
            capability: The :class:`Capability` to look up.

        Returns:
            Ordered ``list[Route]``; empty list if capability is unknown.
        """
        return list(self.routes.get(capability, []))

    def gateway_names(self, capability: Capability) -> list[str]:
        """Return ordered gateway-name strings for *capability*.

        Convenience wrapper over :meth:`for_capability`.

        Args:
            capability: The capability to query.

        Returns:
            List of gateway name strings in priority order.
        """
        return [r.gateway_name for r in self.for_capability(capability)]


# ── Default singleton ──────────────────────────────────────────────────────────

#: Module-level default route table.  Rebuilt on first call; re-used thereafter.
_DEFAULT_TABLE: Final[RouteTable | None] = None


def default_route_table() -> RouteTable:
    """Return (and cache on first call) the default :class:`RouteTable`.

    The SEARCH and SYNTH routes respect the ``AIML_PRIMARY`` env var —
    both default to AIML-before-OpenRouter when the variable is absent or
    ``"1"``.

    Returns:
        The project-wide default :class:`RouteTable`.
    """
    # Build fresh each call — the table is small and immutable so caching
    # at module scope is not needed; tests that manipulate env vars get a
    # consistent fresh table each call.
    table = RouteTable(
        routes={
            Capability.SEARCH: _build_search_routes(),
            Capability.FETCH: _build_fetch_routes(),
            Capability.SYNTH: _build_synth_routes(),
            Capability.TRANSLATE: _build_translate_routes(),
        }
    )
    return table


__all__ = [
    "Capability",
    "CostTier",
    "Route",
    "RouteTable",
    "default_route_table",
]
