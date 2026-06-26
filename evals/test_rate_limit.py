"""EVAL-05 — Key rotation health: no single key carries > 70% of logged API calls.

Reads data/run_log.jsonl. Filters rows where event contains "API" or "CALL" and
a key-identifying field is present (key_prefix, key_id, or key_masked).
Computes per-key load share. Fails if any key carries > 70%.

Skips gracefully when data/run_log.jsonl is absent or has no API call rows
with key-identifying fields — the current pipeline logs API calls via Python's
logging module (not via append_jsonl), so this eval activates only when the
pipeline is explicitly wired to emit key-tagged rows into run_log.jsonl.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

_RUN_LOG = Path("data/run_log.jsonl")
_KEY_LOAD_MAX = 0.70


def test_key_rotation_balance() -> None:
    """No single API key must carry more than 70% of logged API calls (EVAL-05).

    Enforcement is conditional: if run_log.jsonl contains no rows with
    key-identifying fields (key_prefix, key_id, or key_masked), the test
    skips with an informational message rather than failing.
    """
    if not _RUN_LOG.exists():
        pytest.skip("No pipeline output found — run the pipeline first.")

    key_calls: Counter[str] = Counter()
    total_api_rows = 0

    for raw_line in _RUN_LOG.read_text().splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        # Look for rows that represent API calls; field names may vary
        event = str(row.get("event", "")).upper()
        if "API" not in event and "CALL" not in event:
            continue
        # Key may be logged as key_prefix, key_id, or key_masked
        key_id = (
            str(row.get("key_prefix", ""))
            or str(row.get("key_id", ""))
            or str(row.get("key_masked", ""))
        )
        if not key_id:
            continue  # row has no key-identifying field — skip this row
        key_calls[key_id] += 1
        total_api_rows += 1

    if total_api_rows == 0:
        pytest.skip(
            "No API call rows with key-identifying fields in run_log.jsonl — "
            "key rotation balance cannot be evaluated. "
            "Run the pipeline with key logging enabled to activate this eval."
        )

    violations: list[str] = []
    for key, count in key_calls.items():
        share = count / total_api_rows
        if share > _KEY_LOAD_MAX:
            violations.append(f"key={key!r}: {count}/{total_api_rows} = {share:.1%}")

    assert not violations, f"Key(s) exceeding 70% load share ({len(violations)}):\n" + "\n".join(
        violations
    )
