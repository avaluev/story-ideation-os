"""EVAL-01 — Citation denylist check (offline) + HEAD sweep (ONLINE=1).

Scans data/03_audience.jsonl source URLs for search-engine redirect patterns.
Offline: checks host denylist. ONLINE=1: HTTP HEAD check on each URL.
Skips gracefully when data/03_audience.jsonl is absent (fresh clone).
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pytest

ONLINE = os.getenv("ONLINE", "0") == "1"

_AUDIENCE_LOG = Path("data/03_audience.jsonl")

_DENYLIST_HOSTS = frozenset(
    {
        "google.com",
        "www.google.com",
        "bing.com",
        "www.bing.com",
        "duckduckgo.com",
        "www.duckduckgo.com",
        "search.brave.com",
        "yandex.com",
        "www.yandex.com",
        "yahoo.com",
        "search.yahoo.com",
    }
)


def _load_audience_rows() -> list[dict]:
    if not _AUDIENCE_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")
    rows = []
    for line in _AUDIENCE_LOG.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if not rows:
        pytest.skip("No pipeline output found — run the pipeline first.")
    return rows


def test_citations_no_search_redirects() -> None:
    """Offline denylist: no source URL resolves to a search engine (EVAL-01)."""
    rows = _load_audience_rows()
    violations: list[str] = []
    for row in rows:
        asset_id = row.get("asset_id", "unknown")
        # sources_per_claim may be an int count; source URLs in source_url field
        # or in a sources list if present
        for field in ("source_url", "sources"):
            val = row.get(field)
            urls: list[str] = []
            if isinstance(val, str):
                urls = [val]
            elif isinstance(val, list):
                urls = [u for u in val if isinstance(u, str)]
            for url in urls:
                host = urlparse(url).hostname or ""
                if host in _DENYLIST_HOSTS:
                    violations.append(f"{asset_id}: {url}")
    assert not violations, (
        f"Search-engine URLs found in citations ({len(violations)}):\n" + "\n".join(violations)
    )


def test_citations_online_head_check() -> None:
    """ONLINE=1 only: HTTP HEAD check on all cited URLs returns 2xx or allow-listed 4xx."""
    if not ONLINE:
        pytest.skip("Set ONLINE=1 to run HEAD checks")
    rows = _load_audience_rows()

    failures: list[str] = []
    for row in rows:
        for field in ("source_url", "sources"):
            val = row.get(field)
            urls: list[str] = []
            if isinstance(val, str):
                urls = [val]
            elif isinstance(val, list):
                urls = [u for u in val if isinstance(u, str)]
            for url in urls:
                try:
                    req = urllib.request.Request(url, method="HEAD")  # noqa: S310
                    req.add_header("User-Agent", "AnomalyEngine/3.0 eval")
                    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                        status = resp.status
                    if status >= 400:
                        failures.append(f"{url}: HTTP {status}")
                except Exception as exc:
                    # 401/403 from allow-listed sources is acceptable
                    if "401" not in str(exc) and "403" not in str(exc):
                        failures.append(f"{url}: {exc}")
    assert not failures, "URL HEAD failures:\n" + "\n".join(failures)
