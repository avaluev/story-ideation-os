"""Pure-CC dispatch shim for Genius Engine v4.0.

ADR-0007: Replaces the OpenRouter HTTP gateway with Claude Code's native
Task-tool subagent fan-out. This module never calls a model; it only plans
the fan-out manifests and merges the per-Task JSONL outputs back into the
canonical phase JSONL files. The actual `Task` invocations are emitted by
the `/genius` skill body (in the main Claude session), one Task per row of
the dispatch manifest written here.

Why this split exists:
    - The orchestrator (a Claude Code session running the /genius skill) is
      the only place that can call the Task tool. Python code cannot.
    - Python plans the fan-out (which inputs go to which slice, what model
      tier each slice needs, what output path each slice writes to) and
      merges results once Tasks return.
    - This keeps Python LLM-free (ADR-0002 friendly) and lets the harness
      audit every dispatch as a JSONL row.

ADR-0001 compliant: all manifests written via pipeline.state.safe_write;
quota events appended via pipeline.quota.record.

This module MUST NOT import any of: anthropic, httpx, openrouter_client, or
the framework doctrine markdown directory (ANOMALY-001 / ANOMALY-002).

Public API:
    plan(phase, run_id, *, input_path, slice_size, model_tier,
         prompt_template_path, expected_tokens_per_slice) -> Path
    merge(phase, run_id, *, target_path) -> int
    record_task_completion(phase, run_id, slice_id, tokens_in, tokens_out,
                           model_tier) -> None
    cost_estimate(model_tier, tokens_in, tokens_out) -> float

Manifest schema (one row per slice in
`.planning/phase_dispatch/{run_id}/{phase}.jsonl`):

    {
        "run_id": str, "phase": str, "slice_id": int,
        "input_path": str,
        "input_slice": list[dict] (the rows this slice processes),
        "output_path": str (per-Task JSONL the subagent writes),
        "prompt_template_path": str (markdown prompt to render),
        "model_tier": "opus" | "sonnet" | "haiku",
        "expected_tokens": int,
        "produced_at": ISO-8601,
        "status": "PENDING" | "DISPATCHED" | "RETURNED" | "FAILED"
    }

Cost estimation uses the legacy openrouter MODELS rate-card frozen as a
telemetry-only table (no $ billed under the subscription model).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pipeline.quota import ModelTier, PhaseLabel, record
from pipeline.state import append_jsonl, safe_write

DISPATCH_ROOT: Path = Path(".planning/phase_dispatch")
CHUNKS_ROOT: Path = Path("data/_chunks")

# Telemetry-only rate card. Subscription billing is $0; numbers preserved so
# `cost_estimate` keeps backward-compat with the legacy openrouter helper.
_TELEMETRY_RATES: dict[str, tuple[float, float]] = {
    # (input_usd_per_1m, output_usd_per_1m)
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (0.25, 1.25),
}

SliceStatus = Literal["PENDING", "DISPATCHED", "RETURNED", "FAILED"]


def _manifest_path(phase: str, run_id: str) -> Path:
    return DISPATCH_ROOT / run_id / f"{phase}.jsonl"


def _chunks_dir(phase: str, run_id: str) -> Path:
    return CHUNKS_ROOT / run_id / phase


def plan(
    phase: PhaseLabel,
    run_id: str,
    *,
    input_path: Path | str,
    slice_size: int,
    model_tier: ModelTier,
    prompt_template_path: Path | str,
    expected_tokens_per_slice: int,
) -> Path:
    """Slice `input_path` into N dispatch rows and write the manifest.

    Reads `input_path` as JSONL; groups rows in chunks of `slice_size`; emits
    one manifest row per chunk. Returns the manifest path.

    Idempotent: if a manifest already exists, it is overwritten (not
    appended) — the orchestrator can re-plan a phase after a partial failure.
    """
    if slice_size < 1:
        raise ValueError("slice_size must be >= 1")
    if expected_tokens_per_slice < 0:
        raise ValueError("expected_tokens_per_slice must be non-negative")

    input_path = Path(input_path)
    rows: list[dict[str, Any]] = []
    if input_path.exists():
        for line in input_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))

    chunks_dir = _chunks_dir(phase, run_id)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_lines: list[str] = []
    now = datetime.now(UTC).isoformat()

    if not rows:
        # Empty-input edge case: still emit one row so the orchestrator
        # knows the phase ran (e.g. miner has no upstream input).
        manifest_lines.append(
            json.dumps(
                {
                    "run_id": run_id,
                    "phase": phase,
                    "slice_id": 0,
                    "input_path": str(input_path),
                    "input_slice": [],
                    "output_path": str(chunks_dir / "slice_0000.jsonl"),
                    "prompt_template_path": str(prompt_template_path),
                    "model_tier": model_tier,
                    "expected_tokens": expected_tokens_per_slice,
                    "produced_at": now,
                    "status": "PENDING",
                }
            )
        )
    else:
        for slice_id, start in enumerate(range(0, len(rows), slice_size)):
            end = min(start + slice_size, len(rows))
            slice_rows = rows[start:end]
            output_path = chunks_dir / f"slice_{slice_id:04d}.jsonl"
            manifest_lines.append(
                json.dumps(
                    {
                        "run_id": run_id,
                        "phase": phase,
                        "slice_id": slice_id,
                        "input_path": str(input_path),
                        "input_slice": slice_rows,
                        "output_path": str(output_path),
                        "prompt_template_path": str(prompt_template_path),
                        "model_tier": model_tier,
                        "expected_tokens": expected_tokens_per_slice,
                        "produced_at": now,
                        "status": "PENDING",
                    }
                )
            )

    manifest = _manifest_path(phase, run_id)
    safe_write(manifest, "\n".join(manifest_lines) + "\n")
    return manifest


def merge(
    phase: PhaseLabel,
    run_id: str,
    *,
    target_path: Path | str,
) -> int:
    """Merge `data/_chunks/{run_id}/{phase}/slice_*.jsonl` → `target_path`.

    Concatenates all per-Task JSONL outputs into the canonical phase JSONL.
    Deduplicates by the row's `concept_id` or `asset_id` field if present;
    otherwise preserves all rows in slice order.

    Returns the number of unique rows written.
    """
    chunks_dir = _chunks_dir(phase, run_id)
    target = Path(target_path)
    if not chunks_dir.exists():
        safe_write(target, "")
        return 0

    seen: set[str] = set()
    unique_lines: list[str] = []
    for slice_file in sorted(chunks_dir.glob("slice_*.jsonl")):
        for line in slice_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_id = row.get("concept_id") or row.get("asset_id") or row.get("id")
            if row_id is not None:
                if row_id in seen:
                    continue
                seen.add(str(row_id))
            unique_lines.append(line)

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(unique_lines) + ("\n" if unique_lines else "")
    safe_write(target, payload)
    return len(unique_lines)


def record_task_completion(
    phase: PhaseLabel,
    run_id: str,
    slice_id: int,
    tokens_in: int,
    tokens_out: int,
    model_tier: ModelTier,
) -> None:
    """Mark a manifest row RETURNED and record quota burn for that slice.

    Updates the manifest in-place (rewrite via safe_write) and appends a row
    to data/quota.jsonl via pipeline.quota.record.
    """
    record(
        model=model_tier,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        run_id=run_id,
        phase=phase,
    )

    manifest = _manifest_path(phase, run_id)
    if not manifest.exists():
        return

    new_lines: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("slice_id") == slice_id:
            row["status"] = "RETURNED"
            row["completed_at"] = datetime.now(UTC).isoformat()
            row["actual_tokens_in"] = int(tokens_in)
            row["actual_tokens_out"] = int(tokens_out)
        new_lines.append(json.dumps(row))
    safe_write(manifest, "\n".join(new_lines) + "\n")


def cost_estimate(
    model_tier: ModelTier,
    tokens_in: int,
    tokens_out: int,
) -> float:
    """Telemetry-only USD estimate. Subscription billing is $0 in practice.

    The number is preserved so dashboards comparing v3.0 vs v4.0 can show
    the apparent savings; the engine does not act on it.
    """
    if tokens_in < 0 or tokens_out < 0:
        raise ValueError("token counts must be non-negative")
    rates = _TELEMETRY_RATES.get(model_tier)
    if rates is None:
        raise ValueError(f"unknown model_tier: {model_tier!r}")
    in_rate, out_rate = rates
    return (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate


def manifest_summary(phase: PhaseLabel, run_id: str) -> dict[str, int]:
    """Return per-status counts. Used by /genius for human-readable progress."""
    manifest = _manifest_path(phase, run_id)
    counts: dict[str, int] = {
        "PENDING": 0,
        "DISPATCHED": 0,
        "RETURNED": 0,
        "FAILED": 0,
    }
    if not manifest.exists():
        return counts
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        status = row.get("status", "PENDING")
        if status in counts:
            counts[status] += 1
    return counts


def log_dispatch_event(
    phase: PhaseLabel,
    run_id: str,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append a high-level dispatch event to data/run_log.jsonl."""
    append_jsonl(
        Path("data/run_log.jsonl"),
        {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            "phase": phase,
            "run_id": run_id,
            "gateway": "cc",
            **(payload or {}),
        },
    )
