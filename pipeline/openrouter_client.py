"""OpenRouter HTTP client for Anomaly Engine v3.0.

Implements 3-key FIFO rotation (ADR-0003), tenacity retry (4 attempts),
BudgetExceeded exception, model name pinning (PIPE-03), and SEC-07 key masking.

MUST NOT be imported by pipeline/scoring.py (ANOMALY-001).
MUST NOT import from frameworks/ (ANOMALY-002).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Final

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:
    pass

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────

HTTP_402_PAYMENT_REQUIRED: int = 402
HTTP_429_RATE_LIMITED: int = 429

PLATFORM_FEE: float = 1.055
"""OpenRouter platform markup applied to Opus 4.7 cost estimates."""

tokenizer_multiplier: float = 1.35
"""Opus 4.7 token count multiplier for accurate cost estimation."""

PHASE_3_SONAR_CALL_CAP: int = int(os.environ.get("PHASE_3_SONAR_CALL_CAP", "10"))
"""Maximum number of perplexity/sonar calls per pipeline run (Phase 3); env-overridable."""

_HTTP_TIMEOUT_S: float = float(os.environ.get("OPENROUTER_HTTP_TIMEOUT_S", "60"))
"""HTTP request timeout (seconds) for OpenRouter calls; env-overridable."""

DEFAULT_PHASE4_MODEL: str = "anthropic/claude-sonnet-4.6"
"""Default model for Phase 4 Forge (ADR-0006 — Opus promoted only on two-gate pass)."""

_OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/chat/completions"

# ── MODELS registry ───────────────────────────────────────────────────────────

MODELS: dict[str, dict[str, float]] = {
    "anthropic/claude-sonnet-4.6": {
        "input_usd_per_1m": 3.0,
        "output_usd_per_1m": 15.0,
    },
    "anthropic/claude-opus-4.7": {
        "input_usd_per_1m": 15.0,
        "output_usd_per_1m": 75.0,
    },
    "anthropic/claude-haiku-4.5": {
        "input_usd_per_1m": 0.25,
        "output_usd_per_1m": 1.25,
    },
    "perplexity/sonar": {
        "input_usd_per_1m": 1.0,
        "output_usd_per_1m": 1.0,
    },
    "perplexity/sonar-deep-research": {
        "input_usd_per_1m": 2.0,
        "output_usd_per_1m": 2.0,
    },
    # Alias: older agent prompts use sonar-pro; route to sonar-pro-search
    "perplexity/sonar-pro": {
        "input_usd_per_1m": 1.0,
        "output_usd_per_1m": 1.0,
    },
    "meta-llama/llama-3.1-70b-instruct:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "mistralai/mistral-7b-instruct:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    # Free reasoning fleet (operator-supplied 2026-05-10 — fallback when paid
    # quota exhausted). Pricing $0/$0; daily-call caps governed by OpenRouter
    # per-account, not per-key.
    "nvidia/nemotron-3-super-120b-a12b:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "nvidia/nemotron-3-nano-30b-a3b:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "inclusionai/ling-2.6-1t:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "minimax/minimax-m2.5:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "google/gemma-4-31b-it:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "google/gemma-4-26b-a4b-it:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "tencent/hy3-preview:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "liquid/lfm-2.5-1.2b-thinking:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "poolside/laguna-m.1:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    # Deep-research models added 2026-05-12
    "perplexity/sonar-pro-search": {
        "input_usd_per_1m": 1.0,
        "output_usd_per_1m": 1.0,
    },
    "openai/o4-mini-deep-research": {
        "input_usd_per_1m": 1.1,
        "output_usd_per_1m": 4.4,
    },
    "alibaba/tongyi-deepresearch-30b-a3b": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
    "poolside/laguna-xs.2:free": {
        "input_usd_per_1m": 0.0,
        "output_usd_per_1m": 0.0,
    },
}


# ── Exceptions ────────────────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised when all API keys are exhausted or a daily/monthly cap is hit."""


# ── Key state ─────────────────────────────────────────────────────────────────


@dataclass
class KeyState:
    """Tracks exhaustion state for a single API key."""

    key: str
    daily_remaining: int
    exhausted: bool = False


# ── Key masking (SEC-07) ──────────────────────────────────────────────────────

_MASK_PREFIX_LEN: int = 9
"""Number of key chars to expose in masked output (SEC-07).

OpenRouter key format: 'sk-or-v1-...' — expose full prefix including trailing
hyphen (9 chars) so masked output reads 'sk-or-v1-...' and is recognisable."""


def _mask_key(key: str) -> str:
    """Return key[:9] + '...' to prevent accidental key leakage in logs (SEC-07).

    Exposes the first 9 characters so that 'sk-or-v1-' prefix is recognisable
    without leaking the secret portion.

    Args:
        key: Full API key string.

    Returns:
        Masked string: first 9 chars followed by '...' if longer than 9 chars;
        original string unchanged if 9 chars or fewer.
    """
    if len(key) > _MASK_PREFIX_LEN:
        return key[:_MASK_PREFIX_LEN] + "..."
    return key


# ── JSON fence stripper ───────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*", re.MULTILINE)

_PERPLEXITY_MODEL_PREFIX: Final[str] = "perplexity/"


def _is_perplexity_model(model: str) -> bool:
    """Return True if the model id targets Perplexity's Sonar backend.

    Perplexity's chat-completions endpoint accepts only ``response_format``
    types ``text`` or ``json_schema``. The OpenAI/Anthropic ``json_object``
    value triggers HTTP 400 ("json_schema: Field required"). Callers gate the
    ``response_format`` field on this predicate.
    """
    return model.startswith(_PERPLEXITY_MODEL_PREFIX)


def _strip_json_fence(text: str) -> str:
    """Strip leading ```json and trailing ``` fences from LLM responses."""
    stripped = _FENCE_RE.sub("", text.strip())
    return stripped.rstrip("`").strip()


def _parse_possibly_multiple_json(text: str) -> dict[str, object]:
    """Parse JSON that may be multiple stacked objects (model returned N objects instead of array).

    If json.loads succeeds, return as-is. If it fails with 'Extra data', collect all
    JSON objects via raw_decode and wrap them as {"assets": [...]}.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if "Extra data" not in str(exc):
            raise
        decoder = json.JSONDecoder()
        objects: list[object] = []
        pos = 0
        stripped = text.strip()
        while pos < len(stripped):
            while pos < len(stripped) and stripped[pos] in " \t\n\r":
                pos += 1
            if pos >= len(stripped):
                break
            obj, pos = decoder.raw_decode(stripped, pos)
            objects.append(obj)
        if not objects:
            raise
        if len(objects) == 1:
            return objects[0]  # type: ignore[return-value]
        return {"assets": objects}  # type: ignore[return-value]


# ── Client ────────────────────────────────────────────────────────────────────


class OpenRouterClient:
    """3-key FIFO OpenRouter HTTP client.

    Key priority (ADR-0003):
        Index 0: OPENROUTER_KEY_PAID    (1000 calls/day)
        Index 1: OPENROUTER_KEY_FREE_1  (50 calls/day)
        Index 2: OPENROUTER_KEY_FREE_2  (50 calls/day)

    Rotation:
        - paid_required=False: cycle indexes 0→1→2→0… skipping exhausted keys
        - paid_required=True: always use index 0 (PAID key)

    All log output masks keys to first 8 chars (SEC-07).
    """

    def __init__(self) -> None:
        # Accept OPENROUTER_API_KEY as a fallback for OPENROUTER_KEY_PAID so
        # environments that use the common env-var name work without reconfiguration.
        paid_key = os.environ.get("OPENROUTER_KEY_PAID") or os.environ.get("OPENROUTER_API_KEY", "")
        free1_key = os.environ.get("OPENROUTER_KEY_FREE_1", "")
        free2_key = os.environ.get("OPENROUTER_KEY_FREE_2", "")

        if not paid_key:
            logger.warning(
                "Neither OPENROUTER_KEY_PAID nor OPENROUTER_API_KEY is set. "
                "API calls will fail. Set one of these env vars in .env."
            )
            raise ValueError(
                "No OpenRouter API key found. "
                "Set OPENROUTER_KEY_PAID or OPENROUTER_API_KEY in .env."
            )

        self._keys: list[KeyState] = [
            KeyState(key=paid_key, daily_remaining=1000),
            KeyState(key=free1_key, daily_remaining=50),
            KeyState(key=free2_key, daily_remaining=50),
        ]
        self._key_index: int = 0
        self._sonar_call_count: int = 0

    @property
    def sonar_call_count(self) -> int:
        """Number of calls made to perplexity/sonar in this session."""
        return self._sonar_call_count

    def _select_key(self, paid_required: bool) -> KeyState:
        """Select the next KeyState according to FIFO rotation policy.

        Args:
            paid_required: If True, always return PAID key (index 0).

        Returns:
            KeyState for the selected key.

        Raises:
            BudgetExceeded: If all keys are exhausted (or PAID key exhausted
                            when paid_required=True).
        """
        if paid_required:
            ks = self._keys[0]
            if ks.exhausted:
                raise BudgetExceeded("PAID key exhausted and paid_required=True — cannot proceed.")
            return ks

        # FIFO rotation: advance index, skip exhausted, raise if all exhausted
        all_exhausted = all(ks.exhausted for ks in self._keys)
        if all_exhausted:
            raise BudgetExceeded("All 3 API keys are exhausted — BudgetExceeded for this run.")

        # Find next non-exhausted key starting from current index
        for _ in range(len(self._keys)):
            ks = self._keys[self._key_index]
            self._key_index = (self._key_index + 1) % len(self._keys)
            if not ks.exhausted:
                return ks

        raise BudgetExceeded("All 3 API keys are exhausted — BudgetExceeded for this run.")

    def _build_request_payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
    ) -> dict[str, object]:
        """Build the JSON payload for the OpenRouter chat completions endpoint.

        When json_mode=True the payload includes
        ``"response_format": {"type": "json_object"}`` which OpenRouter passes
        through to the Anthropic backend so Claude returns valid JSON
        unconditionally (no prose wrappers, no embedded fences).

        Perplexity Sonar models reject ``{"type": "json_object"}`` with HTTP 400
        ("json_schema: Field required") — Sonar only accepts ``{"type": "text"}``
        (default) or ``{"type": "json_schema", "json_schema": {...}}``. For
        Perplexity models the field is omitted; the prompt instructs the model
        to return raw JSON and ``_strip_json_fence`` + ``_parse_possibly_multiple_json``
        handle parsing on the response side.
        """
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
        }
        if json_mode and not _is_perplexity_model(model):
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _call_once(
        self,
        key: str,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
    ) -> dict[str, object]:
        """Make a single HTTP POST to OpenRouter and return parsed JSON.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses (triggers tenacity retry).
            httpx.ConnectError: On connection failure (triggers tenacity retry).
            json.JSONDecodeError: If response content is not valid JSON after
                                  fence stripping (triggers tenacity retry).
            BudgetExceeded: On HTTP 402 or 429 (key limit hit — not retriable).
        """
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = self._build_request_payload(model, messages, json_mode=json_mode)

        with httpx.Client(timeout=_HTTP_TIMEOUT_S) as client:
            response = client.post(_OPENROUTER_API_URL, headers=headers, json=payload)

        if response.status_code == HTTP_402_PAYMENT_REQUIRED:
            # payment required / quota hard stop — mark key permanently exhausted
            logger.warning(
                "key=%s model=%s status=402 — marking key exhausted",
                _mask_key(key),
                model,
            )
            for ks in self._keys:
                if ks.key == key:
                    ks.exhausted = True
                    break
            raise BudgetExceeded(f"Key {_mask_key(key)} returned HTTP 402 — exhausted.")
        if response.status_code == HTTP_429_RATE_LIMITED:
            # 429 = rate limit — raise HTTPStatusError so tenacity retries with backoff
            logger.warning(
                "key=%s model=%s status=429 — rate limited, will retry",
                _mask_key(key),
                model,
            )
            response.raise_for_status()  # raises HTTPStatusError → tenacity retries

        response.raise_for_status()

        try:
            raw_content: str = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            # Unexpected 200 envelope (e.g. a provider error body) — raise a
            # retriable JSONDecodeError so tenacity retries instead of crashing
            # the run with an unhandled KeyError/IndexError.
            raise json.JSONDecodeError(
                f"unexpected response shape: {exc}", response.text[:500], 0
            ) from exc
        cleaned = _strip_json_fence(raw_content)
        result: dict[str, object] = _parse_possibly_multiple_json(cleaned)
        return result

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        """Send a chat completion request to OpenRouter.

        Applies FIFO key selection, sonar cap enforcement, and tenacity retry
        (4 attempts with exponential backoff on HTTPError / json.JSONDecodeError).

        Args:
            model: Model identifier string (must be a key in MODELS).
            messages: List of {"role": ..., "content": ...} dicts.
            paid_required: If True, always use OPENROUTER_KEY_PAID (for sonar,
                           Phase 3 calls, and any premium-only request).
            json_mode: If True, request JSON-only responses via OpenRouter's
                       ``response_format`` field. Anthropic backend then returns
                       valid JSON unconditionally (no prose wrappers, no fences).

        Returns:
            Parsed JSON dict from the LLM response content.

        Raises:
            BudgetExceeded: When all keys exhausted or sonar cap exceeded.
            httpx.HTTPError: If all 4 tenacity attempts fail (propagated).
            json.JSONDecodeError: If parsing fails after all retries.
        """
        # Sonar call cap enforcement (PHASE_3_SONAR_CALL_CAP)
        if (
            model in ("perplexity/sonar", "perplexity/sonar-deep-research")
            and self._sonar_call_count >= PHASE_3_SONAR_CALL_CAP
        ):
            raise BudgetExceeded(
                f"perplexity/sonar call cap reached "
                f"({PHASE_3_SONAR_CALL_CAP} calls/run). "
                "Set paid_required=True and increase cap if needed."
            )

        # Try each available key in FIFO order; a single-key 402/429 exhausts that
        # key and falls through to the next one rather than aborting the request.
        for _attempt in range(len(self._keys) + 1):
            key_state = self._select_key(paid_required)  # raises if all exhausted
            key = key_state.key
            logger.info(
                "chat key=%s model=%s paid_required=%s",
                _mask_key(key),
                model,
                paid_required,
            )
            try:
                result = self._call_with_retry(key, model, messages, json_mode=json_mode)
            except BudgetExceeded:
                if paid_required:
                    raise  # paid key exhausted and it's required — no fallback
                if all(ks.exhausted for ks in self._keys):
                    raise  # all keys gone
                continue  # try next key
            if model in ("perplexity/sonar", "perplexity/sonar-deep-research"):
                self._sonar_call_count += 1
            return result

        raise BudgetExceeded("All API keys exhausted after key-rotation attempts.")

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
        reraise=True,
    )
    def _call_with_retry(
        self,
        key: str,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
    ) -> dict[str, object]:
        """Tenacity-wrapped single-attempt HTTP call.

        Retries up to 4 attempts on HTTPError or JSONDecodeError.
        BudgetExceeded (402/429) is NOT retried — it propagates immediately.
        """
        return self._call_once(key, model, messages, json_mode=json_mode)

    def cost_estimate(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Estimate USD cost for a model call.

        For Opus 4.7: applies tokenizer_multiplier=1.35 and PLATFORM_FEE=1.055.
        For all other models: straight token-based cost.

        Args:
            model: Model key in MODELS registry.
            prompt_tokens: Number of prompt tokens.
            completion_tokens: Number of completion tokens.

        Returns:
            Estimated USD cost as a float.
        """
        if model not in MODELS:
            raise ValueError(f"Unknown model: {model!r}. Must be a key in MODELS.")

        rates = MODELS[model]
        input_cost = (prompt_tokens / 1_000_000) * rates["input_usd_per_1m"]
        output_cost = (completion_tokens / 1_000_000) * rates["output_usd_per_1m"]
        raw_cost = input_cost + output_cost

        if model == "anthropic/claude-opus-4.7":
            return raw_cost * tokenizer_multiplier * PLATFORM_FEE

        return raw_cost
