#!/usr/bin/env python3
"""One-shot: add eval-evidence, diagnose-keys, export-html targets to Makefile.

Run from the project root:
    python3 scripts/add_makefile_targets.py

Idempotent — safe to re-run. Aborts with a clear error if the anchor strings
are not found verbatim (e.g. Makefile was already restructured).
"""

import pathlib
import sys

MAKEFILE = pathlib.Path("Makefile")

# --- anchor strings (must match the file exactly) ---

PHONY_LINE = (
    ".PHONY: help install lint lint-imports typecheck test eval audit run "
    "refresh-prices clean pre-stage-0 audit-sources lint-prompts add-theme "
    "next-theme stabilize stabilize-commit pathc-eval pathc-index pathc-a4 "
    "eval-format eval-research eval-challenge eval-content gate-publish single "
    "eval-single filter-check"
)

# The tab-indented recipe line that ends the filter-check target
FILTER_CHECK_RECIPE = (
    '\tuv run python -c "from pipeline.template_filter import scan_for_internal_ids; '
    "import pathlib; [print(f) for f in pathlib.Path('runs').rglob('*.md') if "
    'scan_for_internal_ids(f.read_text())]" && echo "filter-check passed (no leaks)" '
    '|| echo "FAIL: internal IDs found"'
)

# --- new content ---

PHONY_ADDITION = " eval-evidence diagnose-keys export-html"

NEW_TARGETS = (
    "\n"
    "## eval-evidence: HEAD-check all cited URLs in the most recent run's research.json\n"
    "eval-evidence:\n"
    "\t@LATEST=$$(ls -td runs/*/research.json 2>/dev/null | head -1); \\\n"
    '\tif [ -z "$$LATEST" ]; then echo "No research.json found in runs/"; exit 1; fi; \\\n'
    '\techo "Checking URLs in $$LATEST ..."; \\\n'
    '\tuv run python -m pipeline.evidence_gate "$$LATEST"\n'
    "\n"
    "## diagnose-keys: Show which OpenRouter API keys are loaded (values masked)\n"
    "diagnose-keys:\n"
    "\tuv run python -m pipeline.key_manager diagnose\n"
    "\n"
    "## export-html: Convert the most recent NARRATOR.md to Google-Docs-compatible HTML\n"
    "export-html:\n"
    "\t@LATEST=$$(ls -td runs/*/*-NARRATOR.md 2>/dev/null | head -1); \\\n"
    '\tif [ -z "$$LATEST" ]; then echo "No NARRATOR.md found in runs/"; exit 1; fi; \\\n'
    '\techo "Converting $$LATEST ..."; \\\n'
    '\tuv run python -m pipeline.export_html "$$LATEST"\n'
)


def main() -> None:
    text = MAKEFILE.read_text()

    # Idempotency guard
    if "eval-evidence" in text:
        print("Already present — nothing to do.")
        return

    errors: list[str] = []
    if PHONY_LINE not in text:
        errors.append(".PHONY anchor line not found verbatim")
    if FILTER_CHECK_RECIPE not in text:
        errors.append("filter-check recipe line not found verbatim")
    if errors:
        print("ERROR: aborting — anchor strings not found:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    text = text.replace(PHONY_LINE, PHONY_LINE + PHONY_ADDITION)
    text = text.replace(FILTER_CHECK_RECIPE, FILTER_CHECK_RECIPE + NEW_TARGETS)

    MAKEFILE.write_text(text)
    print("✓ Makefile updated — three targets added:")
    print("    eval-evidence   diagnose-keys   export-html")


if __name__ == "__main__":
    main()
