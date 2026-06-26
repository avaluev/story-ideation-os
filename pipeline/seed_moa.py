"""pipeline/seed_moa.py — Mixture-of-Experts seed generation (Change 4).

Runs 3 biased CompoundSeedEngine instances in parallel (via concurrent.futures),
each with a different prior (conspiracy / open-science / reptile-fear).

By default a Sonnet LLM judge ranks the 3 candidates on premise originality,
SOM potential, and organic marketing power (Issue #9). If the LLM call fails
(API down, import error, quota exceeded) the module falls back to the pure-Python
max(SOM, genius_score) judge so offline use and tests are unaffected.

The selected seed carries a `moa_candidates` field in hidden_attrs documenting
all 3 sketches so runs are reproducible and auditable.

ADR-0001: seed write uses pipeline.state.safe_write.
ADR-0007: model call routes through openrouter_client (same pattern as
          CompoundSeedEngine._call_haiku_for_premise).
"""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from pipeline.compound_seed import CompoundSeedEngine, CompoundSeedResult

_log = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS: int = 20
_DEFAULT_SEEDER_SEEDS: tuple[int, int, int] = (42, 137, 271)
_JUDGE_MODEL: str = "anthropic/claude-sonnet-4-6"
_JUDGE_MAX_TOKENS: int = 300

# Width of each hex slice consumed from the theme hash to derive one seeder
# seed. 8 hex chars = 32 bits, safely within Python int range and large enough
# to give 4B distinct values per seeder.
_THEME_HASH_HEX_WIDTH: int = 8


def _derive_theme_seeds(
    themes: list[str],
    fallback_seeds: tuple[int, int, int] = _DEFAULT_SEEDER_SEEDS,
) -> tuple[int, int, int]:
    """Hash the operator's themes into 3 distinct RNG seeds.

    Fixed seeds (42, 137, 271) make the engine produce identical samples for
    different themes when the same seeder wins the MoA judge. That defeats
    parameter diversity. Hashing the theme list into the seeds while XOR'ing
    with the original constants preserves the per-seeder bias (each of the 3
    seeders still pulls a distinct slice of the hash space) but makes the
    sampled dimensions actually theme-responsive.

    Returns ``fallback_seeds`` when ``themes`` is empty so existing tests and
    the no-theme generator path keep their deterministic behavior.
    """
    if not themes:
        return fallback_seeds
    digest = hashlib.sha256("|".join(themes).encode("utf-8")).hexdigest()
    w = _THEME_HASH_HEX_WIDTH
    slices = [int(digest[i * w : (i + 1) * w], 16) for i in range(3)]
    return (
        slices[0] ^ fallback_seeds[0],
        slices[1] ^ fallback_seeds[1],
        slices[2] ^ fallback_seeds[2],
    )


@dataclass
class MoASeedResult:
    """Container for the 3 candidates and the judge's pick."""

    selected: CompoundSeedResult
    candidates: list[CompoundSeedResult]
    judge_rationale: str
    seeder_names: list[str]


def _python_judge(candidates: list[CompoundSeedResult], seeder_names: list[str]) -> tuple[int, str]:
    """Pure-Python fallback judge: max(SOM floor, genius_score) tiebreaker."""
    best_idx = max(
        range(len(candidates)),
        key=lambda i: (candidates[i].scores.som_floor_M, candidates[i].scores.genius_score),
    )
    best = candidates[best_idx]
    best_name = seeder_names[best_idx] if best_idx < len(seeder_names) else "unknown"
    rationale = (
        f"Selected {best_name} — SOM=${best.scores.som_floor_M:.0f}M, "
        f"genius={best.scores.genius_score:.3f}. "
        "Candidates: "
        + ", ".join(
            f"{seeder_names[i]}(SOM={c.scores.som_floor_M:.0f}M)" for i, c in enumerate(candidates)
        )
    )
    return best_idx, rationale


def _llm_judge(
    candidates: list[CompoundSeedResult],
    seeder_names: list[str],
    themes: list[str],
) -> tuple[int, str, str]:
    """Call Sonnet to rank candidates and pick the best.

    Returns (selected_index, rationale, method) where method is
    'llm_judge_sonnet' on success or 'python_judge_fallback' on failure.
    Falls back to _python_judge on any API/import error so offline
    use and tests are unaffected.
    """
    try:
        from pipeline.llm_client import build_chat_client  # noqa: PLC0415

        themes_str = "; ".join(themes) if themes else "unspecified"
        sketches = "\n\n".join(
            f"Candidate {i + 1} ({name}):\n"
            f"  Premise: {cand.intersection_premise[:400]}\n"
            f"  SOM floor: ${cand.scores.som_floor_M:.0f}M\n"
            f"  Genius score: {cand.scores.genius_score:.3f}\n"
            f"  Divisiveness: {cand.scores.divisiveness_score:.1f}/10"
            for i, (cand, name) in enumerate(zip(candidates, seeder_names, strict=False))
        )

        prompt = (
            "You are judging 3 film concept seed candidates generated for an investor pitch.\n"
            f"Operator themes: {themes_str}\n\n"
            f"{sketches}\n\n"
            "Select the candidate that best combines: "
            "(1) strongest SOM potential for mass-market global audiences, "
            "(2) most original and surprising intersection premise, "
            "(3) highest organic marketing power.\n\n"
            "Respond with ONLY valid JSON: "
            '{"selected_index": <0|1|2>, "rationale": "<1-2 sentences max>"}'
        )

        client = build_chat_client()
        raw: dict[str, object] = client.chat(
            model=_JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )

        raw_idx = raw.get("selected_index")
        idx = int(str(raw_idx)) if raw_idx is not None else 0
        if not (0 <= idx < len(candidates)):
            idx = 0
        rationale = str(raw.get("rationale") or f"LLM selected candidate {idx + 1}.").strip()
        _log.info("llm_judge selected index=%d: %s", idx, rationale)
        return idx, rationale, "llm_judge_sonnet"

    except Exception as exc:
        _log.warning("LLM judge failed (%s) — falling back to pure-Python judge", exc)
        idx, rationale = _python_judge(candidates, seeder_names)
        return idx, rationale, "python_judge_fallback"


def _run_seeder(
    name: str,
    rng_seed: int,
    themes: list[str],
    problems: list[str],
    max_attempts: int,
    force_kwargs: dict[str, Any] | None = None,
) -> tuple[str, CompoundSeedResult]:
    """Run one seeder and return (name, result). Called in a thread."""
    engine = CompoundSeedEngine(rng_seed=rng_seed)
    force_kwargs = force_kwargs or {}
    result = engine.generate(
        themes=themes,
        problems=problems,
        max_attempts=max_attempts,
        **force_kwargs,
    )
    return name, result


def generate(
    themes: list[str] | None = None,
    problems: list[str] | None = None,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    rng_seeds: tuple[int, int, int] = _DEFAULT_SEEDER_SEEDS,
) -> MoASeedResult:
    """Run 3 biased seeders in parallel, return the judge's pick.

    Each seeder uses a distinct RNG seed to produce naturally different variable
    biases (conspiracy / open-science / reptile-fear priors). A pure-Python judge
    selects the candidate with the highest SOM floor, breaking ties by genius_score.

    Args:
        themes: Optional operator-provided themes (forwarded to each seeder).
        problems: Optional operator-provided problems (forwarded to each seeder).
        max_attempts: Per-seeder generation attempt cap.
        rng_seeds: Tuple of 3 RNG seeds — one per seeder (Conspiracy, OpenSci, Reptile).

    Returns:
        MoASeedResult with the best candidate, all 3 candidates, and judge rationale.
    """
    themes = themes or []
    problems = problems or []

    # If the caller passed the default rng_seeds tuple, derive theme-responsive
    # seeds from the operator themes so different themes get different samples.
    # An explicit non-default rng_seeds (e.g. tests pinning a known sample) is
    # honored verbatim.
    if rng_seeds == _DEFAULT_SEEDER_SEEDS and themes:
        effective_seeds = _derive_theme_seeds(themes, fallback_seeds=rng_seeds)
        _log.info(
            "seed_moa: theme-derived RNG seeds %s (from %d themes)",
            effective_seeds,
            len(themes),
        )
    else:
        effective_seeds = rng_seeds

    seeder_configs: list[tuple[str, int, dict[str, bool]]] = [
        ("conspiracy_mind", effective_seeds[0], {"force_conspiracy": True}),
        ("open_science_mind", effective_seeds[1], {"force_open_problem": True}),
        ("reptile_fear_mind", effective_seeds[2], {"force_reptile": True}),
    ]

    candidates: list[CompoundSeedResult] = []
    seeder_names: list[str] = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _run_seeder,
                name,
                seed,
                themes,
                problems,
                max_attempts,
                force_kwargs,
            ): name
            for name, seed, force_kwargs in seeder_configs
        }
        for future in as_completed(futures):
            seeder_name = futures[future]
            try:
                name, result = future.result()
                candidates.append(result)
                seeder_names.append(name)
                _log.info(
                    "moa_seeder %s: SOM=%.0fM genius=%.3f",
                    name,
                    result.scores.som_floor_M,
                    result.scores.genius_score,
                )
            except Exception as exc:
                _log.warning("moa_seeder %s failed: %s", seeder_name, exc)

    if not candidates:
        _log.error("All 3 MoA seeders failed — falling back to default engine")
        engine = CompoundSeedEngine(rng_seed=effective_seeds[0])
        fallback = engine.generate(themes=themes, problems=problems, max_attempts=50)
        return MoASeedResult(
            selected=fallback,
            candidates=[fallback],
            judge_rationale="fallback — all MoA seeders failed",
            seeder_names=["default_fallback"],
        )

    # LLM judge (Sonnet) with pure-Python fallback (Issue #9)
    winner_idx, rationale, selected_by = _llm_judge(candidates, seeder_names, themes or [])
    selected = candidates[winner_idx]
    winner_name = seeder_names[winner_idx] if winner_idx < len(seeder_names) else "unknown"

    # Embed MoA audit trail in hidden_attrs (ADR-0001: caller writes via safe_write)
    selected.hidden_attrs["moa_candidates"] = [
        {
            "seeder": seeder_names[i] if i < len(seeder_names) else f"seeder_{i}",
            "run_id": c.run_id,
            "som_floor_M": c.scores.som_floor_M,
            "genius_score": c.scores.genius_score,
            "selected": c is selected,
        }
        for i, c in enumerate(candidates)
    ]
    selected.hidden_attrs["moa_judge_rationale"] = rationale
    selected.hidden_attrs["selected_by"] = selected_by

    _log.info("moa_judge selected %s: %s", winner_name, rationale)

    return MoASeedResult(
        selected=selected,
        candidates=candidates,
        judge_rationale=rationale,
        seeder_names=seeder_names,
    )


__all__ = ["MoASeedResult", "generate"]
