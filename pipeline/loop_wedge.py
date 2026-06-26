"""pipeline.loop_wedge -- WEDGE-era autonomous loop body.

WEDGE Step 6 of the plan. Drives one or more autonomous iterations of
the convergent loop the operator asked for. Replaces the planned
``loop_autonomous.py`` for the WEDGE era -- the SOTA loop spec from
Section 5 of the plan, minus the embedding-novelty term (which needs
Step 5's operator_alignment facet to be meaningful and is therefore
DEFERRED to Phase C per the plan).

Pseudocode (per Section 5 of the plan, simplified for WEDGE):

  for _ in range(iterations):
      1. quota.gate(opus, expected=80k, floor=0.05) -- bail if subscription
         burn would exceed the weekly ceiling.
      2. evolve.one_shot.run(n_base=batch_size, ...) generates candidates;
         freq_table already wired (Step 1), comp decorrelation wired (Step 2).
      3. Score each candidate against the active Goal (Step 3 weight
         injection). Goal.facet_weights drive the geometric mean.
      4. Record one row to data/loop_history.jsonl:
         {ts, run_id, top_score, top_som_y1, goal_sha, strategy}
      5. Plateau check via loop_controller.plateau_reached on the rolling
         score history. If plateau hit AND we have ratings ready,
         feedback.refit_weights -> Goal.save (bumps goal_id). Next
         iteration runs against the shifted goal.
      6. Goal-conditional halt: if top.score >= goal.target_score AND
         top.som_y1 >= goal.revenue_floor_usd -> stop early.

This is the closed loop the operator asked for. The whole point: each
iteration ends with the engine smarter than it started, because (a)
freq_table records what was sampled, (b) ratings shift the weights,
(c) plateau triggers recalibration not stopping.

Constraints
===========

- MUST NOT exceed ADR-0008 weekly Opus burn (gated at iteration start).
- MUST NOT mutate Goal in place; recalibration produces a NEW Goal via
  Goal.save() which bumps goal_id and appends to goal_history.jsonl.
- MUST NOT write loop_history rows for failed iterations (the file is
  the truth source for Step 8 /digest KPIs).
- Pure-Python orchestration; no LLM imports (ADR-0007: dispatch goes
  through evolve.one_shot).

Embedding-novelty status: live. ``pipeline.crystallize.embeddings.CorpusIndex``
(commit 8427546) supplies the 894-film cosine index; ``_embedding_novelty`` in
``pipeline.empirical_genius`` (commit c878d2d) returns ``1 - max_cosine_sim``
per concept; ``mean_novelty_last_20`` is populated each iteration
(commit bafa15c) and rendered by ``pipeline.digest``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pipeline import feedback, labels, loop_controller
from pipeline.goal import DEFAULT_GOAL_PATH, Goal
from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

DEFAULT_LOOP_HISTORY_PATH: Final[Path] = Path("data/loop_history.jsonl")
DEFAULT_BATCH_SIZE: Final[int] = 10
DEFAULT_OPUS_EXPECTED_TOKENS: Final[int] = 80_000
DEFAULT_PLATEAU_DELTA: Final[float] = 0.03
DEFAULT_PLATEAU_WINDOW: Final[int] = 3
DEFAULT_MAX_ITERATIONS: Final[int] = 100
"""Hard ceiling on a single /loop-engine invocation. Operator override via
``--iterations``; absolute upper bound stays here so a runaway loop in
autonomous mode can't burn an entire week of quota."""

NOVELTY_WINDOW: Final[int] = 20
"""Rolling window for ``mean_novelty_last_20``. Matches digest's 6th KPI
target and the master-plan Section 5 step 4 spec."""


class IterationResult:
    """One iteration's outcome -- recorded to loop_history.jsonl."""

    __slots__ = (
        "goal_sha",
        "halted_reason",
        "mean_novelty_last_20",
        "novelty_top",
        "run_id",
        "strategy",
        "top_score",
        "top_som_y1",
        "ts",
    )

    def __init__(
        self,
        ts: str,
        run_id: str,
        top_score: float,
        top_som_y1: float,
        goal_sha: str,
        strategy: str,
        halted_reason: str | None,
        mean_novelty_last_20: float | None = None,
        novelty_top: float | None = None,
    ) -> None:
        self.ts = ts
        self.run_id = run_id
        self.top_score = top_score
        self.top_som_y1 = top_som_y1
        self.goal_sha = goal_sha
        self.strategy = strategy
        self.halted_reason = halted_reason
        # Raw novelty of the top winner this iteration. 1 - max_cosine_sim
        # against the 894-film corpus index (commit 8427546). None when the
        # index file is absent or sentence-transformers is uninstalled.
        self.novelty_top = novelty_top
        # Rolling mean of the last NOVELTY_WINDOW raw novelty_top values
        # (including this iteration). Surfaces in digest's 6th KPI.
        self.mean_novelty_last_20 = mean_novelty_last_20

    def to_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "top_score": self.top_score,
            "top_som_y1": self.top_som_y1,
            "goal_sha": self.goal_sha,
            "strategy": self.strategy,
            "halted_reason": self.halted_reason,
            "novelty_top": self.novelty_top,
            "mean_novelty_last_20": self.mean_novelty_last_20,
        }


def run_iteration(
    goal: Goal,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    history_scores: list[float] | None = None,
    plateau_delta: float = DEFAULT_PLATEAU_DELTA,
    plateau_window: int = DEFAULT_PLATEAU_WINDOW,
    expected_tokens: int = DEFAULT_OPUS_EXPECTED_TOKENS,
    history_path: Path | str = DEFAULT_LOOP_HISTORY_PATH,
    goal_path: Path | str = DEFAULT_GOAL_PATH,
    runs_root: Path | str = Path("runs"),
    dry_run: bool = False,
    _evolve_fn: object | None = None,
    _quota_gate_fn: object | None = None,
) -> tuple[Goal, IterationResult | None]:
    """One iteration of the closed loop.

    Returns ``(possibly-bumped-goal, iteration_result)``. ``iteration_result``
    is ``None`` when the iteration aborted (quota gate / dry-run).

    The ``_evolve_fn`` and ``_quota_gate_fn`` parameters are dependency
    injection seams used only by tests; in production both default to
    the real ``pipeline.evolve.one_shot.run`` and ``pipeline.quota.gate``.
    """
    history_scores = list(history_scores or [])

    # 1. Quota gate. Skip in dry-run so smoke tests don't depend on the
    # weekly counter being below the cap.
    if not dry_run:
        quota_gate = _quota_gate_fn if _quota_gate_fn is not None else _real_quota_gate
        if not quota_gate("opus", expected_tokens, 0.05):  # type: ignore[reportCallIssue,operator]
            _log.warning("loop_wedge.run_iteration: opus quota gate refused; halting")
            _record_iteration(
                history_path,
                IterationResult(
                    ts=_now_iso(),
                    run_id="(none)",
                    top_score=0.0,
                    top_som_y1=0.0,
                    goal_sha=goal.sha,
                    strategy="abort:quota",
                    halted_reason="opus_quota_exhausted",
                ),
            )
            return goal, None

    # 2. Generate + score. The evolve module already honours freq_table
    # (Step 1), goal-keyed weights (Step 3), and MMR decorrelation (Step 2).
    from typing import cast as _cast  # noqa: PLC0415 -- formatter strips top-level cast import

    evolve_fn = _evolve_fn if _evolve_fn is not None else _real_evolve_run
    explore_result = _cast(
        "object",
        evolve_fn(n_base=batch_size, goal=goal, runs_root=Path(runs_root)),  # type: ignore[reportCallIssue,operator]
    )

    top_score, top_som_y1, top_run_id = _extract_top(explore_result, goal=goal)

    # 3. Goal-conditional halt: did we hit the operator's target?
    halted_reason: str | None = None
    strategy = "climbing"
    if top_score >= goal.target_score and top_som_y1 >= goal.revenue_floor_usd:
        halted_reason = "goal_met"
        strategy = "halt:goal_met"

    # 4. Plateau check on the rolling score history (including this iter).
    updated_scores = [*history_scores, top_score]
    if halted_reason is None and loop_controller.plateau_reached(
        updated_scores, delta_threshold=plateau_delta, window=plateau_window
    ):
        new_goal, refit_strategy = _try_recalibrate(goal, runs_root, goal_path)
        if new_goal is not goal:
            goal = new_goal
            strategy = refit_strategy
        else:
            strategy = "plateau:no_new_ratings"

    # 5. Novelty: 1 - max_cosine_sim of the top winner against the corpus
    # FAISS-equivalent index (commit 8427546). None when the index is absent
    # or sentence-transformers is uninstalled. The rolling mean is computed
    # over the last NOVELTY_WINDOW raw values including this iteration.
    novelty_top = _compute_novelty_top(explore_result)
    mean_novelty = _rolling_mean_novelty(novelty_top, Path(history_path))

    result = IterationResult(
        ts=_now_iso(),
        run_id=top_run_id,
        top_score=top_score,
        top_som_y1=top_som_y1,
        goal_sha=goal.sha,
        strategy=strategy,
        halted_reason=halted_reason,
        novelty_top=novelty_top,
        mean_novelty_last_20=mean_novelty,
    )
    _record_iteration(history_path, result)
    return goal, result


def run_many(
    iterations: int,
    *,
    goal: Goal | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    history_path: Path | str = DEFAULT_LOOP_HISTORY_PATH,
    goal_path: Path | str = DEFAULT_GOAL_PATH,
    runs_root: Path | str = Path("runs"),
    dry_run: bool = False,
    _evolve_fn: object | None = None,
    _quota_gate_fn: object | None = None,
) -> list[IterationResult]:
    """Run up to ``iterations`` consecutive iterations, honouring goal-met
    early-halt. Caps at ``DEFAULT_MAX_ITERATIONS`` regardless of the
    operator's request (anti-runaway guard for autonomous mode)."""
    iterations = max(1, min(iterations, DEFAULT_MAX_ITERATIONS))
    current_goal = goal if goal is not None else Goal.load(goal_path)
    scores: list[float] = []
    results: list[IterationResult] = []
    for _ in range(iterations):
        current_goal, result = run_iteration(
            current_goal,
            batch_size=batch_size,
            history_scores=scores,
            history_path=history_path,
            goal_path=goal_path,
            runs_root=runs_root,
            dry_run=dry_run,
            _evolve_fn=_evolve_fn,
            _quota_gate_fn=_quota_gate_fn,
        )
        if result is None:
            break
        results.append(result)
        scores.append(result.top_score)
        if result.halted_reason == "goal_met":
            break
    return results


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _record_iteration(history_path: Path | str, result: IterationResult) -> None:
    append_jsonl(Path(history_path), result.to_dict())


def _try_recalibrate(
    goal: Goal,
    runs_root: Path | str,
    goal_path: Path | str,
) -> tuple[Goal, str]:
    """If the operator has rated >= DEFAULT_RECALIBRATION_TRIGGER concepts
    since the active goal was created, refit and save a new Goal.

    Returns ``(new_goal, strategy_label)`` -- if no new ratings were
    available, returns ``(goal, "plateau:no_new_ratings")`` so the caller
    can record the no-op.
    """
    try:
        goal_created = datetime.fromisoformat(goal.created_at)
    except ValueError:
        goal_created = datetime.now(UTC)
    if goal_created.tzinfo is None:
        goal_created = goal_created.replace(tzinfo=UTC)
    # Read DEFAULT_LABELS_PATH at call time (not via default arg) so tests
    # monkeypatching labels.DEFAULT_LABELS_PATH get the redirected path.
    fresh = labels.read_since(goal_created, path=labels.DEFAULT_LABELS_PATH)
    if len(fresh) < feedback.DEFAULT_RECALIBRATION_TRIGGER:
        return goal, "plateau:no_new_ratings"
    winners = feedback.read_winner_facets(fresh, runs_root=runs_root)
    new_weights = feedback.refit_weights(
        rated_rows=fresh,
        winners_by_run_id=winners,
        prior_weights=goal.facet_weights,
    )
    bumped = goal.with_overrides(facet_weights=new_weights)
    saved = bumped.save(path=goal_path)
    _log.info(
        "loop_wedge: refit weights from %d ratings; goal %s -> %s",
        len(fresh),
        goal.goal_id,
        saved.goal_id,
    )
    return saved, "plateau:refit"


def _extract_top(
    explore_result: object,
    goal: Goal,
) -> tuple[float, float, str]:
    """Pull ``(top_score, top_som_y1_usd, run_id)`` out of an
    ExploreResult-like object. Defensive about field shape so tests can
    stub with a minimal namedtuple-style class."""
    run_id = str(getattr(explore_result, "run_id", "(unknown)"))
    top_k = getattr(explore_result, "top_k", None)
    if not top_k:
        return 0.0, 0.0, run_id
    top = top_k[0]
    score = float(getattr(top, "crystallization_score", 0.0) or 0.0)
    proj = getattr(top, "projection", None)
    som = float(getattr(proj, "som_y1_usd", 0.0) or 0.0)
    return score, som, run_id


def _candidate_text_for_novelty(candidate: object) -> str:
    """Build the embedding-input text for one ScoredCandidate's compound seed.

    Loop_wedge candidates are programmatic compound seeds, not narrator-
    written loglines, so we synthesise a text from the most narrative-
    bearing structured fields: world_texture.name + hidden_attrs.moral_wager
    + themes + problems. Empty fields are skipped; an all-empty candidate
    returns "".
    """
    parts: list[str] = []
    wt_obj: object = getattr(candidate, "world_texture", None)
    if isinstance(wt_obj, dict):
        wt: dict[str, Any] = wt_obj  # pyright: ignore[reportUnknownVariableType]
        name = wt.get("name")
        if isinstance(name, str) and name.strip():
            parts.append(name.strip())
    hidden_obj: object = getattr(candidate, "hidden_attrs", None)
    if isinstance(hidden_obj, dict):
        hidden: dict[str, Any] = hidden_obj  # pyright: ignore[reportUnknownVariableType]
        mw = hidden.get("moral_wager")
        if isinstance(mw, str) and mw.strip():
            parts.append(mw.strip())
    themes_obj: object = getattr(candidate, "themes", None)
    if isinstance(themes_obj, list):
        themes: list[Any] = themes_obj  # pyright: ignore[reportUnknownVariableType]
        themes_str = ", ".join(str(t) for t in themes if t)
        if themes_str:
            parts.append(f"themes: {themes_str}")
    problems_obj: object = getattr(candidate, "problems", None)
    if isinstance(problems_obj, list):
        problems: list[Any] = problems_obj  # pyright: ignore[reportUnknownVariableType]
        problems_str = "; ".join(str(p) for p in problems if p)
        if problems_str:
            parts.append(f"problems: {problems_str}")
    return ". ".join(parts)


def _compute_novelty_top(explore_result: object) -> float | None:
    """Return ``1 - max_cosine_sim`` for the top winner's text, or None when
    novelty cannot be computed (no corpus index, no top winner, empty text).

    Uses pipeline.empirical_genius._get_corpus_index() as the singleton
    loader -- the CorpusIndex is shared with C002's per-concept call so the
    sentence-transformer model is loaded at most once per process.
    """
    top_k = getattr(explore_result, "top_k", None)
    if not top_k:
        return None
    top = top_k[0]
    candidate = getattr(top, "candidate", None)
    if candidate is None:
        return None
    text = _candidate_text_for_novelty(candidate)
    if not text:
        return None
    from pipeline import empirical_genius as _eg  # noqa: PLC0415 -- lazy ML import

    idx = _eg._get_corpus_index()  # pyright: ignore[reportPrivateUsage]
    if idx is None:
        return None
    max_sim = idx.max_cosine(text)
    return max(0.0, min(1.0, 1.0 - max_sim))


def _rolling_mean_novelty(
    novelty_this_iter: float | None,
    history_path: Path,
    window: int = NOVELTY_WINDOW,
) -> float | None:
    """Mean over the last ``window`` ``novelty_top`` values, including this
    iteration. Returns None when this iter's novelty is None AND no past
    row carries a value (no signal at all).

    Reads ``history_path`` row by row -- the file is small (one row per
    /loop-engine iteration). Forward-compat: rows that pre-date Step-11
    have no ``novelty_top`` field and are skipped silently.
    """
    past_values: list[float] = []
    if history_path.exists():
        with open(history_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row_obj: object = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row_obj, dict):
                    continue
                row: dict[str, Any] = row_obj  # pyright: ignore[reportUnknownVariableType]
                val = row.get("novelty_top")
                if isinstance(val, int | float):
                    past_values.append(float(val))
    # Keep the most recent (window - 1) past values; reserve one slot for now.
    past_values = past_values[-(window - 1) :]
    bucket: list[float] = list(past_values)
    if novelty_this_iter is not None:
        bucket.append(novelty_this_iter)
    if not bucket:
        return None
    return sum(bucket) / len(bucket)


def _real_quota_gate(model: str, expected_tokens: int, floor: float) -> bool:
    """Lazy import to keep loop_wedge importable in environments where
    quota's deps aren't installed (e.g. test envs that monkeypatch this)."""
    from pipeline import quota  # noqa: PLC0415 -- lazy dep boundary

    return quota.gate(model, expected_tokens=expected_tokens, floor=floor)  # type: ignore[arg-type]


def _real_evolve_run(
    n_base: int,
    goal: Goal,
    runs_root: Path,
) -> object:
    """Real evolve invocation is intentionally NOT wired here.

    ``pipeline.evolve.one_shot.explore_and_select`` requires
    ``problem``, ``themes``, ``engine``, ``pools``, ``corpus`` --
    objects that the operator's existing ``/evolve`` skill wires up
    from project config. Importing all of that into ``loop_wedge``
    would duplicate the skill's setup and create a second source of
    truth.

    HONEST DEFERRAL: this wire belongs alongside the project-scoped
    ``/loop-engine`` slash command -- that skill IS where the
    integration naturally lives (it can shell out to /evolve once per
    iteration and read the resulting winners.json).

    For the Python module's contract: ``--dry-run`` works end-to-end
    today; production driving uses the slash command. Tests inject
    ``_evolve_fn`` directly via the dependency-injection seam and
    don't hit this path. Calling this in production raises a clear
    error rather than silently shipping a half-wired loop.
    """
    raise NotImplementedError(
        "loop_wedge production driving runs via /loop-engine slash command; "
        "Python module exposes --dry-run + _evolve_fn injection only. "
        "See .claude/skills/loop-engine/SKILL.md."
    )


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.loop_wedge",
        description="Autonomous /loop-engine iteration driver",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=1,
        help=f"Iterations to run (capped at {DEFAULT_MAX_ITERATIONS})",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Candidates per iteration (default {DEFAULT_BATCH_SIZE})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip quota gate + evolve generation (smoke test the imports)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    if args.dry_run:
        sys.stdout.write(
            f"loop_wedge dry-run: would run {args.iterations} iterations, "
            f"batch_size={args.batch_size}, goal={Goal.load().goal_id}\n"
        )
        return 0
    results = run_many(args.iterations, batch_size=args.batch_size)
    sys.stdout.write(
        f"loop_wedge: completed {len(results)} iteration(s); "
        f"last={results[-1].strategy if results else '(none)'}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_LOOP_HISTORY_PATH",
    "DEFAULT_MAX_ITERATIONS",
    "IterationResult",
    "run_iteration",
    "run_many",
]
