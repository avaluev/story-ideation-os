"""tests/test_research_dispatch_narrator.py — NB.2 Phase-7 narrator wiring.

Adds ``fetch_market_for_concept`` to mirror the Phase-1 pattern: a single
SKILL-callable that derives ``primary_genre`` from the run's draft_v0 sidecar
and invokes :func:`pipeline.research_dispatch.fetch_market_sizing`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline import research_dispatch, sonar_cache


class _FakeClient:
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
        self.calls.append({"model": model, "messages": messages, "json_mode": json_mode})
        return self._response


@pytest.fixture
def _isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sonar_cache, "_CACHE_DIR", tmp_path / "sonar")
    return tmp_path / "sonar"


def test_fetch_market_for_concept_is_exported() -> None:
    assert hasattr(research_dispatch, "fetch_market_for_concept")


def test_fetch_market_for_concept_reads_primary_genre_from_draft_v0(
    tmp_path: Path, _isolated_cache_dir: Path
) -> None:
    """Reads draft_v0.json, extracts primary_genre, dispatches market sizing."""
    draft = {"primary_genre": "techno-thriller", "logline": "..."}
    (tmp_path / "draft_v0.json").write_text(json.dumps(draft), encoding="utf-8")

    fake = _FakeClient({"choices": [{"message": {"content": '{"tam_usd": 1000000}'}}]})
    result = research_dispatch.fetch_market_for_concept(
        run_dir=tmp_path,
        theme_slug="the-quota",
        client=fake,
    )
    assert result == {"choices": [{"message": {"content": '{"tam_usd": 1000000}'}}]}
    assert (tmp_path / research_dispatch.MARKET_SIZING_FILENAME).exists()
    # Cache key embeds genre — confirm via the underlying call.
    assert len(fake.calls) == 1
    body = fake.calls[0]["messages"][0]["content"]
    assert "techno-thriller" in body


def test_fetch_market_for_concept_caches_on_repeat(
    tmp_path: Path, _isolated_cache_dir: Path
) -> None:
    """Second call with same draft_v0 hits the cache (no second HTTP call)."""
    draft = {"primary_genre": "horror", "logline": "..."}
    (tmp_path / "draft_v0.json").write_text(json.dumps(draft), encoding="utf-8")
    fake = _FakeClient({"choices": [{"message": {"content": "{}"}}]})

    research_dispatch.fetch_market_for_concept(run_dir=tmp_path, theme_slug="x", client=fake)
    research_dispatch.fetch_market_for_concept(run_dir=tmp_path, theme_slug="x", client=fake)
    assert len(fake.calls) == 1


def test_fetch_market_for_concept_missing_draft_raises(tmp_path: Path) -> None:
    """No draft_v0.json — explicit FileNotFoundError so the skill can soft-fail."""
    with pytest.raises(FileNotFoundError):
        research_dispatch.fetch_market_for_concept(
            run_dir=tmp_path, theme_slug="x", client=_FakeClient({})
        )


def test_fetch_market_for_concept_missing_genre_uses_drama_default(
    tmp_path: Path, _isolated_cache_dir: Path
) -> None:
    """If primary_genre is missing from draft_v0, fall back to 'drama' (graceful)."""
    (tmp_path / "draft_v0.json").write_text(json.dumps({"logline": "..."}), encoding="utf-8")
    fake = _FakeClient({"choices": [{"message": {"content": "{}"}}]})
    research_dispatch.fetch_market_for_concept(run_dir=tmp_path, theme_slug="x", client=fake)
    body = fake.calls[0]["messages"][0]["content"]
    assert "drama" in body.lower()
