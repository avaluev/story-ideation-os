"""scripts/build_portfolio.py — generate a diversified MULTI-CONCEPT portfolio.

The v5.2 superset of the single-best-per-format slate. For each of the 6
content formats it generates a large candidate batch (format pinned), prices
each with the live goal + per-format economics + de-franchise flag, applies the
per-format SOM floor + standalone-IP hard filter, and keeps the top-K
**distinct** concepts (no two share a world or a wound — see
:mod:`pipeline.crystallize.portfolio`). It then assigns **distinct** comps
across the whole portfolio (fixing the cross-card comp-reuse defect) and,
optionally, generates a real 302.ai premise per winning concept.

Selection is offline + deterministic (python_executed economics, ADR-0011); the
optional ``--premise-302`` step is the only network call and only touches the
final winners (K * 6 calls, not the whole batch).

    # offline selection only (fast, reproducible):
    TAO_AI_API_KEY= TAO_AI_PRIMARY= OPENROUTER_API_KEY= OPENROUTER_KEY_PAID= \
        uv run python -m scripts.build_portfolio --per-format 3

    # add live 302.ai premise prose to the 18 winners:
    uv run python -m scripts.build_portfolio --per-format 3 --premise-302
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline import diversity
from pipeline.compound_seed import CompoundSeedEngine
from pipeline.crystallize import format_economics as fe
from pipeline.crystallize import portfolio as pf
from pipeline.crystallize.comps import match_comps
from pipeline.crystallize.corpus import FilmsCorpus
from pipeline.crystallize.revenue import ProjectionContext, RevenueProjection, project_revenue
from pipeline.crystallize.score import crystallization_score
from pipeline.empirical_genius import detect_standalone_ip
from pipeline.goal import Goal
from pipeline.state import safe_write

# Reuse the slate's tuned per-format themes, SOM floors, title/logline helpers.
from scripts.run_format_slate import (
    _BASE_SEED,
    _FORMAT_THEMES,
    PER_FORMAT_SOM_FLOOR_USD,
    _logline,
    _title,
)

_USD_M = 1_000_000.0
#: Wide per-concept comp pool so the portfolio-level distinct assignment has
#: room to give every card a unique lead set.
_COMP_POOL_K = 18
#: Candidates to generate per format while hunting for K distinct winners.
_N_CANDIDATES = 90
#: How many SOM-ranked winners to echo in the selection summary line.
_SOM_PREVIEW_N = 8
#: Engine seed-axis nodes carried into each concept for dedup + enrichment.
_SEED_AXES = ("world_texture", "sdt_wound", "structural_inversion", "moral_fault_line")


def som_band(
    som_val: float, p10: float | None, p50: float | None, p90: float | None
) -> tuple[float, float]:
    """Conservative/upside SOM band for one concept.

    Scales the model's raw comp log-quantiles (p10/p90) by the same
    window x geo x audience derate that produced the p50 SOM, so a reader gets a
    defensible three-point estimate instead of a single optimistic floor.
    Non-theatrical formats price off fixed economics (no comp distribution),
    so the band collapses to the point figure.
    """
    if p50 and p50 > 0 and p10 and p90:
        derate = som_val / p50
        return (round(p10 * derate, 2), round(p90 * derate, 2))
    return (round(som_val, 2), round(som_val, 2))


def _concept_dict(
    c_dict: dict[str, Any],
    *,
    eco_key: str,
    proj: RevenueProjection,
    cs: float,
    standalone: bool | None,
    corpus: FilmsCorpus,
) -> dict[str, Any]:
    """Assemble one portfolio concept (economics python_executed; comp pool
    wide for later distinct assignment; seed axes carried for enrichment)."""
    profile = fe.FORMAT_PROFILES[eco_key]
    display = profile.display_name
    comp_match = match_comps(c_dict, corpus, k=_COMP_POOL_K)
    tam_src = str(proj.assumptions.get("tam_source") or "")
    if not tam_src.startswith("https://"):
        tam_src = profile.tam_source_url
    # som is guaranteed non-None here (the caller drops sub-floor candidates).
    som_val = float(proj.som_y1_usd or 0.0)
    lifetime_val = float(proj.assumptions.get("lifetime_som_y1_usd") or som_val)
    som_low, som_high = som_band(som_val, proj.p10_usd, proj.p50_usd, proj.p90_usd)
    return {
        "economics_key": eco_key,
        "format": display,
        "monetization_model": profile.monetization_model,
        "working_title": _title(c_dict),
        "title": _title(c_dict),  # replaced by enrichment
        "engine_logline": _logline(c_dict, display),
        "engine_premise": "",  # filled by --premise-302
        "som_y1_low_usd": som_low,
        "som_y1_usd": round(som_val, 2),
        "som_y1_high_usd": som_high,
        "lifetime_usd": round(lifetime_val, 2),
        "sam_usd": proj.sam_usd,
        "tam_usd": proj.tam_usd,
        "tam_source_url": tam_src,
        "crystallization_score": round(cs, 4),
        "standalone_ip_flag": standalone,
        "calculation_method": proj.calculation_method,
        "comps": comp_match.get("comps", []),
        "genres": comp_match.get("query_genres", []),
        "seed_axes": {a: c_dict.get(a) for a in _SEED_AXES},
        "demand_evidence": [],
        "enrichment": {},
    }


def _candidates_for_format(
    eco_key: str,
    *,
    corpus: FilmsCorpus,
    goal: Goal,
    n: int,
    seed_offset: int,
    freq_table: dict[tuple[str, str], int],
) -> list[dict[str, Any]]:
    """Generate ``n`` candidates with the format pinned; return every concept
    that clears the per-format SOM floor and the standalone-IP filter."""
    profile = fe.FORMAT_PROFILES[eco_key]
    display = profile.display_name
    problem, themes = _FORMAT_THEMES[eco_key]
    floor = PER_FORMAT_SOM_FLOOR_USD[eco_key]
    engine = CompoundSeedEngine(rng_seed=_BASE_SEED + seed_offset)

    concepts: list[dict[str, Any]] = []
    for _ in range(n):
        result = engine.generate(
            themes=themes,
            problems=[problem],
            force_format=display,
            max_attempts=12,
            freq_table=freq_table,
        )
        c_dict = result.to_dict()
        ctx = ProjectionContext(window="auto", geo="global", content_format=eco_key)
        proj = project_revenue(c_dict, corpus, ctx=ctx)
        som = proj.som_y1_usd
        if som is None or som < floor:
            continue
        standalone = detect_standalone_ip(_logline(c_dict, display), "")
        if standalone is False:
            continue
        scores_dict: dict[str, Any] = dict(result.scores.to_dict())
        scores_dict["som_y1_usd"] = som
        scores_dict["content_format"] = eco_key
        scores_dict["standalone_ip_flag"] = standalone
        cs = crystallization_score(scores_dict, goal=goal)
        concepts.append(
            _concept_dict(
                c_dict, eco_key=eco_key, proj=proj, cs=cs, standalone=standalone, corpus=corpus
            )
        )
    return concepts


def _fold_winners(freq_table: dict[tuple[str, str], int], winners: list[dict[str, Any]]) -> None:
    """Fold each winner's defining axes into the running penalty so subsequent
    picks (this format and the next) steer away — breaks cross-card duplicates."""
    for w in winners:
        for axis in _SEED_AXES:
            vid = str((w.get("seed_axes", {}).get(axis) or {}).get("id", ""))
            if vid:
                freq_table[(axis, vid)] = freq_table.get((axis, vid), 0) + 3


def _premise_via_302ai(concept: dict[str, Any]) -> str:
    """Generate a 150-250 word premise for a concept's exact seed axes via the
    shared 302.ai-primary chat client. Returns "" on any provider failure."""
    from pipeline.llm_client import build_chat_client  # noqa: PLC0415

    axes: dict[str, Any] = concept.get("seed_axes") or {}

    def _node(name: str, field: str) -> str:
        node = axes.get(name)
        return str(node.get(field, "")).strip() if isinstance(node, dict) else ""

    world = _node("world_texture", "name")
    wound = _node("sdt_wound", "description")
    inversion = _node("structural_inversion", "description")
    fault = _node("moral_fault_line", "description")
    fmt = str(concept.get("format", "Feature Film"))
    # chat() JSON-parses its response, so use an explicit JSON contract.
    prompt = (
        f"Write a 150-250 word premise for an original, standalone {fmt}. Plain English, "
        f"no framework jargon, no title. It MUST require all of these to be simultaneously "
        f"true:\n- World: {world}\n- Protagonist's wound: {wound}\n- Structural truth: "
        f"{inversion}\n- Impossible dilemma: {fault}\nMake it specific, character-first, and "
        f"emotionally precise — the kind of premise a studio would greenlight. "
        f'Return ONLY a JSON object of the form {{"premise": "<the premise>"}}.'
    )
    try:
        client = build_chat_client()
        resp = client.chat(
            "perplexity/sonar-pro",
            [{"role": "user", "content": prompt}],
            json_mode=True,
        )
        premise = resp.get("premise") if isinstance(resp, dict) else None
        return str(premise).strip() if premise else ""
    except Exception as exc:
        print(f"    (302.ai premise failed for {concept.get('working_title')!r}: {exc})")
        return ""


#: Provider env vars set to "" during candidate SELECTION so the engine uses the
#: fast template premise. NOTE: ``client_302ai`` calls ``load_dotenv()`` at import
#: (override=False), which RE-POPULATES any env var that is *absent* — so we must
#: set them to "" (present-but-empty survives the reload), never ``pop`` them. The
#: winners-only 302.ai premise step is a SEPARATE invocation
#: (:mod:`scripts.add_portfolio_premises`) with the real keys, so selection here
#: stays fully offline regardless of how it is launched.
_LLM_ENV: tuple[str, ...] = (
    "TAO_AI_API_KEY",
    "TAO_AI_PRIMARY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_KEY_PAID",
)


def _assign_ids(winners: list[dict[str, Any]]) -> dict[str, int]:
    """Stamp ``id`` = ``{economics_key}-{n}`` per winner; return per-format counts."""
    counts: dict[str, int] = {}
    for w in winners:
        eco = str(w.get("economics_key", "x"))
        counts[eco] = counts.get(eco, 0) + 1
        w["id"] = f"{eco}-{counts[eco]}"
    return counts


def build_portfolio(
    *,
    per_format: int,
    n_candidates: int,
    rank_by: str = "balanced",
    top_n: int | None = None,
    max_per_format: int | None = None,
) -> dict[str, Any]:
    import os  # noqa: PLC0415 — local: env juggling is confined to this entry point

    for k in _LLM_ENV:  # selection always runs offline (template premise — fast)
        os.environ[k] = ""  # "" survives client_302ai's load_dotenv(override=False)

    corpus = FilmsCorpus.load()
    enabled = corpus.enable_semantic_comps()
    goal = Goal.load()
    freq_table: dict[tuple[str, str], int] = dict(diversity.load_frequency_table())

    all_winners: list[dict[str, Any]] = []
    pooled: list[dict[str, Any]] = []  # SOM-rank mode defers selection to one pool
    per_format_counts: dict[str, int] = {}
    # Cross-slate distinctness: a world_texture claimed by one format is HARD-
    # excluded from every later format, so the slate reads as N distinct worlds
    # rather than the same world wearing three format hats (the duplicate-cluster
    # failure a sophisticated investor catches). 21 worlds in the vocabulary vs
    # 18 slots leaves room. Wounds stay within-format only (sharing a wound across
    # distinct worlds does not read as a duplicate).
    claimed_worlds: set[str] = set()
    for i, eco_key in enumerate(fe.VALID_FORMATS):
        cands = _candidates_for_format(
            eco_key,
            corpus=corpus,
            goal=goal,
            n=n_candidates,
            seed_offset=i * 101,
            freq_table=freq_table,
        )
        if rank_by == "som":
            pooled.extend(cands)
            print(f"  {eco_key:18s} {len(cands)} candidates above floor (pooled for SOM rank)")
            continue
        winners = pf.select_topk_distinct(cands, per_format, seen={"world_texture": claimed_worlds})
        for w in winners:
            wid = str((w.get("seed_axes", {}).get("world_texture") or {}).get("id", ""))
            if wid:
                claimed_worlds.add(wid)
        _fold_winners(freq_table, winners)
        per_format_counts[eco_key] = len(winners)
        for j, w in enumerate(winners):
            w["id"] = f"{eco_key}-{j + 1}"
        all_winners.extend(winners)
        print(
            f"  {eco_key:18s} {len(winners)}/{per_format} distinct "
            f"(from {len(cands)} above floor)  "
            + ", ".join(f"${w['som_y1_usd'] / _USD_M:.0f}M" for w in winners)
        )

    # SOM-rank mode: pick the highest python-executed-SOM distinct concepts across
    # ALL formats at once (max credible headline), capped per format for diversity.
    if rank_by == "som":
        n_target = top_n if top_n is not None else per_format * len(fe.VALID_FORMATS)
        all_winners = pf.select_top_by_som(pooled, n_target, max_per_format=max_per_format)
        per_format_counts = _assign_ids(all_winners)
        print(
            f"\n  SOM-ranked top {len(all_winners)} of {len(pooled)} pooled "
            f"(cap {max_per_format}/format): "
            + ", ".join(f"${w['som_y1_usd'] / _USD_M:.0f}M" for w in all_winners[:_SOM_PREVIEW_N])
            + (" ..." if len(all_winners) > _SOM_PREVIEW_N else "")
        )

    # Portfolio-level distinct comps (trim wide pools to 4, minimal reuse).
    all_winners = pf.assign_distinct_comps(all_winners, k=4)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_label": "portfolio",
        "generated_at": ts,
        "semantic_comps_enabled": enabled,
        "per_format": per_format,
        "n_candidates": n_candidates,
        "rank_by": rank_by,
        "max_per_format": max_per_format,
        "premise_302": False,  # premises added by scripts.add_portfolio_premises (separate)
        "per_format_counts": per_format_counts,
        "concept_count": len(all_winners),
        "concepts": all_winners,
    }
    out_path = Path("runs/portfolio") / f"{ts}-portfolio.json"
    safe_write(out_path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    # A stable pointer to the newest portfolio for downstream steps.
    safe_write(Path("runs/portfolio/latest.json"), json.dumps({"path": str(out_path)}))
    print(f"\nPortfolio JSON: {out_path}  ({len(all_winners)} concepts)")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a diversified multi-concept portfolio.")
    ap.add_argument("--per-format", type=int, default=3, help="distinct concepts per format")
    ap.add_argument("--n-candidates", type=int, default=_N_CANDIDATES, help="batch size per format")
    ap.add_argument(
        "--rank-by",
        choices=("balanced", "som"),
        default="balanced",
        help="balanced = K distinct per format; som = top-N by python-executed SOM "
        "across all formats (max credible headline)",
    )
    ap.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="SOM mode: total winners to keep (default per-format * 6)",
    )
    ap.add_argument(
        "--max-per-format",
        type=int,
        default=None,
        help="SOM mode: cap winners per format so the slate stays diverse",
    )
    args = ap.parse_args()
    build_portfolio(
        per_format=args.per_format,
        n_candidates=args.n_candidates,
        rank_by=args.rank_by,
        top_n=args.top_n,
        max_per_format=args.max_per_format,
    )


if __name__ == "__main__":
    main()
