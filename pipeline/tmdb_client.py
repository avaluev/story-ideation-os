"""TMDB HTTP client for offline corpus expansion.

A thin synchronous wrapper around ``httpx.Client`` that supports both auth
modes of TMDB:

- v3 API key, sent as the ``?api_key=...`` query parameter.
- v4 Read Access Token, sent as ``Authorization: Bearer ...``.

When both are configured the v4 bearer is preferred; the v3 pool is still
exposed for diagnostics and rotation-friendly fallback.

The client is **synchronous and rate-limit aware** — TMDB returns a
``429 Too Many Requests`` with a ``Retry-After`` header when a key is
throttled. This client sleeps for the indicated interval and rotates to
the next v3 key in the pool (if available), surfacing the call as a
single uninterrupted method call to the caller.

This module is offline-time tooling only — it is **not** wired into the
pipeline runtime. It does not import ``openrouter_client``, ``anthropic``,
or anything from ``frameworks/`` (per ADR-0005).

Usage::

    from pipeline.tmdb_client import TMDBClient

    with TMDBClient.from_env() as client:
        for film_id in client.iter_discover(target=3000):
            detail = client.movie_full(film_id)
            ...
"""

from __future__ import annotations

import itertools
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any, Final, cast

import httpx

from pipeline.key_manager import resolve_tmdb_bearer, resolve_tmdb_keys

_log = logging.getLogger(__name__)

_BASE_URL: Final[str] = "https://api.themoviedb.org/3"
_DEFAULT_TIMEOUT: Final[float] = 15.0
_DEFAULT_PAGE_CAP: Final[int] = 500  # TMDB hard limit is 500 pages on most endpoints.
_DEFAULT_MAX_429_RETRIES: Final[int] = 3
_DEFAULT_MAX_NETWORK_RETRIES: Final[int] = 2
_MASK_LEN: Final[int] = 8
_RETRY_AFTER_FALLBACK_S: Final[float] = 2.0

# HTTP status codes — kept as named constants for ruff PLR2004 + readability.
_HTTP_OK: Final[int] = 200
_HTTP_UNAUTHORIZED: Final[int] = 401
_HTTP_FORBIDDEN: Final[int] = 403
_HTTP_NOT_FOUND: Final[int] = 404
_HTTP_TOO_MANY_REQUESTS: Final[int] = 429
_AUTH_STATUSES: Final[frozenset[int]] = frozenset({_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN})

# Default sleep is the standard one — typed to avoid Any escape via signature.
SleepFn = Callable[[float], None]


def _mask(secret: str) -> str:
    """Return the first 8 chars of a secret followed by '...' for safe logging."""
    if len(secret) <= _MASK_LEN:
        return "***"
    return secret[:_MASK_LEN] + "..."


class TMDBError(RuntimeError):
    """Raised when TMDB returns a non-recoverable error or no auth is configured."""


class TMDBClient(AbstractContextManager["TMDBClient"]):
    """Synchronous TMDB v3 client with key rotation and 429 backoff."""

    def __init__(
        self,
        api_keys: list[str] | None = None,
        bearer: str | None = None,
        *,
        base_url: str = _BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_429_retries: int = _DEFAULT_MAX_429_RETRIES,
        max_network_retries: int = _DEFAULT_MAX_NETWORK_RETRIES,
        transport: httpx.BaseTransport | None = None,
        sleep: SleepFn = time.sleep,
    ) -> None:
        """Construct a client.

        Args:
            api_keys: TMDB v3 API keys (list, rotated round-robin). Empty list OK
                only when ``bearer`` is set.
            bearer: TMDB v4 Read Access Token. When set, used as the primary
                authentication for every request; ``api_keys`` becomes a
                fallback used only on 401/403 from the bearer call.
            base_url: TMDB API base, default ``https://api.themoviedb.org/3``.
            timeout: per-request timeout in seconds.
            max_429_retries: retries on 429 before raising. Each retry rotates
                to the next v3 key in the pool when possible.
            max_network_retries: retries on httpx.RequestError (DNS, connect,
                read timeouts) before raising.
            transport: optional pre-built transport (used by tests via
                ``httpx.MockTransport``).
            sleep: injected sleep function for deterministic tests.
        """
        self._keys: list[str] = list(api_keys or [])
        self._bearer: str | None = bearer or None
        if not self._keys and not self._bearer:
            raise TMDBError(
                "TMDBClient: no credentials configured. "
                "Set TMDB_API_KEY (or TMDB_KEY_1..N) or TMDB_READ_TOKEN."
            )

        self._base_url = base_url.rstrip("/")
        self._max_429_retries = max_429_retries
        self._max_network_retries = max_network_retries
        self._sleep = sleep
        self._key_cycle: Iterator[str] | None = itertools.cycle(self._keys) if self._keys else None

        headers: dict[str, str] = {"Accept": "application/json"}
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"

        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    # ── factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str = _BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_429_retries: int = _DEFAULT_MAX_429_RETRIES,
        max_network_retries: int = _DEFAULT_MAX_NETWORK_RETRIES,
        transport: httpx.BaseTransport | None = None,
        sleep: SleepFn = time.sleep,
    ) -> TMDBClient:
        """Build a client by reading TMDB_API_KEY / TMDB_KEY_* / TMDB_READ_TOKEN."""
        return cls(
            api_keys=resolve_tmdb_keys(),
            bearer=resolve_tmdb_bearer(),
            base_url=base_url,
            timeout=timeout,
            max_429_retries=max_429_retries,
            max_network_retries=max_network_retries,
            transport=transport,
            sleep=sleep,
        )

    # ── context manager ───────────────────────────────────────────────────────

    def close(self) -> None:
        self._http.close()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # ── auth helpers ──────────────────────────────────────────────────────────

    def _next_v3_key(self) -> str | None:
        if self._key_cycle is None:
            return None
        return next(self._key_cycle)

    def _build_params(
        self, params: dict[str, Any] | None, use_v3_key: str | None
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(params or {})
        if use_v3_key is not None:
            merged["api_key"] = use_v3_key
        return merged

    def auth_summary(self) -> dict[str, Any]:
        """Return a masked summary suitable for log diagnostics."""
        return {
            "v4_bearer": _mask(self._bearer) if self._bearer else None,
            "v3_keys": [_mask(k) for k in self._keys],
            "rotation_pool_size": len(self._keys),
        }

    # ── core request loop ─────────────────────────────────────────────────────

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET a TMDB endpoint with 429-backoff + key rotation.

        Returns the decoded JSON body on 200. Raises ``TMDBError`` on any
        terminal failure (404, 401 with no fallback, exhausted retries).
        """
        attempt = 0
        network_attempt = 0
        # Bearer is primary if present; v3 key is the fallback / rotation target.
        active_v3_key: str | None = None if self._bearer else self._next_v3_key()

        while True:
            request_params = self._build_params(params, active_v3_key)
            try:
                response = self._http.get(path, params=request_params)
            except httpx.RequestError as exc:
                network_attempt += 1
                if network_attempt > self._max_network_retries:
                    raise TMDBError(
                        f"TMDB network error on {path} after {network_attempt} attempt(s): {exc}"
                    ) from exc
                wait = _RETRY_AFTER_FALLBACK_S * network_attempt
                _log.warning(
                    "tmdb: network error on %s (%s); sleeping %.1fs before retry",
                    path,
                    type(exc).__name__,
                    wait,
                )
                self._sleep(wait)
                continue

            status = response.status_code
            if status == _HTTP_OK:
                return _safe_json(response)

            if status == _HTTP_TOO_MANY_REQUESTS:
                attempt += 1
                if attempt > self._max_429_retries:
                    raise TMDBError(
                        f"TMDB 429 exhausted after {self._max_429_retries} retries on {path}"
                    )
                wait = _parse_retry_after(response.headers.get("Retry-After"))
                _log.warning(
                    "tmdb: 429 on %s (attempt %d/%d); sleeping %.1fs and rotating key",
                    path,
                    attempt,
                    self._max_429_retries,
                    wait,
                )
                self._sleep(wait)
                # Rotate to a fresh v3 key for the retry when we have a pool.
                rotated = self._next_v3_key()
                if rotated is not None:
                    active_v3_key = rotated
                continue

            if status in _AUTH_STATUSES:
                # Bearer denied → try the v3 pool as fallback if available.
                if self._bearer and self._key_cycle is not None and active_v3_key is None:
                    _log.warning(
                        "tmdb: bearer denied (%d) on %s; falling back to v3 pool",
                        status,
                        path,
                    )
                    active_v3_key = self._next_v3_key()
                    continue
                raise TMDBError(
                    f"TMDB auth failed ({status}) on {path}: check TMDB_READ_TOKEN or TMDB_API_KEY."
                )

            if status == _HTTP_NOT_FOUND:
                raise TMDBError(f"TMDB 404 on {path}")

            # Other 4xx/5xx — surface as terminal error.
            raise TMDBError(f"TMDB unexpected status {status} on {path}: {response.text[:200]}")

    # ── high-level endpoints ──────────────────────────────────────────────────

    def list_page(
        self,
        endpoint: str,
        page: int,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch one page from a TMDB list endpoint.

        Args:
            endpoint: short path like ``"movie/top_rated"`` or ``"discover/movie"``.
            page: 1-indexed page number (TMDB max is 500).
            extra_params: additional query parameters merged into the request.
        """
        params: dict[str, Any] = {"page": page, "language": "en-US"}
        if extra_params:
            params.update(extra_params)
        return self._request(f"/{endpoint.lstrip('/')}", params=params)

    def iter_movie_ids(
        self,
        endpoint: str,
        *,
        target: int,
        page_cap: int = _DEFAULT_PAGE_CAP,
        extra_params: dict[str, Any] | None = None,
    ) -> Iterator[int]:
        """Yield up to ``target`` movie IDs from a paginated list endpoint.

        Stops at the soonest of (a) reaching ``target``, (b) hitting
        ``page_cap``, (c) reaching TMDB's reported ``total_pages``, or
        (d) receiving an empty results page.
        """
        emitted = 0
        for page in range(1, page_cap + 1):
            data = self.list_page(endpoint, page=page, extra_params=extra_params)
            raw_results = data.get("results")
            results: list[Any] = (
                cast("list[Any]", raw_results) if isinstance(raw_results, list) else []
            )
            if not results:
                return
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                entry_dict = cast("dict[str, Any]", entry)
                mid = entry_dict.get("id")
                if not isinstance(mid, int):
                    continue
                yield mid
                emitted += 1
                if emitted >= target:
                    return
            total_pages = data.get("total_pages")
            if isinstance(total_pages, int) and page >= total_pages:
                return

    def movie_full(
        self,
        movie_id: int,
        *,
        extra_append: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Fetch a movie with credits + external_ids in a single request.

        ``extra_append`` lets callers add additional sub-resources (e.g.
        ``("keywords",)`` for the v6.0 corpus-enrichment script) to the
        baseline ``append_to_response`` set without further HTTP round-trips.
        """
        base = ("credits", "external_ids", "release_dates")
        appends = ",".join((*base, *(a for a in extra_append if a)))
        return self._request(
            f"/movie/{movie_id}",
            params={
                "append_to_response": appends,
                "language": "en-US",
            },
        )

    def find_by_imdb_id(self, imdb_id: str) -> int | None:
        """Resolve an IMDb id (``ttNNNNNNN``) to a TMDB movie id, or ``None``.

        Uses the public ``/find`` endpoint with ``external_source=imdb_id``.
        Returns the first ``movie_results`` entry's ``id`` and ignores TV /
        person matches — the corpus is movie-only. Raises ``TMDBError`` for
        any non-404 transport failure; 404 / no-match returns ``None``.
        """
        if not imdb_id or not imdb_id.startswith("tt"):
            return None
        try:
            body = self._request(
                f"/find/{imdb_id}",
                params={"external_source": "imdb_id"},
            )
        except TMDBError as exc:
            if "404" in str(exc):
                return None
            raise
        movies_raw = body.get("movie_results")
        if not isinstance(movies_raw, list) or not movies_raw:
            return None
        movies = cast("list[Any]", movies_raw)
        first_any = movies[0]
        if not isinstance(first_any, dict):
            return None
        first = cast("dict[str, Any]", first_any)
        tmdb_id_raw = first.get("id")
        return tmdb_id_raw if isinstance(tmdb_id_raw, int) else None


# ── module-level helpers ─────────────────────────────────────────────────────


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    """Decode response body as JSON object; raise TMDBError on malformed body."""
    try:
        body = response.json()
    except ValueError as exc:
        raise TMDBError(f"TMDB returned non-JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise TMDBError(f"TMDB returned non-object JSON: {type(body).__name__}")
    return cast("dict[str, Any]", body)


def _parse_retry_after(raw: str | None) -> float:
    """Parse the ``Retry-After`` header, defaulting to 2 seconds.

    TMDB sends an integer number of seconds. Negative or unparseable values
    fall back to ``_RETRY_AFTER_FALLBACK_S`` so a buggy header cannot cause
    indefinite sleeps.
    """
    if not raw:
        return _RETRY_AFTER_FALLBACK_S
    try:
        secs = float(raw)
    except ValueError:
        return _RETRY_AFTER_FALLBACK_S
    if secs < 0:
        return _RETRY_AFTER_FALLBACK_S
    # Cap at 60s to avoid pathological waits from misconfigured servers.
    return min(secs, 60.0)


__all__ = [
    "TMDBClient",
    "TMDBError",
    "_parse_retry_after",
    "_safe_json",
]
