#!/usr/bin/env python3
"""Anchor rigorous, python-executed economics onto the hostile-gated WIDEN survivors.

The widen survivors are genuinely-original, kill-switch-passed concepts that carry
NO economics (creative-stage only). This step prices each one through the SAME engine
revenue machinery the verified slate uses — ``project_revenue`` + ``match_comps`` over
the live films corpus — so a fresh, original world ("digital-erasure-as-a-service",
a "tontine") gets a defensible SOM<SAM<TAM off REAL comparable films, never a guess.

Deterministic. Editorial genre tags (a producer's judgment, not a fabricated number)
drive comp retrieval; every dollar figure is computed by the engine, not written here.

Usage:
  uv run python scripts/portfolio/flagship/anchor_widen_economics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pipeline.crystallize.comps import match_comps  # noqa: E402
from pipeline.crystallize.corpus import FilmsCorpus  # noqa: E402
from pipeline.crystallize.revenue import ProjectionContext, project_revenue  # noqa: E402

WIDEN_RESULT = ROOT / "outputs" / "portfolio" / "depth" / "widen" / "_widen_result.json"
OUT_DIR = ROOT / "outputs" / "portfolio" / "flagship" / "_widen_dna"

# Widen format string -> engine economics_key.
FORMAT_KEY = {
    "limited series": "limited_series",
    "returning series": "returning_series",
    "film": "feature",
    "feature": "feature",
    "feature film": "feature",
    "animation": "animation_feature",
    "adult animated feature": "animation_feature",
    "animation feature": "animation_feature",
    "animation series": "animation_series",
    "microdrama": "microdrama",
}

# Cluster -> defensible IMDb-style genres (editorial; mirrors the engine's
# _CLUSTER_GENRE_HINTS philosophy). Animation formats prepend animation/family.
CLUSTER_GENRES = {
    "technology": ["drama", "thriller", "sci-fi"],
    "identity": ["drama", "mystery"],
    "economic": ["drama", "thriller"],
    "civilizational": ["drama", "sci-fi", "thriller"],
    "nature": ["drama", "thriller", "adventure"],
    "temporal": ["drama", "sci-fi"],
    "emotional": ["drama", "romance"],
    "institutional": ["drama", "thriller"],
}


def _genres_for(cluster: str, eco_key: str) -> list[str]:
    base = list(CLUSTER_GENRES.get(cluster.lower(), ["drama"]))
    if eco_key in ("animation_feature", "animation_series"):
        return ["animation", "family", "adventure", *base]
    return base


def _anchor(survivor: dict, corpus: FilmsCorpus) -> dict:
    cluster = survivor.get("cluster", "")
    fmt_raw = (survivor.get("format") or "").strip().lower()
    eco_key = FORMAT_KEY.get(fmt_raw, "feature")
    genres = _genres_for(cluster, eco_key)

    world_name = (
        (survivor.get("title") or "")
        + " — "
        + (survivor.get("logline") or survivor.get("high_concept_25w") or "")
    )
    candidate = {
        "genres": genres,
        "world_texture": {"name": world_name},
        "scores": {"primary_cluster": cluster},
        "audiences": [],
    }
    ctx = ProjectionContext(window="auto", geo="global", content_format=eco_key)
    proj = project_revenue(candidate, corpus, ctx=ctx)
    comp_match = match_comps(candidate, corpus, k=5)

    return {
        "title": survivor.get("title"),
        "format": survivor.get("format"),
        "economics_key": eco_key,
        "cluster": cluster,
        "genres_used": genres,
        "logline": survivor.get("logline"),
        "high_concept_25w": survivor.get("high_concept_25w"),
        "verdict": survivor.get("verdict"),
        "widen_score": survivor.get("score"),
        "has_treatment": bool(survivor.get("concept_markdown")),
        "economics_FIXED": {
            "som_y1_usd": proj.som_y1_usd,
            "lifetime_usd": (proj.assumptions or {}).get("lifetime_som_y1_usd"),
            "sam_usd": proj.sam_usd,
            "tam_usd": proj.tam_usd,
            "calculation_method": proj.calculation_method,
            "n_comps_used": (proj.assumptions or {}).get("n_comps_used"),
        },
        "comps_FIXED": comp_match.get("comps", []),
        "derivative_distance": comp_match.get("derivative_distance"),
    }


def main() -> None:
    data = json.loads(WIDEN_RESULT.read_text())
    cryst = {c["title"]: c for c in data.get("crystallised", [])}
    # union of crystallised (full treatments) + STRONG_PASS ranked survivors
    survivors: dict[str, dict] = {}
    for c in data.get("ranked", []):
        if c.get("verdict") == "STRONG_PASS":
            survivors[c["title"]] = {
                **c,
                "concept_markdown": cryst.get(c["title"], {}).get("concept_markdown"),
            }
    for t, c in cryst.items():
        survivors.setdefault(t, c)

    corpus = FilmsCorpus.load()
    corpus.enable_semantic_comps()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (_title, s) in enumerate(
        sorted(survivors.items(), key=lambda kv: -(kv[1].get("score") or 0)), 1
    ):
        anchored = _anchor(s, corpus)
        if anchored["has_treatment"]:
            (OUT_DIR / f"widen_{i:02d}.json").write_text(
                json.dumps(
                    {**anchored, "concept_markdown": s.get("concept_markdown")},
                    indent=1,
                    ensure_ascii=False,
                )
            )
        rows.append({k: v for k, v in anchored.items() if k != "concept_markdown"})

    (OUT_DIR / "_index.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))

    n_tre = sum(1 for r in rows if r["has_treatment"])
    print(f"Anchored {len(rows)} widen survivors ({n_tre} with full treatments):")
    for r in sorted(rows, key=lambda r: -(r["economics_FIXED"]["som_y1_usd"] or 0)):
        som = r["economics_FIXED"]["som_y1_usd"]
        soms = f"${som / 1e6:.0f}M" if som else "  n/a"
        tre = "TREATMENT" if r["has_treatment"] else "logline  "
        print(f"  {soms:>7}  {tre}  [{r['format']!s:16}] {r['cluster']:14} {r['title']}")


if __name__ == "__main__":
    main()
