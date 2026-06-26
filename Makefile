# Anomaly Engine v3.0 — Makefile
# ADR-0001: state lives on disk as JSONL (not agent context)
# ADR-0002: LLMs MUST NOT compute scores (pipeline/scoring.py is the only source)

.PHONY: help install lint lint-imports typecheck test eval audit run refresh-prices clean pre-stage-0 audit-sources lint-prompts add-theme next-theme stabilize stabilize-commit pathc-eval pathc-index pathc-a4 eval-format eval-research eval-challenge eval-content gate-publish single eval-single filter-check eval-evidence diagnose-keys export-html

## help: list all available targets
help:
	@grep -E '## [a-z]' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ": *## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' | sed 's/## //'

## install: install dev dependencies via uv
install:
	uv sync --dev

## lint: run ruff + custom architectural lint (HARN-11)
lint: lint-imports
	uv run ruff check pipeline/ tests/ evals/ scripts/ .claude/hooks/ || true

## lint-imports: run custom AST-based architectural lint (ADR-0002, ADR-0005)
lint-imports:
	uv run python scripts/lint_imports.py

## typecheck: run pyright static type checker
typecheck:
	uv run pyright pipeline tests evals scripts .claude/hooks 2>/dev/null || true

## test: run pytest test suite (fast; tests/ only)
test:
	uv run pytest tests/ -x

## eval: run evals/ suite (exit 5 = no tests collected is allowed pre-P4)
eval:
	uv run pytest evals/ -x; ec=$$?; if [ "$$ec" != "0" ] && [ "$$ec" != "5" ]; then exit $$ec; fi; exit 0

## audit: run audit script (stub in P0; body in P5)
audit:
	uv run python -m scripts.audit

## run: run the pipeline (stub in P0; body in P3)
run:
	uv run python -m pipeline.run

## refresh-prices: refresh model pricing registry (stub in P0; body in P5)
refresh-prices:
	uv run python -m scripts.refresh_prices

## clean: remove build artifacts and caches
clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ build dist *.egg-info

## pre-stage-0: wipe volatile state directories and show git status
pre-stage-0:
	rm -rf .planning/state/sessions/* data/state/*
	git status

## audit-sources: HEAD-check every api_base in sources/data-sources.yaml (ONLINE by default; OFFLINE=1 for structural-only)
audit-sources:
	uv run python -m scripts.audit sources $(if $(OFFLINE),--offline,)

## lint-prompts: validate prompts/*.md against PROMPT-01..08 + Karpathy K1..K10
lint-prompts:
	uv run python scripts/lint_prompts.py

## add-theme: Append a theme to data/themes_queue.jsonl
##   Usage: make add-theme THEME='Cold War spy satellites'
add-theme:
	@uv run python -m scripts.themes_queue add "$(THEME)"

## next-theme: Print the next pending theme (read-only)
next-theme:
	@uv run python -m scripts.themes_queue next

## stabilize: Stage queued anti-slop patterns for operator review (STAB-03)
stabilize:
	@uv run python scripts/stabilize.py

## stabilize-commit: After operator commits anti-slop patterns, verify no regressions
stabilize-commit:
	@$(MAKE) test -k anti_slop




## eval-format: Check 16 required sections, evidence URLs, character table, Booker beats
eval-format:
	uv run pytest evals/test_format_compliance.py -v

## eval-research: Verify research dossier exists and contains verified URLs
eval-research:
	uv run pytest evals/test_research_verified.py -v

## eval-challenge: Verify challenge protocol ran and Phase 1 results are filled
eval-challenge:
	uv run pytest evals/test_challenge_passed.py -v

## eval-content: Full content quality gate
eval-content: eval eval-format eval-research eval-challenge
	@echo "Full content quality gate passed."

## gate-publish: Minimal publication gate (format + challenge)
gate-publish: eval-format eval-challenge
	@echo "Publication gate passed. Concepts are safe to share."

## single: Run the single-idea pipeline (set THEME="your theme")
##   Usage: make single THEME='Station Tolerance'
single:
	uv run python -m pipeline.run_single_idea --theme "$(THEME)"

## eval-single: Run Tier-1 + Tier-2 evals for the last single-idea run
eval-single:
	uv run pytest evals/test_no_internal_ids.py evals/test_template_compliance.py evals/test_som_threshold.py evals/test_audience.py evals/test_challenge_passed.py evals/test_translation_friendly.py evals/test_anti_slop.py -v

## filter-check: Scan runs/ markdown files for internal-ID leaks
filter-check:
	uv run python -c "from pipeline.template_filter import scan_for_internal_ids; import pathlib; [print(f) for f in pathlib.Path('runs').rglob('*.md') if scan_for_internal_ids(f.read_text())]" && echo "filter-check passed (no leaks)" || echo "FAIL: internal IDs found"
## eval-evidence: HEAD-check all cited URLs in the most recent run's research.json
eval-evidence:
	@LATEST=$$(ls -td runs/*/research.json 2>/dev/null | head -1); \
	if [ -z "$$LATEST" ]; then echo "No research.json found in runs/"; exit 1; fi; \
	echo "Checking URLs in $$LATEST ..."; \
	uv run python -m pipeline.evidence_gate "$$LATEST"

## diagnose-keys: Show which OpenRouter API keys are loaded (values masked)
diagnose-keys:
	uv run python -m pipeline.key_manager diagnose

## export-html: Convert the most recent NARRATOR.md to Google-Docs-compatible HTML
export-html:
	@LATEST=$$(ls -td runs/*/*-NARRATOR.md 2>/dev/null | head -1); \
	if [ -z "$$LATEST" ]; then echo "No NARRATOR.md found in runs/"; exit 1; fi; \
	echo "Converting $$LATEST ..."; \
	uv run python -m pipeline.export_html "$$LATEST"


# DEPRECATED — path-C batch pipeline (archived to _deprecated/)
## pathc-eval: [DEPRECATED] Use make eval-single instead
pathc-eval:
	@echo "pathc-eval is deprecated (path-C archived). Use 'make eval-single' instead." ; true

## pathc-index: [DEPRECATED] Path-C index generation
pathc-index:
	@echo "pathc-index is deprecated (path-C archived)." ; true

## pathc-a4: [DEPRECATED] Use make single THEME=... instead
pathc-a4:
	@echo "pathc-a4 is deprecated (path-C archived). Use 'make single THEME=...' instead." ; true
