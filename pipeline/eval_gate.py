"""Phase-8 eval gate — extracted from the inline SKILL.md python -c block.

The /single-idea skill's STEP 10 historically ran the eval gate as an inline
``uv run python -c "..."`` block. Two problems:

1. The logic was duplicated between the skill prose and any operator script
   that wanted to re-run a gate manually (e.g. after a hand-patch).
2. There was no clean place to add the **quality.json consultation** that the
   master plan calls for — the 5-vector gate had no consumer in the publish
   decision.

NB.5-EVAL-CONSULT (Cycle 1 Session 6) ships ``pipeline.eval_gate`` as a
proper module + CLI that mirrors the existing
:mod:`pipeline.evaluate_draft_quality` and :mod:`pipeline.quality_report`
pattern. The skill's STEP 10 patch (when the operator applies it) becomes
a single ``uv run python -m pipeline.eval_gate --run-dir {run_dir}`` line.

Tier-1 gates (unchanged from the previous inline implementation):

  - INTERNAL_IDS         — :func:`pipeline.template_filter.scan_for_internal_ids`
                           must return an empty list against the concept md.
  - SOM_BELOW_100M       — :func:`pipeline.template_filter.parse_som` must
                           return a value ≥ $100M. With NB-PARSE-SOM-WIDEN,
                           investor-readable variants are now accepted.
  - TEMPLATE_NONCOMPLIANT — :func:`pipeline.template_filter.check_template_compliance`
                           must return passed=True.

Tier-2 gate (NEW with NB.5-EVAL-CONSULT):

  - QUALITY_GATE_FAIL    — When ``runs/{id}/quality.json`` exists AND
                           ``overall_pass`` is False, emit a failure entry.
                           Default mode is **informational** (the eval still
                           returns ``verdict=PASS`` if all Tier-1 gates pass);
                           pass ``--strict-quality`` to make it gating.

Patcher routing (NEW with NB-EVAL-L5-RECONNECT, Cycle 1 Session 7):

Each failure code carries a ``preferred_patcher`` ("drafter" or "narrator")
identifying the agent that owns the failing artifact. The eval.json output
now includes a ``patcher_routing`` field grouping failure codes by patcher,
so the L5 SKILL.md branch can dispatch concept-md-rooted failures to the
concept-drafter and narrator-md-rooted failures to the concept-narrator.

Routing rationale (B1'' closure — eval_gate scans the concept md, L5
previously rewrote only the narrator md, leaving concept-rooted failures
auto-unfixable):

  - INTERNAL_IDS         → drafter (concept md owns the leaked term).
  - SOM_BELOW_100M       → drafter (SOM line lives under "Market & Audience"
                           of {slug}.md, written by the drafter).
  - TEMPLATE_NONCOMPLIANT → drafter (V2 template structure is the drafter's
                           contract).
  - QUALITY_GATE_FAIL    → drafter (the 5-vector axes read from draft_v0
                           sections; remediation revises the draft).
  - CONCEPT_MD_MISSING   → drafter (must produce the md).

Forward-compat: future narrator-rooted codes (e.g. NARRATOR_LOGLINE_DRIFT)
are added to :data:`PREFERRED_PATCHER_BY_CODE`. Unknown codes default to
drafter — the concept md is the canonical artifact, safe fallback.

Soft warnings (non-fatal; surfaced under ``warnings`` field in eval.json):

  - SOM_LINE_NON_CANONICAL — :func:`pipeline.template_filter.is_som_line_canonical`
                             returned False. The SOM parsed, but the line
                             isn't in the preferred ``**SOM (Year 1):** $NNN[M|B]``
                             shape — nudge the drafter without rejecting.
  - QUALITY_GATE_FAIL    — When not strict-quality, the quality failure
                           surfaces as a warning instead of a failure.

Atomic write (ADR-0001): ``eval.json`` is written via
:func:`pipeline.state.safe_write`.

CLI surface (mirrors :mod:`pipeline.phase_timing` and
:mod:`pipeline.evaluate_draft_quality`):

    uv run python -m pipeline.eval_gate --run-dir runs/{id} [--strict-quality]

Returns exit code 0 on PASS, 1 on FAIL. Soft-fail on any internal
exception (logs warning, exits 0) — instrumentation must never block
the pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pipeline import state
from pipeline.template_filter import (
    check_template_compliance,
    is_som_line_canonical,
    parse_som,
    scan_for_internal_ids,
)

_ = cast  # keep the import (typed reference; formatter would otherwise strip it)

_log = logging.getLogger(__name__)

EVAL_FILENAME = "eval.json"
QUALITY_FILENAME = "quality.json"
DRAFT_FILENAME = "draft_v0.json"

# Failure codes (string constants used in eval.json["failures"]).
F_CONCEPT_MD_MISSING = "CONCEPT_MD_MISSING"
F_INTERNAL_IDS = "INTERNAL_IDS"
F_SOM_BELOW_100M = "SOM_BELOW_100M"
F_TEMPLATE_NONCOMPLIANT = "TEMPLATE_NONCOMPLIANT"
F_QUALITY_GATE_FAIL = "QUALITY_GATE_FAIL"

# Warning codes (string constants used in eval.json["warnings"]).
W_SOM_LINE_NON_CANONICAL = "SOM_LINE_NON_CANONICAL"

# Patcher identifiers (eval.json["patcher_routing"] keys).
PATCHER_DRAFTER = "drafter"
PATCHER_NARRATOR = "narrator"

# Canonical mapping from failure code → patcher agent that owns the failing
# artifact. The L5 SKILL.md branch reads ``eval.patcher_routing`` to decide
# whether to invoke the concept-drafter or the concept-narrator.
#
# Today every Tier-1/Tier-2 code is concept-md-rooted. The narrator pathway
# stays exposed (always present as an empty bucket) so the dispatch in the
# skill is symmetric and forward-compatible with future narrator-rooted codes.
PREFERRED_PATCHER_BY_CODE: dict[str, str] = {
    F_CONCEPT_MD_MISSING: PATCHER_DRAFTER,
    F_INTERNAL_IDS: PATCHER_DRAFTER,
    F_SOM_BELOW_100M: PATCHER_DRAFTER,
    F_TEMPLATE_NONCOMPLIANT: PATCHER_DRAFTER,
    F_QUALITY_GATE_FAIL: PATCHER_DRAFTER,
}

_SOM_FLOOR_M = 100.0


def classify_failures(eval_result: dict[str, Any]) -> dict[str, list[str]]:
    """Route eval failures to the patcher agent that owns the failing rule.

    Returns a dict shaped ``{"drafter": [...], "narrator": [...]}`` keyed by
    :data:`PATCHER_DRAFTER` / :data:`PATCHER_NARRATOR`. Both buckets are
    always present (possibly empty) so the SKILL.md L5 dispatch can branch
    without nil-checks.

    Codes not present in :data:`PREFERRED_PATCHER_BY_CODE` default to the
    drafter bucket — the concept md is the canonical artifact, and routing
    an unknown failure to the drafter is the safe fallback (forward-compat
    with future codes added before the table is updated).

    Non-string entries in ``failures`` are silently skipped (defensive).
    """
    routing: dict[str, list[str]] = {PATCHER_DRAFTER: [], PATCHER_NARRATOR: []}
    failures_any = eval_result.get("failures", [])
    if not isinstance(failures_any, list):
        return routing
    failures_list = cast("list[Any]", failures_any)
    for entry in failures_list:
        if not isinstance(entry, str):
            continue
        patcher = PREFERRED_PATCHER_BY_CODE.get(entry, PATCHER_DRAFTER)
        routing.setdefault(patcher, []).append(entry)
    return routing


def _load_json(path: Path) -> dict[str, Any] | None:
    """Read JSON object; return None on missing or malformed."""
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("eval_gate: sidecar %s unreadable: %s", path, exc)
        return None
    if not isinstance(loaded, dict):
        return None
    return cast("dict[str, Any]", loaded)


def _quality_overall_pass(run_dir: Path) -> bool | None:
    """Return overall_pass from quality.json, or None when sidecar is absent.

    None means "the 5-vector gate was not run for this concept" — we treat
    that as informational, not a failure, even in strict-quality mode. Only
    an explicit ``overall_pass: false`` triggers the gate.
    """
    quality = _load_json(run_dir / QUALITY_FILENAME)
    if quality is None:
        return None
    raw = quality.get("overall_pass")
    return raw if isinstance(raw, bool) else None


def run_eval_gate(
    run_dir: Path | str,
    strict_quality: bool = False,
) -> dict[str, Any]:
    """Run the eval gate against a single run directory.

    Args:
        run_dir: path to ``runs/{id}``.
        strict_quality: when True, a failed 5-vector gate (quality.json
            overall_pass=False) becomes a ``QUALITY_GATE_FAIL`` entry in
            ``failures`` and the verdict flips to FAIL. When False (default,
            Cycle 1 contract), a quality failure surfaces as a warning under
            ``warnings`` and the verdict reflects only Tier-1 gates.

    Returns the eval.json payload (also written to ``run_dir/eval.json``).
    """
    run_dir_p = Path(run_dir)
    draft = _load_json(run_dir_p / DRAFT_FILENAME)
    failures: list[str] = []
    warnings: list[str] = []
    per_file: dict[str, dict[str, Any]] = {}

    if draft is None:
        result: dict[str, Any] = {
            "verdict": "FAIL",
            "failures": [F_CONCEPT_MD_MISSING],
            "warnings": warnings,
            "per_file": per_file,
            "quality_consulted": False,
            "strict_quality": bool(strict_quality),
            "produced_at": datetime.now(UTC).isoformat(),
        }
        result["patcher_routing"] = classify_failures(result)
        state.safe_write(run_dir_p / EVAL_FILENAME, json.dumps(result, indent=2))
        return result

    slug = str(draft.get("slug", "")).strip()
    md_path = run_dir_p / f"{slug}.md" if slug else None

    if md_path is None or not md_path.exists():
        result = {
            "verdict": "FAIL",
            "failures": [F_CONCEPT_MD_MISSING],
            "warnings": warnings,
            "per_file": per_file,
            "quality_consulted": False,
            "strict_quality": bool(strict_quality),
            "produced_at": datetime.now(UTC).isoformat(),
        }
        result["patcher_routing"] = classify_failures(result)
        state.safe_write(run_dir_p / EVAL_FILENAME, json.dumps(result, indent=2))
        return result

    text = md_path.read_text(encoding="utf-8")

    # Tier 1 gates.
    hits = scan_for_internal_ids(text)
    som = parse_som(text)
    compliance = check_template_compliance(text)

    if hits:
        failures.append(F_INTERNAL_IDS)
    if som is None or som[0] < _SOM_FLOOR_M:
        failures.append(F_SOM_BELOW_100M)
    elif not is_som_line_canonical(text):
        warnings.append(W_SOM_LINE_NON_CANONICAL)
    template_passed = bool(compliance.get("passed"))
    if not template_passed:
        failures.append(F_TEMPLATE_NONCOMPLIANT)

    # Tier 2 gate (NB.5-EVAL-CONSULT).
    quality_pass = _quality_overall_pass(run_dir_p)
    quality_consulted = quality_pass is not None
    if quality_consulted and quality_pass is False:
        if strict_quality:
            failures.append(F_QUALITY_GATE_FAIL)
        else:
            warnings.append(F_QUALITY_GATE_FAIL)

    per_file[md_path.name] = {
        "internal_id_count": len(hits),
        "som_usd_millions": som[0] if som else None,
        "som_line_canonical": is_som_line_canonical(text),
        "template_passed": template_passed,
        "template_failures": compliance.get("failures", []),
        "quality_overall_pass": quality_pass,
    }

    result = {
        "verdict": "PASS" if not failures else "FAIL",
        "failures": failures,
        "warnings": warnings,
        "per_file": per_file,
        "quality_consulted": quality_consulted,
        "strict_quality": bool(strict_quality),
        "produced_at": datetime.now(UTC).isoformat(),
    }
    result["patcher_routing"] = classify_failures(result)
    state.safe_write(run_dir_p / EVAL_FILENAME, json.dumps(result, indent=2))
    return result


def _main() -> int:
    """CLI entry: ``uv run python -m pipeline.eval_gate --run-dir <run_dir>``.

    Soft-fail on any exception so instrumentation never blocks the pipeline.
    Exit 0 on PASS, 1 on FAIL.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="pipeline.eval_gate")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Treat quality.json.overall_pass=false as a hard FAIL (Cycle 2 toggle).",
    )
    args = parser.parse_args()

    try:
        result = run_eval_gate(Path(args.run_dir), strict_quality=args.strict_quality)
    except Exception as exc:  # pragma: no cover — soft-fail backstop
        _log.warning("eval_gate CLI degraded: %s", exc)
        return 0

    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "DRAFT_FILENAME",
    "EVAL_FILENAME",
    "F_CONCEPT_MD_MISSING",
    "F_INTERNAL_IDS",
    "F_QUALITY_GATE_FAIL",
    "F_SOM_BELOW_100M",
    "F_TEMPLATE_NONCOMPLIANT",
    "PATCHER_DRAFTER",
    "PATCHER_NARRATOR",
    "PREFERRED_PATCHER_BY_CODE",
    "QUALITY_FILENAME",
    "W_SOM_LINE_NON_CANONICAL",
    "classify_failures",
    "run_eval_gate",
]
