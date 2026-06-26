"""pipeline/research/gateways/webfetch.py — PLAN-ONLY WebFetch gateway.

This gateway is intentionally network-free. It NEVER calls WebFetch from
Python. Its two entry-points are:

  fetch(url)
      Raises ``WebFetchDeferred`` — a sentinel that tells the router to
      delegate the URL to the Claude Code WebFetch tool.

  webfetch_manifest(urls) -> list[dict]
      Returns a JSON-serialisable manifest that a downstream ``.mjs``
      workflow consumes to fan-out WebFetch calls.

Design rationale
----------------
WebFetch is a Claude Code tool — it must stay in the ``.mjs`` workflow layer,
not the Python pipeline. Using WebFetch from Python would tangle the
orchestration model (Python pipeline calling a Claude Code tool that itself
calls the pipeline). The PLAN-ONLY pattern keeps WebFetch as a fallback /
fan-out primitive invoked by the workflow layer and never directly by Python.

No ``httpx``, no network, no ``http_pool`` calls here.

ADR-0007: HTTP is forbidden in this module — WebFetch is the HTTP path.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import ``httpx``, ``anthropic``, or ``openrouter_client``.
ANOMALY-003: exported by ``pipeline.research.gateways.__init__`` which is
  imported by ``pipeline.research.__init__`` so the orphan gate stays green.
MUST NOT be imported from ``pipeline/scoring.py``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Sentinel exception ────────────────────────────────────────────────────────


class WebFetchDeferred(Exception):
    """Raised by :func:`fetch` to signal that this URL must be handled by
    the Claude Code WebFetch tool, not by Python HTTP.

    Attributes
    ----------
    url:
        The URL that was requested.
    reason:
        Human-readable explanation for the deferral (for log context).
    """

    def __init__(self, url: str, reason: str = "deferred to WebFetch tool") -> None:
        super().__init__(f"WebFetchDeferred: {url!r} — {reason}")
        self.url = url
        self.reason = reason


# ── Public API ────────────────────────────────────────────────────────────────


def from_env() -> WebFetchGateway:
    """Return the singleton :class:`WebFetchGateway` instance.

    This gateway has no API key requirement, so ``from_env()`` never raises
    :class:`KeyError`.  It always succeeds.

    Returns:
        A fresh :class:`WebFetchGateway` instance.
    """
    return WebFetchGateway()


def fetch(url: str) -> None:
    """Attempt to fetch *url* — always raises :class:`WebFetchDeferred`.

    This is intentional: the WebFetch gateway is PLAN-ONLY.  Calling
    :func:`fetch` from Python signals that the URL must be handed off to the
    Claude Code WebFetch tool in the ``.mjs`` workflow layer.

    Args:
        url: The URL to be fetched.

    Raises:
        WebFetchDeferred: Always.  The caller (router) catches this and routes
            the URL to the WebFetch tool manifest instead.
    """
    logger.debug("webfetch.fetch deferred: url=%.120s", url)
    raise WebFetchDeferred(url)


def webfetch_manifest(urls: list[str]) -> list[dict[str, Any]]:
    """Build a JSON-serialisable manifest for a list of URLs.

    The manifest is consumed by the ``.mjs`` workflow to fan-out WebFetch
    calls.  Each entry carries enough metadata for the workflow to fetch,
    cache, and annotate the result.

    Args:
        urls: List of URL strings to include in the manifest.

    Returns:
        List of dicts, one per URL, with the following keys:

        ``url``      — the URL string.
        ``provider`` — always ``"webfetch"`` (identifies the gateway).
        ``deferred`` — always ``True`` (signals plan-only intent).
        ``fetched``  — always ``False`` (the workflow must fill this in).

    Examples:
        >>> manifest = webfetch_manifest(["https://example.com/data"])
        >>> manifest[0]["provider"]
        'webfetch'
        >>> manifest[0]["deferred"]
        True
    """
    manifest: list[dict[str, Any]] = []
    for url in urls:
        manifest.append(
            {
                "url": url,
                "provider": "webfetch",
                "deferred": True,
                "fetched": False,
            }
        )
    logger.debug("webfetch_manifest: %d url(s) queued", len(manifest))
    return manifest


# ── Gateway class (mirrors from_env() contract of other gateways) ────────────


class WebFetchGateway:
    """PLAN-ONLY WebFetch gateway.

    This class exists so the research router can treat WebFetch the same way
    it treats Exa, Jina, or AIML — as a gateway with ``from_env()``,
    ``fetch()``, and ``manifest()`` methods.  All fetch operations raise
    :class:`WebFetchDeferred`; the router catches the sentinel and emits a
    manifest entry instead of crashing.

    No constructor arguments.  No API keys.  No network.
    """

    _PROVIDER = "webfetch"

    def fetch(self, url: str) -> None:
        """Delegate to module-level :func:`fetch`.

        Args:
            url: URL to be deferred.

        Raises:
            WebFetchDeferred: Always.
        """
        fetch(url)

    def manifest(self, urls: list[str]) -> list[dict[str, Any]]:
        """Delegate to module-level :func:`webfetch_manifest`.

        Args:
            urls: URLs to include in the manifest.

        Returns:
            List of manifest dicts.
        """
        return webfetch_manifest(urls)
