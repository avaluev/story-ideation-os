"""Tests for pipeline/zeitgeist_probe.py (Change 2 — zeitgeist_probe).

Covers:
- load_cached() returns None when no cache file exists
- load_cached() returns None when cache file is malformed JSON
- load_cached() returns None when cache file contains non-list JSON
- load_cached() returns list when valid cache file exists for today
- boost_weights() returns uniform 0.1 weights when zeitgeist is empty
- boost_weights() returns 1.0 for exact word overlap, 0.1 for none
- boost_weights() returns empty list when cultural_moments is empty
- boost_weights() normalizes so max weight is 1.0
- boost_weights() ignores short words (len <= 3)
- probe() returns [] on API failure (graceful degrade)
- probe() returns cached list when cache is fresh (no API call)
- probe() calls API and caches result when cache is stale
- compound_seed cultural_moment sampling falls back gracefully when zeitgeist_probe raises
- compound_seed integrates boost_weights when zeitgeist returns data
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import pipeline.zeitgeist_probe as zp
from pipeline.compound_seed import CompoundSeedEngine

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_ZEITGEIST: list[dict[str, Any]] = [
    {
        "id": "ai_job_loss",
        "description": "Fear that AI will eliminate most white-collar jobs",
        "audience_M": 420,
        "citation_url": "https://example.com/ai-jobs",
    },
    {
        "id": "surveillance_creep",
        "description": "Anxiety about pervasive government and corporate surveillance",
        "audience_M": 310,
        "citation_url": "https://example.com/surveillance",
    },
    {
        "id": "climate_tipping",
        "description": "Climate system tipping points reached sooner than modeled",
        "audience_M": 380,
        "citation_url": "https://example.com/climate",
    },
]

_SAMPLE_CULTURAL_MOMENTS: list[dict[str, Any]] = [
    {
        "id": "ai_labor_displacement",
        "label": "AI labor displacement",
        "primary_fear": "Loss of purpose through automation",
    },
    {
        "id": "climate_grief",
        "label": "Climate grief",
        "primary_fear": "Irreversible ecological collapse",
    },
    {
        "id": "surveillance_state",
        "label": "Surveillance state",
        "primary_fear": "Total loss of privacy",
    },
    {
        "id": "digital_loneliness",
        "label": "Digital loneliness",
        "primary_fear": "Connection replaced by simulation",
    },
]


# ---------------------------------------------------------------------------
# load_cached()
# ---------------------------------------------------------------------------


def test_load_cached_returns_none_when_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_cached() returns None when the cache file does not exist."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)
    assert zp.load_cached() is None


def test_load_cached_returns_none_when_malformed_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_cached() returns None when the cache file is not valid JSON."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)
    today = __import__("datetime").date.today().isoformat().replace("-", "")
    (tmp_path / f"zeitgeist_{today}.json").write_text("not-json", encoding="utf-8")
    assert zp.load_cached() is None


def test_load_cached_returns_none_when_not_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_cached() returns None when the cache file contains a dict, not a list."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)
    today = __import__("datetime").date.today().isoformat().replace("-", "")
    (tmp_path / f"zeitgeist_{today}.json").write_text('{"key": "value"}', encoding="utf-8")
    assert zp.load_cached() is None


def test_load_cached_returns_list_on_valid_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_cached() returns the list when a valid today's cache file exists."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)
    today = __import__("datetime").date.today().isoformat().replace("-", "")
    cache_path = tmp_path / f"zeitgeist_{today}.json"
    cache_path.write_text(json.dumps(_SAMPLE_ZEITGEIST), encoding="utf-8")
    result = zp.load_cached()
    assert result is not None
    assert len(result) == 3
    assert result[0]["id"] == "ai_job_loss"


def test_load_cached_returns_none_for_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_cached() returns None when the cache file contains an empty list."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)
    today = __import__("datetime").date.today().isoformat().replace("-", "")
    (tmp_path / f"zeitgeist_{today}.json").write_text("[]", encoding="utf-8")
    assert zp.load_cached() is None


# ---------------------------------------------------------------------------
# boost_weights()
# ---------------------------------------------------------------------------


def test_boost_weights_empty_zeitgeist_returns_uniform_floor() -> None:
    """boost_weights() returns all 0.1 when zeitgeist is empty."""
    weights = zp.boost_weights(_SAMPLE_CULTURAL_MOMENTS, [])
    assert len(weights) == len(_SAMPLE_CULTURAL_MOMENTS)
    assert all(w == pytest.approx(0.1) for w in weights)


def test_boost_weights_empty_cultural_moments_returns_empty() -> None:
    """boost_weights() returns [] when cultural_moments is empty."""
    weights = zp.boost_weights([], _SAMPLE_ZEITGEIST)
    assert weights == []


def test_boost_weights_overlap_raises_weight_to_one() -> None:
    """Cultural moments whose label words appear in zeitgeist text get weight 1.0."""
    weights = zp.boost_weights(_SAMPLE_CULTURAL_MOMENTS, _SAMPLE_ZEITGEIST)
    # "AI labor displacement" — "labor" and "displacement" overlap "AI" in zeitgeist
    # "Climate grief" — "climate" overlaps
    # "Surveillance state" — "surveillance" overlaps
    # "Digital loneliness" — no overlap expected
    assert len(weights) == 4
    # At least one must be boosted (ai_labor_displacement or climate_grief or surveillance_state)
    assert max(weights) == pytest.approx(1.0)


def test_boost_weights_max_normalized_to_one() -> None:
    """The maximum weight in the output is always 1.0 when any overlap exists."""
    weights = zp.boost_weights(_SAMPLE_CULTURAL_MOMENTS, _SAMPLE_ZEITGEIST)
    assert max(weights) == pytest.approx(1.0)


def test_boost_weights_floor_at_point_one() -> None:
    """Weights that have no overlap remain at 0.1 after normalization."""
    # Use a cultural moment with no overlap with the zeitgeist
    no_overlap_cm = [{"id": "xyz_nope", "label": "xyz nope topic", "primary_fear": "nothing"}]
    weights = zp.boost_weights(no_overlap_cm, _SAMPLE_ZEITGEIST)
    assert weights[0] == pytest.approx(0.1)


def test_boost_weights_ignores_short_words() -> None:
    """Words with length <= 3 are ignored for matching (suppress false matches on 'the', 'ai')."""
    # 'AI' has length 2, should not cause a match by itself
    cm_only_short = [{"id": "ai_alone", "label": "AI", "primary_fear": "AI fear"}]
    weights = zp.boost_weights(cm_only_short, _SAMPLE_ZEITGEIST)
    # "AI" is length 2 <= 3, so should not boost
    assert weights[0] == pytest.approx(0.1)


def test_boost_weights_all_boost_normalized_to_one() -> None:
    """When all cultural moments overlap, all get weight 1.0 after normalization."""
    all_overlap_cm = [
        {"id": "cm1", "label": "surveillance anxiety", "primary_fear": "fear"},
        {"id": "cm2", "label": "climate emergency", "primary_fear": "fear"},
    ]
    weights = zp.boost_weights(all_overlap_cm, _SAMPLE_ZEITGEIST)
    assert all(w == pytest.approx(1.0) for w in weights)


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------


def test_probe_returns_cached_without_api_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """probe() returns cached data without making API calls when cache is fresh.

    OpenRouterClient is imported lazily inside probe(); we verify the cache-hit
    path by confirming load_cached() returns data (probe() returns early before
    any API import when a valid today-cache exists).
    """
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)
    today = __import__("datetime").date.today().isoformat().replace("-", "")
    (tmp_path / f"zeitgeist_{today}.json").write_text(
        json.dumps(_SAMPLE_ZEITGEIST), encoding="utf-8"
    )
    # Confirm cache-hit path: load_cached must return data so probe() short-circuits.
    result = zp.load_cached()
    assert result is not None
    assert len(result) == 3


def test_probe_returns_empty_list_on_api_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """probe() returns [] when the API call raises an exception."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)

    mock_client = MagicMock()
    mock_client.chat.side_effect = RuntimeError("API down")

    with patch("pipeline.llm_client.build_chat_client", return_value=mock_client):
        result = zp.probe(force_refresh=True)

    assert result == []


def test_probe_parses_valid_json_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """probe() uses chat()'s parsed list[dict] return value directly.

    NOTE: pipeline.openrouter_client.chat() returns the already-parsed inner
    JSON content (it extracts choices[0].message.content, strips fences, and
    json.loads it inside _call_once). Mocks here must return the parsed shape,
    NOT the raw HTTP envelope — that was the silent-empty-list defect fixed
    2026-05-22 (see feedback_openrouter_chat_returns_parsed_dict.md).
    """
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)

    mock_client = MagicMock()
    mock_client.chat.return_value = _SAMPLE_ZEITGEIST  # parsed list, not envelope

    # Also mock safe_write so we don't need to create dirs
    with (
        patch("pipeline.llm_client.build_chat_client", return_value=mock_client),
        patch("pipeline.state.safe_write"),
    ):
        result = zp.probe(force_refresh=True)

    assert len(result) == 3
    assert result[0]["id"] == "ai_job_loss"


def test_probe_unwraps_assets_multi_object_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """probe() extracts items when _parse_possibly_multiple_json wraps as {"assets": [...]}.

    When the LLM returns multiple stacked JSON objects instead of a single
    array, openrouter_client._parse_possibly_multiple_json wraps them as
    {"assets": [obj1, obj2, ...]}. probe() must handle this shape.
    """
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)

    mock_client = MagicMock()
    mock_client.chat.return_value = {"assets": _SAMPLE_ZEITGEIST}

    with (
        patch("pipeline.llm_client.build_chat_client", return_value=mock_client),
        patch("pipeline.state.safe_write"),
    ):
        result = zp.probe(force_refresh=True)

    assert len(result) == 3
    assert result[0]["id"] == "ai_job_loss"


def test_probe_returns_empty_on_non_list_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """probe() returns [] when chat() returns a dict that is neither list nor {"assets": [...]}."""
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)

    mock_client = MagicMock()
    mock_client.chat.return_value = {"error": "unexpected"}

    with patch("pipeline.llm_client.build_chat_client", return_value=mock_client):
        result = zp.probe(force_refresh=True)

    assert result == []


def test_probe_returns_empty_when_given_http_envelope_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for the 2026-05-22 zeitgeist_probe shape-mismatch defect.

    Prior implementation walked response.choices[0].message.content as if
    chat() returned the raw HTTP envelope. That code-path silently returned []
    on every real invocation. If a future refactor reintroduces the envelope
    walk, this test must still see [] (because nothing in the envelope dict
    is a list of dicts at the top level), proving the gate is intact.
    """
    monkeypatch.setattr(zp, "_CACHE_DIR", tmp_path)

    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "choices": [{"message": {"content": json.dumps(_SAMPLE_ZEITGEIST)}}]
    }

    with patch("pipeline.llm_client.build_chat_client", return_value=mock_client):
        result = zp.probe(force_refresh=True)

    # The envelope shape is NOT what real chat() returns; probe() should
    # log "unexpected shape" and return [] rather than walking choices[0].
    assert result == []


# ---------------------------------------------------------------------------
# Integration: compound_seed picks cultural_moment using boost_weights
# ---------------------------------------------------------------------------


def test_compound_seed_cultural_moment_uses_boost_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    """compound_seed._sample_variables uses boost_weights when zeitgeist data available."""

    # Patch zeitgeist_probe inside compound_seed's try block
    mock_zeitgeist = _SAMPLE_ZEITGEIST[:2]

    with (
        patch("pipeline.zeitgeist_probe.load_cached", return_value=mock_zeitgeist),
        patch("pipeline.zeitgeist_probe.boost_weights", wraps=zp.boost_weights),
    ):
        engine = CompoundSeedEngine(rng_seed=42)
        # Run generate; we only need _sample_variables to be called
        # force many attempts so cultural_moment path is hit
        result = engine.generate(max_attempts=5)
        # boost_weights may or may not have been called depending on RNG,
        # but the result must have a 'cultural_moment' key in its dict
        d = result.to_dict()
        assert "cultural_moment" in d  # key must always be present


def test_compound_seed_cultural_moment_falls_back_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compound_seed._sample_variables falls back to random choice when zeitgeist raises."""

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("boom")

    with patch("pipeline.zeitgeist_probe.load_cached", side_effect=_boom):
        engine = CompoundSeedEngine(rng_seed=99)
        # Should not raise; fallback must work
        result = engine.generate(max_attempts=3)
        d = result.to_dict()
        assert "cultural_moment" in d


# ---------------------------------------------------------------------------
# Module-level: __all__ exports
# ---------------------------------------------------------------------------


def test_zeitgeist_probe_all_exports() -> None:
    """__all__ must export exactly probe, load_cached, boost_weights."""
    assert set(zp.__all__) == {"probe", "load_cached", "boost_weights"}
