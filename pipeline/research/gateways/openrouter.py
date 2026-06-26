"""pipeline/research/gateways/openrouter.py — OpenRouter gateway wrapper.

Thin gateway that wraps ``pipeline.openrouter_client.OpenRouterClient.chat``
so the research router can treat OpenRouter as just another gateway.

This gateway sits LAST in every route because it is a demoted synth/search
gateway — prefer 302.ai (TaoAIClient) and AIML gateways first.

ADR-0007: OpenRouter HTTP calls originate from ``pipeline.openrouter_client``
  (the codebase's established HTTP path for OpenRouter).  This module does NOT
  re-implement HTTP — it delegates to ``OpenRouterClient.chat`` only.
ADR-0005: MUST NOT import from frameworks/.
ADR-0003: API key masked to first 8 chars in all log output (SEC-07).
ANOMALY-001: MUST NOT import ``httpx``, ``anthropic``, or ``openrouter_client``
  at module level — only inside ``from_env()`` / ``chat()`` so the import-time
  side-effect (key read) is deferred.
ANOMALY-003: imported by ``pipeline.research.gateways`` so the orphan gate
  stays green.

Gateway contract:
  from_env() -> OpenRouterGateway | raises KeyError
  chat(model, messages, *, json_mode, max_tokens, ...) -> dict[str, object]
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from pipeline.research.http_pool import mask_key

logger = logging.getLogger(__name__)

# ── Named constants ────────────────────────────────────────────────────────────

_OPENROUTER_PAID_VARS: tuple[str, ...] = (
    "OPENROUTER_KEY_PAID",
    "OPENROUTER_API_KEY",
)
"""Environment variable names checked for the paid OpenRouter key."""


# ── Protocol for the underlying client ────────────────────────────────────────


@runtime_checkable
class _ChatClientProtocol(Protocol):
    """Structural type accepted by OpenRouterGateway for the wrapped client.

    Matches ``OpenRouterClient.chat`` and test doubles without importing the
    real class at module level.
    """

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = ...,
        json_mode: bool = ...,
    ) -> dict[str, object]: ...


# ── Key-extraction helper ─────────────────────────────────────────────────────


def _extract_masked_key(client: _ChatClientProtocol) -> str:
    """Return a log-safe masked key from an ``OpenRouterClient``-like object.

    ``OpenRouterClient`` stores keys in ``._keys[0].key``.  Any other object
    (test doubles, future clients) will simply fall through to ``"(unknown)"``.
    The attribute access is done via ``getattr`` to avoid pyright errors about
    the private attribute not being part of the Protocol.

    Args:
        client: Any object satisfying ``_ChatClientProtocol``.

    Returns:
        ``mask_key(first_key)`` when the attribute chain resolves; otherwise
        the literal string ``"(unknown)"``.
    """
    try:
        keys_attr = getattr(client, "_keys", None)
        if keys_attr is None:
            return "(unknown)"
        first_key_obj = keys_attr[0]
        raw_key: str = str(getattr(first_key_obj, "key", ""))
        if not raw_key:
            return "(unknown)"
        return mask_key(raw_key)
    except Exception:
        return "(unknown)"


# ── Gateway ────────────────────────────────────────────────────────────────────


class OpenRouterGateway:
    """OpenRouter gateway that delegates to OpenRouterClient.chat.

    This class exposes the same ``from_env()`` / ``chat()`` surface as the
    other research gateways (AimlClient, TaoAIClient) so the router can treat
    it uniformly.

    Authentication:
        Reads ``OPENROUTER_KEY_PAID`` (or ``OPENROUTER_API_KEY`` as fallback)
        at construction time.  ``from_env()`` raises ``KeyError`` when no key
        is present so the router can silently skip OpenRouter if absent.

    Delegation:
        ``chat()`` is a thin pass-through to ``OpenRouterClient.chat()``; it
        does not re-implement HTTP or retry logic.

    Quota:
        ``BudgetExceeded`` from ``openrouter_client`` is re-raised unchanged;
        callers should catch ``pipeline.research.http_pool.BudgetExceeded`` or
        the OpenRouter-specific variant — both are ``Exception`` subclasses.
    """

    def __init__(self, _client: _ChatClientProtocol) -> None:
        """Construct from a ready ``OpenRouterClient`` instance.

        Prefer ``from_env()`` for normal construction; this overload exists for
        testing (inject a mock client without touching os.environ).

        Args:
            _client: An ``OpenRouterClient``-compatible object with a
                     ``chat(model, messages, paid_required, json_mode)`` method.
        """
        self._client: _ChatClientProtocol = _client
        # Mask the key for logging — extracted via the helper to avoid pyright
        # errors about private attributes not declared on the Protocol.
        self._masked: str = _extract_masked_key(_client)

    def __repr__(self) -> str:
        return f"OpenRouterGateway(key={self._masked}...)"

    @classmethod
    def from_env(cls) -> OpenRouterGateway:
        """Construct from environment variables.

        Checks ``OPENROUTER_KEY_PAID`` and ``OPENROUTER_API_KEY``.

        Returns:
            A ready ``OpenRouterGateway``.

        Raises:
            KeyError: When no OpenRouter key is available.
        """
        import os  # noqa: PLC0415

        has_key = any(os.environ.get(v, "").strip() for v in _OPENROUTER_PAID_VARS)
        if not has_key:
            raise KeyError(
                "OPENROUTER_KEY_PAID / OPENROUTER_API_KEY not set — OpenRouterGateway skipped."
            )

        # Import here so module-level import does not drag in httpx at boot.
        from pipeline.openrouter_client import OpenRouterClient  # noqa: PLC0415

        try:
            client = OpenRouterClient()
        except ValueError as exc:
            # OpenRouterClient raises ValueError when the key is empty after its
            # own validation — translate to KeyError so callers see a uniform API.
            raise KeyError(str(exc)) from exc

        return cls(client)

    # ── chat() ─────────────────────────────────────────────────────────────────

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        run_id: str | None = None,
        phase: str | None = None,
        paid_required: bool = False,
    ) -> dict[str, object]:
        """Send a chat completion request via OpenRouter.

        Delegates directly to ``OpenRouterClient.chat()`` without re-implementing
        HTTP, retry, or key-rotation logic.

        Args:
            model: OpenRouter model identifier, e.g.
                   ``"perplexity/sonar-pro"``,
                   ``"anthropic/claude-sonnet-4.6"``.
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            json_mode: Pass ``response_format={"type": "json_object"}`` for
                       non-Perplexity models (Perplexity rejects it).
            max_tokens: Accepted for interface parity with TaoAIClient / AimlClient;
                        not forwarded — ``OpenRouterClient`` does not expose this
                        parameter.
            run_id: Optional run identifier for log tracing.
            phase: Optional phase label for log tracing.
            paid_required: Forward to ``OpenRouterClient.chat(paid_required=...)``
                           so paid key is enforced when True.

        Returns:
            Parsed JSON dict from the LLM response content.

        Raises:
            pipeline.openrouter_client.BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts in OpenRouterClient fail.
        """
        logger.info(
            "OpenRouterGateway.chat key=%s model=%s json_mode=%s paid_required=%s",
            self._masked,
            model,
            json_mode,
            paid_required,
        )
        return self._client.chat(
            model,
            messages,
            paid_required=paid_required,
            json_mode=json_mode,
        )
