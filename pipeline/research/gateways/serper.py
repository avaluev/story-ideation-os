"""pipeline/research/gateways/serper.py — Serper.dev search gateway.

Thin wrapper around ``POST https://google.serper.dev/search`` that returns
a list of :class:`~pipeline.research.providers.types.SearchHit` DTOs.

CONFIRMED endpoint shape (from runs/research/gw_smoke_snapshot.md):
  POST  https://google.serper.dev/search
  Auth  X-API-KEY: <SERPER_API_KEY>
  Body  {"q": ..., "num": ...}
  organic[].{title, link, snippet, position}
  answerBox.{snippet, snippetHighlighted, title, link}  (present for factual queries)

ADR-0007: HTTP lives in pipeline/research/ — NOT on the ANOMALY-001 ban list.
ADR-0003: SERPER_API_KEY masked to first 8 chars in all log output (SEC-07).
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-003: reachable via pipeline.research.gateways.__init__ → pipeline.research.
"""

from __future__ import annotations

import logging
import os
from typing import Any

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:
    pass

from pipeline.research import http_pool
from pipeline.research.providers.types import SearchHit

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────

_SERPER_SEARCH_URL: str = "https://google.serper.dev/search"
_PROVIDER_SLUG: str = "serper"
_ENV_KEY: str = "SERPER_API_KEY"
_DEFAULT_NUM_RESULTS: int = 10

# Score assigned to the answerBox hit (higher than any organic position score).
_ANSWER_BOX_SCORE: float = 0.0


# Convert 1-based organic position to a descending relevance score in [0, 1].
# Position 1 → 1.0, position 10 → ~0.18, etc.
def _position_to_score(position: int) -> float:
    """Return a relevance score derived from 1-based search position.

    Args:
        position: 1-based organic result rank (1 = most relevant).

    Returns:
        Float in (0, 1] — higher is better.
    """
    return 1.0 / max(position, 1)


# ── Exceptions ────────────────────────────────────────────────────────────────


# Re-export for callers who only import this module.
BudgetExceeded = http_pool.BudgetExceeded


# ── Gateway ───────────────────────────────────────────────────────────────────


class SerperGateway:
    """Thin wrapper for the Serper.dev Google Search API.

    Public surface
    --------------
    from_env()              classmethod — construct from ``SERPER_API_KEY``
    search(query, *, num)   -> list[SearchHit]

    Authentication: ``X-API-KEY`` header; value from ``SERPER_API_KEY`` env var.
    Key masking: first 8 chars in all log output (SEC-07 / ADR-0003).
    HTTP: delegated to :mod:`pipeline.research.http_pool` (semaphore + retries).
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise KeyError(_ENV_KEY)
        self._key: str = api_key
        self._masked: str = http_pool.mask_key(api_key)

    def __repr__(self) -> str:
        return f"SerperGateway(key={self._masked})"

    @classmethod
    def from_env(cls) -> SerperGateway:
        """Construct from the ``SERPER_API_KEY`` environment variable.

        Raises:
            KeyError: if ``SERPER_API_KEY`` is not set or is blank.
        """
        key = os.environ.get(_ENV_KEY, "").strip()
        if not key:
            raise KeyError(_ENV_KEY)
        return cls(api_key=key)

    # ── Public search method ──────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        num: int = _DEFAULT_NUM_RESULTS,
    ) -> list[SearchHit]:
        """Submit a query to Serper.dev and return mapped SearchHit objects.

        The ``answerBox`` (when present) is inserted as the first hit with a
        score of 0.0 so callers can detect it by index or inspect its url.
        Organic results follow, scored by inverse position (position 1 → 1.0).

        Args:
            query: Search query string.
            num:   Maximum number of organic results to request.

        Returns:
            List of :class:`SearchHit` instances.  May be empty if the
            response contains neither ``answerBox`` nor ``organic`` results.

        Raises:
            BudgetExceeded:      If Serper returns HTTP 402.
            httpx.HTTPError:     If all retry attempts are exhausted.
            json.JSONDecodeError: If the response body is not valid JSON.
        """
        logger.info(
            "SerperGateway.search key=%s query=%.80s num=%d",
            self._masked,
            query,
            num,
        )

        _, _, body = http_pool.request_json(
            "POST",
            _SERPER_SEARCH_URL,
            headers=self._build_headers(),
            json_body={"q": query, "num": num},
            provider=_PROVIDER_SLUG,
        )

        return self._map_response(body)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self._key,
            "Content-Type": "application/json",
        }

    def _map_response(self, body: dict[str, Any]) -> list[SearchHit]:
        """Convert a Serper JSON response to a list of SearchHit objects.

        Mapping rules (from confirmed snapshot):
        - answerBox.link → url; answerBox.snippet → snippet; score = 0.0
        - organic[].link → url; .snippet → snippet; .position → 1/position score
        - No ``date`` field on web results (only on news results).

        Args:
            body: Parsed JSON dict from Serper.dev.

        Returns:
            List of SearchHit instances; answerBox first when present.
        """
        hits: list[SearchHit] = []

        # ── answerBox ─────────────────────────────────────────────────────────
        answer_box: dict[str, Any] = body.get("answerBox") or {}
        ab_url: str = answer_box.get("link", "")
        ab_snippet: str = answer_box.get("snippet") or answer_box.get("snippetHighlighted", "")
        ab_title: str = answer_box.get("title", "")
        if ab_url and ab_snippet:
            hits.append(
                SearchHit(
                    title=ab_title,
                    url=ab_url,
                    snippet=ab_snippet,
                    score=_ANSWER_BOX_SCORE,
                    provider=_PROVIDER_SLUG,
                    published_date="",
                )
            )

        # ── organic results ───────────────────────────────────────────────────
        organic: list[dict[str, Any]] = body.get("organic") or []
        for item in organic:
            url: str = item.get("link", "")
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("snippet", ""),
                    score=_position_to_score(int(item.get("position", 999))),
                    provider=_PROVIDER_SLUG,
                    published_date="",
                )
            )

        logger.debug(
            "SerperGateway._map_response hits=%d (answerBox=%s organic=%d)",
            len(hits),
            bool(ab_url and ab_snippet),
            len(organic),
        )
        return hits
