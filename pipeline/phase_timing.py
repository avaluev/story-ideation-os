"""Per-phase wall-clock instrumentation (Cycle 1 NB.1).

Goldratt step 1: measure before optimizing. Each ``/single-idea`` phase brackets
its work with ``start_phase`` / ``end_phase``; events stream to
``{run_dir}/phase_timings.jsonl`` via :mod:`pipeline.state.append_jsonl`.

Contract:
    JSONL row schema::

        {"phase_index": int, "phase_name": str, "event": "start"|"end",
         "ts_iso": "<UTC>", "duration_seconds"?: float, "partial"?: bool}

    ``summarize`` pairs start/end events by ``phase_name`` and aggregates.
    Unmatched ``end`` events are recorded as ``partial=true`` with
    ``duration_seconds=None`` (forensic — never raises).

ADR-0001 (state durability): all writes flow through :func:`pipeline.state.append_jsonl`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

PHASE_TIMINGS_FILENAME = "phase_timings.jsonl"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _timings_path(run_dir: Path | str) -> Path:
    return Path(run_dir) / PHASE_TIMINGS_FILENAME


def start_phase(run_dir: Path | str, *, phase_index: int, phase_name: str) -> None:
    """Record the start of a phase. Idempotent at the file level (append-only)."""
    append_jsonl(
        _timings_path(run_dir),
        {
            "phase_index": phase_index,
            "phase_name": phase_name,
            "event": "start",
            "ts_iso": _now_iso(),
        },
    )


def end_phase(run_dir: Path | str, *, phase_index: int, phase_name: str) -> None:
    """Record the end of a phase. If no matching unmatched start exists, mark partial."""
    end_iso = _now_iso()
    timings = read_timings(run_dir)
    # Pair the Nth end with the Nth start (FIFO by file order).
    all_starts = [
        i
        for i, r in enumerate(timings)
        if r.get("phase_name") == phase_name and r.get("event") == "start"
    ]
    end_events_seen = sum(
        1 for r in timings if r.get("phase_name") == phase_name and r.get("event") == "end"
    )
    target_start_idx = all_starts[end_events_seen] if end_events_seen < len(all_starts) else None

    if target_start_idx is not None:
        start_ts = datetime.fromisoformat(
            timings[target_start_idx]["ts_iso"].replace("Z", "+00:00")
        )
        end_ts = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        duration = max(0.0, (end_ts - start_ts).total_seconds())
        row: dict[str, Any] = {
            "phase_index": phase_index,
            "phase_name": phase_name,
            "event": "end",
            "ts_iso": end_iso,
            "duration_seconds": duration,
        }
    else:
        row = {
            "phase_index": phase_index,
            "phase_name": phase_name,
            "event": "end",
            "ts_iso": end_iso,
            "duration_seconds": None,
            "partial": True,
        }
    append_jsonl(_timings_path(run_dir), row)


def read_timings(run_dir: Path | str) -> list[dict[str, Any]]:
    """Return all timing events in file order. Empty list if no file."""
    path = _timings_path(run_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            _log.warning("Skipping malformed timing row in %s: %s", path, exc)
    return rows


def summarize(run_dir: Path | str) -> dict[str, Any]:
    """Aggregate timing events into a phase-keyed summary.

    Returns::

        {"total_seconds": float, "by_phase": {phase_name: {
            "duration_seconds": float, "count": int, "partial"?: bool}}}
    """
    timings = read_timings(run_dir)
    by_phase: dict[str, dict[str, Any]] = {}
    total = 0.0
    for row in timings:
        if row.get("event") != "end":
            continue
        name = row.get("phase_name", "?")
        bucket = by_phase.setdefault(name, {"duration_seconds": 0.0, "count": 0})
        dur = row.get("duration_seconds")
        if dur is None:
            bucket["partial"] = True
            bucket["count"] += 1
            continue
        bucket["duration_seconds"] = float(bucket["duration_seconds"]) + float(dur)
        bucket["count"] += 1
        total += float(dur)
    return {"total_seconds": total, "by_phase": by_phase}


def _main() -> int:
    """CLI entry point: ``uv run python -m pipeline.phase_timing <start|end> ...``.

    Used by ``.claude/skills/single-idea/SKILL.md`` to bracket each phase. Soft-fail
    on any exception so instrumentation never blocks the pipeline.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="pipeline.phase_timing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("start", "end"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True)
        p.add_argument("--phase-index", type=int, required=True)
        p.add_argument("--phase-name", required=True)
    sp = sub.add_parser("summarize")
    sp.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    try:
        if args.cmd == "start":
            start_phase(args.run_dir, phase_index=args.phase_index, phase_name=args.phase_name)
        elif args.cmd == "end":
            end_phase(args.run_dir, phase_index=args.phase_index, phase_name=args.phase_name)
        elif args.cmd == "summarize":
            print(json.dumps(summarize(args.run_dir), indent=2))
    except Exception as exc:
        _log.warning("phase_timing CLI degraded: %s", exc)
        return 0  # never block the pipeline
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "PHASE_TIMINGS_FILENAME",
    "end_phase",
    "read_timings",
    "start_phase",
    "summarize",
]
