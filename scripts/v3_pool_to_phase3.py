"""V4A-004 Stage 4 helper - transform v3.1 audience-pool rows into Phase3Audience schema.

The v4 phase-4-forger subagent reads `data/03_audience.jsonl` rows that match
the canonical Phase3Audience schema (see `pipeline/schema.py`). Our extracted
v3 pool at `data/runs/v4-genius-cc/<run_id>/v3_audience_pool.jsonl` has a
slightly different schema (richer asset metadata + provenance fields).

This transform maps v3-pool keys -> Phase3Audience keys. Output goes ONLY to
the v4 partition; never overwrites the v3-era `data/03_audience.jsonl` at
the repo root (isolation contract per docs/v4_isolation.md).

Usage::

    uv run python scripts/v3_pool_to_phase3.py \\
        --run-id 20260510T035457Z \\
        --limit 30

Output: data/runs/v4-genius-cc/<run_id>/03_audience_v4.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

V4_RUNS_ROOT = Path("data/runs/v4-genius-cc")
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _v3_pool_to_phase3(row: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Map a v3-pool audience row to Phase3Audience schema.

    Required Phase3Audience fields (per pipeline/schema.py):
      asset_id, target_countries, cited_audience, sources_per_claim,
      trend_direction, primary_jtbd_strength, source_quote,
      produced_at, session_id, total_score
    """
    countries: list[str] = []
    for entry in row.get("country_breakdown", []):
        iso2 = entry.get("country_iso2") if isinstance(entry, dict) else None
        if iso2:
            countries.append(iso2)
    sources = {
        entry.get("source_url")
        for entry in row.get("country_breakdown", [])
        if isinstance(entry, dict)
    }
    sources.discard(None)
    # primary_jtbd_strength is a [0..1] confidence; v3 didn't capture it explicitly,
    # but the v3 Phase 2 pipeline only emits rows with strength >= 0.7. Use 0.85 as
    # a conservative midpoint marker.
    return {
        "asset_id": row["asset_id"],
        "target_countries": countries,
        "cited_audience": int(row["audience_size_estimate"]),
        "sources_per_claim": max(1, len(sources)),
        "trend_direction": row.get("trend_direction", "stable"),
        "primary_jtbd_strength": 0.85,
        "source_quote": (row.get("emotional_charge", "") or "")[: 14 * 8].split(".")[0][:80],
        "produced_at": _now_iso(),
        "session_id": session_id,
        "total_score": None,
    }


def _validate_run_id(run_id: str) -> str | None:
    if not RUN_ID_RE.match(run_id):
        return f"run_id must match {RUN_ID_RE.pattern}; got {run_id!r}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transform v3 pool to Phase3Audience JSONL")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int, default=0, help="cap rows (0 = no cap)")
    args = parser.parse_args(argv)

    err = _validate_run_id(args.run_id)
    if err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 4

    pool_path = V4_RUNS_ROOT / args.run_id / "v3_audience_pool.jsonl"
    if not pool_path.is_file():
        print(f"FAIL: v3 pool not found at {pool_path}", file=sys.stderr)
        return 2

    out_path = V4_RUNS_ROOT / args.run_id / "03_audience_v4.jsonl"
    session_id = f"v4-smoke-{args.run_id}"
    written = 0
    with (
        pool_path.open("r", encoding="utf-8") as f_in,
        out_path.open("w", encoding="utf-8") as f_out,
    ):
        for raw_line in f_in:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            phase3 = _v3_pool_to_phase3(row, session_id)
            f_out.write(json.dumps(phase3, ensure_ascii=False) + "\n")
            written += 1
            if args.limit and written >= args.limit:
                break

    summary = {
        "run_id": args.run_id,
        "pool_path": str(pool_path),
        "out_path": str(out_path),
        "rows_written": written,
        "session_id": session_id,
    }
    print(json.dumps(summary, indent=2))
    return 0 if written else 5


if __name__ == "__main__":
    sys.exit(main())
