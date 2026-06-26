"""pipeline/research/http_pool.py — Shared rate-limited httpx helper.

Provides a single module-level semaphore (sized by ``RESEARCH_MAX_CONCURRENCY``,
default 4) that all research providers share, preventing thundering-herd bursts
against external APIs.

Public API
----------
request_json(method, url, *, headers, json_body, params, timeout, provider)
    -> tuple[int, str, dict]        (status_code, final_url, parsed_body)

request_text(method, url, *, headers, json_body, params, timeout, provider)
    -> tuple[int, str, str]         (status_code, final_url, body_text)

BudgetExceeded  — raised when any provider returns HTTP 402.
mask_key(key)   — first-8-chars masking for safe log output (SEC-07).

Design notes
------------
- Synchronous httpx.Client (no event loop dependency).
- Concurrency cap is advisory (threading.Semaphore), matching the existing
  TaoAIClient / openrouter_client.py usage pattern.
- Tenacity 4-attempt exponential backoff mirrors client_302ai.py exactly.
- HTTP 402 -> BudgetExceeded (never retried).
- HTTP 429 -> response.raise_for_status() so tenacity's httpx.HTTPError
  retry clause picks it up.
- Authorization header masked to first 8 chars in all log output (ADR-0003).

ADR-0007: HTTP is allowed in pipeline/research/ — NOT on the ANOMALY-001 ban
list.  scoring.py / cc_dispatch.py / gemini_dispatch.py MUST NOT import this.
ADR-0003: API keys masked to first 8 chars in logs.
ADR-0005: MUST NOT import from frameworks/.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────

_MASK_PREFIX_LEN: int = 8
_DEFAULT_MAX_CONCURRENCY: int = 4
_DEFAULT_TIMEOUT: float = 30.0
_RETRY_ATTEMPTS: int = 4

HTTP_402_PAYMENT_REQUIRED: int = 402
HTTP_429_RATE_LIMITED: int = 429


# ── Exceptions ────────────────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised when a provider returns HTTP 402 (payment required / quota exhausted).

    Args:
        provider: Short provider name included in the error message for triage.
        status:   HTTP status code (always 402 in normal use).
    """

    def __init__(self, message: str, *, provider: str = "", status: int = 402) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status


# ── Key masking (SEC-07 / ADR-0003) ──────────────────────────────────────────


def mask_key(key: str) -> str:
    """Return ``key[:8] + '...'`` for safe inclusion in log messages.

    Args:
        key: Full API key or Authorization header value.

    Returns:
        First 8 characters followed by ``'...'`` if the key is longer than
        8 characters; the original string unchanged otherwise.
    """
    if len(key) > _MASK_PREFIX_LEN:
        return key[:_MASK_PREFIX_LEN] + "..."
    return key


def _mask_auth_header(headers: dict[str, str]) -> str:
    """Return a log-safe representation of the Authorization header value."""
    auth = headers.get("Authorization") or headers.get("authorization", "")
    if not auth:
        return "(no auth)"
    # Strip "Bearer " prefix before masking so the key prefix is visible.
    value = auth.removeprefix("Bearer ").removeprefix("bearer ")
    return mask_key(value)


# ── Module-level semaphore ────────────────────────────────────────────────────


def _build_semaphore() -> threading.Semaphore:
    """Construct the module-level concurrency semaphore.

    The cap is read from ``RESEARCH_MAX_CONCURRENCY`` at import time.
    Invalid values (non-integer, <= 0) fall back to ``_DEFAULT_MAX_CONCURRENCY``.
    """
    raw = os.environ.get("RESEARCH_MAX_CONCURRENCY", "")
    if raw.strip():
        try:
            cap = int(raw.strip())
            if cap > 0:
                return threading.Semaphore(cap)
        except ValueError:
            pass
    return threading.Semaphore(_DEFAULT_MAX_CONCURRENCY)


# Module-level singleton semaphore — shared by all request_json / request_text calls.
_semaphore: threading.Semaphore = _build_semaphore()


# ── Internal retry helpers ────────────────────────────────────────────────────


def _handle_error_status(
    response: httpx.Response,
    *,
    url: str,
    provider: str,
    masked_auth: str,
) -> None:
    """Inspect ``response.status_code`` and raise the appropriate exception.

    HTTP 402 -> :class:`BudgetExceeded` (never retried by tenacity).
    HTTP 429 -> ``response.raise_for_status()`` which raises
                :class:`httpx.HTTPStatusError` (retried by tenacity).
    Other 4xx/5xx -> ``response.raise_for_status()`` (retried by tenacity).

    Args:
        response:    The httpx response to inspect.
        url:         Request URL (for log context only).
        provider:    Provider name tag (for log context and BudgetExceeded).
        masked_auth: Pre-masked Authorization header value for log output.
    """
    if response.status_code == HTTP_402_PAYMENT_REQUIRED:
        logger.warning(
            "http_pool: 402 BudgetExceeded provider=%s url=%.80s auth=%s",
            provider,
            url,
            masked_auth,
        )
        raise BudgetExceeded(
            f"provider={provider!r} returned HTTP 402 — quota exhausted.",
            provider=provider,
            status=402,
        )
    if response.status_code == HTTP_429_RATE_LIMITED:
        logger.warning(
            "http_pool: 429 rate-limited provider=%s url=%.80s auth=%s — will retry",
            provider,
            url,
            masked_auth,
        )
        response.raise_for_status()  # -> HTTPStatusError -> tenacity retries


@retry(
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
    reraise=True,
)
def _do_request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    params: dict[str, Any] | None,
    timeout: float,
    provider: str,
    masked_auth: str,
) -> tuple[int, str, dict[str, Any]]:
    """Single attempt; tenacity wraps with up to 4 retries.

    Returns:
        (status_code, final_url, parsed_json_body)

    Raises:
        BudgetExceeded:          On HTTP 402 (not retried).
        httpx.HTTPError:         On transport / status errors (retried).
        json.JSONDecodeError:    If response body is not valid JSON (retried).
    """
    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
        )
    _handle_error_status(response, url=url, provider=provider, masked_auth=masked_auth)
    response.raise_for_status()

    final_url = str(response.url)
    body: dict[str, Any] = response.json()
    return response.status_code, final_url, body


@retry(
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _do_request_text(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    params: dict[str, Any] | None,
    timeout: float,
    provider: str,
    masked_auth: str,
) -> tuple[int, str, str]:
    """Single attempt for plain-text responses; tenacity wraps with up to 4 retries.

    Returns:
        (status_code, final_url, body_text)

    Raises:
        BudgetExceeded:   On HTTP 402 (not retried).
        httpx.HTTPError:  On transport / status errors (retried).
    """
    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
        )
    _handle_error_status(response, url=url, provider=provider, masked_auth=masked_auth)
    response.raise_for_status()

    final_url = str(response.url)
    return response.status_code, final_url, response.text


# ── Public API ────────────────────────────────────────────────────────────────


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    provider: str = "",
) -> tuple[int, str, dict[str, Any]]:
    """Make an HTTP request and return the JSON-decoded response body.

    Acquires the module-level semaphore before issuing the request, capping
    concurrent outbound connections at ``RESEARCH_MAX_CONCURRENCY`` (default 4).

    Args:
        method:    HTTP method string, e.g. ``"POST"``, ``"GET"``.
        url:       Full request URL.
        headers:   HTTP headers dict.  ``Authorization`` is masked in logs.
        json_body: Optional JSON-serialisable request body (sent as
                   ``Content-Type: application/json``).
        params:    Optional query-string parameters.
        timeout:   Request timeout in seconds (default 30).
        provider:  Provider name tag for log messages and :class:`BudgetExceeded`.

    Returns:
        ``(status_code, final_url, parsed_body)`` — a 3-tuple where
        ``final_url`` reflects any redirects followed by httpx.

    Raises:
        BudgetExceeded:       If the provider returns HTTP 402.
        httpx.HTTPError:      If all 4 retry attempts fail.
        json.JSONDecodeError: If the response body is not valid JSON after retries.
    """
    masked_auth = _mask_auth_header(headers)
    logger.debug(
        "http_pool.request_json method=%s provider=%s url=%.80s auth=%s",
        method,
        provider,
        url,
        masked_auth,
    )
    with _semaphore:
        return _do_request_json(
            method,
            url,
            headers=headers,
            json_body=json_body,
            params=params,
            timeout=timeout,
            provider=provider,
            masked_auth=masked_auth,
        )


def request_text(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    provider: str = "",
) -> tuple[int, str, str]:
    """Make an HTTP request and return the raw text response body.

    Identical to :func:`request_json` except the body is returned as a plain
    string without JSON parsing (suitable for Jina Reader / markdown endpoints).

    Args:
        method:    HTTP method string, e.g. ``"GET"``.
        url:       Full request URL.
        headers:   HTTP headers dict.  ``Authorization`` is masked in logs.
        json_body: Optional JSON-serialisable request body.
        params:    Optional query-string parameters.
        timeout:   Request timeout in seconds (default 30).
        provider:  Provider name tag for log messages and :class:`BudgetExceeded`.

    Returns:
        ``(status_code, final_url, body_text)`` — a 3-tuple.

    Raises:
        BudgetExceeded:  If the provider returns HTTP 402.
        httpx.HTTPError: If all 4 retry attempts fail.
    """
    masked_auth = _mask_auth_header(headers)
    logger.debug(
        "http_pool.request_text method=%s provider=%s url=%.80s auth=%s",
        method,
        provider,
        url,
        masked_auth,
    )
    with _semaphore:
        return _do_request_text(
            method,
            url,
            headers=headers,
            json_body=json_body,
            params=params,
            timeout=timeout,
            provider=provider,
            masked_auth=masked_auth,
        )
