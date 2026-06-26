"""Unit test for KNOW-09 + KNOW-10 + V4A-003a: sources/*.yaml schema + count + categories.

References:
- sources/data-sources.yaml (under test, A..J)
- sources/{books,sciences,medicine,arts,documentary,animation,history,music}.yaml
  (V4A-003a cross-domain catalogs, K..R)
- scripts/audit.py (the runtime enforcer; this test mirrors its offline checks)
- .planning/phases/01-knowledge-layer/01-RESEARCH.md section: Data Sources Registry
- .planning/state/HANDOFF_V4A-003.md §3a: cross-domain catalog requirements
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

REGISTRY_PATH = Path("sources/data-sources.yaml")
CROSS_DOMAIN_CATALOG_FILES = (
    ("sources/books.yaml", "K"),
    ("sources/sciences.yaml", "L"),
    ("sources/medicine.yaml", "M"),
    ("sources/arts.yaml", "N"),
    ("sources/documentary.yaml", "O"),
    ("sources/animation.yaml", "P"),
    ("sources/history.yaml", "Q"),
    ("sources/music.yaml", "R"),
)
REQUIRED_SOURCE_KEYS = {
    "source_id",
    "category",
    "name",
    "homepage_url",
    "api_base",
    "quota",
    "auth_method",
    "auth_required",
    "license",
    "bot_block_allow_listed",
    "last_verified",
}
VALID_AUTH_METHODS = {"none", "token", "key", "oauth"}
SEARCH_REDIRECT_HOSTS = {
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "search.brave.com",
    "yandex.com",
    "yahoo.com",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    assert REGISTRY_PATH.exists(), f"{REGISTRY_PATH} missing -- see plan 01-02 task 1"
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_top_level_schema(registry: dict) -> None:
    for key in ("schema_version", "last_verified", "quotas", "untapped_check_strategy", "sources"):
        assert key in registry, f"missing top-level key: {key}"


def test_count_and_categories(registry: dict) -> None:
    """KNOW-09: >=30 endpoints across all 10 categories A..J."""
    sources = registry["sources"]
    assert len(sources) >= 30, f"len(sources)={len(sources)} < 30"
    cats = {s["category"] for s in sources}
    assert cats == set("ABCDEFGHIJ"), f"missing categories: {set('ABCDEFGHIJ') - cats}"


def test_quotas_block(registry: dict) -> None:
    """KNOW-10: quotas block with operator-locked caps."""
    q = registry["quotas"]
    assert q["openrouter_paid_per_day"] == 1000
    assert q["daily_usd_cap"] == 1000
    assert q["phase_3_sonar_call_cap"] == 10


def test_untapped_check_strategy_block(registry: dict) -> None:
    """KNOW-10: untapped_check_strategy.default.method non-empty."""
    s = registry["untapped_check_strategy"]
    assert "default" in s
    assert s["default"]["method"], "default method is empty"


def test_every_source_has_required_keys(registry: dict) -> None:
    for entry in registry["sources"]:
        missing = REQUIRED_SOURCE_KEYS - set(entry.keys())
        assert not missing, f"source {entry.get('source_id', '?')} missing keys: {missing}"


def test_no_bare_domain_api_base(registry: dict) -> None:
    """FilmIntel deep-link rule: api_base must have path beyond '/'."""
    for entry in registry["sources"]:
        path = urlparse(entry["api_base"]).path
        assert path not in ("", "/"), (
            f"bare-domain api_base in {entry['source_id']}: {entry['api_base']}"
        )


def test_no_search_redirect_host(registry: dict) -> None:
    """FilmIntel deep-link rule: api_base must not point to a search engine."""
    for entry in registry["sources"]:
        host = urlparse(entry["api_base"]).hostname or ""
        for bad in SEARCH_REDIRECT_HOSTS:
            assert bad not in host, (
                f"search-redirect host in {entry['source_id']}: {entry['api_base']}"
            )


def test_auth_method_valid(registry: dict) -> None:
    for entry in registry["sources"]:
        assert entry["auth_method"] in VALID_AUTH_METHODS, (
            f"{entry['source_id']}: invalid auth_method={entry['auth_method']!r}"
        )


def test_source_ids_unique(registry: dict) -> None:
    ids = [e["source_id"] for e in registry["sources"]]
    assert len(set(ids)) == len(ids), (
        f"duplicate source_ids in registry: {len(ids) - len(set(ids))} dupes"
    )


# ─── V4A-003a — Cross-Domain Catalogs (categories K..R) ──────────────────────


def _load_catalog(path: str) -> dict:
    p = Path(path)
    assert p.exists(), f"{path} missing — see HANDOFF_V4A-003.md §3a"
    return yaml.safe_load(p.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def cross_domain_catalogs() -> dict[str, dict]:
    """Load all 8 cross-domain catalog files keyed by file path."""
    return {path: _load_catalog(path) for path, _cat in CROSS_DOMAIN_CATALOG_FILES}


def test_cross_domain_index_present(registry: dict) -> None:
    """data-sources.yaml roots a cross_domain_catalogs index pointing at K..R files."""
    assert "cross_domain_catalogs" in registry, (
        "data-sources.yaml is missing top-level `cross_domain_catalogs:` index"
    )
    listed = {row["path"] for row in registry["cross_domain_catalogs"]}
    expected = {path for path, _cat in CROSS_DOMAIN_CATALOG_FILES}
    assert listed == expected, (
        f"cross_domain_catalogs index drift; missing={expected - listed}, extra={listed - expected}"
    )


def test_cross_domain_each_has_at_least_three_sources(
    cross_domain_catalogs: dict[str, dict],
) -> None:
    """V4A-003a HANDOFF target: each catalog ships ≥3 endpoint rows."""
    for path, doc in cross_domain_catalogs.items():
        assert "sources" in doc, f"{path}: missing top-level `sources:` list"
        assert len(doc["sources"]) >= 3, (
            f"{path}: only {len(doc['sources'])} sources (HANDOFF target ≥3)"
        )


def test_cross_domain_category_matches_filename(
    cross_domain_catalogs: dict[str, dict],
) -> None:
    """File category banner and every row.category match the K..R map."""
    for path, expected_cat in CROSS_DOMAIN_CATALOG_FILES:
        doc = cross_domain_catalogs[path]
        assert doc.get("category") == expected_cat, (
            f"{path}: top-level category={doc.get('category')!r}, expected {expected_cat!r}"
        )
        for row in doc["sources"]:
            assert row["category"] == expected_cat, (
                f"{path}::{row.get('source_id', '?')}: row category={row['category']!r}, "
                f"expected {expected_cat!r}"
            )


def test_cross_domain_required_keys(cross_domain_catalogs: dict[str, dict]) -> None:
    """Schema parity with data-sources.yaml: every K..R row carries the same required keys."""
    for path, doc in cross_domain_catalogs.items():
        for row in doc["sources"]:
            missing = REQUIRED_SOURCE_KEYS - set(row.keys())
            assert not missing, (
                f"{path}::{row.get('source_id', '?')}: missing required keys: {missing}"
            )


def test_cross_domain_no_bare_domain_api_base(
    cross_domain_catalogs: dict[str, dict],
) -> None:
    """FilmIntel deep-link policy: api_base path beyond '/' for every K..R endpoint."""
    for path, doc in cross_domain_catalogs.items():
        for row in doc["sources"]:
            url_path = urlparse(row["api_base"]).path
            assert url_path not in ("", "/"), (
                f"{path}::{row['source_id']}: bare-domain api_base {row['api_base']!r}"
            )


def test_cross_domain_no_search_redirect_host(
    cross_domain_catalogs: dict[str, dict],
) -> None:
    """FilmIntel deep-link policy: api_base must not point to a search engine."""
    for path, doc in cross_domain_catalogs.items():
        for row in doc["sources"]:
            host = urlparse(row["api_base"]).hostname or ""
            for bad in SEARCH_REDIRECT_HOSTS:
                assert bad not in host, (
                    f"{path}::{row['source_id']}: search-redirect host in {row['api_base']!r}"
                )


def test_cross_domain_auth_method_valid(
    cross_domain_catalogs: dict[str, dict],
) -> None:
    for path, doc in cross_domain_catalogs.items():
        for row in doc["sources"]:
            assert row["auth_method"] in VALID_AUTH_METHODS, (
                f"{path}::{row['source_id']}: invalid auth_method={row['auth_method']!r}"
            )


def test_source_ids_unique_across_all_catalogs(
    registry: dict, cross_domain_catalogs: dict[str, dict]
) -> None:
    """Source-IDs are globally unique across A..R (the miner pulls all together)."""
    all_ids: list[str] = [e["source_id"] for e in registry["sources"]]
    for doc in cross_domain_catalogs.values():
        all_ids.extend(row["source_id"] for row in doc["sources"])
    seen: set[str] = set()
    dupes: list[str] = []
    for sid in all_ids:
        if sid in seen:
            dupes.append(sid)
        else:
            seen.add(sid)
    assert not dupes, f"duplicate source_ids across A..R catalogs: {dupes}"
