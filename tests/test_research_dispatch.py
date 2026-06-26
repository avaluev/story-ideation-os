"""tests/test_research_dispatch.py — Cycle 1 Option A.

Verifies the Python research dispatcher:
- Routes through sonar_cache.cached_chat (so cache hits skip HTTP).
- Writes structured JSON sidecars into run_dir.
- Honors model selection (sonar-pro vs sonar-deep-research).
- Distinct themes / genres produce distinct cache keys.
- AIML -> 302 -> OpenRouter fallback chain ordering (ADR-0007).
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


def test_module_interface() -> None:
    for name in (
        "fetch_research_evidence",
        "fetch_research_for_theme",
        "fetch_market_sizing",
        "RESEARCH_EVIDENCE_FILENAME",
        "MARKET_SIZING_FILENAME",
    ):
        assert hasattr(research_dispatch, name)


def test_fetch_research_for_theme_writes_sidecar(tmp_path: Path, _isolated_cache_dir: Path) -> None:
    """Theme-only entry point: callable with just (run_dir, slug, theme_text)."""
    expected = {"inferred": {"primary_genre": "drama"}, "audience_evidence": {}}
    fake = _FakeClient(response=expected)
    result = research_dispatch.fetch_research_for_theme(
        run_dir=tmp_path,
        theme_slug="the-quota",
        theme_text="A disgraced public defender takes a final case to clear her name.",
        client=fake,
    )
    assert result == expected
    sidecar = tmp_path / research_dispatch.RESEARCH_EVIDENCE_FILENAME
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == expected
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "perplexity/sonar-pro"
    assert fake.calls[0]["json_mode"] is True


def test_fetch_research_for_theme_caches_on_repeat(
    tmp_path: Path, _isolated_cache_dir: Path
) -> None:
    """Same theme_slug + theme_text within ISO week → second call hits cache."""
    fake = _FakeClient(response={"inferred": {}})
    research_dispatch.fetch_research_for_theme(
        run_dir=tmp_path / "a",
        theme_slug="the-quota",
        theme_text="A defender takes a case.",
        client=fake,
    )
    research_dispatch.fetch_research_for_theme(
        run_dir=tmp_path / "b",
        theme_slug="the-quota",
        theme_text="A defender takes a case.",
        client=fake,
    )
    assert len(fake.calls) == 1


def test_fetch_research_writes_sidecar(tmp_path: Path, _isolated_cache_dir: Path) -> None:
    expected = {"genre_saturation": {"status": "VERIFIED", "examples": []}}
    fake = _FakeClient(response=expected)
    result = research_dispatch.fetch_research_evidence(
        run_dir=tmp_path,
        theme_slug="the-quota",
        primary_genre="legal-thriller",
        premise_type="institutional whistleblower",
        cultural_claim="trust in courts is declining",
        audience_demographic="working professionals 25-54",
        client=fake,
    )
    assert result == expected
    sidecar = tmp_path / research_dispatch.RESEARCH_EVIDENCE_FILENAME
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == expected
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "perplexity/sonar-pro"
    assert fake.calls[0]["json_mode"] is True


def test_fetch_market_writes_sidecar(tmp_path: Path, _isolated_cache_dir: Path) -> None:
    expected = {"total_subscribers_m": 850.0, "genre_share_pct": 12.0}
    fake = _FakeClient(response=expected)
    result = research_dispatch.fetch_market_sizing(
        run_dir=tmp_path,
        theme_slug="the-quota",
        primary_genre="legal-thriller",
        client=fake,
    )
    assert result == expected
    sidecar = tmp_path / research_dispatch.MARKET_SIZING_FILENAME
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == expected
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "perplexity/sonar-deep-research"


def test_second_call_same_inputs_hits_cache(tmp_path: Path, _isolated_cache_dir: Path) -> None:
    """Same fingerprint + messages within ISO week → no second HTTP call."""
    fake = _FakeClient(response={"genre_saturation": {"status": "VERIFIED"}})
    research_dispatch.fetch_research_evidence(
        run_dir=tmp_path,
        theme_slug="the-quota",
        primary_genre="legal-thriller",
        premise_type="institutional whistleblower",
        cultural_claim="declining trust",
        audience_demographic="adults",
        client=fake,
    )
    research_dispatch.fetch_research_evidence(
        run_dir=tmp_path / "second_run",
        theme_slug="the-quota",
        primary_genre="legal-thriller",
        premise_type="institutional whistleblower",
        cultural_claim="declining trust",
        audience_demographic="adults",
        client=fake,
    )
    assert len(fake.calls) == 1, "second call within ISO week must hit cache"


def test_distinct_themes_produce_distinct_cache_entries(
    tmp_path: Path, _isolated_cache_dir: Path
) -> None:
    fake = _FakeClient(response={"genre_saturation": {"status": "VERIFIED"}})
    research_dispatch.fetch_research_evidence(
        run_dir=tmp_path / "a",
        theme_slug="theme-a",
        primary_genre="thriller",
        premise_type="x",
        cultural_claim="y",
        audience_demographic="z",
        client=fake,
    )
    research_dispatch.fetch_research_evidence(
        run_dir=tmp_path / "b",
        theme_slug="theme-b",
        primary_genre="thriller",
        premise_type="x",
        cultural_claim="y",
        audience_demographic="z",
        client=fake,
    )
    assert len(fake.calls) == 2


def test_distinct_phases_produce_distinct_cache_entries(
    tmp_path: Path, _isolated_cache_dir: Path
) -> None:
    """research vs market fingerprints + different models → never collide."""
    fake = _FakeClient(response={"total_subscribers_m": 1.0})
    research_dispatch.fetch_research_evidence(
        run_dir=tmp_path / "r",
        theme_slug="t",
        primary_genre="thriller",
        premise_type="x",
        cultural_claim="y",
        audience_demographic="z",
        client=fake,
    )
    research_dispatch.fetch_market_sizing(
        run_dir=tmp_path / "m",
        theme_slug="t",
        primary_genre="thriller",
        client=fake,
    )
    assert len(fake.calls) == 2
    assert {c["model"] for c in fake.calls} == {
        "perplexity/sonar-pro",
        "perplexity/sonar-deep-research",
    }


# ---------------------------------------------------------------------------
# _FallbackClient / _build_client chain tests (ADR-0007)
# ---------------------------------------------------------------------------


class _BudgetError(Exception):
    """Sentinel BudgetExceeded raised by a fake primary client."""


class _BudgetClient:
    """Fake client that always raises _BudgetError to simulate 402."""

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        raise _BudgetError("quota exhausted")


class _RecordingClient:
    """Fake client that records calls and returns a fixed response."""

    def __init__(self, response: dict[str, object]) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        self.calls.append({"model": model})
        return self._response


def test_fallback_client_aiml_succeeds_openrouter_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When AIML (primary) succeeds, the OpenRouter tier is never reached.

    This asserts the core ordering guarantee: an OpenRouter 402 is never
    on the hot path when AIML answers successfully.  The test wires a
    recording AIML primary, a recording 302 secondary, and a _BudgetClient
    as the OpenRouter slot to prove OpenRouter.chat() is never invoked.
    """
    aiml_client = _RecordingClient(response={"ok": True})
    openrouter_slot = _BudgetClient()  # would raise BudgetError if called

    fc = research_dispatch._FallbackClient(primary=aiml_client)

    # Inject openrouter_slot so any accidental call surfaces immediately.
    fc._openrouter = openrouter_slot  # type: ignore[assignment]

    # Patch _all_budget_exceptions so _BudgetError is recognised.
    monkeypatch.setattr(research_dispatch, "_all_budget_exceptions", lambda: (_BudgetError,))

    result = fc.chat("perplexity/sonar-pro", [{"role": "user", "content": "hi"}])

    assert result == {"ok": True}
    assert len(aiml_client.calls) == 1, "AIML primary must be called exactly once"
    # openrouter_slot.chat() was never called — it would have raised if it had been.


def test_fallback_client_aiml_budget_falls_to_302(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When AIML raises BudgetExceeded, 302 (TaoAI) is tried next."""
    tao_client = _RecordingClient(response={"tier": "302"})

    fc = research_dispatch._FallbackClient(primary=_BudgetClient())
    # Inject tao directly so _tao_client_or_raise is not called (no real key needed).
    fc._tao = tao_client  # type: ignore[assignment]

    monkeypatch.setattr(research_dispatch, "_all_budget_exceptions", lambda: (_BudgetError,))

    result = fc.chat("perplexity/sonar-pro", [{"role": "user", "content": "hi"}])

    assert result == {"tier": "302"}
    assert len(tao_client.calls) == 1


def test_fallback_client_302_budget_falls_to_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both AIML and 302 are exhausted, OpenRouter is the last resort."""
    or_client = _RecordingClient(response={"tier": "openrouter"})

    fc = research_dispatch._FallbackClient(primary=_BudgetClient())
    fc._tao = _BudgetClient()  # type: ignore[assignment]
    fc._openrouter = or_client  # type: ignore[assignment]

    monkeypatch.setattr(research_dispatch, "_all_budget_exceptions", lambda: (_BudgetError,))

    result = fc.chat("perplexity/sonar-pro", [{"role": "user", "content": "hi"}])

    assert result == {"tier": "openrouter"}
    assert len(or_client.calls) == 1


def test_build_client_aiml_primary_env_selects_aiml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_client() returns a _FallbackClient wrapping AimlClient when AIML_PRIMARY=1."""
    monkeypatch.setenv("AIML_PRIMARY", "1")
    monkeypatch.setenv("TAO_AI_PRIMARY", "")

    fake_aiml = _RecordingClient(response={"src": "aiml"})
    # Patch _aiml_client_or_none to return our fake without a real key.
    monkeypatch.setattr(research_dispatch, "_aiml_client_or_none", lambda: fake_aiml)

    client = research_dispatch._build_client()
    assert isinstance(client, research_dispatch._FallbackClient)

    # Inject a budget-raising tao so the chain terminates cleanly without keys.
    client._tao = _BudgetClient()  # type: ignore[assignment]
    monkeypatch.setattr(research_dispatch, "_all_budget_exceptions", lambda: (_BudgetError,))

    result = client.chat("perplexity/sonar-pro", [{"role": "user", "content": "q"}])
    assert result == {"src": "aiml"}
    assert len(fake_aiml.calls) == 1
