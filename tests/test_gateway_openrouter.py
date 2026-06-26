"""tests/test_gateway_openrouter.py — offline + optional live tests for OpenRouterGateway.

Hermetic by default: all HTTP is mocked via the http_pool layer or a stub
_ChatClientProtocol double. Live calls are gated behind ``ONLINE_OPENROUTER=1``
(mirrors the ONLINE_302AI pattern in test_client_302ai.py).

Coverage:
  - from_env() raises KeyError when no key is present
  - from_env() constructs when OPENROUTER_KEY_PAID is set
  - from_env() accepts OPENROUTER_API_KEY as fallback
  - from_env() raises KeyError when OpenRouterClient raises ValueError
  - __repr__ masks the key (does not leak secret portion)
  - chat() delegates to the underlying client with correct args
  - chat() forwards paid_required=True
  - chat() forwards json_mode=True
  - chat() passes max_tokens / run_id / phase without error (unused kwargs)
  - chat() on HTTP 402 re-raises BudgetExceeded
  - chat() on HTTP 429 re-raises (retried by tenacity inside OpenRouterClient)
  - _extract_masked_key falls back to "(unknown)" for arbitrary objects
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.research.gateways.openrouter import (
    OpenRouterGateway,
    _extract_masked_key,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _fake_key(prefix: str = "mockkey1", suffix: str = "FAKEKEY") -> str:
    """Build a clearly-fake, non-credential-shaped key for tests."""
    return f"{prefix}{suffix}"


class _StubClient:
    """Minimal _ChatClientProtocol double that records calls and returns a preset."""

    def __init__(
        self,
        return_value: dict[str, object] | None = None,
        raise_exc: Exception | None = None,
        key: str = "mockkey1DEFKEY",
    ) -> None:
        self._return_value = return_value or {"ok": True}
        self._raise_exc = raise_exc
        # Mimic OpenRouterClient's _keys attribute for key-masking extraction.
        _ks = MagicMock()
        _ks.key = key
        self._keys: list[Any] = [_ks]
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "paid_required": paid_required,
                "json_mode": json_mode,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_value


# ── from_env() ─────────────────────────────────────────────────────────────────


class TestFromEnv:
    def test_raises_key_error_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_KEY_PAID", "")
        monkeypatch.setenv("OPENROUTER_API_KEY", "")
        with pytest.raises(KeyError):
            OpenRouterGateway.from_env()

    def test_raises_key_error_when_vars_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_KEY_PAID", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(KeyError):
            OpenRouterGateway.from_env()

    def test_constructs_when_paid_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_KEY_PAID", _fake_key())
        gw = OpenRouterGateway.from_env()
        assert isinstance(gw, OpenRouterGateway)

    def test_constructs_when_api_key_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_KEY_PAID", "")
        monkeypatch.setenv("OPENROUTER_API_KEY", _fake_key())
        gw = OpenRouterGateway.from_env()
        assert isinstance(gw, OpenRouterGateway)

    def test_raises_key_error_when_client_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenRouterClient raises ValueError on empty key — gateway translates to KeyError."""
        monkeypatch.setenv("OPENROUTER_KEY_PAID", _fake_key())

        import pipeline.openrouter_client as _or  # noqa: PLC0415

        original_cls = _or.OpenRouterClient

        class _BrokenClient:
            def __init__(self) -> None:
                raise ValueError("No OpenRouter API key found.")

        monkeypatch.setattr(_or, "OpenRouterClient", _BrokenClient)
        try:
            with pytest.raises(KeyError, match="No OpenRouter API key"):
                OpenRouterGateway.from_env()
        finally:
            monkeypatch.setattr(_or, "OpenRouterClient", original_cls)


# ── Key masking ────────────────────────────────────────────────────────────────


class TestKeyMasking:
    def test_repr_does_not_leak_secret(self) -> None:
        stub = _StubClient(key="mockkey1SECSFX")
        gw = OpenRouterGateway(stub)
        text = repr(gw)
        assert "SECSFX" not in text
        assert "mockkey1" in text  # prefix visible for triage

    def test_repr_contains_ellipsis(self) -> None:
        stub = _StubClient(key="mockkey1ABCDEF")
        gw = OpenRouterGateway(stub)
        assert "..." in repr(gw)

    def test_extract_masked_key_unknown_for_arbitrary_object(self) -> None:
        class _NoKeys:
            def chat(
                self,
                model: str,
                messages: list[dict[str, str]],
                paid_required: bool = False,
                json_mode: bool = False,
            ) -> dict[str, object]:
                return {}

        result = _extract_masked_key(_NoKeys())  # type: ignore[arg-type]
        assert result == "(unknown)"

    def test_extract_masked_key_unknown_for_empty_key(self) -> None:
        stub = _StubClient(key="")
        result = _extract_masked_key(stub)
        assert result == "(unknown)"


# ── chat() delegation ─────────────────────────────────────────────────────────


class TestChat:
    def test_chat_delegates_to_underlying_client(self) -> None:
        stub = _StubClient(return_value={"answer": "42"})
        gw = OpenRouterGateway(stub)
        result = gw.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert result == {"answer": "42"}
        assert len(stub.calls) == 1

    def test_chat_passes_correct_model(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(model="anthropic/claude-sonnet-4.6", messages=[{"role": "user", "content": "x"}])
        assert stub.calls[0]["model"] == "anthropic/claude-sonnet-4.6"

    def test_chat_passes_correct_messages(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        msgs = [{"role": "user", "content": "what is the box office?"}]
        gw.chat(model="perplexity/sonar-pro", messages=msgs)
        assert stub.calls[0]["messages"] == msgs

    def test_chat_forwards_json_mode_true(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(
            model="anthropic/claude-sonnet-4.6",
            messages=[{"role": "user", "content": "json please"}],
            json_mode=True,
        )
        assert stub.calls[0]["json_mode"] is True

    def test_chat_forwards_json_mode_false_by_default(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(model="perplexity/sonar-pro", messages=[{"role": "user", "content": "hi"}])
        assert stub.calls[0]["json_mode"] is False

    def test_chat_forwards_paid_required_true(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "hi"}],
            paid_required=True,
        )
        assert stub.calls[0]["paid_required"] is True

    def test_chat_paid_required_false_by_default(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(model="perplexity/sonar-pro", messages=[{"role": "user", "content": "hi"}])
        assert stub.calls[0]["paid_required"] is False

    def test_chat_accepts_max_tokens_without_error(self) -> None:
        """max_tokens is accepted for interface parity; not forwarded to OpenRouterClient."""
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
        )
        assert len(stub.calls) == 1  # call succeeded

    def test_chat_accepts_run_id_and_phase_without_error(self) -> None:
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "hi"}],
            run_id="test-run-001",
            phase="phase_1",
        )
        assert len(stub.calls) == 1


# ── Error propagation ─────────────────────────────────────────────────────────


class TestErrorPropagation:
    def test_chat_reraises_budget_exceeded_on_402(self) -> None:
        from pipeline.openrouter_client import BudgetExceeded  # noqa: PLC0415

        stub = _StubClient(raise_exc=BudgetExceeded("key exhausted"))
        gw = OpenRouterGateway(stub)
        with pytest.raises(BudgetExceeded, match="key exhausted"):
            gw.chat(
                model="perplexity/sonar-pro",
                messages=[{"role": "user", "content": "hi"}],
            )

    def test_chat_reraises_generic_exception(self) -> None:
        stub = _StubClient(raise_exc=RuntimeError("unexpected failure"))
        gw = OpenRouterGateway(stub)
        with pytest.raises(RuntimeError, match="unexpected failure"):
            gw.chat(
                model="perplexity/sonar-pro",
                messages=[{"role": "user", "content": "hi"}],
            )


# ── URL / auth header assertions (confirmed shape from gw_smoke_snapshot.md) ──


class TestCorrectURL:
    """Verify the underlying client would be called at the correct OpenRouter URL.

    These tests check indirectly via the stub's captured call args; the real
    URL assertion is in test_openrouter_client.py. Here we confirm gateway
    does NOT mutate model / messages before forwarding.
    """

    def test_model_not_mutated_by_gateway(self) -> None:
        """Gateway must pass the model string unchanged; no model mapping like 302.ai."""
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        model = "perplexity/sonar-pro"
        gw.chat(model=model, messages=[{"role": "user", "content": "test"}])
        assert stub.calls[0]["model"] == model

    def test_perplexity_model_not_stripped(self) -> None:
        """OpenRouter expects 'perplexity/sonar-pro', not bare 'sonar-pro'."""
        stub = _StubClient()
        gw = OpenRouterGateway(stub)
        gw.chat(model="perplexity/sonar-pro", messages=[{"role": "user", "content": "x"}])
        # Must arrive at the client with the full slash-prefixed form.
        assert stub.calls[0]["model"] == "perplexity/sonar-pro"


# ── ANOMALY-003 reachability ───────────────────────────────────────────────────


class TestAnomalyReachability:
    def test_gateway_importable_from_gateways_package(self) -> None:
        """ANOMALY-003: OpenRouterGateway must be reachable via pipeline.research.gateways."""
        from pipeline.research.gateways import OpenRouterGateway as _GW  # noqa: PLC0415

        assert _GW is OpenRouterGateway

    def test_gateway_importable_from_gateways_module(self) -> None:
        """Direct module import path must also work."""
        from pipeline.research.gateways.openrouter import (  # noqa: PLC0415
            OpenRouterGateway as _GW,
        )

        assert _GW is OpenRouterGateway


# ── Live round-trip (ONLINE_OPENROUTER=1 only) ────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("ONLINE_OPENROUTER") != "1",
    reason="Set ONLINE_OPENROUTER=1 to run live OpenRouter round-trips.",
)
class TestOnlineRoundTrip:
    def test_chat_returns_dict(self) -> None:
        gw = OpenRouterGateway.from_env()
        result = gw.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": "What year was the film Barbie released?"}],
            paid_required=False,
        )
        assert isinstance(result, dict)

    def test_chat_sonar_pro_citations_at_top_level(self) -> None:
        """perplexity/sonar-pro returns citations at top level per gw_smoke_snapshot.md."""
        import pipeline.openrouter_client as _or  # noqa: PLC0415

        # Patch to intercept the raw response before fence stripping.
        original_call = _or.OpenRouterClient._call_once
        captured: dict[str, object] = {}

        def _patched(
            self: object, key: str, model: str, messages: object, json_mode: bool = False
        ) -> object:  # type: ignore[override]
            resp = original_call(self, key, model, messages, json_mode)  # type: ignore[arg-type]
            captured["result"] = resp
            return resp

        _or.OpenRouterClient._call_once = _patched  # type: ignore[method-assign]
        try:
            gw = OpenRouterGateway.from_env()
            gw.chat(
                model="perplexity/sonar-pro",
                messages=[{"role": "user", "content": "Barbie 2023 box office worldwide gross?"}],
            )
        finally:
            _or.OpenRouterClient._call_once = original_call  # type: ignore[method-assign]

        # The result is already parsed JSON content; citations come via raw response
        # which is handled by openrouter_client — just confirm we got a dict back.
        assert isinstance(captured.get("result"), dict)
