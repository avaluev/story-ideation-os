"""pipeline.research.providers — shared types and provider contracts.

Exports frozen dataclasses used by all research provider wrappers so that
callers depend on a stable interface rather than provider-specific shapes.

ADR-0007: HTTP lives in the sibling client modules; this package is pure data.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, httpx, openrouter_client, or pipeline.run.
"""

from pipeline.research.providers.types import FetchedPage, SearchHit

__all__ = ["FetchedPage", "SearchHit"]
