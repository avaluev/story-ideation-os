"""CLI entry point for the v4 Single-Idea Pipeline.

Usage:
    uv run python -m pipeline.run_single_idea --theme "..."
    uv run python -m pipeline.run_single_idea --theme "..." --run-id 2026-05-12-110000
    uv run python -m pipeline.run_single_idea --resume --run-id 2026-05-12-110000

Responsibilities:
  - Create runs/{run_id}/ directory
  - Write seed.json (Phase 0)
  - Print a JSON summary the /single-idea skill reads to drive the rest of the pipeline

MUST NOT import anthropic, httpx, or openrouter_client (ANOMALY-001).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from pipeline import phase_timing
from pipeline.single_idea import SingleIdeaOrchestrator
from pipeline.state import safe_write

try:
    from pipeline import seed_moa as _seed_moa
except ImportError:  # not available in all envs / test harnesses
    _seed_moa = None  # type: ignore[assignment]

_log = logging.getLogger(__name__)

_RUNS_DIR = Path("runs")
_SLUG_MAX_LEN: int = 40

_BYPASS_WARNING = (
    "ENGINE BYPASSED: --use-moa not set. seed.json contains only the 5-key "
    "passthrough (theme + target_format + empty conflict_axes + empty "
    "hidden_attributes + produced_at). The 19.2T-combination compound_seed "
    "engine — sdt_wound, psychological_pattern, structural_inversion, "
    "moral_fault_line, compression_key, divisiveness_engine, world_texture, "
    "civilizational_stake, methodology_protagonist, historical_transplant, "
    "archetypes, conspiracy_engine, reptile_trigger, open_problem, cultural_moment, "
    "tensions, scores, commercial_signal_flags — was NOT sampled. To engage it, "
    "pass --use-moa. The Python judge fallback makes it offline-resilient when "
    "OpenRouter credits are exhausted."
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Single-Idea Pipeline v4.0 — init and phase-state management.",
)


def _slugify(text: str, max_len: int = _SLUG_MAX_LEN) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    slug = slug.strip("-")
    return slug[:max_len].rstrip("-")


def _make_run_id(theme: str) -> str:
    ts = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    return f"{ts}-{_slugify(theme)}"


def _write_seed(run_dir: Path, theme: str, use_moa: bool = False) -> None:
    """Write seed.json for Phase 0.

    When use_moa=True and seed_moa is available, runs the Mixture-of-Experts
    generator (3 biased seeders + pure-Python judge) and merges its output
    with the base seed fields. Falls back to the basic seed if seed_moa is
    unavailable (e.g., in test environments without the full dependency tree).
    """
    base: dict[str, object] = {
        "theme": theme,
        "target_format": "feature",
        "conflict_axes": [],
        "hidden_attributes": {},
        "produced_at": datetime.now(UTC).isoformat(),
    }

    if use_moa and _seed_moa is not None:
        result = _seed_moa.generate(themes=[theme], max_attempts=20)
        moa_dict = result.selected.to_dict()
        # Merge: base fields take precedence for top-level keys that overlap.
        seed: dict[str, object] = {**moa_dict, **base}
        # Expose the MoA candidates list for inspection / downstream agents.
        hidden: dict[str, object] = dict(moa_dict.get("hidden_attrs") or {})
        hidden["moa_candidates"] = result.seeder_names
        hidden["moa_judge_rationale"] = result.judge_rationale
        seed["hidden_attributes"] = hidden
        _log.info("seed_capture: engine engaged — %d dimensions populated", len(seed))
    else:
        seed = base
        # Loud warning so the silent-bypass footgun shipped in Sessions A/B/C
        # cannot recur without the operator seeing it. The 5-key passthrough
        # is a valid mode for some workflows but should never be silent.
        if use_moa and _seed_moa is None:
            _log.warning(
                "ENGINE UNAVAILABLE: --use-moa requested but pipeline.seed_moa "
                "could not be imported — falling back to 5-key passthrough."
            )
        else:
            _log.warning(_BYPASS_WARNING)

    safe_write(run_dir / "seed.json", json.dumps(seed, indent=2))


@app.command()
def main(
    theme: Annotated[str, typer.Option("--theme", help="Film/series theme or pitch sentence")],
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Run identifier (auto-generated if omitted)"),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume/--no-resume", help="Resume from last completed phase"),
    ] = False,
    use_moa: Annotated[
        bool,
        typer.Option(
            "--use-moa/--no-use-moa",
            help="Use Mixture-of-Experts seed generation (3 biased seeders + judge)",
        ),
    ] = False,
) -> None:
    """Initialize a single-idea pipeline run.

    Creates runs/{run_id}/, writes seed.json (Phase 0 when not resuming),
    and prints a JSON summary for the /single-idea skill to consume.
    """
    if run_id is None:
        run_id = _make_run_id(theme)

    run_dir = _RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    orch = SingleIdeaOrchestrator(run_dir=run_dir, theme=theme, resume=resume)
    orch.use_moa = use_moa

    seed_path = orch.sidecar_paths["seed"]
    if not resume and not seed_path.exists():
        phase_timing.start_phase(run_dir, phase_index=0, phase_name="seed_capture")
        _write_seed(run_dir, theme, use_moa=use_moa)
        phase_timing.end_phase(run_dir, phase_index=0, phase_name="seed_capture")
        orch.current_phase = 1  # Phase 0 (seed_capture) is now complete

    phase_idx = orch.current_phase
    phase_name = orch.phase_names[phase_idx] if phase_idx < len(orch.phase_names) else "complete"

    summary = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "theme": theme,
        "current_phase": phase_idx,
        "current_phase_name": phase_name,
        "is_halted": orch.is_halted,
    }
    typer.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    app()
