"""V4A-004 — v4 isolation pre-flight gate.

Run BEFORE every v4 forge / mine / dispatch. Validates that the run
target lives on the v4 partition (NEVER on v3.1) and creates the
destination tree if absent.

Usage::

    uv run python scripts/v4_preflight.py --run-id 20260510T035500Z
    uv run python scripts/v4_preflight.py --run-id 20260510T035500Z --force

Exit codes:
    0 — pre-flight green; safe to dispatch v4 Tasks
    2 — isolation violation (path on v3.1 partition); halt the run
    3 — pre-flight bypass requested but rationale file missing
    4 — invalid run_id format

See docs/v4_isolation.md for the path partition contract.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

V4_RUNS_ROOT = Path("data/runs/v4-genius-cc")
V4_OUT_ROOT = Path("out/concepts/v4-genius-cc")
V3_RUNS_ROOT_PATTERN = re.compile(r"data/runs/v3\.1-")
V3_OUT_ROOT_PATTERN = re.compile(r"out/concepts/v3\.1-")
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _validate_run_id(run_id: str) -> str | None:
    if not RUN_ID_RE.match(run_id):
        return f"run_id must match {RUN_ID_RE.pattern}; got {run_id!r}"
    return None


def _scan_for_v3_pollution(run_dir: Path) -> list[str]:
    """Return list of polluted paths if run_dir contains any v3.1-rooted files."""
    if not run_dir.exists():
        return []
    polluted: list[str] = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        text = str(path)
        if V3_RUNS_ROOT_PATTERN.search(text) or V3_OUT_ROOT_PATTERN.search(text):
            polluted.append(text)
    return polluted


def _emit_envelope(run_id: str, run_dir: Path, out_dir: Path, status: str, **extra: object) -> dict:
    envelope = {
        "schema_version": "1.0",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "out_dir": str(out_dir),
        "ts": _now_iso(),
        "preflight_status": status,
        "v4_isolation_protocol": "docs/v4_isolation.md",
        **extra,
    }
    return envelope


def _check_bypass() -> tuple[bool, str | None]:
    """If V4_PREFLIGHT_BYPASS=1, return (True, rationale_text). Else (False, None).
    Returns (True, None) iff bypass requested but rationale file is missing
    — caller should treat that as exit 3."""
    if os.environ.get("V4_PREFLIGHT_BYPASS", "").strip() != "1":
        return (False, None)
    rationale_glob = list(V4_RUNS_ROOT.rglob("preflight.bypass"))
    if not rationale_glob:
        return (True, None)
    return (True, rationale_glob[-1].read_text(encoding="utf-8").strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v4 isolation pre-flight gate")
    parser.add_argument(
        "--run-id", required=True, help="ISO-8601 compact run-id (YYYYMMDDTHHMMSSZ)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="recreate run dir if it exists with no rows; refuses non-empty dirs",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress JSON envelope output (still writes preflight.json)",
    )
    args = parser.parse_args(argv)

    err = _validate_run_id(args.run_id)
    if err:
        print(f"PREFLIGHT FAIL: {err}", file=sys.stderr)
        return 4

    run_dir = V4_RUNS_ROOT / args.run_id
    out_dir = V4_OUT_ROOT  # shared output dir; per-run grouping is by concept_id prefix

    # Hard partition check: refuse if either path string contains v3.1
    if V3_RUNS_ROOT_PATTERN.search(str(run_dir)) or V3_OUT_ROOT_PATTERN.search(str(out_dir)):
        print(
            f"PREFLIGHT FAIL: target on v3.1 partition: run_dir={run_dir} out_dir={out_dir}",
            file=sys.stderr,
        )
        return 2

    # Scan existing tree for cross-partition pollution
    polluted = _scan_for_v3_pollution(run_dir)
    if polluted:
        print(
            f"PREFLIGHT FAIL: v3.1-rooted paths found inside {run_dir}:\n  "
            + "\n  ".join(polluted),
            file=sys.stderr,
        )
        return 2

    # Bypass handling
    bypass_active, bypass_rationale = _check_bypass()
    if bypass_active and bypass_rationale is None:
        print(
            "PREFLIGHT FAIL: V4_PREFLIGHT_BYPASS=1 set but no preflight.bypass file with rationale",
            file=sys.stderr,
        )
        return 3

    # Force handling: refuse if run_dir has any phase JSONL with rows
    if args.force and run_dir.exists():
        for jsonl in run_dir.glob("*.jsonl"):
            if jsonl.stat().st_size > 0:
                print(
                    f"PREFLIGHT FAIL: --force refused; {jsonl} has rows. Manual review required.",
                    file=sys.stderr,
                )
                return 2

    # Create destination tree
    run_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "_chunks").mkdir(exist_ok=True)

    envelope = _emit_envelope(
        run_id=args.run_id,
        run_dir=run_dir,
        out_dir=out_dir,
        status="GREEN",
        bypass_active=bypass_active,
        bypass_rationale=bypass_rationale,
        force=args.force,
    )
    (run_dir / "preflight.json").write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not args.quiet:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
