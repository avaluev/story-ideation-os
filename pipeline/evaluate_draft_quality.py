"""Thin CLI wrapper for :func:`pipeline.single_idea.evaluate_draft_quality`.

Surfaces the Phase-2 5-vector quality gate as a one-liner the
``/single-idea`` skill (or any operator script) can invoke after STEP 4
without writing inline Python::

    uv run python -m pipeline.evaluate_draft_quality --run-dir runs/{id}

Soft-fail design (mirrors :mod:`pipeline.phase_timing`): any exception
logs a warning and returns 0 so the wrapper never blocks the pipeline.

ADR-0001: writes flow through ``pipeline.state.safe_write`` inside the
delegate. This wrapper performs no writes of its own.
ADR-0002: no arithmetic here — scoring stays in :mod:`pipeline.scorecard`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pipeline.single_idea import evaluate_draft_quality

_log = logging.getLogger(__name__)


def _main() -> int:
    """CLI entry: ``uv run python -m pipeline.evaluate_draft_quality --run-dir <run_dir>``.

    On success: prints a one-line JSON summary (``overall_pass`` and the
    failing vectors/axes when any) and exits 0. On any exception: logs a
    warning and exits 0 — instrumentation must never block the pipeline.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="pipeline.evaluate_draft_quality")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--rules-path",
        default=None,
        help="Override path to axis_selection_rules.jsonl",
    )
    args = parser.parse_args()

    try:
        rules_path = Path(args.rules_path) if args.rules_path else None
        result = evaluate_draft_quality(Path(args.run_dir), rules_path=rules_path)
    except Exception as exc:  # pragma: no cover — soft-fail backstop
        _log.warning("evaluate_draft_quality CLI degraded: %s", exc)
        return 0

    failing_vectors = sorted(q for q, p in result.vector_pass.items() if p is False)
    failing_axes = sorted(a for a, p in result.axis_pass.items() if not p)
    summary = {
        "overall_pass": result.overall_pass,
        "failing_vectors": failing_vectors,
        "failing_axes": failing_axes,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__: list[str] = []
