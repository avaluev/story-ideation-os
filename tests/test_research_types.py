"""Construct + immutability checks for pipeline.research.providers.types.

Kept intentionally minimal — the types carry no logic; we only verify that
both dataclasses construct correctly from positional/keyword args and that
frozen=True prevents mutation (ADR-0001 immutability guarantee).
"""

from __future__ import annotations

import dataclasses

import pytest

from pipeline.research.providers.types import FetchedPage, SearchHit


class TestSearchHit:
    def test_construct_all_fields(self) -> None:
        hit = SearchHit(
            title="Test Title",
            url="https://example.com/article",
            snippet="A short excerpt.",
            score=0.87,
            provider="exa",
            published_date="2026-01-15",
        )
        assert hit.title == "Test Title"
        assert hit.url == "https://example.com/article"
        assert hit.snippet == "A short excerpt."
        assert hit.score == 0.87
        assert hit.provider == "exa"
        assert hit.published_date == "2026-01-15"

    def test_published_date_defaults_to_empty_string(self) -> None:
        hit = SearchHit(
            title="No Date",
            url="https://example.com/",
            snippet="...",
            score=0.5,
            provider="serpapi",
        )
        assert hit.published_date == ""

    def test_is_frozen(self) -> None:
        hit = SearchHit(
            title="Immutable",
            url="https://example.com/",
            snippet=".",
            score=0.1,
            provider="exa",
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            hit.title = "mutated"  # type: ignore[misc]


class TestFetchedPage:
    def test_construct_all_fields(self) -> None:
        page = FetchedPage(
            url="https://example.com/page",
            final_url="https://example.com/page-canonical",
            status=200,
            text="<html>Hello</html>",
            markdown="# Hello",
            content_sha256="abc123",
            fetched_at="2026-06-02T00:00:00Z",
            provider="firecrawl",
            ok=True,
        )
        assert page.url == "https://example.com/page"
        assert page.final_url == "https://example.com/page-canonical"
        assert page.status == 200
        assert page.text == "<html>Hello</html>"
        assert page.markdown == "# Hello"
        assert page.content_sha256 == "abc123"
        assert page.fetched_at == "2026-06-02T00:00:00Z"
        assert page.provider == "firecrawl"
        assert page.ok is True

    def test_ok_false_on_error_page(self) -> None:
        page = FetchedPage(
            url="https://example.com/missing",
            final_url="https://example.com/missing",
            status=404,
            text="",
            markdown="",
            content_sha256="",
            fetched_at="2026-06-02T00:00:00Z",
            provider="httpx",
            ok=False,
        )
        assert page.ok is False
        assert page.status == 404

    def test_is_frozen(self) -> None:
        page = FetchedPage(
            url="https://example.com/",
            final_url="https://example.com/",
            status=200,
            text="body",
            markdown="body",
            content_sha256="deadbeef",
            fetched_at="2026-06-02T00:00:00Z",
            provider="jina",
            ok=True,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            page.status = 500  # type: ignore[misc]
