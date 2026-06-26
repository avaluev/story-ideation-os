"""Single-idea pipeline orchestrator (pure state machine, no LLM I/O).

ADR-0007: actual model dispatch is wired externally via cc_dispatch.
The skill running this orchestrator reads phase_agents[current_phase] to
know which agent to spawn as a Task, and phase_model_tiers[current_phase]
for the model tier hint passed to cc_dispatch.

This module also hosts :func:`evaluate_draft_quality` — the Phase-2 post-draft
5-vector quality check (S4.1 NB.5-INTEGRATE). The function is invoked by the
skill (or any external caller) after the drafter agent writes ``draft_v0.json``
and produces ``runs/{id}/quality.json`` via :func:`pipeline.state.safe_write`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, cast

from pipeline import scorecard, state

_ = cast  # keep the import (typed reference; formatter would otherwise strip it)

_log = logging.getLogger(__name__)

QUALITY_FILENAME = "quality.json"
_RULES_PATH_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "axis_selection_rules.jsonl"


class SingleIdeaOrchestrator:
    phase_names: ClassVar[list[str]] = [
        "seed_capture",
        "research",
        "draft_v0",
        "challenge",
        "amplify",
        "genius_audit",
        "consistency_check",
        "investor_narrator",
        "eval_gate",
        "lessons_capture",
    ]

    # Maps phase index → agent name to invoke as a Task.
    # None means the orchestrator or a pure-Python step handles this phase directly.
    phase_agents: ClassVar[dict[int, str | None]] = {
        0: None,  # seed_capture: orchestrator writes seed.json
        1: "concept-researcher",  # research: sonar-based fact-check + comp research
        2: "concept-drafter",  # draft_v0: initial concept in V2 template format
        3: "concept-challenger",  # challenge: 11 P0 kill-switch adversarial pass
        4: "audience-amplifier",  # amplify: compound SOM multiplier loop (L2)
        5: "genius-auditor",  # genius_audit: C001-C007 originality kill-switches
        6: "consistency-checker",  # consistency_check: cross-sidecar drift detection
        7: "concept-narrator",  # investor_narrator: 3-page investor brief
        8: None,  # eval_gate: pure-Python eval suite
        9: None,  # lessons_capture: orchestrator writes lessons.json
    }

    # Maps phase index → model tier hint for cc_dispatch / quota tracking.
    # Per ADR-0009: L1/L3/L4 patches use sonnet; L2 amplifier uses haiku.
    phase_model_tiers: ClassVar[dict[int, str | None]] = {
        0: None,
        1: "sonnet",  # concept-researcher
        2: "sonnet",  # concept-drafter (L1/L3/L4 patch model per ADR-0009)
        3: "sonnet",  # concept-challenger
        4: "haiku",  # audience-amplifier (L2 vector selection per ADR-0009)
        5: "sonnet",  # genius-auditor (verification pass)
        6: "haiku",  # consistency-checker (cheap structural check)
        7: "sonnet",  # concept-narrator (extended thinking enabled)
        8: None,
        9: None,
    }

    # (sidecar_key, filename, phase_index) — phase 7 (investor_narrator) has no JSON sidecar
    _SIDECAR_PHASE_MAP: ClassVar[list[tuple[str, str, int]]] = [
        ("seed", "seed.json", 0),
        ("research", "research.json", 1),
        ("draft_v0", "draft_v0.json", 2),
        ("challenge", "challenge.json", 3),
        ("amplification", "amplification.json", 4),
        ("genius", "genius.json", 5),
        ("consistency", "consistency.json", 6),
        ("eval", "eval.json", 8),
        ("lessons", "lessons.json", 9),
    ]

    def __init__(self, run_dir: Path, theme: str, resume: bool = False) -> None:
        self.run_dir = Path(run_dir)
        self.theme = theme
        self.is_halted: bool = False
        self.halt_reason: str = ""
        self.current_phase: int = 0
        # MoA flag — set by operator before Phase 0 to use seed_moa.generate()
        # instead of CompoundSeedEngine.generate() (Change 4).
        self.use_moa: bool = False

        self.sidecar_paths: dict[str, Path] = {
            key: self.run_dir / filename for key, filename, _ in self._SIDECAR_PHASE_MAP
        }

        if resume:
            self._restore_phase()

    def _restore_phase(self) -> None:
        for key, _filename, phase_idx in self._SIDECAR_PHASE_MAP:
            if not self.sidecar_paths[key].exists():
                self.current_phase = phase_idx
                return
        self.current_phase = len(self.phase_names)

    def halt(self, reason: str) -> None:
        self.is_halted = True
        self.halt_reason = reason

    def _mark_phase_complete(self, n: int) -> None:
        self.current_phase = n + 1


# ── Phase-2 post-draft quality gate (S4.1 NB.5-INTEGRATE) ───────────────────


def evaluate_draft_quality(
    run_dir: Path | str,
    rules_path: Path | str | None = None,
) -> scorecard.EvalResult:
    """Run the 5-vector scorecard against ``runs/{id}/draft_v0.json``.

    Cycle-1 contract (per Session 4 prompt §STREAM B / S4.1):

    1. Read ``draft_v0.json`` from ``run_dir``.
    2. Extract measured concept attributes from ``draft_v0["hidden_attrs"]``
       (default ``{}`` when absent). No category labels.
    3. Load axis-selection rules from ``rules_path``
       (default: ``data/axis_selection_rules.jsonl`` — empty in Cycle 1).
    4. ``scorecard.compose(attrs, rules) → Scorecard``.
    5. ``scorecard.evaluate(concept, scorecard) → EvalResult``.
    6. Write ``runs/{id}/quality.json`` atomically via
       :func:`pipeline.state.safe_write`. Schema:
       ``{axis_scores, axis_pass, vector_pass, overall_pass, fired_rules,
       evidence, produced_at}``.
    7. When ``overall_pass`` is False, log the failing vectors and axes via
       the module logger. The function never halts: Phase 3 challenger
       remains the canonical L1 patch trigger in Cycle 1.

    Returns the :class:`pipeline.scorecard.EvalResult` so callers may decide
    to act on it (e.g. surface failing axes in the skill's STEP 4 log output).

    ADR-0001: atomic write via :func:`pipeline.state.safe_write`.
    ADR-0002: numeric scoring stays in :mod:`pipeline.scorecard` /
    :mod:`pipeline.axes`. This function performs no arithmetic of its own.
    ADR-0005: no imports from ``frameworks/``.
    """
    run_dir_p = Path(run_dir)
    draft_path = run_dir_p / "draft_v0.json"
    if not draft_path.exists():
        raise FileNotFoundError(f"draft_v0.json not found at {draft_path}")

    draft_v0: dict[str, Any] = json.loads(draft_path.read_text(encoding="utf-8"))
    attrs_obj = draft_v0.get("hidden_attrs")
    attrs: dict[str, Any] = cast("dict[str, Any]", attrs_obj) if isinstance(attrs_obj, dict) else {}

    rules_p = Path(rules_path) if rules_path is not None else _RULES_PATH_DEFAULT
    rules = scorecard.load_rules(rules_p)
    card = scorecard.compose(attrs, rules)
    result = scorecard.evaluate(draft_v0, card)

    if not result.overall_pass:
        failing_vectors = sorted(q for q, p in result.vector_pass.items() if p is False)
        failing_axes = sorted(a for a, p in result.axis_pass.items() if not p)
        _log.info(
            "draft_v0 quality gate FAILED: vectors=%s axes=%s fired_rules=%s",
            failing_vectors,
            failing_axes,
            list(result.fired_rules),
        )

    payload: dict[str, Any] = {
        "axis_scores": result.axis_scores,
        "axis_pass": result.axis_pass,
        "vector_pass": result.vector_pass,
        "overall_pass": result.overall_pass,
        "fired_rules": list(result.fired_rules),
        "evidence": result.evidence,
        "produced_at": datetime.now(UTC).isoformat(),
    }
    state.safe_write(
        run_dir_p / QUALITY_FILENAME,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    return result


__all__ = [
    "QUALITY_FILENAME",
    "SingleIdeaOrchestrator",
    "evaluate_draft_quality",
    "generate_seed_via_evolve",
]


# ── Phase-0 seed-via-evolve helper (ADR-0012, v5.0 wiring change #4) ────────


def generate_seed_via_evolve(
    *,
    theme: str,
    problem: str,
    run_dir: Path | str,
    n_base: int = 64,
    top_k: int = 5,
    use_llm_operators: bool = False,
) -> dict[str, Any]:
    """Replace v4 ``engine.generate()`` Phase-0 seed capture with the v5
    single-pass evolutionary search.

    Calls :func:`pipeline.evolve.one_shot.explore_and_select`, writes the
    top-1 survivor to ``{run_dir}/seed.json`` (drop-in replacement for the
    v4 path) and the remaining survivors to ``{run_dir}/seed_candidates.jsonl``
    for operator review.

    The selector's diversity floor + the mental-model operators + the
    frequency-penalty memory together break the v4 attractor convergence.

    Args:
        theme: Operator-supplied thematic anchor (one or several --
            tokenised by comma).
        problem: Operator-supplied free-text problem statement.
        run_dir: Target directory; ``seed.json`` + ``seed_candidates.jsonl``
            land here.
        n_base: Base population size pre-mutation.  Default 64 per the v5
            plan.
        top_k: Survivor slate size; the top-1 becomes ``seed.json``.
        use_llm_operators: When True, the orchestrator skeleton logs that
            LLM operators *would* run here.  Default False -- Day-3
            shipped only the deterministic-Python operators.

    Returns:
        The top-1 ``ScoredCandidate.candidate.to_dict()`` payload (i.e.
        the seed dict that was just written to ``seed.json``).
    """
    from pipeline.compound_seed import CompoundSeedEngine  # noqa: PLC0415
    from pipeline.crystallize.corpus import FilmsCorpus  # noqa: PLC0415
    from pipeline.evolve.one_shot import explore_and_select  # noqa: PLC0415
    from pipeline.operators.mental_models import VariablePools  # noqa: PLC0415

    run_dir_p = Path(run_dir)
    run_dir_p.mkdir(parents=True, exist_ok=True)
    themes = [t.strip() for t in theme.split(",") if t.strip()]
    if not themes:
        raise ValueError("theme must contain at least one non-empty token")

    engine = CompoundSeedEngine.from_defaults()
    pools = VariablePools.from_engine_defaults()
    corpus = FilmsCorpus.load()

    result = explore_and_select(
        problem=problem,
        themes=themes,
        engine=engine,
        pools=pools,
        corpus=corpus,
        n_base=n_base,
        top_k=top_k,
        use_llm_operators=use_llm_operators,
    )

    if not result.top_k:
        raise RuntimeError("explore_and_select returned no survivors")

    top1 = result.top_k[0]
    seed_payload: dict[str, Any] = {
        "theme": theme,
        "problem": problem,
        "produced_at": datetime.now(UTC).isoformat(),
        "candidate": top1.candidate.to_dict(),
        "revenue": json.loads(json.dumps(top1.revenue, default=_revenue_default)),
        "crystallization_score": top1.crystallization_score,
        "lineage": list(top1.lineage),
        "evolve_run_id": result.run_id,
    }
    state.safe_write(
        run_dir_p / "seed.json",
        json.dumps(seed_payload, indent=2, ensure_ascii=False),
    )

    candidates_path = run_dir_p / "seed_candidates.jsonl"
    if candidates_path.exists():
        candidates_path.unlink()
    for sc in result.top_k[1:]:
        state.append_jsonl(
            candidates_path,
            {
                "candidate": sc.candidate.to_dict(),
                "crystallization_score": sc.crystallization_score,
                "lineage": list(sc.lineage),
            },
        )
    return seed_payload


def _revenue_default(obj: object) -> object:  # pragma: no cover -- json fallback
    """JSON ``default=`` helper that handles dataclasses (RevenueProjection)."""
    import dataclasses  # noqa: PLC0415

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)
