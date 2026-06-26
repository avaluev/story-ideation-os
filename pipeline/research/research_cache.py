"""pipeline/research/research_cache.py — ISO-week cache for research provider calls.

Modeled on pipeline/sonar_cache.py but scoped to the research sub-package.
Cache key: (capability, gateway, model_or_op, payload_sha256, iso_week).
TTL: ISO-week boundary (≤7 days). Identical key within the same week returns
the prior result without any network call.

Cache location: runs/_cache/research/<iso_week>/<gateway_slug>/<cap_slug>__<hash16>.json

ADR-0001: all writes use pipeline.state.safe_write (atomic tmp+fsync+rename).
ADR-0007: MUST NOT import anthropic, httpx, or openrouter_client at module level.
          (httpx is allowed in pipeline/research/ per task brief, but this module
          has no HTTP needs — it is pure I/O and JSON.)
ADR-0005: MUST NOT import from frameworks/.
ADR-0003: API keys MUST NOT appear in any log or cache key — callers are
          responsible for masking; this module never touches raw keys.

MUST NOT be imported from pipeline/scoring.py (ANOMALY-001).

Integration (ANOMALY-003): imported by pipeline/research/__init__.py so the
orphan gate stays green.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, cast

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
_CACHE_DIR: Final[Path] = _REPO_ROOT / "runs" / "_cache" / "research"
_SCHEMA_VERSION: Final[str] = "1.0"
_HASH_PREFIX_LEN: Final[int] = 16
_SLUG_MAX: Final[int] = 40


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Filesystem-safe lowercase slug, max _SLUG_MAX chars."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:_SLUG_MAX] or "anon"


def _payload_sha256(payload: object) -> str:
    """Deterministic SHA-256 of an arbitrary JSON-serialisable payload."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso_week(d: date | None = None) -> str:
    """ISO-8601 week designator, e.g. '2026-W20'."""
    if d is None:
        d = date.today()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _cache_path(
    capability: str,
    gateway: str,
    model_or_op: str,
    payload_sha: str,
    iso_week: str,
) -> Path:
    """Deterministic path under the research cache directory.

    Structure:
        <cache_dir>/<iso_week>/<gateway_slug>/<cap_slug>__<model_slug>__<hash16>.json
    """
    gate_slug = _slugify(gateway)
    cap_slug = _slugify(capability)
    mod_slug = _slugify(model_or_op)
    return (
        _CACHE_DIR
        / iso_week
        / gate_slug
        / f"{cap_slug}__{mod_slug}__{payload_sha[:_HASH_PREFIX_LEN]}.json"
    )


# ---------------------------------------------------------------------------
# On-disk schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchCacheEntry:
    """One on-disk cache record. Frozen — replaces, never mutates."""

    schema_version: str
    capability: str
    gateway: str
    model_or_op: str
    payload_sha256: str
    iso_week: str
    cached_at: str
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Public read / write helpers
# ---------------------------------------------------------------------------


def load_cached(
    *,
    capability: str,
    gateway: str,
    model_or_op: str,
    payload: object,
    iso_week: str | None = None,
) -> dict[str, Any] | None:
    """Return cached result for this exact key, or None if absent/corrupt.

    Args:
        capability: Logical research capability, e.g. "chat", "search", "crawl".
        gateway: Provider gateway name, e.g. "302ai", "openrouter".
        model_or_op: Model identifier or operation name, e.g. "sonar-pro", "exa".
        payload: The full request payload (must be JSON-serialisable). Used to
            compute the payload_sha256 cache-key dimension.
        iso_week: Override the current ISO week (for testing cross-week behaviour).

    Returns:
        The cached result dict, or None on miss/corruption.
    """
    week = iso_week or _iso_week()
    sha = _payload_sha256(payload)
    path = _cache_path(capability, gateway, model_or_op, sha, week)
    if not path.exists():
        return None
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            return None
        raw = cast("dict[str, object]", parsed)
        if raw.get("schema_version") != _SCHEMA_VERSION:
            return None
        result_raw: object = raw.get("result")
        if not isinstance(result_raw, dict):
            return None
        return cast("dict[str, Any]", result_raw)
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("research_cache: unreadable entry %s: %s", path, exc)
        return None


def store(
    *,
    capability: str,
    gateway: str,
    model_or_op: str,
    payload: object,
    result: dict[str, Any],
    iso_week: str | None = None,
) -> Path:
    """Persist result under the canonical cache path via safe_write (atomic).

    Args:
        capability: Logical research capability, e.g. "chat", "search", "crawl".
        gateway: Provider gateway name, e.g. "302ai", "openrouter".
        model_or_op: Model identifier or operation name, e.g. "sonar-pro", "exa".
        payload: The full request payload; used to derive payload_sha256.
        result: The response dict to persist.
        iso_week: Override the current ISO week (for testing).

    Returns:
        Path of the written cache file.
    """
    from pipeline.state import safe_write  # noqa: PLC0415 — avoid import cycle

    week = iso_week or _iso_week()
    sha = _payload_sha256(payload)
    path = _cache_path(capability, gateway, model_or_op, sha, week)
    entry = ResearchCacheEntry(
        schema_version=_SCHEMA_VERSION,
        capability=capability,
        gateway=gateway,
        model_or_op=model_or_op,
        payload_sha256=sha,
        iso_week=week,
        cached_at=datetime.now(UTC).isoformat(),
        result=result,
    )
    safe_write(path, json.dumps(entry.__dict__, indent=2, ensure_ascii=False))
    return path


def cached_call(
    key_parts: tuple[str, str, str],
    payload: object,
    miss_fn: Callable[[], dict[str, Any]],
    *,
    iso_week: str | None = None,
) -> dict[str, Any]:
    """Return cached JSON or compute-and-store it via *miss_fn*.

    This is the primary high-level helper.  Callers pass a 3-tuple that
    identifies the request dimension, the payload (used for the hash key),
    and a zero-argument callable that performs the actual work on a miss.

    Args:
        key_parts: ``(capability, gateway, model_or_op)`` — the three
            dimensions of the cache key beyond the payload hash and ISO week.
        payload: The full request payload (JSON-serialisable). Two calls are
            considered identical when *all five key dimensions* match: the
            three parts, the deterministic sha256 of this payload, and the
            current ISO week.
        miss_fn: Called with no arguments on a cache miss. Must return a
            ``dict[str, Any]``. The result is persisted before being returned.
        iso_week: Override the current ISO week (for testing).

    Returns:
        The cached result dict (on hit) or the freshly-computed result (on miss,
        after persisting it to the cache).

    Cache miss count is 0 for identical same-week calls; cross-week calls
    always trigger miss_fn exactly once per week.
    """
    capability, gateway, model_or_op = key_parts
    week = iso_week or _iso_week()

    cached = load_cached(
        capability=capability,
        gateway=gateway,
        model_or_op=model_or_op,
        payload=payload,
        iso_week=week,
    )
    if cached is not None:
        _log.info(
            "research_cache: HIT cap=%s gw=%s op=%s week=%s",
            capability,
            gateway,
            model_or_op,
            week,
        )
        return cached

    _log.info(
        "research_cache: MISS cap=%s gw=%s op=%s — calling miss_fn",
        capability,
        gateway,
        model_or_op,
    )
    result = miss_fn()
    try:
        store(
            capability=capability,
            gateway=gateway,
            model_or_op=model_or_op,
            payload=payload,
            result=result,
            iso_week=week,
        )
    except OSError as exc:
        _log.warning("research_cache: persist failed (%s) — returning live result", exc)
    return result


def purge_older_than_weeks(weeks: int) -> int:
    """Remove cache entries older than N ISO weeks.

    Args:
        weeks: Number of weeks before the current week to treat as the cutoff.
            Entries from weeks strictly older than this cutoff are deleted.

    Returns:
        Count of JSON files removed.
    """
    if not _CACHE_DIR.exists():
        return 0
    today_week = _iso_week()
    cutoff_year, cutoff_w = (int(p) for p in today_week.replace("W", "").split("-"))
    cutoff_serial = cutoff_year * 100 + cutoff_w - weeks
    removed = 0
    for week_dir in _CACHE_DIR.iterdir():
        if not week_dir.is_dir():
            continue
        try:
            y, w = (int(p) for p in week_dir.name.replace("W", "").split("-"))
        except ValueError:
            continue
        if y * 100 + w < cutoff_serial:
            for entry_file in week_dir.rglob("*.json"):
                entry_file.unlink(missing_ok=True)
                removed += 1
    return removed


__all__ = [
    "ResearchCacheEntry",
    "cached_call",
    "load_cached",
    "purge_older_than_weeks",
    "store",
]
