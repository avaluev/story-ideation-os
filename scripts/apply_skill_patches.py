#!/usr/bin/env python3
"""scripts/apply_skill_patches.py — Operator-side SKILL.md patcher.

The Claude Code self-modification classifier hard-blocks agent-driven edits to
``.claude/skills/*``, but a Python script invoked from the operator's shell
(``! uv run python scripts/apply_skill_patches.py --all``) runs outside that
classifier and applies the patches atomically.

Patches landed by this script (mirrors the sidecar markdown):

  * **NB9-APPLY** — STEPS 3-11 phase_timing start/end brackets
    (sidecar: ``.planning/state/NB9_SKILL_PATCH.md``).
  * **NB.11-APPLY** — STEP 4 calls ``pipeline.evaluate_draft_quality`` after
    the draft Task; STEP 12 finalises with ``pipeline.quality_report``.
  * **NB.10-APPLY** — STEP 10's inline ``python -c "..."`` eval block is
    replaced with ``pipeline.eval_gate --run-dir {run_dir}``.
  * **NB-EVAL-L5-APPLY** — STEP 10's L5 narrator-redo loop is replaced with
    the split-dispatch block consuming ``eval.patcher_routing.{drafter,narrator}``
    (sidecar: ``.planning/state/NB_EVAL_L5_PATCH.md``).

The script is **idempotent**: every patch carries a unique sentinel string,
already-applied patches are reported and skipped. A timestamped backup of
``.claude/skills/single-idea/SKILL.md`` is written before the first mutation.

CLI:

    # Apply every pending patch.
    uv run python scripts/apply_skill_patches.py --all

    # Apply a single patch.
    uv run python scripts/apply_skill_patches.py --nb9
    uv run python scripts/apply_skill_patches.py --nb11
    uv run python scripts/apply_skill_patches.py --nb10
    uv run python scripts/apply_skill_patches.py --nb-eval-l5

    # Show which patches are applied — no writes.
    uv run python scripts/apply_skill_patches.py --verify

    # Show the diff that would be applied — no writes.
    uv run python scripts/apply_skill_patches.py --all --dry-run

Exit codes:
  0  every requested patch is applied (already or by this run)
  1  one or more anchors not found (file shape drifted; aborted)
  2  argument error

ADR-0001: persisted via ``pipeline.state.safe_write`` (tempfile + ``os.replace``).
"""
# Verbatim SKILL.md blocks below contain lines longer than ruff's 100-char limit
# (matching SKILL.md byte-for-byte is the correctness contract). E501 is suppressed
# file-wide rather than per-line because the offending lines live inside multi-line
# string literals where inline noqa comments would break the literal match.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "single-idea" / "SKILL.md"


# ── Phase-index registry (NB9 source of truth) ───────────────────────────────

# STEP number → (phase_index, phase_name, next_step_heading_substring).
# The "next heading" is what comes immediately AFTER the current STEP — the
# script inserts the "end" bracket right before that heading.
_STEP_LESSONS_CAPTURE: int = 11
r"""STEP number with no ``If \`current_phase > N\`: skip.`` line — anchored on heading."""

NB9_STEPS: list[tuple[int, int, str, str]] = [
    (3, 1, "research", "### STEP 4 — PHASE 2: draft_v0"),
    (4, 2, "draft_v0", "### STEP 5 — PHASE 3: challenge + L1 patch loop"),
    (5, 3, "challenge", "### STEP 6 — PHASE 4: amplify + L2 plateau verification"),
    (6, 4, "amplify", "### STEP 7 — PHASE 5: genius_audit + L3 patch loop"),
    (7, 5, "genius_audit", "### STEP 8 — PHASE 6: consistency_check + L4 patch loop"),
    (8, 6, "consistency_check", "### STEP 9 — PHASE 7: investor_narrator (concept-narrator)"),
    (9, 7, "investor_narrator", "### STEP 10 — PHASE 8: eval_gate + L5 narrator-redo loop"),
    (10, 8, "eval_gate", "### STEP 11 — PHASE 9: lessons_capture"),
    (11, 9, "lessons_capture", "### STEP 12 — COMPLETE"),
]


# ── Patch sentinels ───────────────────────────────────────────────────────────

NB9_SENTINEL = "pipeline.phase_timing start --run-dir {run_dir} --phase-index 1"
NB11_DRAFT_SENTINEL = "pipeline.evaluate_draft_quality --run-dir {run_dir}"
NB11_REPORT_SENTINEL = "pipeline.quality_report --run-dir {run_dir}"
NB10_SENTINEL = "**Run eval gate (Tier-1 + Tier-2 checks via pipeline.eval_gate):**"
NB_EVAL_L5_SENTINEL = '**L5 split-dispatch loop (verdict == "FAIL"):**'


# ── Verbatim anchor blocks (read these strings literally; trailing newlines
#    matter for idempotency and clean diffs).


NB10_OLD_BLOCK = """\
**Run eval gate (Tier-1 checks):**
```bash
uv run python -c "
import json, sys
from pathlib import Path
from pipeline.template_filter import scan_for_internal_ids, parse_som, check_template_compliance

run_dir = Path('{run_dir}')
draft = json.loads((run_dir / 'draft_v0.json').read_text())
slug = draft.get('slug', '')
md_path = run_dir / f'{slug}.md'

if not md_path.exists():
    print(json.dumps({'verdict': 'FAIL', 'failures': ['CONCEPT_MD_MISSING'], 'per_file': {}}))
    sys.exit(0)

text = md_path.read_text()
hits = scan_for_internal_ids(text)
som = parse_som(text)
compliance = check_template_compliance(text)

failures = []
if hits:
    failures.append('INTERNAL_IDS')
if som is None or som[0] < 100.0:
    failures.append('SOM_BELOW_100M')
if not compliance['passed']:
    failures.append('TEMPLATE_NONCOMPLIANT')

result = {
    'verdict': 'PASS' if not failures else 'FAIL',
    'failures': failures,
    'per_file': {
        slug + '.md': {
            'internal_id_count': len(hits),
            'som_usd_millions': som[0] if som else None,
            'template_passed': compliance['passed'],
            'template_failures': compliance.get('failures', []),
        }
    },
}
(run_dir / 'eval.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
"
```
"""

NB10_NEW_BLOCK = """\
**Run eval gate (Tier-1 + Tier-2 checks via pipeline.eval_gate):**
```bash
uv run python -m pipeline.eval_gate --run-dir {run_dir}
```
"""

NB_EVAL_L5_OLD_BLOCK = """\
**L5 narrator-redo loop (verdict == "FAIL"):**
```
l5_round = 0
loop while eval.verdict == "FAIL" AND l5_round < L5_budget:
    l5_round += 1

    Print: "Eval gate failed (L5 round {l5_round}/{L5_budget}). Failures: {eval.failures}. Re-invoking narrator..."

    Task(subagent_type="concept-narrator",
         prompt=\"\"\"Re-write the investor companion (L5 narrator redo — round {l5_round}).

Run dir: {run_dir}
Eval failures to address: {eval.failures}

Re-read all sidecar files and rewrite {run_dir}/{title_slug}-NARRATOR.md.
Pay special attention to: no internal framework IDs in prose, SOM >= $100M cited,
full V2 template section structure preserved.
\"\"\")

    Re-run the eval gate Bash script above.
    Read updated {run_dir}/eval.json.

if l5_round >= L5_budget AND eval.verdict == "FAIL":
    Read eval.json and print the failure summary.
    HALT: "L5 budget exhausted ({L5_budget} rounds). Eval gate still failing.
Final failures: {eval.failures}
Run dir: {run_dir}
To debug: uv run python -m pipeline.template_filter {run_dir}/{title_slug}.md"
```
"""

NB_EVAL_L5_NEW_BLOCK = """\
**L5 split-dispatch loop (verdict == "FAIL"):**

Eval failures route to the patcher agent that owns the failing artifact.
`eval.patcher_routing.drafter` lists codes rooted in the concept md
(`{slug}.md`); `eval.patcher_routing.narrator` lists codes rooted in the
narrator companion (`{slug}-NARRATOR.md`). The L5 budget is shared across
both branches (ADR-0009: max 2 rounds total — a round may invoke both
branches, but the counter advances once).

```
l5_round = 0
loop while eval.verdict == "FAIL" AND l5_round < L5_budget:
    l5_round += 1

    drafter_codes  = eval.patcher_routing.drafter   // list of failure codes
    narrator_codes = eval.patcher_routing.narrator  // list of failure codes

    Print: "Eval gate failed (L5 round {l5_round}/{L5_budget}). " +
           "drafter_codes={drafter_codes}, narrator_codes={narrator_codes}."

    if drafter_codes:
        Print: "L5 → concept-drafter patch pass for codes {drafter_codes}"
        Task(subagent_type="concept-drafter",
             prompt=\"\"\"Patch the concept markdown (L5 round {l5_round}, drafter branch).

Run dir: {run_dir}
Concept md path: {run_dir}/{title_slug}.md
Eval failure codes to fix: {drafter_codes}
Eval per-file diagnostics: {eval.per_file}

For each failure code apply a surgical fix to {run_dir}/{title_slug}.md:

  - INTERNAL_IDS         → remove every framework label leaked into prose
                           (TRIZ, JTBD, Booker, McKee, Boden, Csikszentmihalyi,
                           Reagan, Pearson, Egri, Polti, Haidt, Mednick, Wundt,
                           Simonton, Stanton, and any C00N / K00N / G00N codes).
                           Replace with the equivalent plain-English term.
  - SOM_BELOW_100M       → ensure Market & Audience contains a canonical
                           SOM line `**SOM (Year 1):** $NNNM` (or `$N.NNB`)
                           with value >= $100M. Re-cite an existing amplification
                           figure; do NOT invent.
  - TEMPLATE_NONCOMPLIANT → add the missing V2 template sections from
                           Inputs/CONCEPT_TEMPLATE_V2.md (eval.per_file
                           `template_failures` lists the exact missing sections).
  - QUALITY_GATE_FAIL    → strengthen drafter sections (characters/story/market)
                           so the 5-vector axes' prose-resolver picks up the
                           missing signals — see {run_dir}/quality.json for
                           per-axis reasons.

After the patch the file MUST still pass pipeline.template_filter.strip_internal_ids
and remain the canonical {slug}.md (no rename, no run-ID leak).
\"\"\")

    if narrator_codes:
        Print: "L5 → concept-narrator redo for codes {narrator_codes}"
        Task(subagent_type="concept-narrator",
             prompt=\"\"\"Re-write the investor companion (L5 round {l5_round}, narrator branch).

Run dir: {run_dir}
Eval failure codes to fix: {narrator_codes}

Re-read all sidecar files and rewrite {run_dir}/{title_slug}-NARRATOR.md.
Pay special attention to: no internal framework IDs in prose, SOM >= $100M cited,
full V2 template section structure preserved.
\"\"\")

    Re-run the eval gate:
    `uv run python -m pipeline.eval_gate --run-dir {run_dir}`

    Read updated {run_dir}/eval.json.

if l5_round >= L5_budget AND eval.verdict == "FAIL":
    Read eval.json and print the failure summary.
    HALT: "L5 budget exhausted ({L5_budget} rounds). Eval gate still failing.
Final failures: {eval.failures}
Patcher routing on final attempt: drafter={eval.patcher_routing.drafter}, narrator={eval.patcher_routing.narrator}
Run dir: {run_dir}
To debug: uv run python -m pipeline.template_filter {run_dir}/{title_slug}.md"
```
"""


# ── Patch definitions ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PatchResult:
    name: str
    status: str  # "applied" | "already_applied" | "skipped" | "missing_anchor"
    detail: str


def _nb9_bracket_start(phase_index: int, phase_name: str) -> str:
    return (
        "\n```bash\n"
        f"uv run python -m pipeline.phase_timing start "
        f"--run-dir {{run_dir}} --phase-index {phase_index} --phase-name {phase_name}\n"
        "```\n"
    )


def _nb9_bracket_end(phase_index: int, phase_name: str) -> str:
    return (
        "```bash\n"
        f"uv run python -m pipeline.phase_timing end "
        f"--run-dir {{run_dir}} --phase-index {phase_index} --phase-name {phase_name}\n"
        "```\n\n"
    )


def apply_nb9(text: str) -> tuple[str, PatchResult]:
    """Insert NB9 timing brackets around STEPS 3-11.

    Idempotent: detects ``pipeline.phase_timing start --run-dir {run_dir} --phase-index 1``
    and returns ``already_applied`` if present.
    """
    if NB9_SENTINEL in text:
        return text, PatchResult("NB9", "already_applied", "STEPS 3-11 brackets present")

    out = text
    for step_num, phase_index, phase_name, next_heading in NB9_STEPS:
        # Start-bracket anchor: the line `If \`current_phase > N\`: skip.`
        # (STEP 11 lacks a skip line — we anchor on its heading instead.)
        if step_num == _STEP_LESSONS_CAPTURE:
            start_anchor = "### STEP 11 — PHASE 9: lessons_capture\n"
        else:
            start_anchor = f"If `current_phase > {phase_index}`: skip."

        if start_anchor not in out:
            return text, PatchResult(
                "NB9",
                "missing_anchor",
                f"could not find start anchor for STEP {step_num}: {start_anchor!r}",
            )

        # Replace exactly once. For STEP 11 we want the bracket AFTER the
        # heading line; for STEPS 3-10 we want it AFTER the "skip" line.
        start_bracket = _nb9_bracket_start(phase_index, phase_name)
        # Anchor + a trailing newline because we always want a blank visual
        # separation from the prose that follows. The patch sidecar inserts
        # a blank line; we mirror that.
        replacement = start_anchor + start_bracket
        out = out.replace(start_anchor, replacement, 1)

        # End-bracket anchor: the next STEP's heading.
        if next_heading not in out:
            return text, PatchResult(
                "NB9",
                "missing_anchor",
                f"could not find next-step anchor for STEP {step_num}: {next_heading!r}",
            )
        end_bracket = _nb9_bracket_end(phase_index, phase_name)
        out = out.replace(next_heading, end_bracket + next_heading, 1)

    return out, PatchResult("NB9", "applied", f"{len(NB9_STEPS)} STEPS bracketed")


def apply_nb11(text: str) -> tuple[str, PatchResult]:
    """STEP 4 calls evaluate_draft_quality; STEP 12 calls quality_report.

    Two independent insertions handled together because the operator typically
    wants both. Each insertion is independently idempotent.
    """
    out = text
    actions: list[str] = []

    # STEP 4 — append evaluate_draft_quality bash block after the
    # ``Wait for Task. Read `{run_dir}/draft_v0.json`...`` line.
    step4_anchor = (
        "Wait for Task. Read `{run_dir}/draft_v0.json`. "
        "Extract `slug` (use it as `{title_slug}` for all subsequent steps)."
    )
    step4_block = (
        "\n\nEvaluate draft quality (NB.11 — 5-vector sidecar gate):\n"
        "```bash\n"
        "uv run python -m pipeline.evaluate_draft_quality --run-dir {run_dir}\n"
        "```\n"
    )
    if NB11_DRAFT_SENTINEL in out:
        actions.append("STEP 4 already applied")
    elif step4_anchor not in out:
        return text, PatchResult(
            "NB.11",
            "missing_anchor",
            "could not find STEP 4 anchor (post-draft Wait line)",
        )
    else:
        out = out.replace(step4_anchor, step4_anchor + step4_block, 1)
        actions.append("STEP 4 wired evaluate_draft_quality")

    # STEP 12 — append quality_report at the end of the STEP 12 section
    # (just before ``## Resume Protocol``).
    step12_anchor = "## Resume Protocol"
    step12_block = (
        "Print the per-axis quality dashboard (NB.11 — 5-vector report):\n"
        "```bash\n"
        "uv run python -m pipeline.quality_report --run-dir {run_dir}\n"
        "```\n\n"
    )
    if NB11_REPORT_SENTINEL in out:
        actions.append("STEP 12 already applied")
    elif step12_anchor not in out:
        return text, PatchResult(
            "NB.11",
            "missing_anchor",
            "could not find STEP 12 anchor (## Resume Protocol)",
        )
    else:
        out = out.replace(step12_anchor, step12_block + step12_anchor, 1)
        actions.append("STEP 12 wired quality_report")

    if all(a.endswith("already applied") for a in actions):
        return out, PatchResult("NB.11", "already_applied", "; ".join(actions))
    return out, PatchResult("NB.11", "applied", "; ".join(actions))


def apply_nb10(text: str) -> tuple[str, PatchResult]:
    """Replace STEP 10's inline ``python -c`` eval block with the
    ``pipeline.eval_gate`` one-liner."""
    if NB10_SENTINEL in text:
        return text, PatchResult("NB.10", "already_applied", "eval_gate one-liner present")

    if NB10_OLD_BLOCK not in text:
        return text, PatchResult(
            "NB.10",
            "missing_anchor",
            "could not find the inline python -c eval block verbatim — "
            "file may have drifted from the Session-7 baseline",
        )

    out = text.replace(NB10_OLD_BLOCK, NB10_NEW_BLOCK, 1)
    return out, PatchResult("NB.10", "applied", "STEP 10 inline block → eval_gate CLI")


def apply_nb_eval_l5(text: str) -> tuple[str, PatchResult]:
    """Replace STEP 10's L5 narrator-redo block with the split-dispatch block."""
    if NB_EVAL_L5_SENTINEL in text:
        return text, PatchResult("NB-EVAL-L5", "already_applied", "L5 split-dispatch present")

    if NB_EVAL_L5_OLD_BLOCK not in text:
        return text, PatchResult(
            "NB-EVAL-L5",
            "missing_anchor",
            "could not find the L5 narrator-redo block verbatim — "
            "file may have drifted from the Session-7 baseline",
        )

    out = text.replace(NB_EVAL_L5_OLD_BLOCK, NB_EVAL_L5_NEW_BLOCK, 1)
    return out, PatchResult("NB-EVAL-L5", "applied", "L5 loop → split-dispatch")


PatchFn = Callable[[str], tuple[str, "PatchResult"]]

PATCHES: dict[str, PatchFn] = {
    "NB9": apply_nb9,
    "NB.11": apply_nb11,
    "NB.10": apply_nb10,
    "NB-EVAL-L5": apply_nb_eval_l5,
}


# ── Driver ───────────────────────────────────────────────────────────────────


def _selected(args: argparse.Namespace) -> list[str]:
    if args.all:
        return list(PATCHES.keys())
    sel: list[str] = []
    if args.nb9:
        sel.append("NB9")
    if args.nb11:
        sel.append("NB.11")
    if args.nb10:
        sel.append("NB.10")
    if args.nb_eval_l5:
        sel.append("NB-EVAL-L5")
    return sel


def _backup(path: Path) -> Path:
    """Write a timestamped copy next to ``path`` and return its path."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_name(path.name + f".bak.{stamp}")
    bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return bak


def _safe_write(path: Path, content: str) -> None:
    """Atomic write via ``pipeline.state.safe_write`` (ADR-0001)."""
    # Lazy import keeps the script runnable from a fresh checkout even
    # before ``uv sync`` has been called (the helper has no third-party deps).
    sys.path.insert(0, str(REPO_ROOT))
    from pipeline.state import safe_write  # noqa: PLC0415

    safe_write(path, content)


def _print_table(results: list[PatchResult], dry_run: bool) -> None:
    width = max(len(r.name) for r in results)
    header_action = "WOULD APPLY" if dry_run else "STATUS"
    print(f"{'PATCH'.ljust(width)}  {header_action.ljust(20)}  DETAIL")
    print(f"{'-' * width}  {'-' * 20}  {'-' * 60}")
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status.ljust(20)}  {r.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="apply_skill_patches",
        description=(
            "Apply pending SKILL.md patches "
            "(NB9 / NB.11 / NB.10 / NB-EVAL-L5). "
            "Run from the operator's shell to bypass the self-modification "
            "classifier (use Claude Code's '!' prefix)."
        ),
    )
    parser.add_argument("--all", action="store_true", help="Apply every pending patch.")
    parser.add_argument("--nb9", action="store_true", help="Apply NB9 timing brackets.")
    parser.add_argument("--nb11", action="store_true", help="Apply NB.11 STEP4/STEP12 wrappers.")
    parser.add_argument("--nb10", action="store_true", help="Apply NB.10 eval_gate one-liner.")
    parser.add_argument(
        "--nb-eval-l5", action="store_true", help="Apply NB-EVAL-L5 split-dispatch."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Report which patches are applied; no writes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the diff without writing.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the .bak.<timestamp> backup (CI use only).",
    )
    parser.add_argument(
        "--skill-path",
        type=Path,
        default=SKILL_PATH,
        help="Override the target SKILL.md path (for tests).",
    )
    args = parser.parse_args(argv)

    if not args.skill_path.exists():
        print(f"ERROR: SKILL.md not found at {args.skill_path}", file=sys.stderr)
        return 1

    selected = _selected(args)
    if args.verify and not selected:
        selected = list(PATCHES.keys())
    if not selected:
        parser.error(
            "specify --all, --verify, or one or more of --nb9 / --nb11 / --nb10 / --nb-eval-l5"
        )

    original = args.skill_path.read_text(encoding="utf-8")
    current = original
    results: list[PatchResult] = []

    if args.verify:
        # Read-only path: peek each patch's sentinel. The patch functions
        # return ``applied`` when they would have applied the patch, but no
        # write happens in verify mode — relabel as ``pending`` so the
        # operator can tell at a glance which patches still need a run.
        for name in selected:
            func = PATCHES[name]
            _, result = func(original)
            if result.status == "applied":
                result = PatchResult(result.name, "pending", result.detail)
            results.append(result)
        _print_table(results, dry_run=False)
        return 0

    any_writes = False
    for name in selected:
        func = PATCHES[name]
        updated, result = func(current)
        results.append(result)
        if result.status == "applied":
            current = updated
            any_writes = True
        elif result.status == "missing_anchor":
            print(
                f"\nABORT: patch {name} could not find its anchor.\n"
                f"  Detail: {result.detail}\n"
                "  File NOT modified. Inspect the SKILL.md baseline against the\n"
                "  patch sidecars under .planning/state/ and rerun.",
                file=sys.stderr,
            )
            _print_table(results, dry_run=False)
            return 1

    _print_table(results, dry_run=args.dry_run)

    if not any_writes:
        print("\nAll selected patches already applied. No changes.")
        return 0

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        return 0

    if not args.no_backup:
        bak = _backup(args.skill_path)
        print(f"\nBackup → {_display_path(bak)}")

    _safe_write(args.skill_path, current)
    print(f"Wrote   → {_display_path(args.skill_path)}")

    return 0


def _display_path(p: Path) -> Path | str:
    """Render ``p`` relative to the repo root when possible; otherwise absolute.

    ``--skill-path`` may point outside ``REPO_ROOT`` (typical in tests where the
    fixture lives under ``tmp_path``). ``Path.relative_to`` raises in that case;
    falling back to the absolute path keeps the CLI useful in both contexts.
    """
    try:
        return p.relative_to(REPO_ROOT)
    except ValueError:
        return p


if __name__ == "__main__":
    raise SystemExit(main())
