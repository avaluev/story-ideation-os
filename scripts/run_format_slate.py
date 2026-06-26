"""scripts/run_format_slate.py — generate a multi-format investor slate (offline).

For each of the 6 content formats, generate a batch of candidates with the
format pinned (force_format), score each with the live goal + per-format
economics + de-franchise flag, apply a per-format SOM floor + the standalone-IP
hard filter, and keep the best. Writes a slate JSON to runs/format-slate/ that
scripts/build_format_slate.py renders into INVESTOR_SLATE_EN.md.

Offline + LLM-free: premise prose uses the deterministic template (no 302.ai /
OpenRouter credit); every SOM/SAM/TAM is python_executed (ADR-0011). The R6b
semantic-comp blend is enabled on the corpus for richer revenue anchors.

    TAO_AI_API_KEY= TAO_AI_PRIMARY= OPENROUTER_API_KEY= OPENROUTER_KEY_PAID= \
        uv run python scripts/run_format_slate.py [N_PER_FORMAT]
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline import diversity
from pipeline.compound_seed import CompoundSeedEngine
from pipeline.crystallize import format_economics as fe
from pipeline.crystallize.comps import match_comps
from pipeline.crystallize.corpus import FilmsCorpus
from pipeline.crystallize.revenue import ProjectionContext, project_revenue
from pipeline.crystallize.score import crystallization_score
from pipeline.empirical_genius import detect_standalone_ip
from pipeline.goal import Goal
from pipeline.state import safe_write

#: Per-format minimum Year-1 SOM (USD) for slate selection — non-feature formats
#: are structurally smaller, so a single global floor would exclude them all
#: (operator decision: per-format floors so the slate spans every format).
PER_FORMAT_SOM_FLOOR_USD: dict[str, float] = {
    "feature": 150_000_000.0,
    "animation_feature": 150_000_000.0,
    "limited_series": 80_000_000.0,
    "returning_series": 80_000_000.0,
    "animation_series": 40_000_000.0,
    "microdrama": 10_000_000.0,
}

#: Varied theme/problem anchors per format so the slate is thematically diverse.
_FORMAT_THEMES: dict[str, tuple[str, list[str]]] = {
    "feature": ("a civilization-scale moral reckoning", ["power", "sacrifice", "truth"]),
    "animation_feature": ("a mythic coming-of-age across worlds", ["wonder", "family", "courage"]),
    "limited_series": ("an intimate institutional betrayal", ["trust", "guilt", "exposure"]),
    "returning_series": (
        "an ensemble fighting a compounding system",
        ["loyalty", "control", "cost"],
    ),
    "animation_series": (
        "a stylized underworld of rival factions",
        ["identity", "fandom", "honor"],
    ),
    "microdrama": ("a fast-burn romance-revenge melodrama", ["desire", "betrayal", "reversal"]),
}

_BASE_SEED = 20260530
_USD_M = 1_000_000.0


def _cap(text: str) -> str:
    text = text.strip().rstrip(".")
    return (text[0].upper() + text[1:]) if text else ""


def _logline(candidate: dict[str, Any], fmt_display: str) -> str:
    """Construct a grounded, readable premise from the engine's varied
    ``description`` fields (offline; no LLM). Honest essence, not jargon."""
    world = str((candidate.get("world_texture") or {}).get("name", "an uncharted world")).strip()
    inversion = str((candidate.get("structural_inversion") or {}).get("description", "")).strip()
    fault = str((candidate.get("moral_fault_line") or {}).get("description", "")).strip()
    wound = str((candidate.get("sdt_wound") or {}).get("description", "")).strip()
    article = "An" if fmt_display[:1].lower() in "aeiou" else "A"
    parts = [f"{article} {fmt_display.lower()} set in the world of {world}."]
    if wound:
        parts.append(f"The protagonist's wound: {wound.rstrip('.')}.")
    if inversion:
        parts.append(f"{_cap(inversion)}.")
    if fault:
        parts.append(f"The impossible dilemma at its core: {fault.rstrip('.')}.")
    return " ".join(parts)


_TITLE_STOPWORDS = {"a", "an", "the", "of", "or", "and", "during", "at", "in", "on", "holding"}
_TITLE_MIN_WORDS = 2
_TITLE_TAIL_WORDS = 3


def _title(candidate: dict[str, Any]) -> str:
    """An evocative working title from the most concrete noun-phrase in the
    world texture (its tail words are usually the vivid part)."""
    world = str((candidate.get("world_texture") or {}).get("name", "")).strip()
    words = [w for w in world.replace("—", " ").split() if w.lower() not in _TITLE_STOPWORDS]
    tail = words[-_TITLE_TAIL_WORDS:] if len(words) >= _TITLE_MIN_WORDS else words or ["Untitled"]
    return "The " + " ".join(w.capitalize() for w in tail)


def _best_for_format(
    eco_key: str,
    *,
    corpus: FilmsCorpus,
    goal: Goal,
    n: int,
    seed_offset: int,
    freq_table: dict[tuple[str, str], int],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (concept, winning_candidate_dict) or None. ``freq_table`` carries
    the cross-run + accumulating in-slate diversity penalty so the 19 narrative
    axes do not collapse to the same world across formats (the duplicate-concept
    failure). The caller folds the winner's axes back into freq_table."""
    profile = fe.FORMAT_PROFILES[eco_key]
    display = profile.display_name
    problem, themes = _FORMAT_THEMES[eco_key]
    floor = PER_FORMAT_SOM_FLOOR_USD[eco_key]
    engine = CompoundSeedEngine(rng_seed=_BASE_SEED + seed_offset)

    best: dict[str, Any] | None = None
    best_cdict: dict[str, Any] | None = None
    best_score = -1.0
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
        standalone = detect_standalone_ip(result.intersection_premise, "")
        if standalone is False:
            continue
        scores_dict: dict[str, Any] = dict(result.scores.to_dict())
        scores_dict["som_y1_usd"] = som
        scores_dict["content_format"] = eco_key
        scores_dict["standalone_ip_flag"] = standalone
        cs = crystallization_score(scores_dict, goal=goal)
        if cs <= best_score:
            continue
        best_score = cs
        best_cdict = c_dict
        comp_match = match_comps(c_dict, corpus, k=4)
        # P2: prefer a URL-shaped tam_source; the theatrical path stores a human
        # label ("constant:MPA+Ampere_2023") which is not a deep link.
        tam_src = str(proj.assumptions.get("tam_source") or "")
        if not tam_src.startswith("https://"):
            tam_src = profile.tam_source_url
        best = {
            "economics_key": eco_key,
            "format": display,
            "monetization_model": profile.monetization_model,
            "title": _title(c_dict),
            "logline": _logline(c_dict, display),
            "som_y1_usd": round(float(som), 2),
            "lifetime_usd": round(float(proj.assumptions.get("lifetime_som_y1_usd") or som), 2),
            "sam_usd": proj.sam_usd,
            "tam_usd": proj.tam_usd,
            "tam_source_url": tam_src,
            "crystallization_score": round(cs, 4),
            "standalone_ip_flag": standalone,
            "calculation_method": proj.calculation_method,
            "comps": comp_match.get("comps", []),
        }
    if best is None or best_cdict is None:
        return None
    return (best, best_cdict)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    corpus = FilmsCorpus.load()
    enabled = corpus.enable_semantic_comps()  # R6b on for richer revenue anchors
    goal = Goal.load()

    # Cross-run penalty seed + an in-slate accumulator so the 19 narrative axes
    # spread ACROSS formats (no duplicate world/wound/dilemma between cards).
    freq_table: dict[tuple[str, str], int] = dict(diversity.load_frequency_table())

    concepts: list[dict[str, Any]] = []
    for i, eco_key in enumerate(fe.VALID_FORMATS):
        out = _best_for_format(
            eco_key, corpus=corpus, goal=goal, n=n, seed_offset=i * 101, freq_table=freq_table
        )
        if out is not None:
            concept, winner = out
            concepts.append(concept)
            # Fold the winner's defining axes into the running penalty so the
            # next format steers away from them (breaks cross-card duplicates).
            for axis in ("world_texture", "sdt_wound", "structural_inversion", "moral_fault_line"):
                vid = str((winner.get(axis) or {}).get("id", ""))
                if vid:
                    freq_table[(axis, vid)] = freq_table.get((axis, vid), 0) + 3
            print(
                f"  {eco_key:18s} SOM ${concept['som_y1_usd'] / _USD_M:>7.0f}M  "
                f"score {concept['crystallization_score']:.3f}  {concept['title']}"
            )
        else:
            floor_m = PER_FORMAT_SOM_FLOOR_USD[eco_key] / _USD_M
            print(f"  {eco_key:18s} (no candidate cleared the ${floor_m:.0f}M floor)")

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path("runs/format-slate")
    out_path = out_dir / f"{ts}-slate.json"
    payload = {
        "generated_label": "format-slate",
        "generated_at": ts,
        "semantic_comps_enabled": enabled,
        "n_per_format": n,
        "concepts": concepts,
    }
    safe_write(out_path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\nSlate JSON: {out_path}  ({len(concepts)}/{len(fe.VALID_FORMATS)} formats)")


if __name__ == "__main__":
    main()
