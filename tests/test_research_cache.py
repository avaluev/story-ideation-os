"""tests/test_research_cache.py — ISO-week cache for research provider calls.

Tests verify:
  - Second identical call in the same week returns cached payload with 0 misses.
  - Cross-week miss recomputes (miss_fn called again in a different iso_week).
  - Different payloads produce different cache entries.
  - Different key_parts (capability / gateway / model_or_op) produce different entries.
  - Corrupt on-disk entry treated as miss (graceful degradation).
  - store() writes a valid ResearchCacheEntry schema.
  - purge_older_than_weeks() removes old entries, spares current week.

All tests are hermetic — no live network calls; cache dir patched to tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.research import research_cache

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect _CACHE_DIR to an empty temp directory for full isolation."""
    cache_root = tmp_path / "research"
    monkeypatch.setattr(research_cache, "_CACHE_DIR", cache_root)
    return cache_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEY = ("chat", "302ai", "sonar-pro")
_PAYLOAD: dict[str, str] = {"query": "world box office 2025"}
_RESULT: dict[str, Any] = {"answer": "some cached answer", "citations": []}


def _miss_fn_factory(response: dict[str, Any]) -> tuple[list[int], Any]:
    """Return (call_counter_list, miss_fn) so callers can assert call counts."""
    calls: list[int] = []

    def _fn() -> dict[str, Any]:
        calls.append(1)
        return response

    return calls, _fn


# ---------------------------------------------------------------------------
# Core cache-hit / cache-miss semantics
# ---------------------------------------------------------------------------


def test_same_week_second_call_returns_cache_no_miss(
    _isolated_cache: Path,
) -> None:
    """Second identical call in the same ISO week must return cached payload with 0 new misses."""
    calls, miss_fn = _miss_fn_factory(_RESULT)
    week = "2026-W22"

    result1 = research_cache.cached_call(_KEY, _PAYLOAD, miss_fn, iso_week=week)
    result2 = research_cache.cached_call(_KEY, _PAYLOAD, miss_fn, iso_week=week)

    assert result1 == result2 == _RESULT
    assert len(calls) == 1, f"miss_fn should be called exactly once; got {len(calls)}"


def test_cross_week_miss_recomputes(
    _isolated_cache: Path,
) -> None:
    """Same key in a different ISO week must trigger miss_fn again (TTL boundary)."""
    calls, miss_fn = _miss_fn_factory(_RESULT)

    research_cache.cached_call(_KEY, _PAYLOAD, miss_fn, iso_week="2026-W22")
    research_cache.cached_call(_KEY, _PAYLOAD, miss_fn, iso_week="2026-W23")

    assert len(calls) == 2, (
        f"cross-week call should be a miss and invoke miss_fn; got {len(calls)} calls"
    )


# ---------------------------------------------------------------------------
# Key-dimension isolation
# ---------------------------------------------------------------------------


def test_different_payload_produces_different_entry(
    _isolated_cache: Path,
) -> None:
    """Two calls with distinct payloads under the same key_parts must each call miss_fn."""
    calls, miss_fn = _miss_fn_factory(_RESULT)
    week = "2026-W22"

    research_cache.cached_call(_KEY, {"query": "A"}, miss_fn, iso_week=week)
    research_cache.cached_call(_KEY, {"query": "B"}, miss_fn, iso_week=week)

    assert len(calls) == 2, "distinct payloads must not collide in the cache"


def test_different_capability_produces_different_entry(
    _isolated_cache: Path,
) -> None:
    """Different capability strings must be independent cache entries."""
    calls, miss_fn = _miss_fn_factory(_RESULT)
    week = "2026-W22"

    research_cache.cached_call(("chat", "302ai", "sonar-pro"), _PAYLOAD, miss_fn, iso_week=week)
    research_cache.cached_call(("search", "302ai", "sonar-pro"), _PAYLOAD, miss_fn, iso_week=week)

    assert len(calls) == 2


def test_different_gateway_produces_different_entry(
    _isolated_cache: Path,
) -> None:
    """Different gateway strings must be independent cache entries."""
    calls, miss_fn = _miss_fn_factory(_RESULT)
    week = "2026-W22"

    research_cache.cached_call(("chat", "302ai", "sonar-pro"), _PAYLOAD, miss_fn, iso_week=week)
    research_cache.cached_call(
        ("chat", "openrouter", "sonar-pro"), _PAYLOAD, miss_fn, iso_week=week
    )

    assert len(calls) == 2


def test_different_model_or_op_produces_different_entry(
    _isolated_cache: Path,
) -> None:
    """Different model_or_op strings must be independent cache entries."""
    calls, miss_fn = _miss_fn_factory(_RESULT)
    week = "2026-W22"

    research_cache.cached_call(("chat", "302ai", "sonar-pro"), _PAYLOAD, miss_fn, iso_week=week)
    research_cache.cached_call(
        ("chat", "302ai", "sonar-deep-research"), _PAYLOAD, miss_fn, iso_week=week
    )

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# store() schema validation
# ---------------------------------------------------------------------------


def test_store_writes_full_entry_schema(_isolated_cache: Path) -> None:
    """Persisted entry must contain all ResearchCacheEntry fields."""
    path = research_cache.store(
        capability="chat",
        gateway="302ai",
        model_or_op="sonar-pro",
        payload=_PAYLOAD,
        result=_RESULT,
        iso_week="2026-W22",
    )
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    for field in (
        "schema_version",
        "capability",
        "gateway",
        "model_or_op",
        "payload_sha256",
        "iso_week",
        "cached_at",
        "result",
    ):
        assert field in raw, f"missing field {field!r} in stored entry"
    assert raw["result"] == _RESULT
    assert raw["capability"] == "chat"
    assert raw["gateway"] == "302ai"
    assert raw["model_or_op"] == "sonar-pro"
    assert raw["iso_week"] == "2026-W22"


# ---------------------------------------------------------------------------
# Graceful degradation on corrupt on-disk entry
# ---------------------------------------------------------------------------


def test_load_cached_returns_none_on_corrupt_file(
    _isolated_cache: Path,
) -> None:
    """A corrupt JSON file must be treated as a cache miss, not raise."""
    # Plant a corrupt file at the canonical path.
    sha = research_cache._payload_sha256(_PAYLOAD)
    path = research_cache._cache_path("chat", "302ai", "sonar-pro", sha, "2026-W22")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json{{{", encoding="utf-8")

    result = research_cache.load_cached(
        capability="chat",
        gateway="302ai",
        model_or_op="sonar-pro",
        payload=_PAYLOAD,
        iso_week="2026-W22",
    )
    assert result is None


def test_load_cached_returns_none_on_wrong_schema_version(
    _isolated_cache: Path,
) -> None:
    """An entry with a mismatched schema_version must be treated as a miss."""
    sha = research_cache._payload_sha256(_PAYLOAD)
    path = research_cache._cache_path("chat", "302ai", "sonar-pro", sha, "2026-W22")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "99.0", "result": _RESULT}),
        encoding="utf-8",
    )

    result = research_cache.load_cached(
        capability="chat",
        gateway="302ai",
        model_or_op="sonar-pro",
        payload=_PAYLOAD,
        iso_week="2026-W22",
    )
    assert result is None


# ---------------------------------------------------------------------------
# purge_older_than_weeks
# ---------------------------------------------------------------------------


def test_purge_removes_old_entries_spares_current(_isolated_cache: Path) -> None:
    """Entries in a stale week are removed; current-week entries survive.

    Use the module's real current ISO week (not a hardcoded one) because
    ``purge_older_than_weeks`` computes the cutoff from ``_iso_week()`` against
    the system clock. Hardcoding a week made this test rot once wall-clock time
    advanced past it (it would purge the "current" entry it was meant to spare).
    """
    week = research_cache._iso_week()
    calls, miss_fn = _miss_fn_factory(_RESULT)

    # Warm the current-week cache.
    research_cache.cached_call(_KEY, _PAYLOAD, miss_fn, iso_week=week)

    # Plant a stale entry manually.
    stale_dir = _isolated_cache / "2020-W01" / "302ai"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "stale__deadbeef00000000.json").write_text("{}", encoding="utf-8")

    removed = research_cache.purge_older_than_weeks(1)
    assert removed >= 1

    # Current-week entry must still be a hit after purge (no new miss_fn call).
    research_cache.cached_call(_KEY, _PAYLOAD, miss_fn, iso_week=week)
    assert len(calls) == 1, "current-week cache must survive purge"
    assert week in {p.name for p in _isolated_cache.iterdir() if p.is_dir()}


def test_purge_returns_zero_when_cache_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """purge_older_than_weeks returns 0 when the cache directory does not exist."""
    monkeypatch.setattr(research_cache, "_CACHE_DIR", tmp_path / "nonexistent")
    assert research_cache.purge_older_than_weeks(1) == 0


# ---------------------------------------------------------------------------
# Module interface
# ---------------------------------------------------------------------------


def test_module_interface() -> None:
    """All required public symbols are exposed."""
    for name in (
        "ResearchCacheEntry",
        "cached_call",
        "load_cached",
        "purge_older_than_weeks",
        "store",
    ):
        assert hasattr(research_cache, name), f"research_cache missing {name}"
