"""Typer CLI for the Pure-CC dispatch shim (Step 2 of the v4 migration).

The legacy `pipeline.run` still exists for `--gateway=openrouter` compatibility.
This sibling module exposes two new sub-commands the `/genius` skill body
calls between Task fan-outs:

    uv run python -m pipeline.run_cc plan   --phase miner --run-id ...
    uv run python -m pipeline.run_cc merge  --phase miner --run-id ...
    uv run python -m pipeline.run_cc status --run-id ...
    uv run python -m pipeline.run_cc record --phase critic --run-id ... \
                                            --slice-id 3 --tokens-in 800 \
                                            --tokens-out 200 --model-tier sonnet

`plan` writes the dispatch manifest the skill consumes; `merge` concatenates
per-Task slice JSONLs into the canonical phase JSONL; `status` prints a
per-status summary row count; `record` lets the skill confirm a slice
returned (orchestrator → quota.jsonl).

This module MUST NOT import anthropic / httpx / openrouter_client (lint rule
ANOMALY-001 covers it; no Pydantic schema work either — pure CLI plumbing).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from pipeline import cc_dispatch
from pipeline.quota import (
    ModelTier,
    PhaseLabel,
    print_status,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Pure-CC dispatch CLI — plan, merge, record, status.",
)
_console = Console()


@app.command()
def plan(
    phase: Annotated[str, typer.Option(help="Phase label (miner/mapper/...)")],
    run_id: Annotated[str, typer.Option(help="Run UUID hex")],
    input_path: Annotated[
        Path, typer.Option(help="Upstream JSONL to slice (existing file or empty)")
    ],
    slice_size: Annotated[int, typer.Option(min=1, help="Rows per slice")] = 1,
    model_tier: Annotated[str, typer.Option(help="opus | sonnet | haiku")] = "sonnet",
    prompt_template_path: Annotated[
        Path, typer.Option(help="Markdown prompt template the agent renders")
    ] = Path("prompts/01-asset-miner.md"),
    expected_tokens: Annotated[
        int, typer.Option(min=0, help="Expected per-slice token budget")
    ] = 6000,
) -> None:
    """Slice the upstream JSONL into a dispatch manifest.

    Outputs the absolute path of the manifest to stdout (one line, no
    decoration) so the skill body can capture it via `$(...)` shell
    substitution.
    """
    if model_tier not in ("opus", "sonnet", "haiku"):
        _console.print(f"[red]invalid model_tier {model_tier!r}; must be opus|sonnet|haiku[/red]")
        raise typer.Exit(2)

    manifest = cc_dispatch.plan(
        phase=_cast_phase(phase),
        run_id=run_id,
        input_path=input_path,
        slice_size=slice_size,
        model_tier=_cast_tier(model_tier),
        prompt_template_path=prompt_template_path,
        expected_tokens_per_slice=expected_tokens,
    )
    cc_dispatch.log_dispatch_event(
        phase=_cast_phase(phase),
        run_id=run_id,
        event="phase_planned",
        payload={"manifest": str(manifest), "slice_size": slice_size},
    )
    sys.stdout.write(str(manifest) + "\n")


@app.command()
def merge(
    phase: Annotated[str, typer.Option(help="Phase label (miner/mapper/...)")],
    run_id: Annotated[str, typer.Option(help="Run UUID hex")],
    target_path: Annotated[Path, typer.Option(help="Canonical phase JSONL the merge writes")],
) -> None:
    """Concatenate per-Task slice JSONLs into the canonical phase JSONL.

    Prints `merged: <n>` to stdout. Idempotent: re-running with the same
    chunks produces the same target with no duplicates (dedup by row id).
    """
    n = cc_dispatch.merge(
        phase=_cast_phase(phase),
        run_id=run_id,
        target_path=target_path,
    )
    cc_dispatch.log_dispatch_event(
        phase=_cast_phase(phase),
        run_id=run_id,
        event="phase_merged",
        payload={"target": str(target_path), "rows": n},
    )
    sys.stdout.write(f"merged: {n}\n")


@app.command()
def status(
    phase: Annotated[str, typer.Option(help="Phase label (miner/mapper/...)")],
    run_id: Annotated[str, typer.Option(help="Run UUID hex")],
) -> None:
    """Print per-status row counts of the manifest. Used by /genius for progress."""
    summary = cc_dispatch.manifest_summary(
        phase=_cast_phase(phase),
        run_id=run_id,
    )
    sys.stdout.write(json.dumps(summary) + "\n")


@app.command()
def record(
    phase: Annotated[str, typer.Option(help="Phase label (miner/mapper/...)")],
    run_id: Annotated[str, typer.Option(help="Run UUID hex")],
    slice_id: Annotated[int, typer.Option(min=0, help="Slice ID returned by Task")],
    tokens_in: Annotated[int, typer.Option(min=0, help="Actual prompt tokens")],
    tokens_out: Annotated[int, typer.Option(min=0, help="Actual completion tokens")],
    model_tier: Annotated[str, typer.Option(help="opus | sonnet | haiku")],
) -> None:
    """Mark a slice RETURNED + record quota burn. Idempotent on re-run."""
    if model_tier not in ("opus", "sonnet", "haiku"):
        _console.print(f"[red]invalid model_tier {model_tier!r}[/red]")
        raise typer.Exit(2)
    cc_dispatch.record_task_completion(
        phase=_cast_phase(phase),
        run_id=run_id,
        slice_id=slice_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model_tier=_cast_tier(model_tier),
    )
    sys.stdout.write(
        f"recorded slice={slice_id} model={model_tier} tokens={tokens_in}+{tokens_out}\n"
    )


@app.command()
def quota() -> None:
    """Print current ISO-week subscription burn by tier (operator banner)."""
    sys.stdout.write(print_status() + "\n")


def _cast_phase(phase: str) -> PhaseLabel:
    """Narrow the str→PhaseLabel for type-checker satisfaction."""
    valid = {
        "miner",
        "mapper",
        "validator",
        "forger",
        "critic",
        "judge",
        "formatter",
        "mutation",
        "other",
    }
    if phase not in valid:
        raise typer.BadParameter(f"phase must be one of {sorted(valid)}, got {phase!r}")
    return phase  # type: ignore[return-value]


def _cast_tier(tier: str) -> ModelTier:
    """Narrow the str→ModelTier for type-checker satisfaction."""
    return tier  # type: ignore[return-value]


if __name__ == "__main__":
    app()
