"""tests/test_source_claims_router.py — hermetic schema-stability tests for the
re-implemented scripts/source_claims_302.py.

Verifies that the re-implementation on top of EvidenceRouter produces the same
output JSON shape as the original (byte-identical schema) expected by
pipeline.veracity.merge_agent_judgments.

All HTTP is mocked; no live network calls.

ADR-0007: hermetic — no httpx / live calls.
ANOMALY-001: no anthropic / openrouter_client imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.research.evidence_router import EvidenceRouter, Judgment, RouterConfig
from pipeline.research.providers.types import FetchedPage, SearchHit

# ── Re-use the fake gateway helpers from the router fanout tests ──────────────


def _hit(
    url: str,
    title: str = "Test",
    snippet: str = "snippet",
    score: float = 0.9,
    provider: str = "fake",
    published_date: str = "2024-01-15",
) -> SearchHit:
    return SearchHit(
        title=title,
        url=url,
        snippet=snippet,
        score=score,
        provider=provider,
        published_date=published_date,
    )


def _page(
    url: str,
    text: str = "sample page text",
    ok: bool = True,
    provider: str = "fake",
) -> FetchedPage:
    return FetchedPage(
        url=url,
        final_url=url,
        status=200 if ok else 0,
        text=text,
        markdown=text,
        content_sha256="abc123",
        fetched_at="2026-06-02T00:00:00+00:00",
        provider=provider,
        ok=ok,
    )


class FakeSearchGateway:
    def __init__(self, hits: list[SearchHit], gateway_name: str = "fake_search") -> None:
        self.hits = hits
        self.gateway_name = gateway_name

    def search(self, query: str, *, num: int = 10) -> list[SearchHit]:
        return self.hits[:num]


class FakeFetchGateway:
    def __init__(self, pages: dict[str, FetchedPage], gateway_name: str = "fake_fetch") -> None:
        self.pages = pages
        self.gateway_name = gateway_name

    def fetch(self, url: str) -> FetchedPage:
        return self.pages.get(url, _page(url, text="", ok=False))


# ── Credible deep-link URLs ───────────────────────────────────────────────────

_BOM_URL = "https://www.boxofficemojo.com/title/tt1856101/"
_VAR_URL = "https://variety.com/2024/film/news/barbie-box-office-12345/"


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSourceOneOutputSchema:
    """source_one() must return the exact shape consumed by merge_agent_judgments."""

    def _make_router(self, page_text: str, url: str = _BOM_URL) -> EvidenceRouter:
        """Build a hermetic EvidenceRouter that always finds *url* and fetches *page_text*."""
        search_gw = FakeSearchGateway(hits=[_hit(url, published_date="2024-06-01")])
        fetch_gw = FakeFetchGateway(pages={url: _page(url, text=page_text)})
        return EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[search_gw],
            fetch_gateways=[fetch_gw],
        )

    def test_judgment_schema_on_success(self) -> None:
        """source_one() returns {supports, quote, url, date} on a value-on-page match."""
        from scripts.source_claims_302 import source_one  # noqa: PLC0415

        router = self._make_router(
            page_text="Barbie grossed $1.4B worldwide during 2023.",
            url=_BOM_URL,
        )
        claim: dict[str, Any] = {
            "claim_id": "test-001",
            "value": "$1.4B",
            "text": "Barbie grossed $1.4B worldwide",
            "claim_type": "box_office",
            "card": "01",
            "title": "Barbie",
            "tier_hint": "boxofficemojo.com",
        }
        result = source_one(router, claim)

        assert result is not None, "Expected a judgment dict, got None"

        # ── Schema shape must be BYTE-IDENTICAL to old source_one output ────────
        assert set(result.keys()) == {
            "supports",
            "quote",
            "url",
            "date",
        }, f"Unexpected keys: {set(result.keys())}"

        assert result["supports"] is True
        assert isinstance(result["quote"], str)
        assert len(result["quote"]) > 0, "quote must be non-empty on a successful match"
        assert isinstance(result["url"], str)
        assert result["url"] == _BOM_URL
        assert isinstance(result["date"], str)

    def test_judgment_returns_none_when_value_not_on_page(self) -> None:
        """source_one() returns None when the value is absent from the fetched page."""
        from scripts.source_claims_302 import source_one  # noqa: PLC0415

        router = self._make_router(
            page_text="This page discusses something completely unrelated.",
            url=_BOM_URL,
        )
        claim: dict[str, Any] = {
            "claim_id": "test-002",
            "value": "$9.9B",
            "text": "Barbie grossed $9.9B worldwide",
            "claim_type": "box_office",
            "card": "01",
            "title": "Barbie",
            "tier_hint": "boxofficemojo.com",
        }
        result = source_one(router, claim)
        assert result is None

    def test_judgment_returns_none_when_no_hits(self) -> None:
        """source_one() returns None when discover() produces no credible hits."""
        from scripts.source_claims_302 import source_one  # noqa: PLC0415

        router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[FakeSearchGateway(hits=[])],
            fetch_gateways=[],
        )
        claim: dict[str, Any] = {
            "claim_id": "test-003",
            "value": "$1.4B",
            "text": "Barbie grossed $1.4B worldwide",
            "claim_type": "box_office",
            "card": "01",
            "title": "Barbie",
            "tier_hint": "",
        }
        result = source_one(router, claim)
        assert result is None

    def test_claim_text_mapping(self) -> None:
        """source_one() correctly maps 'text' key to router's 'claim_text' key."""
        from scripts.source_claims_302 import source_one  # noqa: PLC0415

        # Intercept the router.source_claim call to verify the adapted claim dict.
        captured: list[dict[str, Any]] = []

        def fake_source_claim(claim_dict: dict[str, Any]) -> Judgment | None:
            captured.append(dict(claim_dict))
            return None

        router = EvidenceRouter(
            config=RouterConfig(),
            search_gateways=[],
            fetch_gateways=[],
        )
        router.source_claim = fake_source_claim  # type: ignore[method-assign]

        claim: dict[str, Any] = {
            "claim_id": "test-004",
            "value": "$500M",
            "text": "The film earned $500M domestically",
            "claim_type": "box_office",
            "card": "02",
            "title": "Test Film",
            "tier_hint": "",
        }
        source_one(router, claim)

        assert len(captured) == 1
        adapted = captured[0]
        assert adapted["claim_id"] == "test-004"
        assert adapted["value"] == "$500M"
        # "text" must be mapped to "claim_text" for the router
        assert adapted["claim_text"] == "The film earned $500M domestically"
        assert adapted["claim_type"] == "box_office"


class TestOutputFileSchema:
    """The output JSON file schema must be byte-identical to the original."""

    def test_checkpoint_output_shape(self, tmp_path: Path) -> None:
        """The written JSON wraps judgments under a 'judgments' top-level key."""
        from scripts.source_claims_302 import _load_checkpoint  # noqa: PLC0415

        # Write a checkpoint in the expected shape.
        judgments: dict[str, dict[str, Any]] = {
            "claim-001": {
                "supports": True,
                "quote": "The film grossed $1.4B worldwide.",
                "url": _BOM_URL,
                "date": "2024-01-15",
            }
        }
        out_file = tmp_path / "judgments.json"
        out_file.write_text(
            json.dumps({"judgments": judgments}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # _load_checkpoint must unwrap the top-level "judgments" key.
        loaded = _load_checkpoint(out_file)
        assert "claim-001" in loaded
        j = loaded["claim-001"]
        assert set(j.keys()) == {"supports", "quote", "url", "date"}
        assert j["supports"] is True
        assert j["url"] == _BOM_URL

    def test_checkpoint_returns_empty_on_missing_file(self, tmp_path: Path) -> None:
        from scripts.source_claims_302 import _load_checkpoint  # noqa: PLC0415

        result = _load_checkpoint(tmp_path / "nonexistent.json")
        assert result == {}

    def test_checkpoint_returns_empty_on_corrupt_file(self, tmp_path: Path) -> None:
        from scripts.source_claims_302 import _load_checkpoint  # noqa: PLC0415

        bad = tmp_path / "bad.json"
        bad.write_text("not valid json{{{", encoding="utf-8")
        result = _load_checkpoint(bad)
        assert result == {}


class TestMainEndToEnd:
    """Smoke-test main() with a mocked EvidenceRouter to verify the full pipeline."""

    def test_main_writes_correct_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() writes {judgments: {claim_id: {supports, quote, url, date}}} on a match."""
        import scripts.source_claims_302 as sc302  # noqa: PLC0415

        # Build a hermetic router and monkeypatch from_defaults to return it.
        bom_url = _BOM_URL
        page_text = "Barbie earned $1.4B worldwide in 2023."
        search_gw = FakeSearchGateway(
            hits=[_hit(bom_url, published_date="2024-06-01")],
        )
        fetch_gw = FakeFetchGateway(pages={bom_url: _page(bom_url, text=page_text)})
        hermetic_router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[search_gw],
            fetch_gateways=[fetch_gw],
        )
        monkeypatch.setattr(EvidenceRouter, "from_defaults", staticmethod(lambda: hermetic_router))

        # Write a minimal manifest
        manifest = {
            "claims": [
                {
                    "claim_id": "e2e-001",
                    "card": "01",
                    "title": "Barbie",
                    "claim_type": "box_office",
                    "text": "Barbie earned $1.4B worldwide",
                    "value": "$1.4B",
                    "tier_hint": "boxofficemojo.com",
                }
            ]
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        out_path = tmp_path / "judgments.json"

        ret = sc302.main(
            [
                "--manifest",
                str(manifest_path),
                "--out",
                str(out_path),
                "--workers",
                "1",
            ]
        )
        assert ret == 0

        # ── Verify the output file schema ─────────────────────────────────────
        written = json.loads(out_path.read_text(encoding="utf-8"))

        # Top-level key must be "judgments" (not "claims", not flat)
        assert "judgments" in written, (
            f"Expected top-level 'judgments' key, got: {list(written.keys())}"
        )

        jdict: dict[str, Any] = written["judgments"]
        assert "e2e-001" in jdict, f"Claim 'e2e-001' missing from judgments: {list(jdict.keys())}"

        j = jdict["e2e-001"]
        # Schema must be byte-identical to the original source_one output shape.
        assert set(j.keys()) == {
            "supports",
            "quote",
            "url",
            "date",
        }, f"Unexpected judgment keys: {set(j.keys())}"
        assert j["supports"] is True
        assert isinstance(j["quote"], str) and j["quote"]
        assert j["url"] == bom_url
        assert isinstance(j["date"], str)

    def test_main_respects_limit_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--limit N caps the number of claims processed."""
        import scripts.source_claims_302 as sc302  # noqa: PLC0415

        hermetic_router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[FakeSearchGateway(hits=[])],
            fetch_gateways=[],
        )
        monkeypatch.setattr(EvidenceRouter, "from_defaults", staticmethod(lambda: hermetic_router))

        claims = [
            {
                "claim_id": f"cl-{i:03d}",
                "card": "01",
                "title": "Film",
                "claim_type": "box_office",
                "text": f"Film earned ${i}B",
                "value": f"${i}B",
                "tier_hint": "",
            }
            for i in range(1, 11)  # 10 claims
        ]
        manifest = {"claims": claims}
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        out_path = tmp_path / "judgments.json"

        # Track how many claims were processed
        processed: list[str] = []
        original_source_one = sc302.source_one

        def counting_source_one(
            router: EvidenceRouter, claim: dict[str, Any]
        ) -> dict[str, Any] | None:
            processed.append(claim["claim_id"])
            return original_source_one(router, claim)

        monkeypatch.setattr(sc302, "source_one", counting_source_one)

        sc302.main(
            [
                "--manifest",
                str(manifest_path),
                "--out",
                str(out_path),
                "--workers",
                "1",
                "--limit",
                "3",
            ]
        )

        assert len(processed) == 3, f"Expected 3 claims processed, got {len(processed)}"

    def test_main_respects_cards_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--cards 01 filters to only claims whose card starts with '01'."""
        import scripts.source_claims_302 as sc302  # noqa: PLC0415

        hermetic_router = EvidenceRouter(
            config=RouterConfig(search_fanout=1, limit=3),
            search_gateways=[FakeSearchGateway(hits=[])],
            fetch_gateways=[],
        )
        monkeypatch.setattr(EvidenceRouter, "from_defaults", staticmethod(lambda: hermetic_router))

        claims = [
            {
                "claim_id": "a-001",
                "card": "01",
                "title": "Film A",
                "claim_type": "box_office",
                "text": "Film A earned $1B",
                "value": "$1B",
                "tier_hint": "",
            },
            {
                "claim_id": "b-001",
                "card": "02",
                "title": "Film B",
                "claim_type": "box_office",
                "text": "Film B earned $2B",
                "value": "$2B",
                "tier_hint": "",
            },
            {
                "claim_id": "a-002",
                "card": "01b",
                "title": "Film A2",
                "claim_type": "box_office",
                "text": "Film A2 earned $3B",
                "value": "$3B",
                "tier_hint": "",
            },
        ]
        manifest = {"claims": claims}
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        out_path = tmp_path / "judgments.json"

        processed: list[str] = []
        original_source_one = sc302.source_one

        def tracking_source_one(
            router: EvidenceRouter, claim: dict[str, Any]
        ) -> dict[str, Any] | None:
            processed.append(claim["claim_id"])
            return original_source_one(router, claim)

        monkeypatch.setattr(sc302, "source_one", tracking_source_one)

        sc302.main(
            [
                "--manifest",
                str(manifest_path),
                "--out",
                str(out_path),
                "--workers",
                "1",
                "--cards",
                "01",
            ]
        )

        # Only cards starting with "01" should be processed (01 and 01b)
        assert set(processed) == {"a-001", "a-002"}, f"Unexpected processed claims: {processed}"
        assert "b-001" not in processed, "Card 02 claim must be excluded"
