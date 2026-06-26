"""pipeline/llm_client.py — Shared chat-client factory (302.ai-primary capable).

Single source of OpenRouter <-> 302.ai provider selection. Every LLM call site
(generation premise prose, micro-amplify, zeitgeist probe, seed mixture-of-agents,
research dispatch) builds its client here so the whole engine survives an
OpenRouter outage on the operator's 302.ai key.

Provider priority (resolved per call to ``build_chat_client``):
  * 302.ai PRIMARY when ``TAO_AI_PRIMARY`` is truthy OR no OpenRouter key is set.
    OpenRouter is then used only as a fallback when 302.ai raises ``BudgetExceeded``.
  * OpenRouter PRIMARY otherwise, with 302.ai as the ``BudgetExceeded`` fallback.

ADR-0007: this module SELECTS HTTP clients; it never imports httpx / anthropic.
ADR-0003: key masking is handled inside each underlying client.
MUST NOT be imported from pipeline/scoring.py (ANOMALY-001).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Protocol

_log = logging.getLogger(__name__)

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


class ChatClient(Protocol):
    """Structural type shared by OpenRouterClient and TaoAIClient."""

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = ...,
        json_mode: bool = ...,
    ) -> dict[str, object]: ...


def tao_primary_requested() -> bool:
    """Return True when ``TAO_AI_PRIMARY`` asks for 302.ai-first routing."""
    return os.environ.get("TAO_AI_PRIMARY", "").strip().lower() in _TRUTHY


def _has_openrouter_key() -> bool:
    return bool(os.environ.get("OPENROUTER_KEY_PAID") or os.environ.get("OPENROUTER_API_KEY"))


def _has_tao_key() -> bool:
    return bool(os.environ.get("TAO_AI_API_KEY", "").strip())


def _make_openrouter() -> ChatClient:
    from pipeline.openrouter_client import OpenRouterClient  # noqa: PLC0415

    return OpenRouterClient()


def _make_tao() -> ChatClient:
    from pipeline.research.client_302ai import TaoAIClient  # noqa: PLC0415

    # TaoAIClient.chat interleaves extra optional kwargs (max_tokens/run_id/phase)
    # but is call-compatible with the ChatClient protocol — same pattern as
    # research_dispatch._tao_client_or_raise.
    return TaoAIClient.from_env()  # type: ignore[return-value]


def _budget_exceptions() -> tuple[type[Exception], ...]:
    """Both providers' quota-exhausted exception types (lazy-imported)."""
    excs: list[type[Exception]] = []
    try:
        from pipeline.openrouter_client import BudgetExceeded as _ORBudget  # noqa: PLC0415

        excs.append(_ORBudget)
    except ImportError:  # pragma: no cover - import guard
        pass
    try:
        from pipeline.research.client_302ai import BudgetExceeded as _TaoBudget  # noqa: PLC0415

        excs.append(_TaoBudget)
    except ImportError:  # pragma: no cover - import guard
        pass
    return tuple(excs) or (Exception,)


class FallbackClient:
    """Wrap a primary chat client; retry on a lazily-built secondary when the
    primary raises a provider ``BudgetExceeded`` (HTTP 402).

    The secondary is built only on first need so an absent fallback key never
    blocks the primary path.
    """

    def __init__(
        self,
        primary: ChatClient,
        make_secondary: Callable[[], ChatClient] | None = None,
    ) -> None:
        self._primary = primary
        self._make_secondary = make_secondary
        self._secondary: ChatClient | None = None

    def _get_secondary(self) -> ChatClient | None:
        if self._secondary is None and self._make_secondary is not None:
            self._secondary = self._make_secondary()
        return self._secondary

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        try:
            return self._primary.chat(
                model, messages, paid_required=paid_required, json_mode=json_mode
            )
        except _budget_exceptions() as exc:
            secondary = self._get_secondary()
            if secondary is None:
                raise
            _log.warning(
                "llm_client: primary BudgetExceeded (%s) — falling back to secondary provider",
                exc,
            )
            return secondary.chat(model, messages, paid_required=paid_required, json_mode=json_mode)


def build_chat_client() -> ChatClient:
    """Return a chat client honoring the 302.ai-primary policy.

    Raises ``KeyError`` / ``ValueError`` (from the underlying client) only when NO
    provider key is configured at all. Every caller already wraps this in a
    try/except that degrades gracefully, so the raise surfaces a helpful message
    rather than a silent failure.
    """
    use_tao_primary = tao_primary_requested() or not _has_openrouter_key()

    if use_tao_primary:
        if _has_tao_key():
            secondary = _make_openrouter if _has_openrouter_key() else None
            return FallbackClient(_make_tao(), secondary)
        # No 302.ai key — use OpenRouter if present, else let _make_tao raise the
        # helpful KeyError describing how to set TAO_AI_API_KEY.
        if _has_openrouter_key():
            return _make_openrouter()
        return _make_tao()

    # OpenRouter primary (default when an OR key exists and TAO_AI_PRIMARY is unset).
    secondary = _make_tao if _has_tao_key() else None
    return FallbackClient(_make_openrouter(), secondary)


__all__ = [
    "ChatClient",
    "FallbackClient",
    "build_chat_client",
    "tao_primary_requested",
]
