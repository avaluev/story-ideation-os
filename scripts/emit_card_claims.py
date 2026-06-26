#!/usr/bin/env python3
"""Emit the per-claim sourcing manifest for the ``source-claims`` workflow.

Enumerates every EXTERNAL claim across a slate of rendered concept cards (using
the section-aware ``pipeline.veracity.enumerate``) and writes a manifest the
guarded live-sourcing workflow consumes — one row per claim that needs a primary
source + verbatim quote. COMPUTED economics (SAM/SOM/lifetime) and narrative are
excluded (they are not URL-sourced). Pure/offline — no network, no LLM.

Usage::

    uv run python -m scripts.emit_card_claims \\
        --dir outputs/portfolio/flagship --out outputs/portfolio/flagship/_claims_manifest.json
    # then (operator-gated): launch the source-claims workflow with the manifest as args.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.veracity.enumerate import enumerate_claims  # noqa: E402

#: Where to look first for each claim type (the workflow's finder prompt refines).
_TIER_HINT: dict[str, str] = {
    "comp_roi": "Box Office Mojo / The Numbers title page (worldwide gross + budget)",
    "market_tam": "MPA THEME report / Ampere / Omdia market-size primary",
    "cultural_signal": "Pew / Gallup / KFF / government survey with the exact %",
    "box_office": "Variety / Deadline / THR box-office article (deep path)",
    "demand": "Parrot Analytics / Nielsen / trade demand figure (deep path)",
    "market_claim": "MPA / Ampere / Parrot report substantiating the superlative",
}


def _title_of(md: str, stem: str) -> str:
    m = re.search(r"^#\s+(.+)$", md, flags=re.MULTILINE)
    return m.group(1).strip() if m else stem


def build_manifest(card_dir: Path, only: set[str] | None) -> dict[str, object]:
    claims: list[dict[str, str]] = []
    cards = sorted(card_dir.glob("[0-9]*.md"))
    for card in cards:
        if only and card.stem not in only:
            continue
        md = card.read_text(encoding="utf-8")
        title = _title_of(md, card.stem)
        for c in enumerate_claims(md, concept_id=card.stem, concept_title=title):
            if c.is_computed:
                continue
            claims.append(
                {
                    "claim_id": c.claim_id,
                    "card": card.name,
                    "title": title,
                    "claim_type": c.claim_type,
                    "text": c.text,
                    "value": c.value,
                    "tier_hint": _TIER_HINT.get(c.claim_type, ""),
                }
            )
    return {"source_dir": str(card_dir), "n_cards": len(cards), "claims": claims}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.emit_card_claims")
    p.add_argument("--dir", default="outputs/portfolio/flagship", help="directory of NN_*.md cards")
    p.add_argument(
        "--out", default="", help="manifest JSON output path (default: <dir>/_claims_manifest.json)"
    )
    p.add_argument(
        "--cards", default="", help="comma-separated card stems to limit to (e.g. 04_tremor)"
    )
    args = p.parse_args(argv)

    card_dir = Path(args.dir)
    if not card_dir.is_dir():
        print(f"no such directory: {card_dir}", file=sys.stderr)
        return 2
    only = {s.strip() for s in args.cards.split(",") if s.strip()} or None
    manifest = build_manifest(card_dir, only)
    out = Path(args.out) if args.out else card_dir / "_claims_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    n = len(manifest["claims"])  # type: ignore[arg-type]
    print(f"Wrote {n} external claims from {manifest['n_cards']} cards -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
