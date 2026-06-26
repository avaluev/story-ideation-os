# CLAUDE.md — Anomaly Engine v4 Lean Single-Idea Pipeline

> Policy gateway. Every line is MUST or MUST NOT. Every rule has a mechanical enforcer.
> If a rule has no enforcer, it does not exist.

## Recovery Protocol (read FIRST in any new session)

- MUST read `.planning/state/RESUME.md` before any other action (enforced by: tests/test_claude_md_compliance.py::test_recovery_protocol_documented)
- MUST read newest `.planning/state/handoffs/*_to_<my_agent>_*.json` second (enforced by: tests/test_claude_md_compliance.py::test_recovery_protocol_documented)
- MUST read `.planning/STATE.md` third (enforced by: tests/test_claude_md_compliance.py::test_recovery_protocol_documented)

## State Durability (ADR-0001)

- MUST write all cross-boundary state to disk before declaring done (ADR-0001)
- MUST use `pipeline.state.safe_write` for atomic file writes (enforced by: tests/test_state.py::test_atomic_write_under_kill)
- MUST append per-phase outputs to `data/0X_<phase>.jsonl` (ADR-0001)
- MUST NOT keep cross-session state in agent context only (ADR-0001)

## Scoring (ADR-0002)

- MUST compute all numeric scores in `pipeline/scoring.py` (ADR-0002)
- MUST NOT import `openrouter_client`, `anthropic`, or `httpx` from `pipeline/scoring.py` (enforced by: ANOMALY-001 in scripts/lint_imports.py)
- MUST NOT let LLMs populate `total_score`; the field is `None` until scoring.py runs (ADR-0002)

## Key Rotation + Secrets (ADR-0003)

- MUST mask API key prefixes to first 8 chars in all logs and stack traces (enforced by: tests/test_log_masking.py)
- MUST keep API keys only in `.env` (gitignored) (enforced by: tests/test_secret_leak.py)
- MUST NOT commit any file containing `sk-or-v1-`, `sk-ant-`, `ghp_` outside `.env.example` (enforced by: tests/test_secret_leak.py)
- MUST run gitleaks before any `git push` (enforced by: tests/hooks/test_bash_gate.sh)
- MUST NOT use `git commit --no-verify` from agent context (enforced by: tests/hooks/test_bash_gate.sh)
- MUST NOT use `git push --force` to main (enforced by: tests/hooks/test_bash_gate.sh)

## Canonical Data (ADR-0004)

- MUST consult `synthesis_brief.canonical_data` first when a field is canonical (ADR-0004)
- MUST NOT pull a canonical-tracked field from upstream files when canonical_data has it (ADR-0004)

## Frameworks Read-Only (ADR-0005)

- MUST NOT import from `frameworks/` in any Python module (enforced by: ANOMALY-002 in scripts/lint_imports.py)
- MUST cite the framework section when duplicating a doctrine rule in `pipeline/scoring.py` (ADR-0005)

## Dead-Code Reappearance Gate (ANOMALY-003)

- MUST NOT leave any `pipeline/**/*.py` unreferenced (not imported, not a CLI entrypoint, not in allowlist) (enforced by: ANOMALY-003 in scripts/lint_imports.py)

## Forge Promotion (ADR-0006)

- MUST default to Sonnet 4.6 K=3 for Phase 4 Forge unless quality+budget two-gate is met (ADR-0006)
- MUST gate Opus 4.7 promotion on (preliminary critic score >= --quality-pass-floor) AND (--quality-pass-budget remaining) (ADR-0006)

## Pure-CC Dispatch (ADR-0007 / ADR-0008)

- MUST route all v4 model calls through `pipeline/cc_dispatch.py` or `pipeline/gemini_dispatch.py` (ADR-0007)
- MUST gate Opus 4.7 dispatch on weekly subscription quota remaining via `pipeline.quota.gate` (ADR-0008)
- MUST NOT import `anthropic`, `httpx`, or `openrouter_client` from `pipeline/cc_dispatch.py` or `pipeline/gemini_dispatch.py` (enforced by: ANOMALY-001 in scripts/lint_imports.py)
- MUST record every Task dispatch's token burn via `pipeline.quota.record` (enforced by: tests/test_quota.py::test_record_appends_one_row)

## Sandbox + Config Protection

- MUST NOT edit `pyproject.toml`, `lefthook.yml`, `.claude/settings.json`, `Makefile`, `uv.lock` from agent context (enforced by: tests/hooks/test_pretool_protect.sh)
- MUST NOT run `curl`, `wget`, `sudo`, `chmod 777`, `rm -rf /`, `rm -rf ~` from Bash (enforced by: tests/hooks/test_bash_gate.sh)
- MUST NOT read `.env*` post-P0 (enforced by: tests/test_settings_sandbox.py::test_deny_list_blocks_env_reads)

## ONE STAGE per session (HARN-13)

- MUST treat each Claude Code session as one stage of the pipeline; subagents fan out for read-only work only (enforced by: tests/test_claude_md_compliance.py::test_recovery_protocol_documented)
- MUST NOT cross stage boundaries in a single session (enforced by: tests/test_claude_md_compliance.py::test_recovery_protocol_documented)

## Stop Gate

- MUST pass `make test && make eval` before declaring done (enforced by: tests/hooks/test_stop_verify.py::test_stop_blocks_on_stale_resume)
- MUST update `.planning/state/RESUME.md` so its mtime > most recent `data/run_log.jsonl` event (enforced by: tests/hooks/test_stop_verify.py::test_stop_blocks_on_stale_resume)

## Plan-Compliance Loop (v3.1 redesign)

- MUST run `pipeline.plan_compliance --pre-task <T-ID>` before starting any work item (enforced by: tests/test_plan_compliance.py::test_pretask_blocks_without_prereqs)
- MUST run `pipeline.plan_compliance --post-task <T-ID>` after finishing any work item (enforced by: tests/test_plan_compliance.py::test_posttask_blocks_on_missing_artifacts)
- MUST keep `.planning/state/PLAN_LEDGER.jsonl` and `.planning/state/RESUME.md` in sync at session end (enforced by: tests/test_plan_compliance.py::test_stop_gate_blocks_on_stale_resume)

## Single-Idea Loops (ADR-0009)

- MUST cap challenge loop (L1) at 3 patch rounds before REJECT_FINAL (ADR-0009)
- MUST cap amplification loop (L2) at 5 iterations OR stop on plateau defined as Δ < 5% for two consecutive iters (ADR-0009)
- MUST cap genius (L3) and consistency (L4) loops at 3 patches each (ADR-0009)
- MUST cap narrator-redo loop (L5) at 2 rounds before halt with eval.failure_summary (ADR-0009)
- MUST implement plateau detection in `pipeline/loop_controller.py`, not in any LLM prompt (enforced by: tests/test_loop_controller.py::TestPlateauReached)

## Output Filter (ADR-0010)

- MUST strip all internal IDs and framework labels via `pipeline.template_filter.strip_internal_ids` before writing any file to `runs/` (ADR-0010)
- MUST NOT expose TRIZ, JTBD, Booker, McKee, Boden, Csikszentmihalyi, Reagan, Pearson, Egri, Polti, Haidt, Mednick, Wundt, Simonton, or Stanton in any `runs/` markdown file (enforced by: evals/test_no_internal_ids.py)
- MUST name each investor markdown file after the film title slug, not iter-N.md or run IDs (enforced by: evals/test_no_internal_ids.py)

## Data-Driven Revenue (ADR-0011)

- MUST compute `som_y1_usd` via `pipeline.crystallize.revenue.project_revenue` (ADR-0011)
- MUST NOT write LLM-suggested SOM/SAM/TAM numbers to `runs/*.md` without `calculation_method: "python_executed"` in the source `RevenueProjection` (enforced by: evals/test_revenue_projection.py::TestCalculationMethod::test_calculation_method_set)

## Anti-Overfit Sampling (ADR-0012)

- MUST pass `freq_table` to `_thematic_weighted_choice` when sampling in v5 production mode (ADR-0012)
- MUST NOT let any single `(axis, value_id)` exceed 40% frequency over the rolling 20-run window (enforced by: tests/test_anti_overfit_ceiling.py::test_survivor_axes_no_value_exceeds_forty_percent)

## Compliance (HARN-04)

- MUST keep CLAUDE.md <=250 lines (enforced by: tests/test_claude_md_length.py)
- MUST keep every MUST/MUST NOT line followed by either `(enforced by: <name>)` or `(ADR-NNNN)` (enforced by: tests/test_claude_md_compliance.py::test_every_must_rule_has_enforcer)

---

*Last updated: 2026-05-24 (v5.0 Day 4 — Modules 1+2+3+4+5+6 + 4 surgical wirings landed). AGENTS.md is a byte-equal mirror; do not edit one without the other.*
