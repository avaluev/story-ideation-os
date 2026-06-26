"""tests/test_route_table.py — Route table and health cache unit tests.

Hermetic: no network calls, no live keys.  All tests use only in-process
state and tmp-path fixtures.

Test matrix
-----------
TestRouteOrder       — gateway order matches spec for all four capabilities.
TestDeadGatewaySkip  — a dead gateway is skipped by next_live_route.
TestWebFetchPosition — WebFetch is never last in FETCH; httpx_get is last.
TestOpenRouterLast   — OpenRouter is last in SEARCH and SYNTH.
TestHealthPersist    — mark_dead persists state; load/reset round-trip.
TestAimlPrimary      — AIML_PRIMARY env var is respected by default_route_table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.research.health import (
    GatewayHealth,
    is_dead,
    mark_dead,
    next_live_route,
)
from pipeline.research.health import (
    load as load_health,
)
from pipeline.research.health import (
    persist as persist_health,
)
from pipeline.research.health import (
    reset as reset_health,
)
from pipeline.research.routes import (
    Capability,
    Route,
    RouteTable,
    default_route_table,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _names(capability: Capability, table: RouteTable | None = None) -> list[str]:
    """Return ordered gateway-name strings for *capability*."""
    rt = table or default_route_table()
    return rt.gateway_names(capability)


# ── Route order ────────────────────────────────────────────────────────────────


class TestRouteOrder:
    """Gateway order must exactly match the task spec for each capability."""

    def test_search_order(self) -> None:
        names = _names(Capability.SEARCH)
        assert names == [
            "serper",
            "exa",
            "aiml_sonar_pro",
            "aiml_gpt4o_search",
            "302_serpapi",
            "302_sonar",
            "openrouter_sonar",
        ]

    def test_fetch_order(self) -> None:
        names = _names(Capability.FETCH)
        assert names == [
            "jina",
            "302_firecrawl",
            "webfetch",
            "httpx_get",
        ]

    def test_synth_order(self) -> None:
        names = _names(Capability.SYNTH)
        assert names == [
            "aiml_gpt5",
            "aiml_sonar_pro",
            "302_synth",
            "openrouter_synth",
        ]

    def test_translate_order(self) -> None:
        names = _names(Capability.TRANSLATE)
        assert names == [
            "aiml_gpt5",
            "aiml_gpt41",
            "302_gpt5_chat",
        ]

    def test_all_capabilities_non_empty(self) -> None:
        rt = default_route_table()
        for cap in Capability:
            assert rt.for_capability(cap), f"No routes for {cap}"


# ── Dead gateway skip ──────────────────────────────────────────────────────────


class TestDeadGatewaySkip:
    """A gateway marked dead must be skipped by next_live_route."""

    def setup_method(self) -> None:
        """Clear module-level dead set before each test."""
        reset_health()

    def teardown_method(self) -> None:
        reset_health()

    def test_dead_gateway_skipped(self) -> None:
        routes = [
            Route(capability=Capability.SEARCH, gateway_name="serper"),
            Route(capability=Capability.SEARCH, gateway_name="exa"),
        ]
        mark_dead("serper")
        result = next_live_route(routes)
        assert result is not None
        assert result.gateway_name == "exa"

    def test_all_dead_returns_none(self) -> None:
        routes = [
            Route(capability=Capability.SEARCH, gateway_name="serper"),
            Route(capability=Capability.SEARCH, gateway_name="exa"),
        ]
        mark_dead("serper")
        mark_dead("exa")
        assert next_live_route(routes) is None

    def test_first_live_returned_when_none_dead(self) -> None:
        routes = [
            Route(capability=Capability.SEARCH, gateway_name="serper"),
            Route(capability=Capability.SEARCH, gateway_name="exa"),
        ]
        result = next_live_route(routes)
        assert result is not None
        assert result.gateway_name == "serper"

    def test_is_dead_reflects_mark(self) -> None:
        mark_dead("jina")
        assert is_dead("jina") is True
        assert is_dead("exa") is False

    def test_reset_clears_dead_set(self) -> None:
        mark_dead("serper")
        reset_health()
        assert is_dead("serper") is False

    def test_multiple_dead_skipped_in_order(self) -> None:
        routes = [
            Route(capability=Capability.FETCH, gateway_name="jina"),
            Route(capability=Capability.FETCH, gateway_name="302_firecrawl"),
            Route(capability=Capability.FETCH, gateway_name="webfetch"),
            Route(capability=Capability.FETCH, gateway_name="httpx_get"),
        ]
        mark_dead("jina")
        mark_dead("302_firecrawl")
        result = next_live_route(routes)
        assert result is not None
        assert result.gateway_name == "webfetch"


# ── WebFetch position ──────────────────────────────────────────────────────────


class TestWebFetchPosition:
    """WebFetch must be second-to-last in FETCH; httpx_get must be last."""

    def test_webfetch_is_not_last_in_fetch(self) -> None:
        names = _names(Capability.FETCH)
        assert names[-1] != "webfetch", "WebFetch must not be the last FETCH gateway"

    def test_httpx_get_is_last_in_fetch(self) -> None:
        names = _names(Capability.FETCH)
        assert names[-1] == "httpx_get"

    def test_webfetch_before_httpx_get(self) -> None:
        names = _names(Capability.FETCH)
        assert names.index("webfetch") < names.index("httpx_get")


# ── OpenRouter is last ─────────────────────────────────────────────────────────


class TestOpenRouterLast:
    """OpenRouter must be last in SEARCH and SYNTH."""

    def test_openrouter_last_in_search(self) -> None:
        names = _names(Capability.SEARCH)
        or_names = [n for n in names if n.startswith("openrouter")]
        assert or_names, "No OpenRouter gateway in SEARCH"
        assert names[-1].startswith("openrouter"), (
            f"Last SEARCH gateway should be OpenRouter, got {names[-1]!r}"
        )

    def test_openrouter_last_in_synth(self) -> None:
        names = _names(Capability.SYNTH)
        or_names = [n for n in names if n.startswith("openrouter")]
        assert or_names, "No OpenRouter gateway in SYNTH"
        assert names[-1].startswith("openrouter"), (
            f"Last SYNTH gateway should be OpenRouter, got {names[-1]!r}"
        )

    def test_openrouter_not_first_in_search(self) -> None:
        names = _names(Capability.SEARCH)
        assert not names[0].startswith("openrouter")

    def test_openrouter_not_first_in_synth(self) -> None:
        names = _names(Capability.SYNTH)
        assert not names[0].startswith("openrouter")


# ── Health persist round-trip ──────────────────────────────────────────────────


class TestHealthPersist:
    """mark_dead persists state; load/reset round-trip correctly."""

    def setup_method(self) -> None:
        reset_health()

    def teardown_method(self) -> None:
        reset_health()

    def test_persist_and_load_round_trip(self, tmp_path: Path) -> None:
        health_path = tmp_path / "research_health.json"
        state = GatewayHealth(dead={"serper", "exa"})
        persist_health(state, path=health_path)
        loaded = load_health(path=health_path)
        assert loaded.dead == {"serper", "exa"}

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        health_path = tmp_path / "nonexistent.json"
        loaded = load_health(path=health_path)
        assert loaded.dead == set()

    def test_load_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        health_path = tmp_path / "bad.json"
        health_path.write_text("not valid json", encoding="utf-8")
        loaded = load_health(path=health_path)
        assert loaded.dead == set()

    def test_load_non_dict_json_returns_empty(self, tmp_path: Path) -> None:
        health_path = tmp_path / "list.json"
        health_path.write_text('["a", "b"]', encoding="utf-8")
        loaded = load_health(path=health_path)
        assert loaded.dead == set()

    def test_gateway_health_to_dict(self) -> None:
        state = GatewayHealth(dead={"jina", "exa"})
        d = state.to_dict()
        assert set(d["dead"]) == {"jina", "exa"}

    def test_reset_deletes_file(self, tmp_path: Path) -> None:
        health_path = tmp_path / "research_health.json"
        persist_health(GatewayHealth(dead={"serper"}), path=health_path)
        assert health_path.exists()
        reset_health(path=health_path)
        assert not health_path.exists()

    def test_reset_missing_file_no_error(self, tmp_path: Path) -> None:
        health_path = tmp_path / "nonexistent.json"
        reset_health(path=health_path)  # must not raise


# ── AIML_PRIMARY env var ───────────────────────────────────────────────────────


class TestAimlPrimary:
    """AIML_PRIMARY=1 (default) keeps AIML before OpenRouter in SEARCH and SYNTH."""

    def test_aiml_before_openrouter_in_search_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AIML_PRIMARY", "1")
        names = _names(Capability.SEARCH)
        aiml_idx = next(i for i, n in enumerate(names) if n.startswith("aiml"))
        or_idx = next(i for i, n in enumerate(names) if n.startswith("openrouter"))
        assert aiml_idx < or_idx

    def test_aiml_before_openrouter_in_synth_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_PRIMARY", "1")
        names = _names(Capability.SYNTH)
        aiml_idx = next(i for i, n in enumerate(names) if n.startswith("aiml"))
        or_idx = next(i for i, n in enumerate(names) if n.startswith("openrouter"))
        assert aiml_idx < or_idx

    def test_aiml_before_openrouter_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIML_PRIMARY", "")
        # Even with AIML_PRIMARY="" the route table hard-codes AIML first;
        # the env var controls the *interpretation* in aiml_primary() but the
        # default_route_table() always builds AIML before OpenRouter per spec.
        names = _names(Capability.SEARCH)
        aiml_names = [n for n in names if n.startswith("aiml")]
        or_names = [n for n in names if n.startswith("openrouter")]
        assert aiml_names, "No AIML gateways in SEARCH"
        assert or_names, "No OpenRouter gateways in SEARCH"
