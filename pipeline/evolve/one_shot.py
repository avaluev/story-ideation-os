"""pipeline.evolve.one_shot -- v5.0 single-pass search orchestrator (ADR-0012).

This is the **Day-3 skeleton** of Module 6.  It wires the parts whose
dependencies already exist (the engine, the mental-model operators, the
revenue projector, the diversity-floor selector, the axis-frequency log)
and stubs the two parts that ship later in v5.0:

  * Step 3 -- LLM operators (``first_principles`` / ``second_order`` /
    ``yes_and``) -- ships in Day 4 as ``pipeline.operators.llm_operators``.
    Until then, the skeleton silently skips them when
    ``use_llm_operators=True`` and logs a single INFO.

  * Step 8 -- lineage-tree visualisation -- ships in v5.1.  The lineage
    *data* is captured on every mutant via
    :attr:`pipeline.compound_seed.CompoundSeedResult.lineage`; we just
    don't render trees yet.

The remaining pipeline (1, 2, 4, 5, 6, 7) is fully wired and the skeleton
runs end-to-end with the real engine + real corpus.

Pure Python plus the engine / projector / selector calls.  ADR-0001
(every artifact written through :func:`pipeline.state.safe_write` or
:func:`pipeline.state.append_jsonl`) + ADR-0002 (no LLM-computed scores
land in :attr:`ScoredCandidate.crystallization_score`) + ADR-0012.

MUST NOT be imported from ``pipeline/scoring.py`` (ANOMALY-001).
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from pipeline import diversity
from pipeline.crystallize.revenue import (
    ProjectionContext,
    RevenueProjection,
    project_revenue,
)
from pipeline.crystallize.score import crystallization_score
from pipeline.empirical_genius import detect_standalone_ip
from pipeline.goal import Goal
from pipeline.operators.mental_models import (
    VariablePools,
    constraint_strip,
    invert,
    scamper_substitute,
)
from pipeline.select.diversity_select import SelectCandidate, select_top_k
from pipeline.state import append_jsonl, safe_write

if TYPE_CHECKING:
    from pipeline.compound_seed import CompoundSeedEngine, CompoundSeedResult
    from pipeline.crystallize.corpus import FilmsCorpus

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_N_BASE: Final[int] = 64
"""Base population size before mutation fan-out."""

DEFAULT_TOP_K: Final[int] = 5
"""Operator-facing slate size (Day-3 default; Day-4 surfaces ``top_k`` to CLI)."""

DEFAULT_RUNS_ROOT: Final[Path] = Path("runs")
"""Per-run artifacts live under ``runs/{run_id}/evolve/genN/`` (ADR-0001)."""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


def _empty_lineage() -> list[str]:
    return []


@dataclass(frozen=True)
class ScoredCandidate:
    """A compound seed plus its v5 scores and provenance.

    :attr:`revenue` is the output of
    :func:`pipeline.crystallize.revenue.project_revenue` -- this is the
    ADR-0011 ``calculation_method == "python_executed"`` payload that the
    investor-facing narrator must use.

    :attr:`crystallization_score` is the scalar quality computed via
    :func:`pipeline.crystallize.score.crystallization_score`.

    :attr:`lineage` mirrors the parent
    :class:`pipeline.compound_seed.CompoundSeedResult.lineage` so it can
    be persisted into the per-generation JSONL without re-walking the
    candidate graph.
    """

    candidate: CompoundSeedResult
    revenue: RevenueProjection
    crystallization_score: float
    lineage: list[str] = field(default_factory=_empty_lineage)


def _empty_scored() -> list[ScoredCandidate]:
    return []


def _empty_str_dict() -> dict[str, int]:
    return {}


def _empty_path_list() -> list[Path]:
    return []


@dataclass(frozen=True)
class ExploreResult:
    """The Module-6 public output.

    Attributes:
        run_id: The orchestrator-generated identifier shared by every
            artifact under :data:`DEFAULT_RUNS_ROOT` ``/{run_id}/evolve/``.
        top_k: Selected survivors after the diversity-floor pass.
        all_scored: Every scored candidate (base + mutants).  Useful for
            offline analysis of operator yield.
        operator_yield: ``{operator_name: count}`` -- how many mutants
            each operator produced.  Lets ``one_shot`` evidence whether a
            given operator pulls its weight before v5.1 wires more.
        artifacts: Absolute paths of the JSON files written
            (``base_candidates.jsonl`` / ``mutants.jsonl`` /
            ``projected.jsonl`` / ``winners.json`` / ``seed.json``).
    """

    run_id: str
    top_k: list[ScoredCandidate] = field(default_factory=_empty_scored)
    all_scored: list[ScoredCandidate] = field(default_factory=_empty_scored)
    operator_yield: dict[str, int] = field(default_factory=_empty_str_dict)
    artifacts: list[Path] = field(default_factory=_empty_path_list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def explore_and_select(
    problem: str,
    themes: list[str],
    *,
    engine: CompoundSeedEngine,
    pools: VariablePools,
    corpus: FilmsCorpus,
    n_base: int = DEFAULT_N_BASE,
    top_k: int = DEFAULT_TOP_K,
    use_llm_operators: bool = True,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    rng: random.Random | None = None,
) -> ExploreResult:
    """Run one generation of v5 search and return the survivor slate.

    Step-by-step (see module docstring for the deferred parts):

      1. Generate ``n_base`` candidates via :meth:`engine.generate` with
         a frequency-table-aware sampler (Day-3 reads
         :func:`pipeline.diversity.load_frequency_table`; the
         ``_thematic_weighted_choice`` ``freq_table=`` argument is
         wired in Day 4).
      2. Apply the three Python mental-model operators to each base
         candidate.
      3. (Day-4) LLM operators -- currently a no-op.
      4. Compute :func:`project_revenue` for every candidate.
      5. Compute :func:`crystallization_score` for every candidate using
         the v5 ``som_y1_usd`` payload.
      6. Run :func:`select_top_k` with the v5 diversity floor.
      7. Persist per-generation artifacts and record axis frequencies.
      8. (v5.1) Lineage-tree viz -- currently captured as raw data only.

    Args:
        problem: Operator-supplied free-text problem (passed to the engine).
        themes: Operator-supplied thematic anchors (also passed through).
        engine: Pre-constructed :class:`pipeline.compound_seed.CompoundSeedEngine`.
            Caller controls RNG seeding via the engine.
        pools: :class:`pipeline.operators.mental_models.VariablePools` used
            by the mental-model operators.  Typically built from the
            engine's loaded JSON pools.
        corpus: :class:`pipeline.crystallize.corpus.FilmsCorpus` used by
            ``project_revenue`` to anchor SOM in real comp data.
        n_base: Base population size.  Default :data:`DEFAULT_N_BASE`.
        top_k: Survivor slate size.  Default :data:`DEFAULT_TOP_K`.
        use_llm_operators: When True, log that LLM operators would run
            here (Day-4 will execute them via cc_dispatch).  ``False``
            silences the log.
        runs_root: Override for the per-run artifact root (mostly tests).
        rng: Deterministic RNG for the mental-model operators.  ``None``
            defaults to a fresh :class:`random.Random` seeded from the
            system clock.

    Returns:
        :class:`ExploreResult` -- ``top_k`` is the operator-facing slate;
        ``all_scored`` enables post-hoc analysis.  Every file written is
        listed in ``artifacts`` for the orchestrator's resume contract.
    """
    if n_base <= 0:
        raise ValueError(f"n_base must be > 0, got {n_base}")
    if top_k <= 0:
        raise ValueError(f"top_k must be > 0, got {top_k}")
    if rng is None:
        rng = random.Random()  # noqa: S311 -- not cryptographic

    # R2: load the operator's Goal once so its facet_weights (SOM 0.25,
    # derivative 0.20) drive live scoring instead of the v4 fallback.
    goal = Goal.load()

    run_id = _new_run_id()
    run_dir = runs_root / run_id / "evolve" / "gen0"
    artifacts: list[Path] = []

    # Step 1 -- base population.
    freq_table = diversity.load_frequency_table()
    base = _generate_base(engine, problem=problem, themes=themes, n=n_base, freq_table=freq_table)
    artifacts.append(_persist_jsonl(run_dir / "base_candidates.jsonl", base))

    # Step 2 -- Python operator fan-out.
    mutants, operator_yield = _apply_python_operators(
        base, pools=pools, freq_table=freq_table, rng=rng
    )
    artifacts.append(_persist_jsonl(run_dir / "mutants.jsonl", mutants))

    # Step 3 -- LLM operators (Day 4).
    if use_llm_operators:
        _log.info(
            "evolve.one_shot: use_llm_operators=True but LLM operators "
            "ship Day 4 (Module 4) -- skipping in skeleton"
        )

    # Steps 4 + 5 -- project revenue + crystallization score for every candidate.
    all_candidates: list[CompoundSeedResult] = [*base, *mutants]
    scored = _score_population(all_candidates, corpus=corpus, goal=goal)
    artifacts.append(_persist_scored_jsonl(run_dir / "projected.jsonl", scored))

    # Step 6 -- diversity-floor selection.
    selected = _select_top_k(scored, top_k=top_k)

    # Step 7 -- persist winners + axis-frequency feedback loop.
    artifacts.append(_persist_winners(run_dir / "winners.json", selected))
    artifacts.append(_persist_seed_top1(runs_root / run_id / "seed.json", selected))
    _record_axis_frequencies(selected, run_id=run_id)

    return ExploreResult(
        run_id=run_id,
        top_k=selected,
        all_scored=scored,
        operator_yield=operator_yield,
        artifacts=artifacts,
    )


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("evolve-%Y%m%dT%H%M%SZ")


def _generate_base(
    engine: CompoundSeedEngine,
    *,
    problem: str,
    themes: list[str],
    n: int,
    freq_table: dict[tuple[str, str], int] | None = None,
) -> list[CompoundSeedResult]:
    """Call ``engine.generate(...)`` ``n`` times.

    ``freq_table`` is threaded into :meth:`CompoundSeedEngine.generate` so the
    ADR-0012 cross-run frequency penalty applies to base sampling, not only
    mutants. Pass ``None`` to preserve v4 uniform-weight behaviour.
    """
    base: list[CompoundSeedResult] = []
    for _ in range(n):
        result = engine.generate(themes=themes, problems=[problem], freq_table=freq_table)
        # Tag the engine's own output as the root of every lineage tree.
        # We do this here (not in the engine) to keep this an additive
        # mutation rather than a behaviour change in the v4 path.
        if not result.lineage:
            result.lineage.append("base")
        base.append(result)
    return base


def _apply_python_operators(
    base: list[CompoundSeedResult],
    *,
    pools: VariablePools,
    freq_table: dict[tuple[str, str], int] | None,
    rng: random.Random,
) -> tuple[list[CompoundSeedResult], dict[str, int]]:
    """Run the three mental-model operators on every base candidate."""
    mutants: list[CompoundSeedResult] = []
    yield_counts: dict[str, int] = {"scamper": 0, "invert": 0, "constraint_strip": 0}

    for parent in base:
        s = scamper_substitute(parent, pools, freq_table=freq_table, rng=rng)
        i = invert(parent, pools, rng=rng)
        c = constraint_strip(parent, rng=rng)
        mutants.extend(s)
        mutants.extend(i)
        mutants.extend(c)
        yield_counts["scamper"] += len(s)
        yield_counts["invert"] += len(i)
        yield_counts["constraint_strip"] += len(c)

    return mutants, yield_counts


# R4: tentpole-tier thresholds (engine pre-derate som_floor_M, in $M) that pick
# the theatrical window for the ProjectionContext. Named constants only, so SOM
# stays python_executed (ADR-0011); no LLM, no network.
_TENTPOLE_SOM_FLOOR_M: Final[float] = 400.0
_PRESTIGE_SOM_FLOOR_M: Final[float] = 200.0


def _infer_projection_context(
    candidate_scores: dict[str, Any], *, content_format: str | None = None
) -> ProjectionContext:
    """R4: choose a revenue :class:`ProjectionContext` from the engine's own
    pre-derate commercial-scale estimate (``som_floor_M``).

    ``geo`` is ``global`` for every candidate: the engine produces
    worldwide-ambition original concepts and the legacy ``english_5`` default
    structurally under-counts the ~57% of box office that is international.
    ``window`` scales with the engine's commercial tier so only genuinely
    tentpole-scale candidates get the theatrical-wide multiplier; smaller
    concepts keep the conservative prestige/mixed windows. The old call site
    passed no context, so every candidate was crushed by the english_5 + mixed
    (~0.47) derate regardless of scale.
    """
    som_floor_m = 0.0
    raw = candidate_scores.get("som_floor_M")
    if raw is not None:
        try:
            som_floor_m = float(raw)
        except (TypeError, ValueError):
            som_floor_m = 0.0
    if som_floor_m >= _TENTPOLE_SOM_FLOOR_M:
        return ProjectionContext(
            window="theatrical_wide", geo="global", content_format=content_format
        )
    if som_floor_m >= _PRESTIGE_SOM_FLOOR_M:
        return ProjectionContext(
            window="theatrical_prestige", geo="global", content_format=content_format
        )
    return ProjectionContext(window="mixed", geo="global", content_format=content_format)


def _score_population(
    candidates: list[CompoundSeedResult],
    *,
    corpus: FilmsCorpus,
    goal: Goal | None = None,
) -> list[ScoredCandidate]:
    """Run :func:`project_revenue` + :func:`crystallization_score` per candidate.

    R2: ``goal`` (``config/goal.json``) supplies the live facet weights so the
    operator's SOM 0.25 / derivative 0.20 priorities actually drive ranking --
    the v4 fallback used SOM 0.09 and silently discarded goal.json. R4: each
    candidate gets a tentpole-aware ProjectionContext so SOM reflects global,
    theatrical-scale ambition instead of the conservative english_5 + mixed
    default.
    """
    scored: list[ScoredCandidate] = []
    for c in candidates:
        c_dict = c.to_dict()
        scores_dict: dict[str, Any] = dict(c.scores.to_dict())
        # v5.1.0: thread the sampled content format into BOTH the revenue
        # projection (per-format economics) and the score (per-format SOM scale).
        fmt_obj = c_dict.get("format")
        fmt_key: str | None = None
        if isinstance(fmt_obj, dict):
            raw_key = cast("dict[str, Any]", fmt_obj).get("economics_key")
            fmt_key = str(raw_key) if raw_key else None
        ctx = _infer_projection_context(scores_dict, content_format=fmt_key)
        proj = project_revenue(c_dict, corpus, ctx=ctx)
        # Feed the python-executed post-derate som_y1_usd into the score input;
        # crystallize/score.py prefers it over the legacy pre-derate som_floor_M.
        if proj.som_y1_usd is not None:
            scores_dict["som_y1_usd"] = proj.som_y1_usd
            scores_dict.setdefault("som_floor_M", proj.som_y1_usd / 1_000_000.0)
        if fmt_key:
            scores_dict["content_format"] = fmt_key
        # v5.1.0 de-franchise: flag concepts whose premise leans on pre-existing
        # IP so the standalone_ip facet (live in goal.json) ranks them lower.
        # getattr-guarded: a real CompoundSeedResult always carries the premise,
        # but test stubs may not -- degrade to ambiguous (None) rather than crash.
        premise = getattr(c, "intersection_premise", "") or ""
        scores_dict["standalone_ip_flag"] = detect_standalone_ip(premise, "")
        cs = crystallization_score(scores_dict, goal=goal)
        scored.append(
            ScoredCandidate(
                candidate=c,
                revenue=proj,
                crystallization_score=cs,
                lineage=list(c.lineage),
            )
        )
    return scored


def _select_top_k(scored: list[ScoredCandidate], *, top_k: int) -> list[ScoredCandidate]:
    """Wrap each :class:`ScoredCandidate` in a :class:`SelectCandidate` and
    delegate to :func:`pipeline.select.diversity_select.select_top_k`.

    ``SelectCandidate.payload`` holds the index back into ``scored`` so we
    can map survivors back without identity tricks.
    """
    adapters: list[SelectCandidate] = []
    for idx, sc in enumerate(scored):
        prot = sc.candidate.variables.protagonist_archetype or {}
        world = sc.candidate.variables.world_texture or {}
        adapters.append(
            SelectCandidate(
                score=sc.crystallization_score,
                primary_cluster=sc.candidate.scores.primary_cluster or "",
                archetype_id=str(prot.get("id") or ""),
                world_texture_id=str(world.get("id") or ""),
                payload=idx,
            )
        )
    survivors = select_top_k(adapters, k=top_k)
    indices: list[int] = [int(s.payload) for s in survivors if isinstance(s.payload, int)]
    return [scored[i] for i in indices]


# ---------------------------------------------------------------------------
# Persistence helpers (ADR-0001 -- every write goes through pipeline.state)
# ---------------------------------------------------------------------------


def _persist_jsonl(path: Path, candidates: list[CompoundSeedResult]) -> Path:
    if path.exists():
        path.unlink()  # idempotent re-run
    for c in candidates:
        append_jsonl(path, c.to_dict())
    return path


def _persist_scored_jsonl(path: Path, scored: list[ScoredCandidate]) -> Path:
    if path.exists():
        path.unlink()
    for sc in scored:
        row: dict[str, Any] = {
            "candidate": sc.candidate.to_dict(),
            "revenue": _revenue_to_dict(sc.revenue),
            "crystallization_score": sc.crystallization_score,
            "lineage": list(sc.lineage),
        }
        append_jsonl(path, row)
    return path


def _persist_winners(path: Path, winners: list[ScoredCandidate]) -> Path:
    payload: list[dict[str, Any]] = []
    for sc in winners:
        payload.append(
            {
                "candidate": sc.candidate.to_dict(),
                "revenue": _revenue_to_dict(sc.revenue),
                "crystallization_score": sc.crystallization_score,
                "lineage": list(sc.lineage),
            }
        )
    safe_write(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return path


def _persist_seed_top1(path: Path, winners: list[ScoredCandidate]) -> Path:
    if not winners:
        safe_write(path, "{}")
        return path
    top1 = winners[0]
    payload = {
        "candidate": top1.candidate.to_dict(),
        "revenue": _revenue_to_dict(top1.revenue),
        "crystallization_score": top1.crystallization_score,
        "lineage": list(top1.lineage),
    }
    safe_write(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return path


def _revenue_to_dict(proj: RevenueProjection) -> dict[str, Any]:
    """:class:`RevenueProjection` is frozen and contains nested dataclasses;
    :func:`dataclasses.asdict` handles the recursion."""
    return asdict(proj)


def _record_axis_frequencies(winners: list[ScoredCandidate], *, run_id: str) -> None:
    """Feed the survivor set's axis values back into the diversity log so
    the *next* invocation samples away from them."""
    for sc in winners:
        v = sc.candidate.variables
        _record_axis_if_present(
            v.protagonist_archetype, axis="protagonist_archetype", run_id=run_id
        )
        _record_axis_if_present(v.structural_inversion, axis="structural_inversion", run_id=run_id)
        _record_axis_if_present(v.world_texture, axis="world_texture", run_id=run_id)
        _record_axis_if_present(v.civilizational_stake, axis="civilizational_stake", run_id=run_id)
        _record_axis_if_present(v.divisiveness_engine, axis="divisiveness_engine", run_id=run_id)
        _record_axis_if_present(v.moral_fault_line, axis="moral_fault_line", run_id=run_id)
        _record_axis_if_present(v.dark_archetype, axis="dark_archetype", run_id=run_id)
        # R3: also record the axes whose sampling just moved off raw rng.choice,
        # so their cross-run diversity penalty has memory to act on.
        _record_axis_if_present(v.compression_key, axis="compression_key", run_id=run_id)
        _record_axis_if_present(
            v.methodology_protagonist, axis="methodology_protagonist", run_id=run_id
        )
        _record_axis_if_present(
            v.historical_transplant, axis="historical_transplant", run_id=run_id
        )
        # v5.1.0: the content-format axis, so the next run samples toward the
        # under-represented formats (drives slate-level format diversity).
        _record_axis_if_present(v.format_value, axis="format", run_id=run_id)


def _record_axis_if_present(value: dict[str, Any] | None, *, axis: str, run_id: str) -> None:
    if not value:
        return
    vid = value.get("id")
    if not vid:
        return
    diversity.record_sample(axis, str(vid), run_id)


__all__ = [
    "DEFAULT_N_BASE",
    "DEFAULT_RUNS_ROOT",
    "DEFAULT_TOP_K",
    "ExploreResult",
    "ScoredCandidate",
    "explore_and_select",
]
