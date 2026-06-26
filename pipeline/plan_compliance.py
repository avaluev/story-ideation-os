"""Plan-compliance loop CLI.

Tracks execution against the approved plan at ``PLAN_FILE`` (default
``~/.claude/plans/part-1-what-s-misty-rose.md``). Every work item gets a row
in ``.planning/state/PLAN_LEDGER.jsonl``. This module verifies that:

  1. Prerequisites are completed before a work item starts (--pre-task).
  2. Expected artifacts exist before a work item is marked done (--post-task).
  3. Ledger and plan agree on what is completed (--audit).
  4. Commits do not include files the plan does not declare (--pre-commit).
  5. RESUME.md mtime is fresher than the ledger at session end (--stop-gate).

Drift detection: every ledger row carries the SHA-256 of the plan file at the
moment of completion. --pre-task pauses with a notice if the SHA has changed
since the most recent ledger row.

CLAUDE.md MUST rules enforced by tests/test_plan_compliance.py:
  - pre-task before any work item
  - post-task after any work item
  - ledger / RESUME.md sync at session end
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

# Default plan file (overridable via PLAN_FILE env var or --plan flag).
DEFAULT_PLAN_FILE = Path.home() / ".claude" / "plans" / "part-1-what-s-misty-rose.md"

LEDGER_PATH = Path(".planning/state/PLAN_LEDGER.jsonl")
RESUME_PATH = Path(".planning/state/RESUME.md")
RUN_LOG = Path("data/run_log.jsonl")

# Audit thresholds.
AUDIT_OK_THRESHOLD = 90.0  # % compliance below which an audit is treated as a hard failure.

# Exit codes.
EXIT_OK = 0
EXIT_GENERIC_ERROR = 1
EXIT_UNKNOWN_ITEM = 2
EXIT_PLAN_DRIFT = 3
EXIT_BLOCKED = 4


@dataclass(frozen=True)
class TodoItem:
    """One row of the Ultra TODO List in the plan markdown.

    Immutable — instances are constructed once per parse cycle.
    """

    item_id: str
    title: str
    prereqs: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    verify_command: str


# ---------------------------------------------------------------------------
# Plan-file parsing
# ---------------------------------------------------------------------------

# The Ultra TODO List section header anchors the relevant tables.
TODO_SECTION_RE = re.compile(r"^## Ultra TODO List", re.MULTILINE)

# Markdown table row whose first cell is a Tnnn id.
TODO_ROW_RE = re.compile(
    r"^\|\s*(T\d{3,4})\s*\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$",
    re.MULTILINE,
)

# Tnnn token (used to extract prereq IDs from the prereq column).
T_ID_RE = re.compile(r"T\d{3,4}")

# Range expression like 'T036<dash>T043'. Accepts U+2013, U+2014, ASCII hyphen.
T_RANGE_RE = re.compile("(T\\d{3,4})\\s*[–—\\-]\\s*(T\\d{3,4})")  # noqa: RUF001

# Path-looking artifact (contains "/" or a recognised extension).
PATH_HINT_RE = re.compile(r"[/\\]|\.(py|md|csv|jsonl|json|toml|yml|yaml|sh|txt)\b")


def _expand_prereqs(prereq_str: str) -> tuple[str, ...]:
    """Extract all T-IDs from the prereq cell, expanding ranges.

    A range like "T036<dash>T043" expands to T036, T037, ..., T043. Single
    IDs and comma-lists are also supported. ASCII hyphen, U+2013, and U+2014
    are all treated as range separators.
    """
    expanded: list[str] = []
    for m in T_RANGE_RE.finditer(prereq_str):
        start = int(m.group(1)[1:])
        end = int(m.group(2)[1:])
        if start <= end:
            expanded.extend(f"T{n:03d}" for n in range(start, end + 1))
    cleaned = T_RANGE_RE.sub("", prereq_str)
    expanded.extend(T_ID_RE.findall(cleaned))
    seen: set[str] = set()
    out: list[str] = []
    for tid in expanded:
        if tid not in seen:
            seen.add(tid)
            out.append(tid)
    return tuple(out)


def _strip_md(cell: str) -> str:
    """Remove backticks and surrounding whitespace from a markdown cell."""
    return cell.strip().strip("`").strip()


def _extract_artifacts(artifact_cell: str) -> tuple[str, ...]:
    """Pull path-looking tokens out of the artifact cell.

    Cells like "csv" or "code" or "tests" carry no path; we return an empty
    tuple so post-task does not block on them. The caller is expected to
    treat empty-tuple as "soft check".
    """
    tokens = re.split(r"[,\s]+", artifact_cell)
    paths: list[str] = []
    for token in tokens:
        clean = _strip_md(token)
        if clean and PATH_HINT_RE.search(clean):
            paths.append(clean)
    return tuple(paths)


def parse_plan(plan_file: Path) -> dict[str, TodoItem]:
    """Parse the Ultra TODO List from the plan markdown file.

    Returns an empty dict if the file is missing or has no TODO section. A
    non-zero exit code is the caller's responsibility — this is a pure parser.
    """
    if not plan_file.exists():
        return {}
    text = plan_file.read_text(encoding="utf-8")
    section_match = TODO_SECTION_RE.search(text)
    if section_match is None:
        return {}
    section_text = text[section_match.start() :]
    items: dict[str, TodoItem] = {}
    for m in TODO_ROW_RE.finditer(section_text):
        item_id = m.group(1)
        title = _strip_md(m.group(2))
        prereqs = _expand_prereqs(m.group(3))
        expected_artifacts = _extract_artifacts(m.group(4))
        verify_command = _strip_md(m.group(5))
        items[item_id] = TodoItem(
            item_id=item_id,
            title=title,
            prereqs=prereqs,
            expected_artifacts=expected_artifacts,
            verify_command=verify_command,
        )
    return items


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def compute_plan_sha(plan_file: Path) -> str:
    """SHA-256 of the plan file bytes; empty string if the file is missing."""
    if not plan_file.exists():
        return ""
    return hashlib.sha256(plan_file.read_bytes()).hexdigest()


def read_ledger(ledger: Path | None = None) -> list[dict[str, Any]]:
    """Return all rows from the plan ledger, oldest-first.

    Resolves ``LEDGER_PATH`` at call time so monkeypatching the module-level
    constant works in tests.
    """
    if ledger is None:
        ledger = LEDGER_PATH
    if not ledger.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            _log.warning("Skipping unparseable ledger line: %s", exc)
    return rows


def latest_status(rows: list[dict[str, Any]], item_id: str) -> str | None:
    """Most recent status for ``item_id``, or None if it has never been logged."""
    for row in reversed(rows):
        if row.get("item_id") == item_id:
            status = row.get("status")
            return str(status) if status is not None else None
    return None


def latest_plan_sha(rows: list[dict[str, Any]]) -> str:
    """Most recent ``plan_file_sha`` recorded; empty if no rows exist."""
    for row in reversed(rows):
        sha = row.get("plan_file_sha")
        if sha:
            return str(sha)
    return ""


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _resolve_plan_file(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("PLAN_FILE")
    if env:
        return Path(env)
    return DEFAULT_PLAN_FILE


def cmd_pre_task(args: argparse.Namespace) -> int:
    """Refuse to start a work item whose prereqs are not DONE in the ledger."""
    plan_file = _resolve_plan_file(args.plan)
    items = parse_plan(plan_file)
    item = items.get(args.item_id)
    if item is None:
        sys.stderr.write(f"[pre-task] UNKNOWN item_id={args.item_id} (not in plan)\n")
        return EXIT_UNKNOWN_ITEM

    sha = compute_plan_sha(plan_file)
    rows = read_ledger()
    last_sha = latest_plan_sha(rows)
    if last_sha and last_sha != sha and not args.allow_drift:
        sys.stderr.write(
            f"[pre-task] PLAN DRIFT — last={last_sha[:12]}, current={sha[:12]}\n"
            "[pre-task] Run --audit to review, then re-run with --allow-drift if intentional.\n"
        )
        return EXIT_PLAN_DRIFT

    missing = [p for p in item.prereqs if latest_status(rows, p) != "DONE"]
    if missing:
        sys.stderr.write(f"[pre-task] BLOCKED for {item.item_id}: missing prereqs {missing}\n")
        return EXIT_BLOCKED

    sys.stdout.write(f"[pre-task] OK to start {item.item_id} — {item.title}\n")
    return EXIT_OK


def cmd_post_task(args: argparse.Namespace) -> int:
    """Refuse to mark DONE if expected artifacts are missing; append ledger row otherwise."""
    plan_file = _resolve_plan_file(args.plan)
    items = parse_plan(plan_file)
    item = items.get(args.item_id)
    if item is None:
        sys.stderr.write(f"[post-task] UNKNOWN item_id={args.item_id}\n")
        return EXIT_UNKNOWN_ITEM

    actual_artifacts: list[str] = []
    missing_artifacts: list[str] = []
    for art in item.expected_artifacts:
        if Path(art).exists():
            actual_artifacts.append(art)
        else:
            missing_artifacts.append(art)

    if missing_artifacts and not args.force:
        sys.stderr.write(
            f"[post-task] BLOCKED for {item.item_id}: missing artifacts "
            f"{missing_artifacts}\n"
            "[post-task] Re-run with --force only if the artifact is non-file.\n"
        )
        return EXIT_BLOCKED

    row: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "item_id": item.item_id,
        "title": item.title,
        "plan_file_sha": compute_plan_sha(plan_file),
        "expected_artifacts": list(item.expected_artifacts),
        "actual_artifacts": actual_artifacts,
        "tests_run": list(args.tests),
        "tests_status": args.tests_status or ("PASS" if args.tests else "N/A"),
        "deviations": list(args.deviations or []),
        "status": "DONE",
    }
    append_jsonl(LEDGER_PATH, row)
    sys.stdout.write(f"[post-task] DONE {item.item_id} — ledger row appended\n")
    return EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    """Print compliance summary; exit 0 if score >= AUDIT_OK_THRESHOLD."""
    plan_file = _resolve_plan_file(args.plan)
    items = parse_plan(plan_file)
    rows = read_ledger()

    completed_ids = {
        str(r.get("item_id")) for r in rows if r.get("status") == "DONE" and r.get("item_id")
    }
    plan_ids = set(items.keys())

    in_plan_done = completed_ids & plan_ids
    pending = sorted(plan_ids - completed_ids)
    extras = sorted(completed_ids - plan_ids)
    total = len(plan_ids)
    score = (len(in_plan_done) / total * 100.0) if total else 0.0

    sys.stdout.write(f"[audit] Plan: {plan_file}\n")
    sys.stdout.write(f"[audit] SHA: {compute_plan_sha(plan_file)[:16]}\n")
    sys.stdout.write(f"[audit] Total plan items: {total}\n")
    sys.stdout.write(f"[audit] Completed (in plan): {len(in_plan_done)}\n")
    sys.stdout.write(f"[audit] Pending: {len(pending)}\n")
    sys.stdout.write(f"[audit] Extras (in ledger, not in plan): {len(extras)}\n")
    sys.stdout.write(f"[audit] Compliance score: {score:.1f}%\n")
    if args.verbose:
        if pending:
            sys.stdout.write("[audit] Pending items:\n")
            for tid in pending:
                sys.stdout.write(f"  {tid}: {items[tid].title}\n")
        if extras:
            sys.stdout.write("[audit] Extras (drift candidates):\n")
            for tid in extras:
                sys.stdout.write(f"  {tid}\n")

    if args.strict and score < AUDIT_OK_THRESHOLD:
        sys.stderr.write(
            f"[audit] FAIL: compliance {score:.1f}% < {AUDIT_OK_THRESHOLD:.1f}% (--strict)\n"
        )
        return EXIT_GENERIC_ERROR
    return EXIT_OK


def cmd_pre_commit(args: argparse.Namespace) -> int:
    """Lefthook pre-commit. Warns when staged files are not declared in any plan item.

    The plan declares this hook as a soft warning for Day 1 (so we can stage
    routine maintenance edits without scope-blocking). It writes the warning
    to stderr but exits 0; promote to hard block once the codebase is on plan.
    """
    git_bin = shutil.which("git") or "git"
    r = subprocess.run(  # noqa: S603
        [git_bin, "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        sys.stderr.write(f"[pre-commit] git diff failed: {r.stderr}\n")
        return EXIT_GENERIC_ERROR
    modified = [f.strip() for f in r.stdout.splitlines() if f.strip()]
    if not modified:
        sys.stdout.write("[pre-commit] no staged files\n")
        return EXIT_OK

    plan_file = _resolve_plan_file(args.plan)
    items = parse_plan(plan_file)
    declared: set[str] = set()
    for it in items.values():
        for art in it.expected_artifacts:
            declared.add(art)

    safe_prefixes = (
        ".planning/state/",
        "tests/",
        "pipeline/",
        "data/",
        "prompts/",
        ".claude/",
        "out/",
        "scripts/",
    )
    undeclared = [m for m in modified if m not in declared and not m.startswith(safe_prefixes)]
    if undeclared:
        sys.stderr.write(
            f"[pre-commit] WARN: {len(undeclared)} files not declared in any plan item:\n"
        )
        for f in undeclared[:10]:
            sys.stderr.write(f"  - {f}\n")
    sys.stdout.write("[pre-commit] OK\n")
    return EXIT_OK


def cmd_stop_gate(args: argparse.Namespace) -> int:
    """Claude Code Stop hook. Refuses session-end if RESUME.md is older than the ledger."""
    if not RESUME_PATH.exists():
        sys.stderr.write("[stop-gate] FAIL: RESUME.md missing\n")
        return EXIT_GENERIC_ERROR
    if not LEDGER_PATH.exists() or LEDGER_PATH.stat().st_size == 0:
        sys.stdout.write("[stop-gate] OK: ledger is empty\n")
        return EXIT_OK
    ledger_mtime = LEDGER_PATH.stat().st_mtime
    resume_mtime = RESUME_PATH.stat().st_mtime
    if resume_mtime < ledger_mtime:
        sys.stderr.write(
            f"[stop-gate] FAIL: RESUME.md mtime ({resume_mtime}) < "
            f"ledger mtime ({ledger_mtime})\n"
            "[stop-gate] Update RESUME.md before ending the session.\n"
        )
        return EXIT_GENERIC_ERROR
    sys.stdout.write("[stop-gate] OK: RESUME.md is current\n")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Argparse glue
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Top-level argparse with mutually-exclusive subcommand flags.

    The flag form (--pre-task instead of subparser names) matches the plan
    documentation: ``python -m pipeline.plan_compliance --pre-task <T-ID>``.
    """
    p = argparse.ArgumentParser(
        prog="plan_compliance",
        description="Plan-following verification loop for the Anomaly Engine redesign.",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--pre-task", metavar="T-ID", help="Verify prerequisites before starting an item."
    )
    group.add_argument(
        "--post-task", metavar="T-ID", help="Append a DONE row after finishing an item."
    )
    group.add_argument(
        "--audit", action="store_true", help="Print plan-vs-ledger compliance summary."
    )
    group.add_argument("--pre-commit", action="store_true", help="Lefthook pre-commit hook entry.")
    group.add_argument("--stop-gate", action="store_true", help="Claude Code Stop-hook entry.")

    p.add_argument(
        "--plan", default=None, help="Override plan file path (else PLAN_FILE env or default)."
    )
    p.add_argument(
        "--allow-drift", action="store_true", help="Permit pre-task even if plan SHA changed."
    )
    p.add_argument("--force", action="store_true", help="post-task: skip artifact existence check.")
    p.add_argument("--tests", nargs="*", default=[], help="post-task: pytest IDs that ran.")
    p.add_argument("--tests-status", default=None, help="post-task: PASS / FAIL.")
    p.add_argument("--deviations", nargs="*", default=[], help="post-task: deviation strings.")
    p.add_argument("--verbose", action="store_true", help="audit: list pending and extra items.")
    p.add_argument(
        "--strict", action="store_true", help="audit: nonzero exit if score < threshold."
    )
    return p


def _dispatch(args: argparse.Namespace) -> int:
    if args.pre_task:
        args.item_id = args.pre_task
        return cmd_pre_task(args)
    if args.post_task:
        args.item_id = args.post_task
        return cmd_post_task(args)
    if args.audit:
        return cmd_audit(args)
    if args.pre_commit:
        return cmd_pre_commit(args)
    if args.stop_gate:
        return cmd_stop_gate(args)
    return EXIT_GENERIC_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
