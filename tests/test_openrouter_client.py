"""Tests for pipeline/openrouter_client.py.

Covers:
    - MODELS registry exact model name pins (no stale 4.5/4 names)
    - Named constants: PLATFORM_FEE, PHASE_3_SONAR_CALL_CAP
    - 3-key FIFO rotation (free_1 → free_2 → paid cycling)
    - paid_required=True always selects PAID key regardless of rotation state
    - BudgetExceeded raised when all keys are exhausted
    - Tenacity 4-attempt retry then re-raises on persistent HTTPError
    - _mask_key masks API keys to first 8 chars + "..."
    - JSON fence stripping ("```json\\n{...}\\n```" parsed correctly)

All tests use pytest-httpx for transport-level mocking.
pytest.importorskip ensures clean SKIP if module not yet implemented.
"""

from __future__ import annotations

import json as _json
import os
from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

# Safe import — SKIP entire module if pipeline.openrouter_client not yet created.
# Tests become GREEN once Task 2 lands openrouter_client.py.
_mod = pytest.importorskip(
    "pipeline.openrouter_client",
    reason="P3 Task 2 implements; Task 1 RED stubs document the contract.",
)

OpenRouterClient = _mod.OpenRouterClient
BudgetExceeded = _mod.BudgetExceeded
MODELS = _mod.MODELS
PLATFORM_FEE = _mod.PLATFORM_FEE
PHASE_3_SONAR_CALL_CAP = _mod.PHASE_3_SONAR_CALL_CAP
DEFAULT_PHASE4_MODEL = _mod.DEFAULT_PHASE4_MODEL
_mask_key = _mod._mask_key


# ── Helpers ───────────────────────────────────────────────────────────────────

_FAKE_KEYS = {
    "OPENROUTER_KEY_PAID": "sk-or-v1-paidkey123456789",
    "OPENROUTER_KEY_FREE_1": "sk-or-v1-free1key12345",
    "OPENROUTER_KEY_FREE_2": "sk-or-v1-free2key12345",
}

_OK_RESPONSE_BODY = {"choices": [{"message": {"content": '{"asset_id": "test-1"}'}}]}

_OK_RESPONSE_BODY_FENCED = {
    "choices": [{"message": {"content": '```json\n{"asset_id": "test-1"}\n```'}}]
}


def _make_client(**env_overrides: str) -> OpenRouterClient:
    """Return an OpenRouterClient with fake keys injected via env."""
    env = {**_FAKE_KEYS, **env_overrides}
    with patch.dict(os.environ, env, clear=False):
        return OpenRouterClient()


# ── Test 1: Model name pins ───────────────────────────────────────────────────


def test_model_names() -> None:
    """MODELS dict must contain exact pinned model name strings.

    PIPE-03: sonnet-4.6 (not 4.5), opus-4.7 (not 4), haiku-4.5.
    Any deviation from these exact strings is a hard failure.
    """
    assert "anthropic/claude-sonnet-4.6" in MODELS, (
        "MODELS must contain 'anthropic/claude-sonnet-4.6' (not 4.5)"
    )
    assert "anthropic/claude-opus-4.7" in MODELS, (
        "MODELS must contain 'anthropic/claude-opus-4.7' (not 4)"
    )
    assert "anthropic/claude-haiku-4.5" in MODELS, (
        "MODELS must contain 'anthropic/claude-haiku-4.5'"
    )
    # Guard against stale names
    assert "anthropic/claude-sonnet-4.5" not in MODELS, (
        "MODELS must NOT contain 'anthropic/claude-sonnet-4.5' (stale; use 4.6)"
    )
    assert "anthropic/claude-opus-4" not in MODELS, (
        "MODELS must NOT contain 'anthropic/claude-opus-4' (stale; use 4.7)"
    )
    # Free-tier entries present (at least 2)
    free_entries = [k for k in MODELS if k.endswith(":free")]
    assert len(free_entries) >= 2, (
        f"MODELS must contain at least 2 :free entries; found {free_entries}"
    )
    # Perplexity sonar entries
    assert "perplexity/sonar" in MODELS, "MODELS must contain 'perplexity/sonar'"
    assert "perplexity/sonar-deep-research" in MODELS, (
        "MODELS must contain 'perplexity/sonar-deep-research'"
    )


# ── Test 2: Named constants ───────────────────────────────────────────────────


def test_platform_fee_constant() -> None:
    """PLATFORM_FEE must equal 1.055 and PHASE_3_SONAR_CALL_CAP must equal 10.

    These are load-bearing constants used in cost computation and sonar cap.
    """
    assert PLATFORM_FEE == 1.055, f"PLATFORM_FEE must be 1.055; got {PLATFORM_FEE}"
    assert PHASE_3_SONAR_CALL_CAP == 10, (
        f"PHASE_3_SONAR_CALL_CAP must be 10; got {PHASE_3_SONAR_CALL_CAP}"
    )
    # DEFAULT_PHASE4_MODEL must be Sonnet (ADR-0006: Opus only on two-gate promotion)
    assert DEFAULT_PHASE4_MODEL == "anthropic/claude-sonnet-4.6", (
        f"DEFAULT_PHASE4_MODEL must be 'anthropic/claude-sonnet-4.6'; got {DEFAULT_PHASE4_MODEL}"
    )


# ── Test 3: FIFO key rotation ─────────────────────────────────────────────────


def test_key_rotation_fifo(httpx_mock: HTTPXMock) -> None:
    """Three consecutive calls (paid_required=False) cycle through keys in FIFO order.

    ADR-0003: keys cycle free_1 → free_2 → paid (or paid → free_1 → free_2,
    depending on index order). The important property is that a single key is
    NOT used for all three calls — the rotation index advances each call.
    """
    client = _make_client()
    messages: list[dict[str, str]] = [{"role": "user", "content": "hello"}]

    # Track which Authorization headers are used via callbacks
    used_keys: list[str] = []

    def capture_request(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        used_keys.append(auth)
        return httpx.Response(200, json=_OK_RESPONSE_BODY)

    httpx_mock.add_callback(capture_request)
    httpx_mock.add_callback(capture_request)
    httpx_mock.add_callback(capture_request)

    client.chat("anthropic/claude-sonnet-4.6", messages, paid_required=False)
    client.chat("anthropic/claude-sonnet-4.6", messages, paid_required=False)
    client.chat("anthropic/claude-sonnet-4.6", messages, paid_required=False)

    # All 3 calls must have happened
    assert len(used_keys) == 3, f"Expected 3 calls; got {len(used_keys)}"
    # At least 2 distinct keys used (FIFO rotation in effect)
    distinct_keys = set(used_keys)
    assert len(distinct_keys) >= 2, (
        f"FIFO rotation must use at least 2 distinct keys in 3 calls; "
        f"all calls used same key: {used_keys[0]}"
    )


# ── Test 4: paid_required always uses PAID key ────────────────────────────────


def test_paid_required_always_paid(httpx_mock: HTTPXMock) -> None:
    """paid_required=True must always route to OPENROUTER_KEY_PAID.

    ADR-0003: paid key is at index 0; sonar and Phase 3 calls pass paid_required=True.
    """
    paid_key = _FAKE_KEYS["OPENROUTER_KEY_PAID"]

    captured: list[str] = []

    def capture_request(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        captured.append(auth)
        return httpx.Response(200, json=_OK_RESPONSE_BODY)

    httpx_mock.add_callback(capture_request)
    httpx_mock.add_callback(capture_request)

    client = _make_client()
    messages: list[dict[str, str]] = [{"role": "user", "content": "sonar call"}]

    client.chat("perplexity/sonar", messages, paid_required=True)
    client.chat("perplexity/sonar", messages, paid_required=True)

    for auth_header in captured:
        assert paid_key in auth_header, (
            f"paid_required=True must always use PAID key; got Authorization: {auth_header!r}"
        )


# ── Test 5: BudgetExceeded when all keys exhausted ────────────────────────────


def test_budget_exceeded_all_exhausted() -> None:
    """When all 3 KeyState entries are exhausted, chat() raises BudgetExceeded.

    No network call should be made — the check happens before the HTTP request.
    """
    client = _make_client()
    # Mark all keys as exhausted directly
    for ks in client._keys:
        ks.exhausted = True

    messages: list[dict[str, str]] = [{"role": "user", "content": "test"}]
    with pytest.raises(BudgetExceeded):
        client.chat("anthropic/claude-sonnet-4.6", messages)


# ── Test 6: Tenacity retries 4 times then re-raises ──────────────────────────


def test_tenacity_retries_4_times(httpx_mock: HTTPXMock) -> None:
    """Persistent ConnectError causes 4 attempts then raises the exception.

    tenacity stop_after_attempt(4): attempts 1..4 all fail → exception propagates.
    The mock must record 4 calls (not 3, not 5).
    """
    attempt_count = 0

    def always_fail(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        raise httpx.ConnectError("simulated network failure")

    # Add 4 callbacks (tenacity makes exactly 4 attempts)
    for _ in range(4):
        httpx_mock.add_callback(always_fail)

    client = _make_client()
    messages: list[dict[str, str]] = [{"role": "user", "content": "retry test"}]

    with pytest.raises((httpx.HTTPError, httpx.ConnectError, Exception)):
        client.chat("anthropic/claude-sonnet-4.6", messages)

    assert attempt_count == 4, (
        f"tenacity must make exactly 4 attempts before giving up; made {attempt_count}"
    )


# ── Test 7: Key masking ───────────────────────────────────────────────────────


def test_key_masked_in_logs() -> None:
    """_mask_key must return key[:8] + '...' for keys longer than 8 chars.

    SEC-07: all log lines emit only the first 8 chars of any API key.
    """
    full_key = "sk-or-v1-abcdefghijk"
    masked = _mask_key(full_key)
    assert masked == "sk-or-v1-...", (
        f"_mask_key('sk-or-v1-abcdefghijk') must return 'sk-or-v1-...'; got {masked!r}"
    )
    # Short key returned as-is (no truncation needed)
    short = "sk12345"
    assert _mask_key(short) == short, (
        f"Short key (<=8 chars) must be returned unchanged; got {_mask_key(short)!r}"
    )


# ── Test 8: JSON fence stripping ──────────────────────────────────────────────


def test_json_fence_stripping(httpx_mock: HTTPXMock) -> None:
    """Response content wrapped in ```json...``` fences must be parsed correctly.

    OpenRouter (and Claude) sometimes wraps JSON output in markdown code fences.
    The client must strip them before json.loads().
    """
    httpx_mock.add_response(json=_OK_RESPONSE_BODY_FENCED)

    client = _make_client()
    messages: list[dict[str, str]] = [{"role": "user", "content": "parse test"}]

    result = client.chat("anthropic/claude-sonnet-4.6", messages)
    assert isinstance(result, dict), f"chat() must return a dict; got {type(result)}"
    assert result.get("asset_id") == "test-1", (
        f"Fenced JSON must be parsed correctly; got {result!r}"
    )


# ── Test 9: json_mode=False omits response_format from payload ────────────────


def test_chat_json_mode_false_omits_response_format(httpx_mock: HTTPXMock) -> None:
    """chat(json_mode=False) must NOT include response_format in the request payload.

    Default behaviour (json_mode unset / False) preserves the historical wire
    format so existing call-sites are unaffected.
    """
    captured_payloads: list[dict[str, object]] = []

    def capture_request(request: httpx.Request) -> httpx.Response:

        captured_payloads.append(_json.loads(request.content))
        return httpx.Response(200, json=_OK_RESPONSE_BODY)

    httpx_mock.add_callback(capture_request)

    client = _make_client()
    client.chat(
        "anthropic/claude-sonnet-4.6",
        [{"role": "user", "content": "default"}],
        json_mode=False,
    )

    assert len(captured_payloads) == 1, "Expected exactly one HTTP call"
    payload = captured_payloads[0]
    assert "response_format" not in payload, (
        f"json_mode=False must omit response_format; got payload keys: {list(payload.keys())}"
    )


# ── Test 10: json_mode=True adds response_format to payload ──────────────────


def test_chat_json_mode_true_adds_response_format(httpx_mock: HTTPXMock) -> None:
    """chat(json_mode=True) must include {"response_format": {"type": "json_object"}}.

    OpenRouter passes response_format through to the Anthropic backend so
    Sonnet 4.6 returns valid JSON unconditionally (no prose wrappers, no fences).
    """
    captured_payloads: list[dict[str, object]] = []

    def capture_request(request: httpx.Request) -> httpx.Response:

        captured_payloads.append(_json.loads(request.content))
        return httpx.Response(200, json=_OK_RESPONSE_BODY)

    httpx_mock.add_callback(capture_request)

    client = _make_client()
    client.chat(
        "anthropic/claude-sonnet-4.6",
        [{"role": "user", "content": "json please"}],
        json_mode=True,
    )

    assert len(captured_payloads) == 1, "Expected exactly one HTTP call"
    payload = captured_payloads[0]
    assert payload.get("response_format") == {"type": "json_object"}, (
        f"json_mode=True must set response_format={{'type':'json_object'}}; "
        f"got {payload.get('response_format')!r}"
    )


# ── Test 11: json_mode=True parses JSON-mode response cleanly ────────────────


def test_chat_json_mode_response_parses_cleanly(httpx_mock: HTTPXMock) -> None:
    """A response returned under json_mode=True must round-trip through chat().

    JSON-mode responses come back as raw JSON (no markdown fences). The client
    must still parse them via the existing _strip_json_fence + json.loads path.
    """
    json_only_body = {
        "choices": [{"message": {"content": '{"high_concept_logline": "a forge test"}'}}]
    }
    httpx_mock.add_response(json=json_only_body)

    client = _make_client()
    result = client.chat(
        "anthropic/claude-sonnet-4.6",
        [{"role": "user", "content": "json only"}],
        json_mode=True,
    )
    assert isinstance(result, dict)
    assert result.get("high_concept_logline") == "a forge test", (
        f"json_mode response must parse cleanly; got {result!r}"
    )


# ── Test 12: json_mode=True omits response_format for Perplexity Sonar ───────


@pytest.mark.parametrize(
    "perplexity_model",
    [
        "perplexity/sonar",
        "perplexity/sonar-pro",
        "perplexity/sonar-pro-search",
        "perplexity/sonar-deep-research",
    ],
)
def test_chat_json_mode_true_perplexity_omits_response_format(
    httpx_mock: HTTPXMock, perplexity_model: str
) -> None:
    """Perplexity Sonar models must NOT receive response_format={"type":"json_object"}.

    Perplexity's chat-completions endpoint accepts only "text" or "json_schema"
    response_format types. Sending {"type": "json_object"} (OpenAI/Anthropic
    style) returns HTTP 400 with "json_schema: Field required". For any model id
    starting with ``perplexity/`` the client must omit response_format entirely
    and rely on prompt-level JSON constraints plus the existing fence stripper.

    This was the root cause of the NB.10 sonar-pro 400 fallback to WebSearch.
    """
    captured_payloads: list[dict[str, object]] = []

    def capture_request(request: httpx.Request) -> httpx.Response:

        captured_payloads.append(_json.loads(request.content))
        return httpx.Response(200, json=_OK_RESPONSE_BODY)

    httpx_mock.add_callback(capture_request)

    client = _make_client()
    client.chat(
        perplexity_model,
        [{"role": "user", "content": "json please"}],
        paid_required=True,
        json_mode=True,
    )

    assert len(captured_payloads) == 1, "Expected exactly one HTTP call"
    payload = captured_payloads[0]
    assert "response_format" not in payload, (
        f"Perplexity model {perplexity_model!r} under json_mode=True must omit "
        f"response_format; got payload keys: {list(payload.keys())}"
    )


def test_is_perplexity_model_predicate() -> None:
    """_is_perplexity_model classifies model ids by 'perplexity/' prefix only.

    Defensive guard: a future Anthropic or OpenAI model whose name happens to
    contain 'sonar' must not be misclassified. Only the org prefix matters.
    """
    is_pp = _mod._is_perplexity_model

    assert is_pp("perplexity/sonar") is True
    assert is_pp("perplexity/sonar-pro") is True
    assert is_pp("perplexity/sonar-pro-search") is True
    assert is_pp("perplexity/sonar-deep-research") is True

    assert is_pp("anthropic/claude-sonnet-4.6") is False
    assert is_pp("anthropic/claude-opus-4.7") is False
    assert is_pp("openai/o4-mini-deep-research") is False
    assert is_pp("meta-llama/llama-3.1-70b-instruct:free") is False
    # Hostile case: model id contains 'sonar' but org is not perplexity
    assert is_pp("acme/sonar-clone") is False


def test_malformed_envelope_retries_then_raises(httpx_mock: HTTPXMock) -> None:
    """A 200 response missing choices/message/content raises a retriable
    JSONDecodeError (regression: previously an unhandled KeyError that bypassed
    tenacity and crashed the run)."""
    attempt_count = 0

    def bad_envelope(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(200, json={"error": "no choices here"})

    for _ in range(4):
        httpx_mock.add_callback(bad_envelope)

    client = _make_client()
    with pytest.raises(_json.JSONDecodeError):
        client.chat("anthropic/claude-sonnet-4.6", [{"role": "user", "content": "x"}])
    assert attempt_count == 4, f"must retry 4x on malformed envelope; got {attempt_count}"
