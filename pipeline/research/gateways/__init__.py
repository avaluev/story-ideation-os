"""pipeline.research.gateways — thin provider gateway wrappers.

Each gateway exposes ``from_env()`` (raises ``KeyError`` when its key is
missing) and a ``chat()`` or ``fetch()`` method that mirrors the established
client contracts so any gateway can be dropped into the research router.

ADR-0007: HTTP lives here — this sub-package is NOT on the ANOMALY-001 ban list.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-003: imported by ``pipeline.research`` so the orphan gate stays green.
"""

from pipeline.research.gateways.aiml import AimlClient
from pipeline.research.gateways.exa import ExaGateway
from pipeline.research.gateways.gw302 import GW302
from pipeline.research.gateways.jina import JinaGateway
from pipeline.research.gateways.openrouter import OpenRouterGateway
from pipeline.research.gateways.serper import SerperGateway
from pipeline.research.gateways.webfetch import WebFetchDeferred, WebFetchGateway, webfetch_manifest

__all__ = [
    "GW302",
    "AimlClient",
    "ExaGateway",
    "JinaGateway",
    "OpenRouterGateway",
    "SerperGateway",
    "WebFetchDeferred",
    "WebFetchGateway",
    "webfetch_manifest",
]
