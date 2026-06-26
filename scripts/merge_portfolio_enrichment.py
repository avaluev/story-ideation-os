"""scripts/merge_portfolio_enrichment.py — fold workflow enrichment into the portfolio.

Reads the portfolio JSON (from :mod:`scripts.build_portfolio`) and an enrichment
JSON produced by the enrichment/review workflow — a list of
``{"id": <concept id>, "enrichment": {...}, "demand_evidence": [...]}`` — and
writes an enriched portfolio JSON the slate/HTML builders consume.

Per concept it sets ``concept["enrichment"]`` (title/tagline/logline/story/
why_now/audience/revenue_thesis/risk) and ``concept["demand_evidence"]`` (the
deep-linked proof rows). Demand rows that fail the deep-link evidence policy are
dropped here (never silently shipped). Pure I/O — no LLM, no network.

    uv run python -m scripts.merge_portfolio_enrichment PORTFOLIO.json ENRICH.json [OUT.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pipeline.crystallize import portfolio as pf

#: Free-text enrichment fields (everything except demand_evidence).
_PROSE_FIELDS = (
    "title",
    "tagline",
    "logline",
    "story",
    "what_different",
    "why_now",
    "audience",
    "revenue_thesis",
    "risk",
)


def _index_enrichment(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = str(row.get("id", ""))
        if cid:
            out[cid] = row
    return out


def _clean_demand(rows: object) -> list[dict[str, Any]]:
    """Keep only demand rows that satisfy the deep-link evidence policy."""
    if not isinstance(rows, list):
        return []
    kept: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict) and pf.validate_demand_evidence(r)[0]:
            kept.append(
                {
                    "claim": str(r.get("claim", "")).strip(),
                    "stat": str(r.get("stat", "")).strip(),
                    "source_url": str(r.get("source_url", "")).strip(),
                    "date": str(r.get("date", "")).strip(),
                }
            )
    return kept


def merge(portfolio_json: Path, enrichment_json: Path, out_json: Path) -> dict[str, Any]:
    pdata = json.loads(Path(portfolio_json).read_text(encoding="utf-8"))
    edata = json.loads(Path(enrichment_json).read_text(encoding="utf-8"))
    rows = (
        edata if isinstance(edata, list) else list(edata.get("results", edata.get("enriched", [])))
    )
    by_id = _index_enrichment(rows)

    matched = 0
    demand_total = 0
    for c in pdata.get("concepts", []):
        row = by_id.get(str(c.get("id", "")))
        if not row:
            continue
        enr_raw = row.get("enrichment")
        enr: dict[str, Any] = enr_raw if isinstance(enr_raw, dict) else row
        prose = {
            k: str(enr.get(k, "")).strip() for k in _PROSE_FIELDS if str(enr.get(k, "")).strip()
        }
        if prose:
            c["enrichment"] = prose
            matched += 1
        demand = _clean_demand(enr.get("demand_evidence") or row.get("demand_evidence"))
        if demand:
            c["demand_evidence"] = demand
            demand_total += len(demand)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(pdata, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return {
        "concepts": len(pdata.get("concepts", [])),
        "enriched": matched,
        "demand_rows_kept": demand_total,
        "out": str(out_json),
    }


_REQUIRED_ARGV = 3  # script + portfolio.json + enrichment.json


def main() -> None:
    if len(sys.argv) < _REQUIRED_ARGV:
        raise SystemExit(
            "usage: merge_portfolio_enrichment <portfolio.json> <enrichment.json> [out.json]"
        )
    portfolio_json = Path(sys.argv[1])
    enrichment_json = Path(sys.argv[2])
    out_json = (
        Path(sys.argv[_REQUIRED_ARGV])
        if len(sys.argv) > _REQUIRED_ARGV
        else portfolio_json.with_name("portfolio_enriched.json")
    )
    print(json.dumps(merge(portfolio_json, enrichment_json, out_json), indent=2))


if __name__ == "__main__":
    main()
