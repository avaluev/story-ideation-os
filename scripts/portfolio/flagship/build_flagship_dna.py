#!/usr/bin/env python3
"""Build the FLAGSHIP deepening DNA set from fresh engine portfolio runs.

Deterministic. No LLM calls. Maps the engine's portfolio-concept schema onto the
DNA-file contract the depth tournament consumes (economics_FIXED / dna_FIXED /
comps_FIXED / demand_evidence_FIXED), dedupes every (world, wound) combination
against the existing verified 18-slate, drops junk-scored concepts, and keeps the
highest crystallization_score concepts per the live investor_v2 taste contract.

Usage:
  uv run python scripts/portfolio/flagship/build_flagship_dna.py \
      runs/portfolio/20260530T191511Z-portfolio.json \
      runs/portfolio/20260530T191848Z-portfolio.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "outputs" / "portfolio" / "flagship" / "_dna"
EXISTING_DNA = ROOT / "outputs" / "portfolio" / "depth" / "_dna"

SCORE_FLOOR = 0.62  # drop the engine's below-quality tail (junk landed ~0.19)
TARGET_N = 20  # cap the fresh deepening set (keeps the depth tournament bounded)


def _existing_pairs() -> set[tuple[str, str]]:
    """(world_texture, format) pairs already deepened+shipped in the verified 18-slate.

    Deduping at (world, format) — not (world, wound) — forces genuine seed-novelty
    against the shipped slate: a fresh concept survives only if it is a NEW world or
    a NEW format-pairing of a known world (e.g. an 'alien ecosystem' that the shipped
    slate had only as a $22M microdrama, now surfacing as a $675M animation feature).
    """
    pairs: set[tuple[str, str]] = set()
    for f in sorted(EXISTING_DNA.glob("idea_*.json")):
        d = json.loads(f.read_text())
        w = (d.get("dna_FIXED", {}).get("world_texture") or "").strip().lower()
        fmt = (d.get("format") or "").strip().lower()
        pairs.add((w, fmt))
    return pairs


def _comp_block(comps: list[dict]) -> list[dict]:
    out = []
    for c in comps or []:
        out.append(
            {
                "title": c.get("title"),
                "year": c.get("release_year") or c.get("year"),
                "ww_gross_usd": c.get("worldwide_gross_usd") or c.get("ww_gross_usd"),
                "budget_usd": c.get("budget_usd"),
                "roi": c.get("roi"),
                "genres": c.get("genres"),
                "boxofficemojo_url": c.get("boxofficemojo_url"),
                "imdb_url": c.get("imdb_url"),
            }
        )
    return out


def _to_dna(c: dict) -> dict:
    sa = c.get("seed_axes", {}) or {}
    wt = sa.get("world_texture", {}) or {}
    wound = sa.get("sdt_wound", {}) or {}
    inv = sa.get("structural_inversion", {}) or {}
    mfl = sa.get("moral_fault_line", {}) or {}
    return {
        "format": c.get("format"),
        "economics_key": c.get("economics_key"),
        "monetization_model": c.get("monetization_model"),
        "placeholder_title": c.get("working_title") or c.get("title"),
        "current_title": c.get("working_title") or c.get("title"),
        "engine_logline": c.get("engine_logline"),
        "economics_FIXED": {
            "som_y1_usd": c.get("som_y1_usd"),
            "som_y1_low_usd": c.get("som_y1_low_usd"),
            "som_y1_high_usd": c.get("som_y1_high_usd"),
            "lifetime_usd": c.get("lifetime_usd"),
            "sam_usd": c.get("sam_usd"),
            "tam_usd": c.get("tam_usd"),
            "tam_source_url": c.get("tam_source_url"),
            "calculation_method": c.get("calculation_method", "python_executed"),
        },
        "crystallization_score": c.get("crystallization_score"),
        "standalone_ip_flag": c.get("standalone_ip_flag"),
        "genres": c.get("genres", []),
        "dna_FIXED": {
            "world_texture": wt.get("name"),
            "world_domain_tags": wt.get("domain_tags"),
            "thematic_cluster": wt.get("thematic_cluster"),
            "sdt_need": wound.get("need"),
            "sdt_wound": wound.get("description"),
            "structural_inversion": inv.get("description"),
            "moral_dilemma": mfl.get("description"),
            "audience_resonance_M": wound.get("audience_resonance_M"),
            "wound_commercial_proof": wound.get("commercial_proof"),
            "inversion_commercial_proof": inv.get("commercial_proof"),
        },
        "comps_FIXED": _comp_block(c.get("comps", [])),
        "demand_evidence_FIXED": c.get("demand_evidence", []),
    }


def main() -> None:
    runs = [Path(p) for p in sys.argv[1:]]
    if not runs:
        raise SystemExit("pass one or more portfolio JSON paths")

    existing = _existing_pairs()
    best_by_pair: dict[tuple[str, str], dict] = {}
    for run in runs:
        payload = json.loads(run.read_text())
        for c in payload.get("concepts", []):
            score = c.get("crystallization_score") or 0.0
            if score < SCORE_FLOOR:
                continue
            sa = c.get("seed_axes", {}) or {}
            w = (sa.get("world_texture", {}) or {}).get("name", "").strip().lower()
            fmt = (c.get("format") or "").strip().lower()
            pair = (w, fmt)
            if pair in existing:  # already shipped at this world+format — skip
                continue
            prev = best_by_pair.get(pair)
            if prev is None or score > (prev.get("crystallization_score") or 0.0):
                best_by_pair[pair] = c  # keep the highest-score concept per world+format

    pool = list(best_by_pair.values())
    # Highest investor_v2 score first (score already weights SOM 0.28).
    pool.sort(key=lambda c: c.get("crystallization_score") or 0.0, reverse=True)
    pool = pool[:TARGET_N]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for i, c in enumerate(pool, start=1):
        dna = _to_dna(c)
        dna["idx"] = i
        fname = f"idea_{i:02d}.json"
        (OUT_DIR / fname).write_text(json.dumps(dna, indent=1, ensure_ascii=False))
        index.append(
            {
                "idx": i,
                "file": f"outputs/portfolio/flagship/_dna/{fname}",
                "format": dna["format"],
                "current_title": dna["current_title"],
                "som_y1_usd": dna["economics_FIXED"]["som_y1_usd"],
                "world": dna["dna_FIXED"]["world_texture"],
                "cluster": dna["dna_FIXED"]["thematic_cluster"],
                "score": dna["crystallization_score"],
            }
        )
    (OUT_DIR / "_index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False))

    by_fmt: dict[str, int] = {}
    for it in index:
        by_fmt[it["format"]] = by_fmt.get(it["format"], 0) + 1
    print(f"Wrote {len(index)} fresh, combination-distinct DNA files to {OUT_DIR}")
    for fmt, n in sorted(by_fmt.items()):
        soms = [it["som_y1_usd"] for it in index if it["format"] == fmt]
        print(f"  {fmt:18} {n:2}  SOM ${min(soms) / 1e6:.0f}M..${max(soms) / 1e6:.0f}M")


if __name__ == "__main__":
    main()
