"""tests/test_gateway_webfetch.py — hermetic tests for the PLAN-ONLY WebFetch gateway.

The WebFetch gateway is intentionally network-free.  These tests verify:

  1. ``fetch(url)`` always raises ``WebFetchDeferred`` — never touches the network.
  2. ``webfetch_manifest(urls)`` returns a correct, JSON-serialisable manifest.
  3. ``WebFetchGateway`` (class API) mirrors the module-level functions.
  4. ``from_env()`` always succeeds (no key required).
  5. ``WebFetchDeferred`` carries the original URL and reason.
  6. No ``httpx`` or ``http_pool`` calls are made (gateway is truly PLAN-ONLY).

No ``ONLINE_WEBFETCH`` flag is needed because this gateway never calls the
network — the sentinel / manifest tests are the full coverage.

ADR-0007: HTTP is forbidden in this module; tests confirm no http_pool usage.
"""

from __future__ import annotations

import json

import pytest

from pipeline.research.gateways.webfetch import (
    WebFetchDeferred,
    WebFetchGateway,
    fetch,
    from_env,
    webfetch_manifest,
)

# ── WebFetchDeferred exception ────────────────────────────────────────────────


class TestWebFetchDeferred:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(WebFetchDeferred, Exception)

    def test_carries_url(self) -> None:
        exc = WebFetchDeferred("https://example.com/page")
        assert exc.url == "https://example.com/page"

    def test_default_reason(self) -> None:
        exc = WebFetchDeferred("https://example.com/page")
        assert exc.reason  # non-empty string
        assert "WebFetch" in exc.reason

    def test_custom_reason(self) -> None:
        exc = WebFetchDeferred("https://example.com/page", reason="too large")
        assert exc.reason == "too large"

    def test_str_contains_url(self) -> None:
        exc = WebFetchDeferred("https://example.com/page")
        assert "https://example.com/page" in str(exc)


# ── module-level fetch() ──────────────────────────────────────────────────────


class TestFetch:
    def test_always_raises_deferred(self) -> None:
        with pytest.raises(WebFetchDeferred):
            fetch("https://example.com/data")

    def test_raised_exception_carries_url(self) -> None:
        url = "https://boxofficemojo.com/title/tt1234567/"
        with pytest.raises(WebFetchDeferred) as exc_info:
            fetch(url)
        assert exc_info.value.url == url

    def test_never_calls_http_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confirm fetch() raises before any network call could happen."""
        import pipeline.research.http_pool as pool  # noqa: PLC0415

        calls: list[str] = []

        def _boom(*_a: object, **_kw: object) -> None:
            calls.append("http_pool called")

        monkeypatch.setattr(pool, "request_json", _boom)
        monkeypatch.setattr(pool, "request_text", _boom)

        with pytest.raises(WebFetchDeferred):
            fetch("https://example.com/")

        assert calls == [], "fetch() must not call http_pool before raising"

    def test_no_httpx_import_in_module(self) -> None:
        """webfetch.py must not import httpx (PLAN-ONLY / ADR-0007)."""
        import sys  # noqa: PLC0415

        import pipeline.research.gateways.webfetch as wf  # noqa: PLC0415

        # The webfetch module's own globals must not reference httpx.
        assert "httpx" not in dir(wf), "webfetch module must not expose httpx"
        # httpx may be loaded by other modules; we only require webfetch didn't
        # pull it in at module level.  Check the module's __dict__ directly.
        assert "httpx" not in vars(wf), "webfetch module must not import httpx"
        # Suppress unused variable warning — sys is needed for context.
        _ = sys


# ── webfetch_manifest() ───────────────────────────────────────────────────────


class TestWebfetchManifest:
    def test_empty_list_returns_empty(self) -> None:
        assert webfetch_manifest([]) == []

    def test_single_url_shape(self) -> None:
        result = webfetch_manifest(["https://example.com/data"])
        assert len(result) == 1
        entry = result[0]
        assert entry["url"] == "https://example.com/data"
        assert entry["provider"] == "webfetch"
        assert entry["deferred"] is True
        assert entry["fetched"] is False

    def test_multiple_urls_preserves_order(self) -> None:
        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]
        result = webfetch_manifest(urls)
        assert len(result) == 3
        assert [e["url"] for e in result] == urls

    def test_all_entries_deferred_true(self) -> None:
        urls = ["https://a.com", "https://b.com"]
        result = webfetch_manifest(urls)
        assert all(e["deferred"] is True for e in result)

    def test_all_entries_fetched_false(self) -> None:
        urls = ["https://a.com", "https://b.com"]
        result = webfetch_manifest(urls)
        assert all(e["fetched"] is False for e in result)

    def test_result_is_json_serialisable(self) -> None:
        urls = [
            "https://boxofficemojo.com/title/tt1234567/",
            "https://the-numbers.com/movie/Barbie",
        ]
        result = webfetch_manifest(urls)
        # Must not raise
        serialised = json.dumps(result)
        parsed = json.loads(serialised)
        assert len(parsed) == 2

    def test_provider_slug_is_webfetch(self) -> None:
        result = webfetch_manifest(["https://example.com"])
        assert result[0]["provider"] == "webfetch"


# ── from_env() ────────────────────────────────────────────────────────────────


class TestFromEnv:
    def test_always_succeeds_no_key_needed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WebFetch requires no API key — from_env() must never raise KeyError."""
        # Remove any env var that might coincidentally help or hinder.
        for var in ("WEBFETCH_API_KEY", "TAO_AI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.setenv(var, "")
        gateway = from_env()
        assert gateway is not None

    def test_returns_webfetch_gateway_instance(self) -> None:
        gateway = from_env()
        assert isinstance(gateway, WebFetchGateway)


# ── WebFetchGateway class ─────────────────────────────────────────────────────


class TestWebFetchGateway:
    def test_fetch_raises_deferred(self) -> None:
        gw = WebFetchGateway()
        with pytest.raises(WebFetchDeferred):
            gw.fetch("https://example.com/data")

    def test_fetch_deferred_carries_url(self) -> None:
        gw = WebFetchGateway()
        url = "https://variety.com/2024/film/box-office/barbie-1234/"
        with pytest.raises(WebFetchDeferred) as exc_info:
            gw.fetch(url)
        assert exc_info.value.url == url

    def test_manifest_returns_list(self) -> None:
        gw = WebFetchGateway()
        result = gw.manifest(["https://example.com"])
        assert isinstance(result, list)
        assert len(result) == 1

    def test_manifest_shape(self) -> None:
        gw = WebFetchGateway()
        result = gw.manifest(["https://example.com/page"])
        assert result[0]["provider"] == "webfetch"
        assert result[0]["deferred"] is True
        assert result[0]["fetched"] is False

    def test_manifest_empty(self) -> None:
        gw = WebFetchGateway()
        assert gw.manifest([]) == []

    def test_repr_does_not_expose_key(self) -> None:
        """WebFetchGateway has no key; repr must not leak secrets."""
        gw = WebFetchGateway()
        text = repr(gw)
        # Should be a reasonable repr string and not crash.
        assert "WebFetchGateway" in text

    def test_no_http_pool_on_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WebFetchGateway.fetch() must not touch http_pool."""
        import pipeline.research.http_pool as pool  # noqa: PLC0415

        calls: list[str] = []

        def _boom(*_a: object, **_kw: object) -> None:
            calls.append("http_pool called")

        monkeypatch.setattr(pool, "request_json", _boom)
        monkeypatch.setattr(pool, "request_text", _boom)

        gw = WebFetchGateway()
        with pytest.raises(WebFetchDeferred):
            gw.fetch("https://example.com/")

        assert calls == []


# ── Plan-only guarantee (integration-style) ───────────────────────────────────


class TestPlanOnlyGuarantee:
    """Verify the gateway truly stays network-free end-to-end."""

    def test_fetch_raises_before_any_io(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even if httpx were somehow reachable, fetch() raises first."""
        import builtins  # noqa: PLC0415

        original_open = builtins.open
        io_calls: list[str] = []

        def _spy_open(name: object, *a: object, **kw: object) -> object:
            io_calls.append(str(name))
            return original_open(name, *a, **kw)  # type: ignore[call-overload]

        # Only spy on file-open calls — we don't expect any during fetch().
        monkeypatch.setattr(builtins, "open", _spy_open)

        with pytest.raises(WebFetchDeferred):
            fetch("https://example.com/data")

        # No file I/O triggered by the fetch() call itself.
        assert io_calls == []

    def test_manifest_is_pure_dict_construction(self) -> None:
        """webfetch_manifest() is pure data — no I/O, no exceptions."""
        urls = [f"https://example.com/{i}" for i in range(10)]
        result = webfetch_manifest(urls)
        assert len(result) == 10
        # All required keys present in every entry.
        for entry in result:
            assert {"url", "provider", "deferred", "fetched"} <= entry.keys()
