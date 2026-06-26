"""pipeline.research — HTTP research-provider clients for Anomaly Engine.

Exposes thin, swappable provider wrappers. Each client implements the
_ChatClient protocol so research_dispatch.py can substitute them without
upstream code changes.

ADR-0007: all external HTTP calls live in this sub-package (or in
pipeline/openrouter_client.py). MUST NOT be imported from scoring.py.
ADR-0005: MUST NOT import from frameworks/.
"""

from pipeline.research.client_302ai import BudgetExceeded, TaoAIClient
from pipeline.research.evidence_router import (
    EvidenceRouter,
    FetchGateway,
    Judgment,
    RouterConfig,
    SearchGateway,
    SynthGateway,
)
from pipeline.research.gateways.aiml import AimlClient
from pipeline.research.gateways.exa import ExaGateway
from pipeline.research.gateways.gw302 import GW302
from pipeline.research.gateways.jina import JinaGateway
from pipeline.research.gateways.openrouter import OpenRouterGateway
from pipeline.research.gateways.webfetch import (
    WebFetchDeferred,
    WebFetchGateway,
    webfetch_manifest,
)
from pipeline.research.health import (
    GatewayHealth,
    is_dead,
    live_routes_for,
    mark_dead,
    next_live_route,
)
from pipeline.research.health import (
    load as load_health,
)
from pipeline.research.health import (
    persist as persist_health,
)
from pipeline.research.health import (
    reset as reset_health,
)
from pipeline.research.http_pool import mask_key, request_json, request_text
from pipeline.research.providers import FetchedPage, SearchHit
from pipeline.research.research_cache import (
    ResearchCacheEntry,
    cached_call,
    load_cached,
    purge_older_than_weeks,
    store,
)
from pipeline.research.routes import (
    Capability,
    CostTier,
    Route,
    RouteTable,
    aiml_primary,
    default_route_table,
)
from pipeline.research.value_on_page import (
    ValueMatch,
    build_provenance,
    is_credible,
    is_deep_link,
    number_variants,
    source_tier,
    value_on_page,
)

__all__ = [
    "GW302",
    "AimlClient",
    "BudgetExceeded",
    "Capability",
    "CostTier",
    "EvidenceRouter",
    "ExaGateway",
    "FetchGateway",
    "FetchedPage",
    "GatewayHealth",
    "JinaGateway",
    "Judgment",
    "OpenRouterGateway",
    "ResearchCacheEntry",
    "Route",
    "RouteTable",
    "RouterConfig",
    "SearchGateway",
    "SearchHit",
    "SynthGateway",
    "TaoAIClient",
    "ValueMatch",
    "WebFetchDeferred",
    "WebFetchGateway",
    "aiml_primary",
    "build_provenance",
    "cached_call",
    "default_route_table",
    "is_credible",
    "is_dead",
    "is_deep_link",
    "live_routes_for",
    "load_cached",
    "load_health",
    "mark_dead",
    "mask_key",
    "next_live_route",
    "number_variants",
    "persist_health",
    "purge_older_than_weeks",
    "request_json",
    "request_text",
    "reset_health",
    "source_tier",
    "store",
    "value_on_page",
    "webfetch_manifest",
]
