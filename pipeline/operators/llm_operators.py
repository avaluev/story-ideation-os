"""pipeline.operators.llm_operators -- LLM-assisted v5 mutators (ADR-0012).

Three prose-level operators that complement the deterministic Python
mutators in :mod:`pipeline.operators.mental_models`:

  * :func:`first_principles` -- "strip to three undeniable truths, then
    rebuild from those truths only" (3 mutants per parent, Sonnet 4.6).
  * :func:`second_order`     -- "trace 3 steps deep, mutate into the
    Year-2 tension that emerges" (1 mutant per parent, Sonnet 4.6).
  * :func:`yes_and`          -- "borrow ONE beat from the strongest other
    recent winner; intensify, do not dilute" (0..1 per parent, Sonnet 4.6).

ADR-0007 split (Python plans, Claude Code dispatches): this module never
calls a model.  It writes ``.planning/phase_dispatch/{run_id}/mutation.jsonl``
manifest rows for the ``/single-idea`` skill (or any operator-side runner)
to dispatch as ``Task`` invocations.  Each manifest row carries the
candidate, the prompt-template path, the model tier, and the expected-token
estimate.  Quota is recorded *at the merge* via
:func:`pipeline.quota.record` so abandoned dispatches don't burn budget.

ADR-0008 quota gate: each candidate-shaped manifest row is wrapped in a
:func:`pipeline.quota.gate` check before it is written.  Rows that would
push the Sonnet weekly cap below the 5% floor are dropped (logged at
WARNING) -- the orchestrator then proceeds with the deterministic-Python
mutants only.

ADR-0009 budget cap: the fan-out per call is capped at
:func:`pipeline.loop_controller.patch_budget` ``("L2")`` rows -- the same
ceiling the v4 amplification loop uses.  This keeps the Day-3
``one_shot.py`` orchestrator's total LLM cost predictable.

Pure Python.  No model calls.  No anthropic / httpx imports (ANOMALY-001).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

from pipeline import loop_controller, quota
from pipeline.state import safe_write

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Operator name -> prompt template path.
PROMPT_TEMPLATES: Final[dict[str, Path]] = {
    "first_principles": Path("prompts/v5-llm-operator-first-principles.md"),
    "second_order": Path("prompts/v5-llm-operator-second-order.md"),
    "yes_and": Path("prompts/v5-llm-operator-yes-and.md"),
}

#: Sonnet 4.6 is the v5 LLM-operator tier (ADR-0006 + ADR-0009 default).
_MODEL_TIER: Final[Literal["sonnet"]] = "sonnet"

#: Per-call expected token budget.  Empirical -- a 30-word premise + a few
#: hundred tokens of reasoning + ~1 KB of structured output rounds to ~3 KB.
DEFAULT_EXPECTED_TOKENS: Final[int] = 3_000

#: All three operators land in the engine's existing ``mutation`` phase.
_PHASE: Final[Literal["mutation"]] = "mutation"

#: Manifest path under .planning/phase_dispatch/{run_id}/.
DISPATCH_ROOT: Final[Path] = Path(".planning/phase_dispatch")

OperatorName = Literal["first_principles", "second_order", "yes_and"]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


def _empty_path_list() -> list[Path]:
    return []


def _empty_mutant_list() -> list[dict[str, Any]]:
    return []


@dataclass(frozen=True)
class ManifestResult:
    """Outcome of one manifest-write call.

    Attributes:
        run_id: The orchestrator-assigned identifier shared with the
            :class:`pipeline.evolve.one_shot.ExploreResult` that drove this
            dispatch.
        operator: Which v5 LLM operator wrote the manifest.
        manifest_path: Where the JSONL was written.
        rows_written: Number of candidate-shaped rows the dispatch will
            cover (after :func:`pipeline.quota.gate` filtering).
        rows_skipped_quota: Candidates dropped because the weekly Sonnet
            cap would fall below floor.
        rows_skipped_budget: Candidates dropped because the per-call
            :func:`pipeline.loop_controller.patch_budget` was hit.
    """

    run_id: str
    operator: OperatorName
    manifest_path: Path
    rows_written: int
    rows_skipped_quota: int
    rows_skipped_budget: int


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging operator outputs back into the candidate stream.

    Attributes:
        run_id: Same run identifier as the upstream manifest.
        operator: Which operator's outputs were merged.
        mutants: Raw mutant dicts parsed from the per-Task JSONL outputs.
            The orchestrator wraps these into ``CompoundSeedResult`` for
            re-scoring.
        tokens_in: Total input tokens recorded via
            :func:`pipeline.quota.record`.
        tokens_out: Total output tokens recorded.
        artifacts: Files read during merge.
    """

    run_id: str
    operator: OperatorName
    mutants: list[dict[str, Any]] = field(default_factory=_empty_mutant_list)
    tokens_in: int = 0
    tokens_out: int = 0
    artifacts: list[Path] = field(default_factory=_empty_path_list)


# ---------------------------------------------------------------------------
# Manifest writers
# ---------------------------------------------------------------------------


def first_principles(
    candidates: list[dict[str, Any]],
    *,
    run_id: str,
    expected_tokens: int = DEFAULT_EXPECTED_TOKENS,
    dispatch_root: Path = DISPATCH_ROOT,
) -> ManifestResult:
    """Write a ``mutation`` manifest for the first-principles operator.

    One manifest row per candidate.  Each row will be dispatched as one
    ``Task(subagent_type="claude")`` invocation that renders
    :data:`PROMPT_TEMPLATES` ``["first_principles"]`` against the row's
    ``input_slice`` and writes back a ``slice_NNNN.jsonl`` of mutants.

    Returns:
        :class:`ManifestResult` with row counts (written + skipped).
    """
    return _write_manifest(
        operator="first_principles",
        candidates=candidates,
        run_id=run_id,
        expected_tokens=expected_tokens,
        dispatch_root=dispatch_root,
        extra_input=None,
    )


def second_order(
    candidates: list[dict[str, Any]],
    *,
    run_id: str,
    expected_tokens: int = DEFAULT_EXPECTED_TOKENS,
    dispatch_root: Path = DISPATCH_ROOT,
) -> ManifestResult:
    """Write a ``mutation`` manifest for the second-order operator.

    Same shape as :func:`first_principles` but with the second-order
    template.  One manifest row per candidate.
    """
    return _write_manifest(
        operator="second_order",
        candidates=candidates,
        run_id=run_id,
        expected_tokens=expected_tokens,
        dispatch_root=dispatch_root,
        extra_input=None,
    )


def yes_and(
    candidates: list[dict[str, Any]],
    winners: list[dict[str, Any]],
    *,
    run_id: str,
    expected_tokens: int = DEFAULT_EXPECTED_TOKENS,
    dispatch_root: Path = DISPATCH_ROOT,
) -> ManifestResult:
    """Write a ``mutation`` manifest for the yes-and operator.

    Unlike the other two operators, ``yes_and`` needs a second input -- the
    list of strongest other recent winners to borrow beats from.  We attach
    it once to each manifest row (replicated; the dispatch tool can dedupe).

    Args:
        candidates: Source seeds to mutate.
        winners: Other strong candidates from this run -- the operator
            borrows ONE beat per mutant from one of these.
    """
    return _write_manifest(
        operator="yes_and",
        candidates=candidates,
        run_id=run_id,
        expected_tokens=expected_tokens,
        dispatch_root=dispatch_root,
        extra_input={"winners": winners},
    )


# ---------------------------------------------------------------------------
# Merger
# ---------------------------------------------------------------------------


def merge(
    operator: OperatorName,
    run_id: str,
    *,
    dispatch_root: Path = DISPATCH_ROOT,
) -> MergeResult:
    """Read every per-Task JSONL produced by ``operator`` for ``run_id`` and
    return the merged mutants.

    Per-Task outputs land at the ``output_path`` named in each manifest
    row (one JSONL per row).  Missing or empty outputs are silently
    skipped -- the orchestrator handles the empty case by falling back to
    the deterministic-Python mutants only.

    Quota is recorded once per output file (one ``quota.record`` call) so
    abandoned dispatches don't get counted.
    """
    manifest_path = _manifest_path(operator, run_id, dispatch_root)
    if not manifest_path.exists():
        _log.warning("merge: no manifest for %s/%s -- nothing to merge", run_id, operator)
        return MergeResult(run_id=run_id, operator=operator)

    mutants: list[dict[str, Any]] = []
    artifacts: list[Path] = []
    tokens_in_total = 0
    tokens_out_total = 0

    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        output_path = Path(row["output_path"])
        if not output_path.exists():
            continue
        for line in output_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                _log.warning("merge: skipping malformed mutant row in %s", output_path)
                continue
            for mut in payload.get("mutants", []):
                mutants.append(_attach_lineage(mut, operator=operator, parent=payload))
        tokens_in_total += int(row.get("tokens_in_actual", 0))
        tokens_out_total += int(row.get("tokens_out_actual", 0))
        artifacts.append(output_path)

    if tokens_in_total or tokens_out_total:
        quota.record(
            model=_MODEL_TIER,
            tokens_in=tokens_in_total,
            tokens_out=tokens_out_total,
            run_id=run_id,
            phase=_PHASE,
        )

    return MergeResult(
        run_id=run_id,
        operator=operator,
        mutants=mutants,
        tokens_in=tokens_in_total,
        tokens_out=tokens_out_total,
        artifacts=artifacts,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _manifest_path(operator: OperatorName, run_id: str, dispatch_root: Path) -> Path:
    return dispatch_root / run_id / f"{_PHASE}-{operator}.jsonl"


def _write_manifest(
    *,
    operator: OperatorName,
    candidates: list[dict[str, Any]],
    run_id: str,
    expected_tokens: int,
    dispatch_root: Path,
    extra_input: dict[str, Any] | None,
) -> ManifestResult:
    if expected_tokens < 0:
        raise ValueError("expected_tokens must be non-negative")
    template_path = PROMPT_TEMPLATES[operator]

    cap = loop_controller.patch_budget("L2")
    written = 0
    skipped_quota = 0
    skipped_budget = 0
    now = datetime.now(UTC).isoformat()
    rows: list[str] = []

    for slice_id, candidate in enumerate(candidates):
        if written >= cap:
            skipped_budget += 1
            continue
        if not quota.gate(model=_MODEL_TIER, expected_tokens=expected_tokens):
            skipped_quota += 1
            continue
        input_slice: dict[str, Any] = {"candidate": candidate}
        if extra_input is not None:
            input_slice.update(extra_input)
        output_path = _output_path(operator, run_id, slice_id, dispatch_root)
        row: dict[str, Any] = {
            "run_id": run_id,
            "phase": _PHASE,
            "operator": operator,
            "slice_id": slice_id,
            "input_slice": input_slice,
            "output_path": str(output_path),
            "prompt_template_path": str(template_path),
            "model_tier": _MODEL_TIER,
            "expected_tokens": expected_tokens,
            "produced_at": now,
            "status": "PENDING",
        }
        rows.append(json.dumps(row, ensure_ascii=False))
        written += 1

    manifest_path = _manifest_path(operator, run_id, dispatch_root)
    if rows:
        safe_write(manifest_path, "\n".join(rows) + "\n")
    else:
        # Still emit an empty manifest so the orchestrator sees the
        # operator ran (zero rows) -- this is distinguishable from
        # "manifest missing entirely".
        safe_write(manifest_path, "")

    if skipped_quota:
        _log.warning(
            "llm_operators.%s: dropped %d/%d candidates -- Sonnet weekly cap floor",
            operator,
            skipped_quota,
            len(candidates),
        )
    if skipped_budget:
        _log.info(
            "llm_operators.%s: dropped %d/%d candidates -- L2 budget (%d) exhausted",
            operator,
            skipped_budget,
            len(candidates),
            cap,
        )

    return ManifestResult(
        run_id=run_id,
        operator=operator,
        manifest_path=manifest_path,
        rows_written=written,
        rows_skipped_quota=skipped_quota,
        rows_skipped_budget=skipped_budget,
    )


def _output_path(operator: OperatorName, run_id: str, slice_id: int, dispatch_root: Path) -> Path:
    return dispatch_root / run_id / f"{_PHASE}-{operator}-out" / f"slice_{slice_id:04d}.jsonl"


def _attach_lineage(
    mutant: dict[str, Any],
    *,
    operator: OperatorName,
    parent: dict[str, Any],
) -> dict[str, Any]:
    """Stamp the operator name into the mutant's lineage list.

    The Task subagent writes the candidate shape but doesn't know about
    the v5 lineage convention; we attach it here at merge time so the
    orchestrator can attribute winners back to the operator.
    """
    parent_lineage_obj = parent.get("parent_lineage", [])
    parent_lineage: list[str] = []
    if isinstance(parent_lineage_obj, list):
        typed_parent = cast("list[Any]", parent_lineage_obj)
        parent_lineage = [str(item) for item in typed_parent]
    return {
        **mutant,
        "lineage": [*parent_lineage, f"llm:{operator}"],
    }


__all__ = [
    "DEFAULT_EXPECTED_TOKENS",
    "DISPATCH_ROOT",
    "PROMPT_TEMPLATES",
    "ManifestResult",
    "MergeResult",
    "OperatorName",
    "first_principles",
    "merge",
    "second_order",
    "yes_and",
]
