"""EVAL-03 — Audience floor: every PUBLISHED concept's asset has >=50M audience, >=3 countries.

Reads data/03_audience.jsonl and intersects with concepts published to out/concepts/.
Upstream rows that were correctly filtered out by the formatter are not asserted on.
Uses the same thresholds as pipeline/scoring.py
(_AJTBD_AUDIENCE_MIN = 50_000_000, _AJTBD_COUNTRY_MIN = 3).
Skips gracefully when data file or out/concepts/ is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_AUDIENCE_LOG = Path("data/03_audience.jsonl")
_CRITIQUES_LOG = Path("data/05_critiques.jsonl")
_OUT_DIR = Path("out") / "concepts"
_AUDIENCE_MIN = 50_000_000
_COUNTRY_MIN = 3


def _published_asset_ids() -> set[str]:
    """Return the set of asset_ids whose concepts were published to out/concepts/."""
    if not _OUT_DIR.exists() or not _CRITIQUES_LOG.exists():
        return set()
    published_concept_ids = {p.stem for p in _OUT_DIR.glob("*.md")}
    asset_ids: set[str] = set()
    for line in _CRITIQUES_LOG.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("concept_id") in published_concept_ids:
            # Critique row may carry asset_id (or fall back to its concept_id stem)
            asset_ids.add(str(row.get("asset_id") or row.get("concept_id")))
    return asset_ids


def test_audience_50m_floor() -> None:
    """Every PUBLISHED concept's audience profile must have cited_audience >=50M (EVAL-03)."""
    if not _AUDIENCE_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")
    published = _published_asset_ids()
    if not published:
        pytest.skip("No concepts published — formatter floor filtered all rows.")
    violations: list[str] = []
    for line in _AUDIENCE_LOG.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        asset_id = str(row.get("asset_id", "unknown"))
        if asset_id not in published:
            continue
        audience = int(row.get("cited_audience", 0))
        if audience < _AUDIENCE_MIN:
            violations.append(f"{asset_id}: cited_audience={audience:,}")
    assert not violations, (
        f"Published concepts below 50M audience floor ({len(violations)}):\n"
        + "\n".join(violations)
    )


def test_audience_3_countries() -> None:
    """Every PUBLISHED concept's audience profile must cover >=3 distinct countries (EVAL-03)."""
    if not _AUDIENCE_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")
    published = _published_asset_ids()
    if not published:
        pytest.skip("No concepts published — formatter floor filtered all rows.")
    violations: list[str] = []
    for line in _AUDIENCE_LOG.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        asset_id = str(row.get("asset_id", "unknown"))
        if asset_id not in published:
            continue
        countries = row.get("target_countries", [])
        if len(countries) < _COUNTRY_MIN:
            violations.append(f"{asset_id}: countries={countries}")
    assert not violations, (
        f"Published concepts with <3 countries ({len(violations)}):\n" + "\n".join(violations)
    )
