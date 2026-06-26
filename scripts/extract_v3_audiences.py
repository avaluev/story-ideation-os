"""V4A-004 Stage 2 — extract v3.1-pathc-a4 audience data into v4-consumable JSONL.

Parses every brief under `out/concepts/v3.1-pathc-a4/<concept_id>.md`,
extracts audience+JTBD+asset facts, and writes a Phase3-shaped JSONL
to `data/runs/v4-genius-cc/<run_id>/v3_audience_pool.jsonl` so the v4
phase-4-forger can consume it without re-running mining/mapping.

This is the read-only bridge between v3.1 outputs and v4 forge inputs.
NEVER writes to a v3.1 path. Pre-flight gate enforced via
`scripts/v4_preflight.py` before invocation.

Usage::

    uv run python scripts/extract_v3_audiences.py --run-id 20260510T040000Z

The output rows are shaped to satisfy the v4 phase-4-forger's input
contract (asset_id, audience_size_estimate, audience_size_source_url,
country_breakdown, jtbd_segment_id, asset_name, asset_type) plus a
`v3_concept_id` field for one-to-one comparison provenance.

Cost: zero. Pure-Python markdown parser, no LLM calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

V3_BRIEFS_ROOT = Path("out/concepts/v3.1-pathc-a4")
V4_RUNS_ROOT = Path("data/runs/v4-genius-cc")
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")

# Phase 3 audience floor (mirrors evals/test_audience.py and v3 sidecar contract).
AUDIENCE_FLOOR_MIN_PEOPLE = 50_000_000
COUNTRY_BREAKDOWN_MIN = 3

# Section parsers — each returns the body string between its header and the next H2.
H2_RE = re.compile(r"^## ([^\n]+)$", re.MULTILINE)
AUDIENCE_SIZE_RE = re.compile(r"Estimated audience:\s*([\d,]+)", re.IGNORECASE)
AUDIENCE_URL_RE = re.compile(
    r"\[Source[^\]]*\]\((https?://[^)]+)\)|source:\s*\[[^\]]+\]\((https?://[^)]+)\)"
)
COUNTRIES_RE = re.compile(r"Countries:\s*([A-Z]{2}(?:\s*,\s*[A-Z]{2})*)")
TREND_RE = re.compile(r"Trend:\s*(\w+)", re.IGNORECASE)
JTBD_BOLD_RE = re.compile(r"\*\*([a-z_]+)\*\*", re.IGNORECASE)
DEPRIVATION_RE = re.compile(r"Deprivation:\s*(.+?)(?=\n\n|\n##|\Z)", re.DOTALL)
ASSET_NAME_TYPE_RE = re.compile(r"\*\*([^*]+?)\*\*\s*\(([^)]+)\)")
ASSET_PRECEDENT_RE = re.compile(r"Precedent:\s*\[[^\]]+\]\((https?://[^)]+)\)")
EMOTIONAL_CHARGE_RE = re.compile(r"Emotional charge:\s*(.+?)(?=\n\n|\n##|\Z)", re.DOTALL)
SEED_RE = re.compile(r"\*\*Seed:\*\*\s*`(\d+)`")
CONCEPT_ID_RE = re.compile(r"\*\*Concept ID:\*\*\s*`([0-9a-f]+)`")


def _section_body(text: str, header: str) -> str:
    """Return body between `## {header}` and the next `## ` header."""
    pattern = re.compile(
        rf"^## {re.escape(header)}\n(.*?)(?=\n## [A-Z]|\Z)", re.DOTALL | re.MULTILINE
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _parse_brief(path: Path) -> dict[str, Any] | None:
    """Parse a single v3.1 brief into a v4-consumable audience row.
    Returns None if any required field is missing."""
    text = path.read_text(encoding="utf-8")

    cid_m = CONCEPT_ID_RE.search(text)
    seed_m = SEED_RE.search(text)
    if not (cid_m and seed_m):
        return None
    v3_concept_id = cid_m.group(1)
    seed_int = int(seed_m.group(1))

    audience_body = _section_body(text, "Audience Size & Evidence")
    asize_m = AUDIENCE_SIZE_RE.search(audience_body)
    aurl_m = AUDIENCE_URL_RE.search(audience_body)
    countries_m = COUNTRIES_RE.search(audience_body)
    trend_m = TREND_RE.search(audience_body)
    if not (asize_m and aurl_m and countries_m):
        return None
    audience_size = int(asize_m.group(1).replace(",", ""))
    audience_url = aurl_m.group(1) or aurl_m.group(2)
    countries = [c.strip() for c in countries_m.group(1).split(",")]
    trend = trend_m.group(1).lower() if trend_m else "stable"

    jtbd_body = _section_body(text, "JTBD")
    jtbd_m = JTBD_BOLD_RE.search(jtbd_body)
    deprivation_m = DEPRIVATION_RE.search(jtbd_body)
    jtbd_segment_id = jtbd_m.group(1) if jtbd_m else "unknown"
    deprivation = deprivation_m.group(1).strip() if deprivation_m else ""

    asset_body = _section_body(text, "Asset")
    asset_m = ASSET_NAME_TYPE_RE.search(asset_body)
    asset_name = asset_m.group(1).strip() if asset_m else ""
    asset_type = asset_m.group(2).strip() if asset_m else ""
    precedent_m = ASSET_PRECEDENT_RE.search(asset_body)
    precedent_url = precedent_m.group(1) if precedent_m else None
    emotional_m = EMOTIONAL_CHARGE_RE.search(asset_body)
    emotional_charge = emotional_m.group(1).strip() if emotional_m else ""

    if not (
        audience_size >= AUDIENCE_FLOOR_MIN_PEOPLE
        and len(countries) >= COUNTRY_BREAKDOWN_MIN
        and asset_name
    ):
        return None

    # asset_id is deterministic from (v3_concept_id, asset_name) so re-runs
    # produce identical outputs (idempotency for resume).
    asset_seed = f"{v3_concept_id}|{asset_name}".encode()
    asset_id = "v4-asset-" + hashlib.sha1(asset_seed, usedforsecurity=False).hexdigest()[:12]

    # Build the v4-shaped audience row. country_breakdown is approximated from
    # the single source URL since v3 didn't capture per-country sizes.
    per_country_size = audience_size // len(countries)
    country_breakdown = [
        {"country_iso2": c, "size": per_country_size, "source_url": audience_url} for c in countries
    ]

    return {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": asset_type,
        "precedent_url": precedent_url,
        "emotional_charge": emotional_charge,
        "audience_size_estimate": audience_size,
        "audience_size_source_url": audience_url,
        "country_breakdown": country_breakdown,
        "trend_direction": trend,
        "jtbd_segment_id": jtbd_segment_id,
        "deprivation_lens": deprivation,
        "seed_used": seed_int,
        "v3_concept_id": v3_concept_id,
        "v3_brief_path": str(path),
        "source_pipeline": "v3.1-pathc-a4",
    }


def _validate_run_id(run_id: str) -> str | None:
    if not RUN_ID_RE.match(run_id):
        return f"run_id must match {RUN_ID_RE.pattern}; got {run_id!r}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract v3.1 briefs into v4 audience JSONL")
    parser.add_argument(
        "--run-id", required=True, help="ISO-8601 compact run-id (YYYYMMDDTHHMMSSZ)"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="cap the number of rows extracted (0 = no cap)"
    )
    parser.add_argument(
        "--briefs-root",
        default=str(V3_BRIEFS_ROOT),
        help="override v3 briefs root (default: out/concepts/v3.1-pathc-a4)",
    )
    args = parser.parse_args(argv)

    err = _validate_run_id(args.run_id)
    if err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 4

    briefs_root = Path(args.briefs_root)
    if not briefs_root.is_dir():
        print(f"FAIL: briefs root {briefs_root} not a directory", file=sys.stderr)
        return 2

    run_dir = V4_RUNS_ROOT / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "v3_audience_pool.jsonl"

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for brief in sorted(briefs_root.glob("*.md")):
        row = _parse_brief(brief)
        if row is None:
            skipped.append(brief.name)
            continue
        rows.append(row)
        if args.limit and len(rows) >= args.limit:
            break

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "run_id": args.run_id,
        "briefs_root": str(briefs_root),
        "out_path": str(out_path),
        "total_briefs": len(list(briefs_root.glob("*.md"))),
        "extracted": len(rows),
        "skipped": len(skipped),
        "skipped_first_10": skipped[:10],
    }
    print(json.dumps(summary, indent=2))
    return 0 if rows else 5


if __name__ == "__main__":
    sys.exit(main())
