"""V4A-003a — Offline regex lint for cross-domain catalog deep-link compliance.

Pure-pattern checks for the 8 V4A-003a catalog files (sources/{books,sciences,
medicine,arts,documentary,animation,history,music}.yaml). Distinct from
test_data_sources_registry.py: that module asserts schema and uniqueness; this
module asserts URL shape (deep-link, no search-engine, no markdown auto-link).

References:
- ~/.claude/rules/filmintel/deep-link-evidence.md (deep-link evidence policy)
- .planning/state/HANDOFF_V4A-003.md §3a (pass criteria)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

CATALOG_FILES: tuple[str, ...] = (
    "sources/books.yaml",
    "sources/sciences.yaml",
    "sources/medicine.yaml",
    "sources/arts.yaml",
    "sources/documentary.yaml",
    "sources/animation.yaml",
    "sources/history.yaml",
    "sources/music.yaml",
)

BARE_DOMAIN_RE = re.compile(r"^https?://[^/]+/?$", re.IGNORECASE)
SEARCH_ENGINE_RE = re.compile(
    r"(?:google|bing|duckduckgo|search\.brave|yandex|yahoo)\.[a-z]+/(?:search|s)\b",
    re.IGNORECASE,
)
MD_AUTO_LINK_RE = re.compile(r"<https?://[^>]+>")


@pytest.fixture(scope="module")
def catalog_rows() -> list[tuple[str, dict]]:
    """Yield (file_path, row_dict) tuples for every endpoint across the 8 catalogs."""
    pairs: list[tuple[str, dict]] = []
    for path in CATALOG_FILES:
        p = Path(path)
        assert p.exists(), f"{path} missing — see HANDOFF_V4A-003.md §3a"
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        for row in doc.get("sources", []):
            pairs.append((path, row))
    return pairs


def test_api_base_has_path_beyond_root(catalog_rows: list[tuple[str, dict]]) -> None:
    """No api_base may be a bare domain (e.g. https://example.com or https://example.com/)."""
    offenders: list[str] = []
    for path, row in catalog_rows:
        api_base = row.get("api_base", "")
        if BARE_DOMAIN_RE.match(api_base):
            offenders.append(f"{path}::{row.get('source_id', '?')} → {api_base!r}")
    assert not offenders, "bare-domain api_base detected:\n  " + "\n  ".join(offenders)


def test_api_base_no_search_engine_redirect(catalog_rows: list[tuple[str, dict]]) -> None:
    """No api_base may be a search-engine redirect (google.com/search, bing.com/s, etc.)."""
    offenders: list[str] = []
    for path, row in catalog_rows:
        api_base = row.get("api_base", "")
        if SEARCH_ENGINE_RE.search(api_base):
            offenders.append(f"{path}::{row.get('source_id', '?')} → {api_base!r}")
    assert not offenders, "search-engine redirect in api_base:\n  " + "\n  ".join(offenders)


def test_homepage_url_no_search_engine_redirect(
    catalog_rows: list[tuple[str, dict]],
) -> None:
    """No homepage_url may be a search-engine redirect (homepage may be bare domain)."""
    offenders: list[str] = []
    for path, row in catalog_rows:
        homepage_url = row.get("homepage_url", "")
        if SEARCH_ENGINE_RE.search(homepage_url):
            offenders.append(f"{path}::{row.get('source_id', '?')} → {homepage_url!r}")
    assert not offenders, "search-engine redirect in homepage_url:\n  " + "\n  ".join(offenders)


def test_no_markdown_auto_link_form_in_notes(
    catalog_rows: list[tuple[str, dict]],
) -> None:
    """FilmIntel rule: no markdown auto-link form `<https://...>` in registry notes.

    The auto-link form is policy-banned because GitHub renders it but most other
    surfaces don't. Use plain URLs or [text](url) markdown links.
    """
    offenders: list[str] = []
    for path, row in catalog_rows:
        notes = row.get("notes", "") or ""
        if MD_AUTO_LINK_RE.search(notes):
            offenders.append(f"{path}::{row.get('source_id', '?')}")
    assert not offenders, "markdown auto-link form in notes:\n  " + "\n  ".join(offenders)


def test_urls_use_https_scheme(catalog_rows: list[tuple[str, dict]]) -> None:
    """All api_base + homepage_url use https:// (deep-link evidence policy)."""
    offenders: list[str] = []
    for path, row in catalog_rows:
        for field in ("api_base", "homepage_url"):
            url = row.get(field, "")
            if url and not url.startswith("https://"):
                offenders.append(f"{path}::{row.get('source_id', '?')} {field} → {url!r}")
    assert not offenders, "non-https URL detected:\n  " + "\n  ".join(offenders)
