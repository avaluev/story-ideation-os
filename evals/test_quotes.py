"""EVAL-02 — Source quote word-count check: every cited quote <=14 words.

Scans data/03_audience.jsonl source_quote fields. Fails if any quote exceeds
the copyright-safe 14-word ceiling (SOURCE_QUOTE_MAX_WORDS from schema.py).
Skips gracefully when data file is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_AUDIENCE_LOG = Path("data/03_audience.jsonl")
_MAX_WORDS = 14


def test_quotes_under_14_words() -> None:
    """Every source_quote in data/03_audience.jsonl must be <=14 words (EVAL-02)."""
    if not _AUDIENCE_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")
    violations: list[str] = []
    for line in _AUDIENCE_LOG.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        quote = row.get("source_quote", "")
        wc = len(quote.split())
        if wc > _MAX_WORDS:
            asset_id = row.get("asset_id", "unknown")
            violations.append(f"{asset_id}: {wc} words — {quote!r}")
    assert not violations, (
        f"Quotes exceeding {_MAX_WORDS}-word limit ({len(violations)}):\n" + "\n".join(violations)
    )
