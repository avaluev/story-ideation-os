"""Apply 302.ai source judgments to the flagship slate, then regrade online.

The convergence step of the verified-delivery pipeline:

  1. ``render_inline`` injects each verified source URL into its card (comp-table
     title linkify / prose citation) — byte-identical ``$`` (ADR-0011).
  2. the existing veracity CLI re-enumerates the now-linked card, probes every
     cited URL live (``--online``), folds in the agent ``--judgments`` (supports
     + verbatim quote), and writes ``<card>.CREDIBILITY.md`` + ``.veracity.json``.

Produces a per-card + slate grade/density report. No ``$`` figure is ever
touched; unsourced claims simply stay UNVERIFIED (operator's drop choice).

Usage:
    uv run python -m scripts.apply_source_claims \
        --dir outputs/portfolio/flagship \
        --judgments runs/veracity/judgments_302.json \
        --out outputs/veracity [--offline]
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.state import safe_write
from pipeline.veracity.__main__ import main as veracity_main
from pipeline.veracity.render_inline import render_inline


def _load_judgments(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    inner = raw.get("judgments", raw) if isinstance(raw, dict) else {}
    return inner if isinstance(inner, dict) else {}


def _read_score(out_dir: Path, stem: str) -> dict[str, Any]:
    p = out_dir / f"{stem}.veracity.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("scorecard", {})
    except (json.JSONDecodeError, OSError):
        return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply source judgments + regrade the slate.")
    ap.add_argument("--dir", default="outputs/portfolio/flagship")
    ap.add_argument("--judgments", default="runs/veracity/judgments_302.json")
    ap.add_argument("--out", default="outputs/veracity")
    ap.add_argument("--offline", action="store_true", help="skip live probing (structural only)")
    args = ap.parse_args(argv)

    judgments = _load_judgments(Path(args.judgments))
    cards = sorted(Path(p) for p in glob.glob(str(Path(args.dir) / "[0-9]*.md")))
    print(
        f"applying {len(judgments)} judgments across {len(cards)} cards (online={not args.offline})"
    )

    rows: list[tuple[str, float, str, float, int]] = []
    injected_total = 0
    for card in cards:
        md = card.read_text(encoding="utf-8")
        new_md = render_inline(md, judgments, concept_id=card.stem)
        if new_md != md:
            injected_total += 1
            safe_write(card, new_md)
        cli = [str(card), "--card", "--judgments", args.judgments, "--out", args.out]
        if not args.offline:
            cli.append("--online")
        veracity_main(cli)
        sc = _read_score(Path(args.out), card.stem)
        rows.append(
            (
                card.stem,
                float(sc.get("composite", 0.0)),
                str(sc.get("grade", "?")),
                float(sc.get("deep_link_pct", 0.0)),
                int(sc.get("fabricated_count", 0)),
            )
        )

    rows.sort(key=lambda r: -r[1])
    print("\n=== per-card (sorted by composite) ===")
    for stem, comp, grade, dl, fab in rows:
        print(f"  {stem:18s} {comp:5.1f} {grade:>2s}  deep-link {dl:5.1f}%  fab {fab}")

    n = len(rows) or 1
    mean = sum(r[1] for r in rows) / n
    a_grade = sum(1 for r in rows if r[2] == "A")
    fab = sum(r[4] for r in rows)
    summary = {
        "cards": len(rows),
        "cards_with_injection": injected_total,
        "mean_composite": round(mean, 1),
        "grade_A": a_grade,
        "fabricated_total": fab,
        "per_card": [
            {"card": s, "composite": c, "grade": g, "deep_link_pct": d, "fabricated": f}
            for s, c, g, d, f in rows
        ],
    }
    safe_write(Path(args.out) / "_slate_regrade.json", json.dumps(summary, indent=2))
    print(f"\nslate: mean {mean:.1f} | grade-A {a_grade}/{len(rows)} | fabricated {fab}")
    print(f"-> {args.out}/_slate_regrade.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
