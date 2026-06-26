"""pipeline/sonar_cache.py — Opt-in cache wrapper for sonar / sonar-deep-research calls.

Cycle 1 C1.3 — attacks B2 speed bottleneck (2-3h → ≤30 min target).
Each cache hit eliminates one 5-15 min sonar latency.

Cache key: (fingerprint, model, messages_sha256, iso_week).
TTL: ISO-week boundary (≤7 days). A re-run within the same week with the same
fingerprint + messages returns the prior result without an HTTP call.

ADR-0001: cache write uses pipeline.state.safe_write (atomic).
ADR-0007: MUST NOT import anthropic, httpx, openrouter_client directly here —
this module is called BY agents; OpenRouterClient is passed in as a parameter.
MUST NOT import from frameworks/ (ADR-0005).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, Protocol, cast

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_CACHE_DIR: Final[Path] = _REPO_ROOT / "runs" / "_cache" / "sonar"
_SCHEMA_VERSION: Final[str] = "1.0"
_HASH_PREFIX_LEN: Final[int] = 16
_SLUG_MAX: Final[int] = 40


class _ChatClient(Protocol):
    """Structural type matching OpenRouterClient.chat — duck-typed for testability."""

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = ...,
        json_mode: bool = ...,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class CacheEntry:
    """One on-disk cache record. Frozen — replaces, never mutates."""

    schema_version: str
    fingerprint: str
    model: str
    messages_sha256: str
    iso_week: str
    cached_at: str
    result: dict[str, Any]


def _slugify(text: str) -> str:
    """Filesystem-safe lowercase slug, max _SLUG_MAX chars."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:_SLUG_MAX] or "anon"


def _messages_hash(messages: list[dict[str, str]]) -> str:
    """Stable SHA-256 of the messages list (key order canonicalized)."""
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso_week(d: date | None = None) -> str:
    """ISO-8601 week designator, e.g. '2026-W20'."""
    if d is None:
        d = date.today()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _cache_path(fingerprint: str, model: str, messages_hash: str, iso_week: str) -> Path:
    """Deterministic path: <iso_week>/<model_slug>/<fingerprint_slug>__<hash16>.json."""
    return (
        _CACHE_DIR
        / iso_week
        / _slugify(model)
        / f"{_slugify(fingerprint)}__{messages_hash[:_HASH_PREFIX_LEN]}.json"
    )


def load_cached(
    *,
    fingerprint: str,
    model: str,
    messages: list[dict[str, str]],
    iso_week: str | None = None,
) -> dict[str, Any] | None:
    """Return cached result for this exact key, or None if absent/corrupt."""
    week = iso_week or _iso_week()
    path = _cache_path(fingerprint, model, _messages_hash(messages), week)
    if not path.exists():
        return None
    try:
        raw_any: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw_any, dict):
            return None
        raw = cast("dict[str, Any]", raw_any)
        if raw.get("schema_version") != _SCHEMA_VERSION:
            return None
        result_any: Any = raw.get("result")
        if not isinstance(result_any, dict):
            return None
        return cast("dict[str, Any]", result_any)
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("sonar_cache: unreadable entry %s: %s", path, exc)
        return None


def store(
    *,
    fingerprint: str,
    model: str,
    messages: list[dict[str, str]],
    result: dict[str, Any],
    iso_week: str | None = None,
) -> Path:
    """Persist result under the canonical cache path via safe_write (atomic)."""
    from pipeline.state import safe_write  # noqa: PLC0415 — avoid import cycle at module load

    week = iso_week or _iso_week()
    msg_hash = _messages_hash(messages)
    path = _cache_path(fingerprint, model, msg_hash, week)
    entry = CacheEntry(
        schema_version=_SCHEMA_VERSION,
        fingerprint=fingerprint,
        model=model,
        messages_sha256=msg_hash,
        iso_week=week,
        cached_at=datetime.now(UTC).isoformat(),
        result=result,
    )
    safe_write(path, json.dumps(entry.__dict__, indent=2, ensure_ascii=False))
    return path


def cached_chat(
    client: _ChatClient,
    *,
    model: str,
    messages: list[dict[str, str]],
    fingerprint: str,
    paid_required: bool = True,
    json_mode: bool = False,
) -> dict[str, object]:
    """Chat with cache.

    On cache hit (same fingerprint + model + messages + current ISO week): return
    the cached result without an HTTP call.

    On cache miss: delegate to client.chat(...), persist the result, return it.

    Args:
        client: Any object exposing .chat(model, messages, paid_required, json_mode).
        model: Model identifier (e.g. 'perplexity/sonar-deep-research').
        messages: Chat-completion message list.
        fingerprint: Semantic intent tag from caller. Use 'research:<slug>' for
            Phase-1 research, 'narrator:<slug>' for Phase-7 narrator, etc.
        paid_required: Forwarded to client.chat. Defaults True for sonar.
        json_mode: Forwarded to client.chat.

    Returns:
        The OpenRouter response dict (cached or freshly fetched).
    """
    cached = load_cached(fingerprint=fingerprint, model=model, messages=messages)
    if cached is not None:
        _log.info(
            "sonar_cache: HIT fingerprint=%s model=%s week=%s",
            fingerprint,
            model,
            _iso_week(),
        )
        return cached

    _log.info(
        "sonar_cache: MISS fingerprint=%s model=%s — calling client.chat",
        fingerprint,
        model,
    )
    result = client.chat(
        model=model,
        messages=messages,
        paid_required=paid_required,
        json_mode=json_mode,
    )
    # Persist for the next caller in this ISO week.
    try:
        store(fingerprint=fingerprint, model=model, messages=messages, result=result)
    except OSError as exc:
        _log.warning("sonar_cache: persist failed (%s) — returning live result", exc)
    return result


def purge_older_than_weeks(weeks: int) -> int:
    """Remove cache entries older than N ISO weeks. Returns count removed."""
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
    "CacheEntry",
    "cached_chat",
    "load_cached",
    "purge_older_than_weeks",
    "store",
]
