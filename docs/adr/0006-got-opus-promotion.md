# ADR-0006: GoT Opus-4.7 promotion = automatic two-gate (score ≥75 AND budget remaining)

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Operator ("do your best") + Orchestrator

## Context

The Forge agent (Phase 4) defaults to Sonnet 4.6 with Generate(k=3). The spec says "Opus 4.7 for top-3 cycles" but doesn't specify the trigger. Pitfall 2.1 (PITFALLS.md): defaulting to Opus K=8 for every concept causes 5–10× cost overage. The operator wants automatic, predictable promotion without per-concept manual decisions.

## Decision

Opus 4.7 promotion is **automatic** with two gates that BOTH must pass:

**Gate A — Quality:** the preliminary critic score on the Sonnet 4.6 first-pass concept must be ≥ `--quality-pass-floor` (default `75`).

**Gate B — Budget:** the remaining daily Opus budget must be ≥ `EXPECTED_OPUS_PASS_COST` for K=8 candidates. Cost estimate uses `MODELS["claude-opus-4.7"]` × prompt token count × `K=8` × tokenizer multiplier `1.35`.

**Default scope:** `--quality-pass=top-3` (only the 3 highest-scoring concepts per run promote to Opus). Operator overrides:

- `--quality-pass={off|top-3|top-5|all}` (default `top-3`)
- `--quality-pass-floor=75` (default; override per run)
- `--quality-pass-budget=10` (default $10/run; raise `BudgetExceeded` if hit)

## Consequences

(+) Predictable cost — Opus only runs on top-3 high-promise concepts.
(+) Quality where it matters — borderline-PASS concepts (75–84 range) get the Opus boost that pushes them over the 85 floor.
(+) Operator override knobs cover ad-hoc experiments, deep-dive runs, and budget-constrained runs.
(−) Adds a `quality_pass` orchestration step between Phase 4 and Phase 5 — but per ARCHITECTURE.md §"Only Phases 4 and 5 become GoT operator graphs" this fits naturally as `Generate(3) → Score → KeepBestN(3) → ValidateAndImprove[Opus K=8] → Score → KeepBestN(1)`.

## Verifies

CLAUDE.md MUST rule "Forge agent MUST default to Sonnet 4.6 K=3 unless the (score ≥ floor AND budget remaining) two-gate is met" (enforced by: `pipeline/operators/keep_best.py::test_quality_pass_promotion_gate` + `tests/test_run_quality_pass.py`).
