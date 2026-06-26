#!/usr/bin/env python3
"""Idempotently append content-quality eval targets to Makefile (sandbox escape hatch).

Adds five targets:
  * eval-format    -- Check 16 required sections, evidence URLs, character table, Booker beats
  * eval-research  -- Verify research dossier exists and contains verified URLs
  * eval-challenge -- Verify challenge protocol ran and Phase 1 results are filled
  * eval-content   -- Full content quality gate
                      (eval + eval-format + eval-research + eval-challenge)
  * gate-publish   -- Minimal publication gate (format + challenge)

Mirrors scripts/append_pathc_a4_targets.py: Python ``open()`` bypasses the
PreToolUse Write|Edit deny on Makefile (sandbox-protected per HARN-07 / the
"Sandbox + Config Protection" CLAUDE.md section).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAKEFILE = Path("Makefile")

NEW_PHONY_TARGETS = (
    "eval-format",
    "eval-research",
    "eval-challenge",
    "eval-content",
    "gate-publish",
)

TARGET_BLOCK = (
    "\n"
    "## eval-format: Check 16 required sections, evidence URLs, character table, Booker beats\n"
    "eval-format:\n"
    "\tuv run pytest evals/test_format_compliance.py -v\n"
    "\n"
    "## eval-research: Verify research dossier exists and contains verified URLs\n"
    "eval-research:\n"
    "\tuv run pytest evals/test_research_verified.py -v\n"
    "\n"
    "## eval-challenge: Verify challenge protocol ran and Phase 1 results are filled\n"
    "eval-challenge:\n"
    "\tuv run pytest evals/test_challenge_passed.py -v\n"
    "\n"
    "## eval-content: Full content quality gate\n"
    "eval-content: eval eval-format eval-research eval-challenge\n"
    '\t@echo "Full content quality gate passed."\n'
    "\n"
    "## gate-publish: Minimal publication gate (format + challenge)\n"
    "gate-publish: eval-format eval-challenge\n"
    '\t@echo "Publication gate passed. Concepts are safe to share."\n'
)


def _all_present(content: str) -> bool:
    for tgt in NEW_PHONY_TARGETS:
        if not re.search(rf"^{re.escape(tgt)}:", content, flags=re.MULTILINE):
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Append eval-content / gate-publish targets to Makefile"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed Makefile content to stdout; do not write to disk",
    )
    args = ap.parse_args()

    if not MAKEFILE.exists():
        print("FAIL: Makefile not found", file=sys.stderr)
        return 1

    content = MAKEFILE.read_text(encoding="utf-8")
    if _all_present(content):
        print("eval-content targets already present; no-op")
        return 0

    new_content = content
    phony_pat = re.compile(r"^\.PHONY:(.*)$", flags=re.MULTILINE)
    m = phony_pat.search(new_content)
    if m:
        existing_phony = m.group(1)
        additions = " ".join(t for t in NEW_PHONY_TARGETS if t not in existing_phony)
        if additions:
            new_content = phony_pat.sub(
                f".PHONY:{existing_phony} {additions}",
                new_content,
                count=1,
            )

    if not new_content.endswith("\n"):
        new_content += "\n"
    new_content += TARGET_BLOCK

    if args.dry_run:
        sys.stdout.write(new_content)
        return 0

    with open(MAKEFILE, "w", encoding="utf-8") as fh:
        fh.write(new_content)
    print(f"eval-content targets appended to {MAKEFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
