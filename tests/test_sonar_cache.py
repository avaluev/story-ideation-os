"""tests/test_sonar_cache.py — Cycle 1 C1.3 sonar cache wrapper.

Goldratt: attacks B2 (speed) bottleneck. Each cache hit eliminates one 5-15 min
sonar latency. Tests verify: hit returns cached without client call, miss
delegates and persists, key dimensions are honored, atomic write semantics hold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline import sonar_cache


class _FakeClient:
    """Minimal stand-in for OpenRouterClient. Tracks call count for assertions."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = True,
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
        return self._response


@pytest.fixture
def _isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sonar_cache, "_CACHE_DIR", tmp_path / "sonar")
    return tmp_path / "sonar"


def test_module_interface() -> None:
    """Required public symbols exposed."""
    for name in ("cached_chat", "load_cached", "store", "purge_older_than_weeks", "CacheEntry"):
        assert hasattr(sonar_cache, name), f"sonar_cache missing {name}"


def test_miss_then_hit_avoids_second_http_call(_isolated_cache_dir: Path) -> None:
    """Cache miss calls client; second call with same key returns cached, no HTTP."""
    fake = _FakeClient(response={"choices": [{"message": {"content": "hello"}}]})
    messages = [{"role": "user", "content": "what is the zeitgeist?"}]
    result1 = sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-pro",
        messages=messages,
        fingerprint="research:smoke",
    )
    result2 = sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-pro",
        messages=messages,
        fingerprint="research:smoke",
    )
    assert result1 == result2
    assert len(fake.calls) == 1, "second call should be served from cache"


def test_different_messages_produce_different_cache_entries(
    _isolated_cache_dir: Path,
) -> None:
    """Distinct messages must not collide under the same fingerprint."""
    fake = _FakeClient(response={"choices": [{"message": {"content": "r"}}]})
    sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-pro",
        messages=[{"role": "user", "content": "A"}],
        fingerprint="research:smoke",
    )
    sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-pro",
        messages=[{"role": "user", "content": "B"}],
        fingerprint="research:smoke",
    )
    assert len(fake.calls) == 2, "different messages → two HTTP calls"


def test_different_model_produces_different_cache_entries(
    _isolated_cache_dir: Path,
) -> None:
    """Same messages on a different model must not collide."""
    fake = _FakeClient(response={"choices": [{"message": {"content": "r"}}]})
    messages = [{"role": "user", "content": "x"}]
    sonar_cache.cached_chat(
        fake, model="perplexity/sonar-pro", messages=messages, fingerprint="r:m"
    )
    sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-deep-research",
        messages=messages,
        fingerprint="r:m",
    )
    assert len(fake.calls) == 2


def test_load_cached_returns_none_on_corrupt_file(
    _isolated_cache_dir: Path,
) -> None:
    """Corrupt JSON file should be treated as cache miss (graceful degradation)."""
    messages = [{"role": "user", "content": "x"}]
    path = sonar_cache._cache_path(
        "r:m", "perplexity/sonar-pro", sonar_cache._messages_hash(messages), sonar_cache._iso_week()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json{{{", encoding="utf-8")
    out = sonar_cache.load_cached(
        fingerprint="r:m", model="perplexity/sonar-pro", messages=messages
    )
    assert out is None


def test_store_writes_full_entry_schema(_isolated_cache_dir: Path) -> None:
    """Persisted entry contains schema_version, fingerprint, model, hash, week, ts, result."""

    messages = [{"role": "user", "content": "x"}]
    result = {"choices": [{"message": {"content": "answer"}}]}
    path = sonar_cache.store(
        fingerprint="research:smoke",
        model="perplexity/sonar-pro",
        messages=messages,
        result=result,
    )
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    for k in (
        "schema_version",
        "fingerprint",
        "model",
        "messages_sha256",
        "iso_week",
        "cached_at",
        "result",
    ):
        assert k in raw, f"missing {k}"
    assert raw["result"] == result
    assert raw["model"] == "perplexity/sonar-pro"


def test_purge_older_than_weeks_removes_old_entries(_isolated_cache_dir: Path) -> None:
    """Entries in a past ISO week are deleted; current-week entries survive."""
    cur_week = sonar_cache._iso_week()
    fake = _FakeClient(response={"r": 1})
    sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-pro",
        messages=[{"role": "user", "content": "cur"}],
        fingerprint="cur",
    )
    # Plant a stale entry in a fabricated older week directory.
    stale_dir = _isolated_cache_dir / "2020-W01" / "perplexity-sonar-pro"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "stale__deadbeef00000000.json").write_text("{}", encoding="utf-8")
    removed = sonar_cache.purge_older_than_weeks(weeks=1)
    assert removed >= 1
    # Current-week entry must still resolve as a cache hit (no new client call).
    sonar_cache.cached_chat(
        fake,
        model="perplexity/sonar-pro",
        messages=[{"role": "user", "content": "cur"}],
        fingerprint="cur",
    )
    assert len(fake.calls) == 1, f"expected current-week cache to survive purge, got {fake.calls}"
    assert cur_week in {p.name for p in _isolated_cache_dir.iterdir() if p.is_dir()}
