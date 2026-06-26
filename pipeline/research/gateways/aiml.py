"""pipeline/research/gateways/aiml.py — AIML API gateway for Anomaly Engine.

Provides chat completions via api.aimlapi.com (OpenAI-compatible protocol)
with model-aware citation extraction.  Mirrors the ``TaoAIClient.chat``
surface so ``sonar_cache.cached_chat`` can substitute gateways without
upstream changes.

Supported models (confirmed live — see runs/research/gw_smoke_snapshot.md):
  openai/gpt-5-chat-latest      — translation / synthesis; no citations
  perplexity/sonar-pro          — citations at top-level response["citations"]
  openai/gpt-4o-search-preview  — citations as inline markdown links in content

Key env vars:
  AIML_API_KEY          — Bearer token (required; raises KeyError when absent)
  AIML_MODEL_OVERRIDES  — optional JSON object mapping model → model (same
                          pattern as TAO_AI_MODEL_OVERRIDES in client_302ai.py)

ADR-0007: HTTP is allowed in pipeline/research/ — NOT on the ANOMALY-001 ban
  list.  scoring.py / cc_dispatch.py / gemini_dispatch.py MUST NOT import this.
ADR-0003: API keys masked to first 8 chars in all log output (SEC-07).
ADR-0005: MUST NOT import from frameworks/.
ADR-0008: every chat() call records token burn via pipeline.quota.record.
ANOMALY-003: imported by pipeline/research/gateways/__init__.py which is in
  turn imported by pipeline/research/__init__.py — orphan gate stays green.
MUST NOT be imported from pipeline/scoring.py (ANOMALY-001).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, cast

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:
    pass


from pipeline.research import http_pool

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────

_AIML_CHAT_URL: str = "https://api.aimlapi.com/v1/chat/completions"
_MASK_PREFIX_LEN: int = 8
_HTTP_TIMEOUT: float = 30.0
_RETRY_ATTEMPTS: int = 4

HTTP_402_PAYMENT_REQUIRED: int = 402
HTTP_429_RATE_LIMITED: int = 429


# ── Exceptions ────────────────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised when the AIML API key returns HTTP 402 (quota exhausted)."""


# ── Key masking (SEC-07 / ADR-0003) ──────────────────────────────────────────


def _mask_key(key: str) -> str:
    """Return ``key[:8] + '...'`` for safe inclusion in log messages.

    Args:
        key: Full API key string.

    Returns:
        First 8 characters followed by ``'...'`` if the key is longer than
        8 characters; original string unchanged otherwise.
    """
    if len(key) > _MASK_PREFIX_LEN:
        return key[:_MASK_PREFIX_LEN] + "..."
    return key


# ── Model-override helpers ────────────────────────────────────────────────────


def _load_model_overrides() -> dict[str, str]:
    """Operator overrides from ``AIML_MODEL_OVERRIDES`` (a JSON object).

    Mirrors the ``TAO_AI_MODEL_OVERRIDES`` pattern in ``client_302ai.py``.
    Malformed JSON is silently ignored so a misconfigured env var never
    crashes the pipeline.
    """
    raw = os.environ.get("AIML_MODEL_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AIML_MODEL_OVERRIDES is not valid JSON — ignoring")
        return {}
    if not isinstance(data, dict):
        return {}
    typed: dict[str, Any] = cast("dict[str, Any]", data)
    return {str(k): str(v) for k, v in typed.items()}


def _resolve_model(model: str) -> str:
    """Apply operator override if present; otherwise return model unchanged.

    AIML API accepts both bare ids (``gpt-5-chat-latest``) and qualified ids
    (``openai/gpt-5-chat-latest``).  The confirmed working ids already include
    the provider prefix so we pass them through as-is unless the operator has
    overridden.
    """
    override = _load_model_overrides().get(model)
    return override if override else model


# ── Citation extraction (model-family-aware) ──────────────────────────────────

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\)]+)\)")


def citations(response: dict[str, Any], model: str) -> list[str]:
    """Extract citation URLs from an AIML API response dict.

    Branches on model family as documented in gw_smoke_snapshot.md:

    ``perplexity/sonar-pro``
        Citations are at top-level ``response["citations"]`` — a plain list
        of URL strings.  Also checks ``response["search_results"]`` for
        additional URLs not already in the citations list.

    ``openai/gpt-4o-search-preview``
        Citations are embedded as markdown links inside
        ``choices[0].message.content``.  Also inspects
        ``choices[0].message.annotations`` for structured citation objects
        (each with a ``url`` key) when present.

    ``openai/gpt-5-chat-latest`` (and any other model)
        No web citations — returns an empty list.

    Args:
        response: The full parsed JSON response dict from the AIML API.
        model:    The model identifier as passed by the caller (may include
                  provider prefix, e.g. ``"perplexity/sonar-pro"``).

    Returns:
        Ordered, deduplicated list of citation URL strings.
    """
    seen: set[str] = set()
    urls: list[str] = []

    def _add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    resolved = _resolve_model(model)

    # ── perplexity/sonar-pro branch ───────────────────────────────────────────
    if "sonar" in model or "sonar" in resolved:
        raw_citations: list[Any] = list(response.get("citations") or [])
        for item in raw_citations:
            if isinstance(item, str):
                _add(item)
        raw_search_results: list[Any] = list(response.get("search_results") or [])
        for sr in raw_search_results:
            if isinstance(sr, dict):
                sr_dict = cast("dict[str, Any]", sr)
                _add(str(sr_dict.get("url") or ""))
        return urls

    # ── openai/gpt-4o-search-preview branch ──────────────────────────────────
    if "gpt-4o-search" in model or "gpt-4o-search" in resolved:
        raw_choices: list[Any] = list(response.get("choices") or [])
        if raw_choices:
            first_choice = cast(
                "dict[str, Any]",
                raw_choices[0] if isinstance(raw_choices[0], dict) else {},
            )
            raw_message: Any = first_choice.get("message") or {}
            message = cast(
                "dict[str, Any]",
                raw_message if isinstance(raw_message, dict) else {},
            )
            content: str = str(message.get("content") or "")
            for _text, url in _MARKDOWN_LINK_RE.findall(content):
                _add(str(url))
            raw_annotations: list[Any] = list(message.get("annotations") or [])
            for annotation in raw_annotations:
                if isinstance(annotation, dict):
                    ann = cast("dict[str, Any]", annotation)
                    _add(str(ann.get("url") or ""))
        return urls

    # ── all other models (gpt-5, etc.) — no citations ────────────────────────
    return urls


# ── Client ────────────────────────────────────────────────────────────────────


class AimlClient:
    """AIML API gateway — OpenAI-compatible chat completions.

    Public surface mirrors ``TaoAIClient.chat`` so this client can be used
    as a drop-in in ``sonar_cache.cached_chat``.

    Authentication: Bearer key from ``AIML_API_KEY`` env var.
    Key masking:    first 8 chars only in all log output (SEC-07 / ADR-0003).
    Retry:          tenacity 4 attempts, exponential backoff, on HTTPError.
    Quota:          every ``chat()`` call records token burn via
                    ``pipeline.quota.record`` (ADR-0008).
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise KeyError("AIML_API_KEY not set")
        self._key = api_key
        self._masked = _mask_key(api_key)

    def __repr__(self) -> str:
        return f"AimlClient(key={self._masked}...)"

    @classmethod
    def from_env(cls) -> AimlClient:
        """Construct from ``AIML_API_KEY`` environment variable.

        Raises:
            KeyError: if ``AIML_API_KEY`` is not set or empty after stripping.
        """
        key = os.environ.get("AIML_API_KEY", "").strip()
        if not key:
            raise KeyError("AIML_API_KEY not set")
        return cls(api_key=key)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    # ── chat() ────────────────────────────────────────────────────────────────

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        run_id: str | None = None,
        phase: str | None = None,
        # Accept (and ignore) paid_required kwarg so callers that pass it to
        # OpenRouterClient / TaoAIClient don't need code changes when swapping.
        paid_required: bool = False,
    ) -> dict[str, Any]:
        """Send a chat completion request to AIML API.

        Returns the parsed JSON dict from the LLM response content field,
        mirroring the return shape of ``TaoAIClient.chat``.  For perplexity
        and gpt-4o-search-preview models the raw response (including citations)
        is available via :func:`citations`.

        Args:
            model:        Model identifier, e.g. ``"openai/gpt-5-chat-latest"``.
            messages:     List of ``{"role": ..., "content": ...}`` dicts.
            json_mode:    Request JSON-only responses.  For ``perplexity/*``
                          models the ``response_format`` field is omitted
                          (Perplexity rejects it — same behaviour as
                          ``TaoAIClient``).
            max_tokens:   Maximum tokens for the completion.
            run_id:       Optional run identifier for quota tracking.
            phase:        Optional phase label for quota tracking.
            paid_required: Accepted for interface compatibility; ignored.

        Returns:
            Parsed JSON dict from the LLM response content.

        Raises:
            BudgetExceeded:      On HTTP 402.
            httpx.HTTPError:     If all retry attempts fail.
            json.JSONDecodeError: If parsing fails after all retries.
        """
        logger.info(
            "AimlClient.chat key=%s model=%s json_mode=%s",
            self._masked,
            model,
            json_mode,
        )
        result = self._chat_with_retry(model, messages, json_mode, max_tokens)
        self._record_quota(model, messages, result, run_id=run_id, phase=phase)
        return result

    def _chat_with_retry(
        self,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build payload and POST; delegated to pool with tenacity retry."""
        resolved = _resolve_model(model)
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Perplexity rejects response_format — detect on original or resolved id.
        is_perplexity = "sonar" in model or "sonar" in resolved
        if json_mode and not is_perplexity:
            payload["response_format"] = {"type": "json_object"}

        # Use http_pool so the shared semaphore and tenacity retry are applied.
        _status, _url, body = http_pool.request_json(
            "POST",
            _AIML_CHAT_URL,
            headers=self._auth_headers(),
            json_body=payload,
            timeout=_HTTP_TIMEOUT,
            provider="aiml",
        )

        # http_pool.BudgetExceeded is raised by the pool on 402; re-raise as
        # our own BudgetExceeded so callers that catch AimlClient.BudgetExceeded
        # work correctly.  The pool also retries 429 automatically.
        try:
            raw_content: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise json.JSONDecodeError(
                f"AimlClient: unexpected response shape: {exc}",
                json.dumps(body)[:500],
                0,
            ) from exc

        return _parse_content(raw_content)

    # ── Quota recording (ADR-0008) ────────────────────────────────────────────

    def _record_quota(
        self,
        model: str,
        messages: list[dict[str, str]],
        result: dict[str, Any],
        *,
        run_id: str | None,
        phase: str | None,
    ) -> None:
        """Append token burn to quota.jsonl.  Best-effort — never raises."""
        try:
            from pipeline import quota  # noqa: PLC0415

            tokens_in = sum(len(m.get("content", "")) // 4 for m in messages)
            tokens_out = len(json.dumps(result)) // 4

            tier: quota.ModelTier
            if "opus" in model:
                tier = "opus"
            elif "haiku" in model:
                tier = "haiku"
            else:
                tier = "sonnet"

            quota.record(
                model=tier,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                run_id=run_id or "unknown",
                phase=phase or "other",  # type: ignore[arg-type]
            )
        except Exception:
            logger.debug("AimlClient._record_quota failed (non-fatal)", exc_info=True)


# ── JSON fence stripper (mirrors client_302ai) ────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*", re.MULTILINE)


def _strip_json_fence(text: str) -> str:
    """Strip leading ```json / ``` fences from LLM response text."""
    stripped = _FENCE_RE.sub("", text.strip())
    return stripped.rstrip("`").strip()


def _parse_content(raw: str) -> dict[str, Any]:
    """Strip fences and JSON-parse LLM content.

    Falls back gracefully when the model returns prose instead of JSON by
    wrapping the text in ``{"text": ...}``.

    Args:
        raw: Raw string content from ``choices[0].message.content``.

    Returns:
        Parsed JSON dict.

    Raises:
        json.JSONDecodeError: Only if the stripped content cannot be parsed
            and the model was in strict json_mode (the caller will retry via
            tenacity).
    """
    cleaned = _strip_json_fence(raw)
    try:
        return json.loads(cleaned)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        # Non-JSON prose response (e.g. translation, synthesis without json_mode).
        return {"text": raw}
