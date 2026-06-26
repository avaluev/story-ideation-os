"""302.ai unified API client for Anomaly Engine — drop-in fallback for OpenRouter.

302.ai exposes Perplexity, Firecrawl, Jina, Exa, and SerpApi behind a single
Bearer key (TAO_AI_API_KEY).  This module mirrors the public surface of
pipeline/openrouter_client.py so that research_dispatch.py can substitute
providers without upstream changes.

ADR-0007: this IS the HTTP layer — HTTP is allowed here.
ADR-0001: any state written to disk uses pipeline.state.safe_write.
ADR-0003: API key masked to first 8 chars in all log output (SEC-07).
ADR-0008: every call records token burn via pipeline.quota.record.
ADR-0005: MUST NOT import from frameworks/.

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

_MASK_PREFIX_LEN: int = 8
"""Chars exposed in masked key output (SEC-07 — first 8 chars)."""

_HTTP_TIMEOUT: float = 30.0
_RETRY_ATTEMPTS: int = 4

# ── 302.ai endpoint catalogue ─────────────────────────────────────────────────
# Unified base; all providers share the same Bearer auth.

_TAO_CHAT_URL: str = "https://api.302.ai/v1/chat/completions"
_TAO_EXA_SEARCH_URL: str = "https://api.302.ai/exa/search"
_TAO_FIRECRAWL_SCRAPE_URL: str = "https://api.302.ai/firecrawl/v1/scrape"
_TAO_SERP_URL: str = "https://api.302.ai/serpapi/search"
_TAO_JINA_EMBED_URL: str = "https://api.302.ai/jina/v1/embeddings"

# ── Model-id mapping (OpenRouter-style → 302.ai catalog) ──────────────────────
# 302.ai's OpenAI-compatible endpoint expects BARE provider model ids
# (e.g. "sonar-pro"), not OpenRouter's "perplexity/sonar-pro" prefix form.
# Callers in this repo use the OpenRouter ids, so translate before building the
# payload — otherwise 302.ai rejects the model with a 4xx and the call degrades
# silently to WebSearch even when the key is valid.
_MODEL_MAP: dict[str, str] = {
    "perplexity/sonar": "sonar",
    "perplexity/sonar-pro": "sonar-pro",
    "perplexity/sonar-pro-search": "sonar-pro",
    "perplexity/sonar-reasoning": "sonar-reasoning",
    "perplexity/sonar-reasoning-pro": "sonar-reasoning-pro",
    "perplexity/sonar-deep-research": "sonar-deep-research",
}
_PROVIDER_PREFIXES: tuple[str, ...] = (
    "perplexity/",
    "anthropic/",
    "openai/",
    "google/",
    "x-ai/",
    "meta-llama/",
    "mistralai/",
)


def _load_model_overrides() -> dict[str, str]:
    """Operator overrides from ``TAO_AI_MODEL_OVERRIDES`` (a JSON object).

    Lets the operator correct a model id without a code change if 302.ai's
    catalog naming differs from the defaults. Malformed JSON is ignored.
    """
    raw = os.environ.get("TAO_AI_MODEL_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("TAO_AI_MODEL_OVERRIDES is not valid JSON — ignoring")
        return {}
    if not isinstance(data, dict):
        return {}
    typed: dict[str, Any] = cast("dict[str, Any]", data)
    return {str(k): str(v) for k, v in typed.items()}


def map_model(model: str) -> str:
    """Translate an OpenRouter-style model id to 302.ai's catalog id.

    Resolution order: operator override → static map → strip a known provider
    prefix → unchanged.
    """
    override = _load_model_overrides().get(model)
    if override:
        return override
    if model in _MODEL_MAP:
        return _MODEL_MAP[model]
    for prefix in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model


# ── JSON fence stripper (mirrors openrouter_client) ───────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*", re.MULTILINE)


def _strip_json_fence(text: str) -> str:
    """Strip leading ```json and trailing ``` fences from LLM responses."""
    stripped = _FENCE_RE.sub("", text.strip())
    return stripped.rstrip("`").strip()


def _parse_possibly_multiple_json(text: str) -> dict[str, Any]:
    """Parse JSON that may be multiple stacked objects.

    If json.loads succeeds, return as-is. If it fails with 'Extra data',
    collect all JSON objects via raw_decode and wrap as {"assets": [...]}.
    """
    try:
        return json.loads(text)  # type: ignore[no-any-return]
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


# ── Exceptions ────────────────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised when the 302.ai key returns HTTP 402 (quota exhausted)."""


# ── Key masking (SEC-07) ──────────────────────────────────────────────────────


def _mask_key(key: str) -> str:
    """Return key[:8] + '...' to prevent accidental key leakage in logs.

    Args:
        key: Full API key string.

    Returns:
        Masked string: first 8 chars followed by '...' if longer than 8 chars;
        original string unchanged if 8 chars or fewer.
    """
    if len(key) > _MASK_PREFIX_LEN:
        return key[:_MASK_PREFIX_LEN] + "..."
    return key


# ── Client ────────────────────────────────────────────────────────────────────


class TaoAIClient:
    """302.ai unified research client.

    Provides:
      - chat()   — LLM chat completions (Perplexity, OpenAI, etc.)
      - search() — Exa semantic web search
      - crawl()  — Firecrawl page scraping
      - serp()   — SerpApi search engine results
      - embed()  — Jina text embeddings

    Authentication: single Bearer key from TAO_AI_API_KEY env var.
    Key masking: first 8 chars only in all log output (SEC-07 / ADR-0003).
    Retry: tenacity 4 attempts, exponential backoff, on HTTPError / JSONDecodeError.
    Quota: every chat() call records token burn via pipeline.quota.record (ADR-0008).
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise KeyError("TAO_AI_API_KEY not set")
        self._key = api_key
        self._masked = _mask_key(api_key)

    def __repr__(self) -> str:
        return f"TaoAIClient(key={self._masked}...)"

    @classmethod
    def from_env(cls) -> TaoAIClient:
        """Construct from TAO_AI_API_KEY environment variable.

        Raises:
            KeyError: if TAO_AI_API_KEY is not set or is empty after stripping.
        """
        from pipeline.key_manager import resolve_302ai_key  # noqa: PLC0415

        key: str = resolve_302ai_key()
        return cls(api_key=key)

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def _handle_error_status(self, response: httpx.Response, context: str) -> None:
        """Raise BudgetExceeded on 402; re-raise HTTPStatusError on 429 for retry."""
        if response.status_code == HTTP_402_PAYMENT_REQUIRED:
            logger.warning(
                "key=%s context=%s status=402 — BudgetExceeded",
                self._masked,
                context,
            )
            raise BudgetExceeded(f"302.ai key {self._masked} returned HTTP 402 — quota exhausted.")
        if response.status_code == HTTP_429_RATE_LIMITED:
            logger.warning(
                "key=%s context=%s status=429 — rate limited, will retry",
                self._masked,
                context,
            )
            response.raise_for_status()  # raises HTTPStatusError → tenacity retries

    # ── chat() ────────────────────────────────────────────────────────────────

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        max_tokens: int = 2048,
        run_id: str | None = None,
        phase: str | None = None,
        # Accept (and ignore) paid_required kwarg so callers that pass it to
        # OpenRouterClient don't need code changes when swapping to TaoAIClient.
        paid_required: bool = False,
    ) -> dict[str, Any]:
        """Send a chat completion request to 302.ai.

        Mirrors the return shape of OpenRouterClient.chat() — returns the
        parsed JSON dict from the LLM response content field.

        Args:
            model: Model identifier, e.g. "perplexity/sonar-pro".
            messages: List of {"role": ..., "content": ...} dicts.
            json_mode: Request JSON-only responses.  For non-Perplexity models
                       this adds ``response_format={"type":"json_object"}``.
                       For ``perplexity/*`` models the field is omitted (same
                       behaviour as OpenRouterClient — Perplexity rejects it).
            max_tokens: Maximum tokens for the completion.
            run_id: Optional run identifier for quota tracking (ADR-0008).
            phase: Optional phase label for quota tracking (ADR-0008).
            paid_required: Accepted for interface compatibility; ignored.

        Returns:
            Parsed JSON dict from the LLM response content.

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
            json.JSONDecodeError: If parsing fails after all retries.
        """
        logger.info(
            "TaoAIClient.chat key=%s model=%s json_mode=%s",
            self._masked,
            model,
            json_mode,
        )
        result = self._chat_with_retry(model, messages, json_mode, max_tokens)
        self._record_quota(model, messages, result, run_id=run_id, phase=phase)
        return result

    @retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
        reraise=True,
    )
    def _chat_with_retry(
        self,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Single-attempt HTTP POST; tenacity wraps this with 4-attempt retry."""
        mapped_model = map_model(model)
        payload: dict[str, Any] = {
            "model": mapped_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Perplexity rejects response_format; detect it on either the original
        # ("perplexity/...") or mapped ("sonar...") id so the special-case holds
        # regardless of which form the caller passed.
        is_perplexity = model.startswith("perplexity/") or mapped_model.startswith("sonar")
        if json_mode and not is_perplexity:
            payload["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                _TAO_CHAT_URL,
                headers=self._auth_headers(),
                json=payload,
            )

        self._handle_error_status(response, context=f"chat/{model}")
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
        return _parse_possibly_multiple_json(cleaned)

    # ── search() ─────────────────────────────────────────────────────────────

    def search(self, query: str, *, max_results: int = 8) -> list[dict[str, Any]]:
        """Exa semantic search via 302.ai.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of dicts, each with keys: title, url, snippet, score.

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
        """
        logger.info(
            "TaoAIClient.search key=%s query=%.60s max_results=%d",
            self._masked,
            query,
            max_results,
        )
        return self._search_with_retry(query, max_results)

    @retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _search_with_retry(self, query: str, max_results: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "query": query,
            "numResults": max_results,
            "useAutoprompt": True,
        }
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                _TAO_EXA_SEARCH_URL,
                headers=self._auth_headers(),
                json=payload,
            )
        self._handle_error_status(response, context="search")
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        results_raw: list[dict[str, Any]] = data.get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("text", r.get("snippet", "")),
                "score": float(r.get("score", 0.0)),
            }
            for r in results_raw
        ]

    # ── crawl() ───────────────────────────────────────────────────────────────

    def crawl(
        self,
        url: str,
        *,
        formats: list[str] | tuple[str, ...] = ("markdown",),
    ) -> dict[str, Any]:
        """Firecrawl page scrape via 302.ai.

        Args:
            url: URL to scrape.
            formats: List of desired output formats, e.g. ["markdown", "html"].

        Returns:
            Dict with keys: url, markdown, html, meta.

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
        """
        logger.info(
            "TaoAIClient.crawl key=%s url=%.80s",
            self._masked,
            url,
        )
        return self._crawl_with_retry(url, list(formats))

    @retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _crawl_with_retry(self, url: str, formats: list[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url, "formats": formats}
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                _TAO_FIRECRAWL_SCRAPE_URL,
                headers=self._auth_headers(),
                json=payload,
            )
        self._handle_error_status(response, context="crawl")
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        inner: dict[str, Any] = data.get("data", data)
        return {
            "url": inner.get("url", url),
            "markdown": inner.get("markdown", ""),
            "html": inner.get("html", ""),
            "meta": inner.get("metadata", inner.get("meta", {})),
        }

    # ── serp() ────────────────────────────────────────────────────────────────

    def serp(
        self,
        query: str,
        *,
        engine: str = "google",
        num: int = 10,
    ) -> dict[str, Any]:
        """SerpApi SERP via 302.ai.

        Args:
            query: Search query.
            engine: Search engine backend, e.g. "google", "bing".
            num: Number of results to request.

        Returns:
            Raw SERP JSON dict from SerpApi.

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
        """
        logger.info(
            "TaoAIClient.serp key=%s engine=%s query=%.60s",
            self._masked,
            engine,
            query,
        )
        return self._serp_with_retry(query, engine, num)

    @retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _serp_with_retry(self, query: str, engine: str, num: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": query,
            "engine": engine,
            "num": num,
        }
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(
                _TAO_SERP_URL,
                headers=self._auth_headers(),
                params=params,
            )
        self._handle_error_status(response, context="serp")
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    # ── embed() ───────────────────────────────────────────────────────────────

    def embed(
        self,
        texts: list[str],
        *,
        model: str = "jina-embeddings-v3",
    ) -> list[list[float]]:
        """Jina text embeddings via 302.ai.

        Args:
            texts: List of strings to embed.
            model: Jina embedding model identifier.

        Returns:
            List of embedding vectors (one per input text).

        Raises:
            BudgetExceeded: On HTTP 402.
            httpx.HTTPError: If all retry attempts fail.
        """
        logger.info(
            "TaoAIClient.embed key=%s model=%s n_texts=%d",
            self._masked,
            model,
            len(texts),
        )
        return self._embed_with_retry(texts, model)

    @retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _embed_with_retry(self, texts: list[str], model: str) -> list[list[float]]:
        payload: dict[str, Any] = {"input": texts, "model": model}
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                _TAO_JINA_EMBED_URL,
                headers=self._auth_headers(),
                json=payload,
            )
        self._handle_error_status(response, context="embed")
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        embedding_objects: list[dict[str, Any]] = data.get("data", [])
        return [obj["embedding"] for obj in embedding_objects]

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

            # Rough token estimation if usage not provided by API.
            tokens_in = sum(len(m.get("content", "")) // 4 for m in messages)
            tokens_out = len(json.dumps(result)) // 4

            # Map model prefix to quota tier.
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
            logger.debug("TaoAIClient._record_quota failed (non-fatal)", exc_info=True)
