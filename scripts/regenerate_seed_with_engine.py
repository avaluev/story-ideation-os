"""scripts/regenerate_seed_with_engine.py — Engage the compound_seed engine on an existing theme.

Why this exists
---------------
``pipeline/run_single_idea.py:_write_seed`` defaults to a 5-key passthrough
(theme, target_format, conflict_axes=[], hidden_attributes={}, produced_at) and
only engages ``pipeline/seed_moa.generate`` when ``--use-moa`` is set on the
CLI. Sessions A/B/C ran in default mode, so the 19.2T-combination compound
seed engine was never invoked for them — only the operator's prose theme
reached the drafter.

This script re-runs the seed stage with the engine engaged on an existing
theme. It works offline: ``seed_moa.generate`` uses ``CompoundSeedEngine``
which falls back to template generation when the OpenRouter PAID key is
exhausted (HTTP 402), and ``_llm_judge`` falls back to ``_python_judge``
on any LLM failure. Result is a fully populated 30+ field seed.json that
preserves the operator's original theme.

Usage
-----
    uv run python -m scripts.regenerate_seed_with_engine \\
        --source-seed runs/2026-05-21-T1541-climate-cascade/seed.json \\
        --output-dir   runs/2026-05-22-Txxxx-climate-cascade-engine

Outputs
-------
- ``{output_dir}/seed.json``        — engine-engaged seed (30+ keys, original
                                       theme preserved verbatim)
- ``{output_dir}/seed_diff.json``   — old vs new key list + dimension counts
- Stdout: human-readable summary
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline import seed_moa
from pipeline.state import safe_write

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_source_seed(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Source seed not found: {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if "theme" not in data:
        raise ValueError(f"Source seed at {path} has no 'theme' field")
    return data


def regenerate(
    theme: str,
    target_format: str,
    output_dir: Path,
    max_attempts: int = 20,
) -> dict[str, Any]:
    """Run seed_moa on the theme and write a merged seed.json.

    Returns the new seed dict (also written to ``output_dir/seed.json``).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    _log.info("Engaging seed_moa.generate(themes=[<%d chars>])", len(theme))
    result = seed_moa.generate(themes=[theme], max_attempts=max_attempts)
    selected_dict: dict[str, Any] = result.selected.to_dict()

    base = {
        "theme": theme,
        "target_format": target_format,
        "produced_at": datetime.now(UTC).isoformat(),
        # conflict_axes/hidden_attributes intentionally omitted from base so
        # engine-provided values pass through; we patch them below.
    }

    seed: dict[str, Any] = {**selected_dict, **base}

    # Preserve hidden_attrs from the engine, plus MoA audit trail.
    hidden_attrs = dict(selected_dict.get("hidden_attrs") or {})
    hidden_attrs["moa_candidates"] = [
        {
            "seeder": seeder,
            "som_floor_M": cand.scores.som_floor_M,
            "genius_score": cand.scores.genius_score,
            "selected": cand is result.selected,
        }
        for seeder, cand in zip(result.seeder_names, result.candidates, strict=False)
    ]
    hidden_attrs["moa_judge_rationale"] = result.judge_rationale
    hidden_attrs["regenerated_by"] = "scripts/regenerate_seed_with_engine.py"
    seed["hidden_attributes"] = hidden_attrs
    # Drop the duplicate hidden_attrs key (now lives under hidden_attributes).
    seed.pop("hidden_attrs", None)

    seed_path = output_dir / "seed.json"
    safe_write(seed_path, json.dumps(seed, indent=2, ensure_ascii=False))
    _log.info("Wrote engaged seed to %s", seed_path)

    return seed


def _summarize_seed(seed: dict[str, Any]) -> dict[str, Any]:
    """Return a {key: cardinality} summary for human-readable diffing."""
    summary: dict[str, Any] = {}
    for k, v in seed.items():
        if isinstance(v, list):
            summary[k] = f"list[{len(v)}]"
        elif isinstance(v, dict):
            summary[k] = f"dict[{len(v)}]"
        elif isinstance(v, str):
            summary[k] = f"str[{len(v)}]"
        elif v is None:
            summary[k] = "null"
        else:
            summary[k] = str(type(v).__name__)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--source-seed",
        type=Path,
        required=True,
        help="Path to an existing seed.json (provides theme + target_format).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write the new seed.json (will be created).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=20,
        help="Per-seeder generation attempt cap (default 20).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show INFO-level logs from the engine.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    source = _load_source_seed(args.source_seed.resolve())
    theme: str = source["theme"]
    target_format: str = source.get("target_format", "feature")

    new_seed = regenerate(
        theme=theme,
        target_format=target_format,
        output_dir=args.output_dir.resolve(),
        max_attempts=args.max_attempts,
    )

    # Write a side-by-side diff sidecar.
    diff = {
        "source_seed_path": str(args.source_seed),
        "source_key_count": len(source),
        "source_summary": _summarize_seed(source),
        "new_seed_path": str((args.output_dir / "seed.json").resolve()),
        "new_key_count": len(new_seed),
        "new_summary": _summarize_seed(new_seed),
        "delta_keys_added": sorted(set(new_seed) - set(source)),
        "delta_keys_removed": sorted(set(source) - set(new_seed)),
    }
    diff_path = args.output_dir / "seed_diff.json"
    safe_write(diff_path, json.dumps(diff, indent=2, ensure_ascii=False))

    # Stdout summary.
    print("=" * 72)
    print(f"SOURCE  : {args.source_seed} — {len(source)} keys")
    print(f"NEW     : {args.output_dir}/seed.json — {len(new_seed)} keys")
    print("=" * 72)
    print(f"Keys added by engine ({len(diff['delta_keys_added'])}):")
    for k in diff["delta_keys_added"]:
        print(f"  + {k:32s}  {_summarize_seed(new_seed)[k]}")
    if diff["delta_keys_removed"]:
        print(f"Keys removed ({len(diff['delta_keys_removed'])}):")
        for k in diff["delta_keys_removed"]:
            print(f"  - {k}")
    print("=" * 72)
    print(f"Diff sidecar: {diff_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
