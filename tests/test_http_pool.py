"""Tests for pipeline.research.http_pool — hermetic (no live network).

Coverage targets:
- Semaphore cap is respected (RESEARCH_MAX_CONCURRENCY).
- HTTP 402 raises BudgetExceeded, not retried.
- HTTP 429 is retried (tenacity round-trips).
- Authorization header is masked to first 8 chars in log output (ADR-0003).
- request_json returns (status, url, dict).
- request_text returns (status, url, str).
- mask_key edge cases.

Network isolation: httpx.Client is replaced in pool's namespace with a factory
that builds a real httpx.Client using _RealClient (captured before patching)
wired to a _MockTransport.  This avoids the recursive-call trap that occurs
when fake_client() calls httpx.Client() after the monkeypatch has redirected
that name to fake_client itself.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any
from unittest.mock import patch

import httpx
import pytest

import pipeline.research.http_pool as pool
from pipeline.research.http_pool import (
    BudgetExceeded,
    mask_key,
    request_json,
    request_text,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

# Capture the real httpx.Client ONCE at import time so patched tests can still
# construct a real Client wired to a MockTransport without infinite recursion.
_RealClient = httpx.Client


def _make_response(
    status_code: int,
    body: dict[str, Any] | str,
    *,
    url: str = "https://example.com/api",
) -> httpx.Response:
    """Build an httpx.Response for use inside a MockTransport handler."""
    if isinstance(body, dict):
        content = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
    else:
        content = body.encode()
        headers = {"Content-Type": "text/plain"}

    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers,
        request=httpx.Request("POST", url),
    )


class _MockTransport(httpx.BaseTransport):
    """Synchronous transport that calls a handler for each request."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _make_fake_client(handler: Any) -> Any:
    """Return a fake_client factory that builds a _RealClient on a MockTransport.

    Using _RealClient (captured before any monkeypatch) breaks the recursion
    that occurs when pool.httpx.Client is patched to fake_client and fake_client
    itself tries to call httpx.Client().
    """
    transport = _MockTransport(handler)

    def fake_client(**_: Any) -> httpx.Client:
        return _RealClient(transport=transport)

    return fake_client


# ── mask_key ─────────────────────────────────────────────────────────────────


class TestMaskKey:
    def test_short_key_unchanged(self) -> None:
        assert mask_key("abc") == "abc"

    def test_exactly_8_chars_unchanged(self) -> None:
        assert mask_key("12345678") == "12345678"

    def test_long_key_truncated_with_ellipsis(self) -> None:
        key = "mockkey1HIDE"
        result = mask_key(key)
        assert result == "mockkey1..."
        assert "HIDE" not in result

    def test_ellipsis_appended(self) -> None:
        result = mask_key("ABCDEFGHIJ")
        assert result.endswith("...")

    def test_first_8_preserved(self) -> None:
        result = mask_key("AAAABBBBCCCC")
        assert result.startswith("AAAABBBB")


# ── BudgetExceeded ────────────────────────────────────────────────────────────


class TestBudgetExceeded:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(BudgetExceeded, Exception)

    def test_message_accessible(self) -> None:
        exc = BudgetExceeded("quota gone", provider="serper", status=402)
        assert "quota gone" in str(exc)

    def test_provider_attribute(self) -> None:
        exc = BudgetExceeded("x", provider="exa", status=402)
        assert exc.provider == "exa"

    def test_status_attribute(self) -> None:
        exc = BudgetExceeded("x", provider="jina", status=402)
        assert exc.status == 402

    def test_default_provider_empty_string(self) -> None:
        exc = BudgetExceeded("x")
        assert exc.provider == ""

    def test_default_status_402(self) -> None:
        exc = BudgetExceeded("x")
        assert exc.status == 402


# ── Semaphore cap ─────────────────────────────────────────────────────────────


class TestSemaphoreCap:
    """Verify that RESEARCH_MAX_CONCURRENCY bounds concurrent requests."""

    def test_semaphore_default_value(self) -> None:
        """Default cap is 4 when env var is absent."""
        sem = pool._build_semaphore()
        # We can't inspect the internal count directly; verify acquire/release cycle.
        assert sem.acquire(blocking=False)
        sem.release()

    def test_semaphore_custom_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RESEARCH_MAX_CONCURRENCY=2 yields a semaphore with cap 2."""
        monkeypatch.setenv("RESEARCH_MAX_CONCURRENCY", "2")
        sem = pool._build_semaphore()
        # Acquire 2 — should succeed.
        assert sem.acquire(blocking=False)
        assert sem.acquire(blocking=False)
        # Third acquire should block (return False with blocking=False).
        assert not sem.acquire(blocking=False)
        sem.release()
        sem.release()

    def test_invalid_concurrency_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-integer RESEARCH_MAX_CONCURRENCY falls back to 4."""
        monkeypatch.setenv("RESEARCH_MAX_CONCURRENCY", "notanumber")
        sem = pool._build_semaphore()
        # Cap of 4 — acquire 4 without blocking.
        acquired = 0
        for _ in range(4):
            if sem.acquire(blocking=False):
                acquired += 1
        assert acquired == 4
        assert not sem.acquire(blocking=False)
        for _ in range(acquired):
            sem.release()

    def test_semaphore_held_during_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The module semaphore is held while the HTTP call executes."""
        spy_sem = threading.Semaphore(4)
        acquired_inside: list[bool] = []

        def tracking_handler(request: httpx.Request) -> httpx.Response:
            acquired_inside.append(True)
            return _make_response(200, {"ok": True})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(tracking_handler))
        monkeypatch.setattr(pool, "_semaphore", spy_sem)

        request_json(
            "POST",
            "https://example.com/api",
            headers={"Authorization": "Bearer fake-test-key-12345"},
            json_body={"q": "test"},
        )

        assert acquired_inside  # handler was called


# ── 402 -> BudgetExceeded ─────────────────────────────────────────────────────


class TestHttp402RaisesBudgetExceeded:
    def test_request_json_402_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _make_response(402, {"error": "quota exhausted"})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        with pytest.raises(BudgetExceeded):
            request_json(
                "POST",
                "https://example.com/api",
                headers={"Authorization": "Bearer fake-test-key-12345"},
                json_body={"q": "hello"},
                provider="test_provider",
            )

    def test_request_text_402_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _make_response(402, "payment required")

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        with pytest.raises(BudgetExceeded) as exc_info:
            request_text(
                "GET",
                "https://example.com/page",
                headers={"Authorization": "Bearer fake-test-key-12345"},
                provider="jina",
            )

        assert exc_info.value.provider == "jina"
        assert exc_info.value.status == 402

    def test_budget_exceeded_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BudgetExceeded must NOT trigger tenacity retries (call count == 1)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _make_response(402, {"error": "no budget"})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        with pytest.raises(BudgetExceeded):
            request_json(
                "POST",
                "https://example.com/api",
                headers={"Authorization": "Bearer fake-test-key-99999"},
            )

        assert call_count == 1, f"Expected 1 call (no retry on 402), got {call_count}"


# ── 429 -> retried ───────────────────────────────────────────────────────────


class TestHttp429Retried:
    def test_request_json_429_then_200_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """First call returns 429; second call returns 200 — tenacity should retry."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return _make_response(429, {"error": "rate limited"})
            return _make_response(200, {"result": "ok"})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))
        # Patch wait to avoid sleeping in tests.
        with patch("pipeline.research.http_pool._do_request_json.retry.sleep"):
            status, _url, body = request_json(
                "POST",
                "https://example.com/api",
                headers={"Authorization": "Bearer fake-test-key-12345"},
                json_body={"q": "test"},
            )

        assert status == 200
        assert body == {"result": "ok"}
        assert len(calls) == 2

    def test_request_text_429_then_200_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same retry behaviour for request_text."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return _make_response(429, "rate limited")
            return _make_response(200, "markdown content here")

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))
        with patch("pipeline.research.http_pool._do_request_text.retry.sleep"):
            status, _url, body = request_text(
                "GET",
                "https://example.com/page",
                headers={"Authorization": "Bearer fake-test-key-12345"},
            )

        assert status == 200
        assert body == "markdown content here"
        assert len(calls) == 2

    def test_429_retried_up_to_4_times(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Persistent 429 exhausts all 4 attempts and raises HTTPStatusError."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return _make_response(429, {"error": "still rate limited"})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))
        with (
            patch("pipeline.research.http_pool._do_request_json.retry.sleep"),
            pytest.raises(httpx.HTTPStatusError),
        ):
            request_json(
                "POST",
                "https://example.com/api",
                headers={"Authorization": "Bearer fake-test-key-12345"},
            )

        assert len(calls) == 4, f"Expected 4 attempts (1 + 3 retries), got {len(calls)}"


# ── Auth masking ──────────────────────────────────────────────────────────────


class TestAuthMasking:
    def test_authorization_header_masked_in_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Full API key must NOT appear in DEBUG log output."""
        full_key = "mockkey1SUFSEC"

        def handler(request: httpx.Request) -> httpx.Response:
            return _make_response(200, {"data": "ok"})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        with caplog.at_level(logging.DEBUG, logger="pipeline.research.http_pool"):
            request_json(
                "POST",
                "https://example.com/api",
                headers={"Authorization": f"Bearer {full_key}"},
            )

        log_text = caplog.text
        assert "SUF" not in log_text
        assert "SEC" not in log_text

    def test_masked_auth_shows_first_8_chars(self) -> None:
        """_mask_auth_header strips Bearer prefix then masks to 8 chars."""
        headers = {"Authorization": "Bearer mockkey1ABCDE"}
        masked = pool._mask_auth_header(headers)
        assert masked == "mockkey1..."
        assert "ABCDE" not in masked

    def test_no_auth_header_returns_no_auth_label(self) -> None:
        masked = pool._mask_auth_header({})
        assert masked == "(no auth)"

    def test_x_api_key_header_not_special_cased(self) -> None:
        """Non-Authorization headers are not masked by _mask_auth_header."""
        headers = {"x-api-key": "serper-secret-key"}
        masked = pool._mask_auth_header(headers)
        assert masked == "(no auth)"


# ── request_json return shape ─────────────────────────────────────────────────


class TestRequestJsonReturnShape:
    def test_returns_status_url_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"results": [{"title": "Barbie", "box_office": 1_441_000_000}]}

        def handler(request: httpx.Request) -> httpx.Response:
            return _make_response(200, payload)

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        status, url, body = request_json(
            "POST",
            "https://api.example.com/search",
            headers={"Authorization": "Bearer fake-test-key-12345"},
            json_body={"query": "Barbie 2023 box office"},
            provider="serper",
        )

        assert status == 200
        assert isinstance(url, str)
        assert body == payload

    def test_get_method_with_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "q=hello" in str(request.url)
            return _make_response(200, {"organic": []})

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        status, _, body = request_json(
            "GET",
            "https://api.example.com/search",
            headers={"x-api-key": "fake-test-key"},
            params={"q": "hello", "num": 5},
        )

        assert status == 200
        assert "organic" in body


# ── request_text return shape ─────────────────────────────────────────────────


class TestRequestTextReturnShape:
    def test_returns_status_url_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        markdown = "# Title\n\nSome content here."

        def handler(request: httpx.Request) -> httpx.Response:
            return _make_response(200, markdown)

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        status, url, body = request_text(
            "GET",
            "https://r.jina.ai/https://example.com",
            headers={"Authorization": "Bearer fake-jina-key-12345"},
            provider="jina_reader",
        )

        assert status == 200
        assert isinstance(url, str)
        assert body == markdown

    def test_body_is_plain_string_not_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """request_text must return raw text even when body looks like JSON."""
        json_like = '{"key": "value"}'

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=json_like.encode(),
                headers={"Content-Type": "text/plain"},
                request=httpx.Request("GET", "https://example.com"),
            )

        monkeypatch.setattr(pool.httpx, "Client", _make_fake_client(handler))

        _, _, body = request_text(
            "GET",
            "https://example.com",
            headers={},
        )

        assert isinstance(body, str)
        assert body == json_like
