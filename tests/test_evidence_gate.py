"""Tests for pipeline.evidence_gate -- the research.json URL gate.

evidence_gate.py had ZERO test references (audit-named coverage gap). These
hermetic tests cover URL extraction, the no-URL SKIP path, and per-URL verdict
logic via an injected stub client (no network).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pipeline import evidence_gate as eg


def test_extract_urls_pulls_all_cited_and_filters_non_http() -> None:
    research: dict[str, Any] = {
        "audience_source_url": "https://example.gov/a/b",
        "cultural_moment_source_url": "https://example.org/c/d",
        "not_a_url_field": "n/a",
        "comps": [
            {"source_url": "https://www.the-numbers.com/movie/x"},
            {"source_url": "ftp://nope"},  # non-http -> filtered
            {"title": "no source"},
        ],
    }
    urls = eg._extract_urls(research)
    assert "https://example.gov/a/b" in urls
    assert "https://example.org/c/d" in urls
    assert "https://www.the-numbers.com/movie/x" in urls
    assert "ftp://nope" not in urls
    assert len(urls) == 3


def test_run_gate_skips_when_no_urls(tmp_path: Path) -> None:
    research = tmp_path / "research.json"
    research.write_text(json.dumps({"comps": []}), encoding="utf-8")
    result = eg.run_gate(research)
    assert result["verdict"] == "SKIP"
    assert result["checked"] == 0


class _StubResp:
    def __init__(self, status: int) -> None:
        self.status_code = status


class _StubClient:
    """Minimal stand-in for httpx.Client.head."""

    def __init__(self, status: int | None, *, raise_exc: bool = False) -> None:
        self._status = status
        self._raise = raise_exc

    def head(self, url: str, follow_redirects: bool = True) -> _StubResp:
        if self._raise:
            raise ConnectionError("boom")
        assert self._status is not None
        return _StubResp(self._status)


def test_check_url_2xx_passes() -> None:
    verdict = eg._check_url(cast("Any", _StubClient(200)), "https://x.com/a/b")
    assert verdict["verdict"] == "PASS"
    assert verdict["status"] == 200


def test_check_url_404_fails() -> None:
    verdict = eg._check_url(cast("Any", _StubClient(404)), "https://x.com/a/b")
    assert verdict["verdict"] == "FAIL"
    assert verdict["status"] == 404


def test_check_url_exception_is_error_not_crash() -> None:
    verdict = eg._check_url(cast("Any", _StubClient(None, raise_exc=True)), "https://x.com/a/b")
    assert verdict["verdict"] == "ERROR"
    assert verdict["status"] is None
