"""Tests for pipeline/tmdb_client.py — auth, rotation, 429 backoff, parsing.

All requests are intercepted by ``httpx.MockTransport`` so the suite never
touches the real TMDB API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pipeline.tmdb_client import (
    TMDBClient,
    TMDBError,
    _parse_retry_after,
    _safe_json,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(body).encode("utf-8"))


def _captured_handler(
    captured: list[httpx.Request],
    response: httpx.Response,
):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response

    return handler


# ── _parse_retry_after ───────────────────────────────────────────────────────


def test_parse_retry_after_int() -> None:
    assert _parse_retry_after("5") == 5.0


def test_parse_retry_after_none_defaults_to_two() -> None:
    assert _parse_retry_after(None) == 2.0


def test_parse_retry_after_garbage_defaults_to_two() -> None:
    assert _parse_retry_after("not-a-number") == 2.0


def test_parse_retry_after_negative_defaults_to_two() -> None:
    assert _parse_retry_after("-7") == 2.0


def test_parse_retry_after_caps_at_sixty() -> None:
    assert _parse_retry_after("9999") == 60.0


# ── _safe_json ────────────────────────────────────────────────────────────────


def test_safe_json_decodes_dict() -> None:
    response = httpx.Response(200, content=b'{"id": 1, "title": "X"}')
    assert _safe_json(response) == {"id": 1, "title": "X"}


def test_safe_json_rejects_array() -> None:
    response = httpx.Response(200, content=b"[1, 2]")
    with pytest.raises(TMDBError):
        _safe_json(response)


def test_safe_json_rejects_garbage() -> None:
    response = httpx.Response(200, content=b"not json")
    with pytest.raises(TMDBError):
        _safe_json(response)


# ── construction guards ─────────────────────────────────────────────────────


def test_client_requires_some_credential() -> None:
    with pytest.raises(TMDBError):
        TMDBClient(api_keys=[], bearer=None)


def test_auth_summary_masks_secrets() -> None:
    transport = httpx.MockTransport(lambda req: _ok({"id": 1}))
    with TMDBClient(
        api_keys=["k_aaaaaaaa_long_secret_1", "k_bbbbbbbb_long_secret_2"],
        bearer="b_cccccccc_long_bearer_token",
        transport=transport,
    ) as client:
        summary = client.auth_summary()
    assert summary["rotation_pool_size"] == 2
    # Each secret should be masked — first 8 chars + ellipsis.
    assert "long_secret_1" not in str(summary)
    assert "long_bearer_token" not in str(summary)
    assert all(isinstance(k, str) and k.endswith("...") for k in summary["v3_keys"])


# ── v3 key flow ──────────────────────────────────────────────────────────────


def test_v3_key_sent_as_query_param() -> None:
    captured: list[httpx.Request] = []
    handler = _captured_handler(captured, _ok({"results": [{"id": 7}], "total_pages": 1}))
    transport = httpx.MockTransport(handler)
    with TMDBClient(api_keys=["KEY_A"], transport=transport) as client:
        client.list_page("movie/top_rated", page=1)
    assert len(captured) == 1
    assert captured[0].url.params.get("api_key") == "KEY_A"
    # Bearer absent in v3-only mode.
    assert "Authorization" not in captured[0].headers


def test_bearer_sent_as_authorization_header() -> None:
    captured: list[httpx.Request] = []
    handler = _captured_handler(captured, _ok({"id": 7}))
    transport = httpx.MockTransport(handler)
    with TMDBClient(bearer="BEARER_TOKEN", transport=transport) as client:
        client.movie_full(7)
    assert captured[0].headers.get("Authorization") == "Bearer BEARER_TOKEN"
    # v3 api_key NOT added when bearer is configured.
    assert "api_key" not in captured[0].url.params


# ── 429 + rotation ───────────────────────────────────────────────────────────


def test_429_rotates_to_next_key_then_succeeds() -> None:
    captured: list[httpx.Request] = []
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "0"}, content=b"{}"),
            _ok({"results": [], "total_pages": 1}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    transport = httpx.MockTransport(handler)
    sleeps: list[float] = []
    with TMDBClient(
        api_keys=["KEY_1", "KEY_2"],
        transport=transport,
        sleep=sleeps.append,
    ) as client:
        client.list_page("movie/top_rated", page=1)
    assert len(captured) == 2
    # First attempt used the first key in the cycle.
    assert captured[0].url.params.get("api_key") == "KEY_1"
    # Retry rotated to the next key.
    assert captured[1].url.params.get("api_key") == "KEY_2"
    # We slept once before the retry.
    assert len(sleeps) == 1


def test_429_exhausted_raises_after_max_retries() -> None:
    def always_throttle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, content=b"{}")

    transport = httpx.MockTransport(always_throttle)
    with (
        TMDBClient(
            api_keys=["KEY"],
            transport=transport,
            max_429_retries=2,
            sleep=lambda _s: None,
        ) as client,
        pytest.raises(TMDBError, match="429 exhausted"),
    ):
        client.list_page("movie/top_rated", page=1)


# ── auth fallback ─────────────────────────────────────────────────────────────


def test_bearer_401_falls_back_to_v3_pool() -> None:
    captured: list[httpx.Request] = []
    responses = iter(
        [
            httpx.Response(401, content=b"{}"),
            _ok({"results": [], "total_pages": 1}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    transport = httpx.MockTransport(handler)
    with TMDBClient(
        api_keys=["FALLBACK_KEY"],
        bearer="DEAD_BEARER",
        transport=transport,
        sleep=lambda _s: None,
    ) as client:
        client.list_page("movie/top_rated", page=1)
    # First call: bearer header, no api_key.
    assert captured[0].headers.get("Authorization") == "Bearer DEAD_BEARER"
    assert "api_key" not in captured[0].url.params
    # Retry uses the v3 fallback key.
    assert captured[1].url.params.get("api_key") == "FALLBACK_KEY"


def test_bearer_only_401_without_fallback_raises() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(401, content=b"{}"))
    with (
        TMDBClient(bearer="DEAD", transport=transport, sleep=lambda _s: None) as client,
        pytest.raises(TMDBError, match="auth failed"),
    ):
        client.list_page("movie/top_rated", page=1)


# ── 404 / unexpected status ──────────────────────────────────────────────────


def test_404_raises_terminal() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(404, content=b"{}"))
    with (
        TMDBClient(api_keys=["K"], transport=transport, sleep=lambda _s: None) as client,
        pytest.raises(TMDBError, match="404"),
    ):
        client.movie_full(99999)


def test_500_raises_terminal() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(500, content=b"server down"))
    with (
        TMDBClient(api_keys=["K"], transport=transport, sleep=lambda _s: None) as client,
        pytest.raises(TMDBError, match="unexpected status 500"),
    ):
        client.movie_full(99999)


# ── pagination ───────────────────────────────────────────────────────────────


def test_iter_movie_ids_yields_in_order_and_stops_at_target() -> None:
    pages = iter(
        [
            _ok(
                {
                    "results": [{"id": 1}, {"id": 2}, {"id": 3}],
                    "total_pages": 2,
                }
            ),
            _ok(
                {
                    "results": [{"id": 4}, {"id": 5}],
                    "total_pages": 2,
                }
            ),
        ]
    )

    def handler(_req: httpx.Request) -> httpx.Response:
        return next(pages)

    transport = httpx.MockTransport(handler)
    with TMDBClient(api_keys=["K"], transport=transport) as client:
        ids = list(client.iter_movie_ids("movie/top_rated", target=4))
    assert ids == [1, 2, 3, 4]


def test_iter_movie_ids_stops_at_total_pages() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return _ok({"results": [{"id": 1}], "total_pages": 1})

    transport = httpx.MockTransport(handler)
    with TMDBClient(api_keys=["K"], transport=transport) as client:
        ids = list(client.iter_movie_ids("movie/top_rated", target=100, page_cap=10))
    # Only one valid id available across the total pages.
    assert ids == [1]


def test_iter_movie_ids_handles_empty_results() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return _ok({"results": [], "total_pages": 1})

    transport = httpx.MockTransport(handler)
    with TMDBClient(api_keys=["K"], transport=transport) as client:
        assert list(client.iter_movie_ids("movie/top_rated", target=10)) == []


def test_iter_movie_ids_skips_malformed_entries() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return _ok(
            {
                "results": [
                    {"id": 1},
                    "not a dict",
                    {"id": "string-id"},
                    {"no_id_field": True},
                    {"id": 2},
                ],
                "total_pages": 1,
            }
        )

    transport = httpx.MockTransport(handler)
    with TMDBClient(api_keys=["K"], transport=transport) as client:
        assert list(client.iter_movie_ids("movie/top_rated", target=10)) == [1, 2]


# ── network retry ─────────────────────────────────────────────────────────────


def test_network_error_retried_then_succeeds() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("boom", request=request)
        return _ok({"id": 7})

    transport = httpx.MockTransport(handler)
    sleeps: list[float] = []
    with TMDBClient(
        api_keys=["K"],
        transport=transport,
        sleep=sleeps.append,
    ) as client:
        body = client.movie_full(7)
    assert body == {"id": 7}
    assert len(attempts) == 2
    assert len(sleeps) == 1


def test_network_error_exhausted_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    with (
        TMDBClient(
            api_keys=["K"],
            transport=transport,
            max_network_retries=1,
            sleep=lambda _s: None,
        ) as client,
        pytest.raises(TMDBError, match="network error"),
    ):
        client.movie_full(7)


# ── append_to_response ────────────────────────────────────────────────────────


def test_movie_full_requests_appended_fields() -> None:
    captured: list[httpx.Request] = []
    handler = _captured_handler(captured, _ok({"id": 7}))
    transport = httpx.MockTransport(handler)
    with TMDBClient(api_keys=["K"], transport=transport) as client:
        client.movie_full(7)
    appended = captured[0].url.params.get("append_to_response")
    assert appended == "credits,external_ids,release_dates"
