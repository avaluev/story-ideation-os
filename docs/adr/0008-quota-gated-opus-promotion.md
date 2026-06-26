# ADR-0008: Opus 4.7 promotion gated by weekly subscription-quota burn

**Status:** Accepted
**Date:** 2026-05-09
**Supersedes:** ADR-0006 (Gate B: dollar-budget) — the quality-floor gate (Gate A) survives unchanged.
**Decided by:** Operator + Orchestrator

## Context

ADR-0006 gated Opus 4.7 promotion on a per-run dollar budget (`--quality-pass-budget=10` default). With ADR-0007's pure-CC dispatch, dollar budgets become meaningless — the cost is subscription-quota burn, not external API spend. The operator's Claude Code subscription has a weekly Opus token ceiling that the engine must respect to avoid mid-run quota-exhaustion failures.

A 1000-concept Path C run with default `--quality-pass=top-3` triggers Opus on the top 30 concepts (3 per 100). At ~9k input + 3k output tokens per Opus call, that's ~360k tokens per 1000-concept run. The operator's weekly Opus ceiling depends on the subscription tier (Pro / Max / Team) and is set in `.env` via `OPUS_WEEKLY_TOKEN_CAP`.

## Decision

Opus promotion remains a **two-gate** decision; Gate A (quality) is unchanged from ADR-0006; Gate B (budget) is rebound to weekly subscription quota:

**Gate A — Quality (unchanged):** preliminary critic score ≥ `--quality-pass-floor` (default 75).

**Gate B — Quota:** `pipeline.quota.gate("opus", expected_tokens=EXPECTED_OPUS_PASS_COST, floor=0.05)` returns True. Specifically:
- Read current weekly Opus burn from `data/quota.jsonl` (sum of tokens_in + tokens_out for current ISO week).
- If `(used + expected) >= cap`, gate returns False.
- Otherwise return True iff `(remaining / cap) > floor` (default 5%).

If Gate B returns False, the orchestrator **automatically falls back to Sonnet K=3** (no Opus promotion). The operator may override the floor via `--opus-budget-floor 0.0` to drain the remaining quota.

Per-tier weekly token caps come from environment variables:
- `OPUS_WEEKLY_TOKEN_CAP` (default 2,000,000 — conservative Pro estimate)
- `SONNET_WEEKLY_TOKEN_CAP` (default 20,000,000)
- `HAIKU_WEEKLY_TOKEN_CAP` (default 100,000,000 — effectively unlimited)

A cap of `0` disables gating for that tier. The operator tunes these once in `.env` based on actual subscription tier.

## Consequences

(+) Predictable quota burn — Opus dispatch is denied when the weekly ceiling is approaching exhaustion, preserving headroom for borderline Phase 4 KeepBest passes that lift 75–84 concepts above the 85 floor.
(+) Subscription-tier portable — switching from Pro to Max only requires updating one environment variable.
(+) ISO-week reset semantics align with how Anthropic exposes weekly Opus ceilings to subscribers.
(+) The `--opus-budget-floor` knob lets the operator deliberately spend remaining quota on a final all-out run.
(−) The first run of an ISO week may falsely-permit Opus dispatch if `data/quota.jsonl` is fresh (no historical burn) — the floor (5%) prevents catastrophic over-allocation.
(−) Operator must initialize `OPUS_WEEKLY_TOKEN_CAP` to match actual subscription; mis-set caps cause either premature gating or genuine over-burn.

## Verifies

CLAUDE.md MUST rule "MUST gate Opus 4.7 dispatch on weekly subscription quota remaining" (enforced by: `tests/test_quota.py::test_gate_blocks_when_below_floor`, `test_gate_blocks_when_dispatch_overflows_cap`).

## Migration

ADR-0006 Gate B (`--quality-pass-budget`) is removed in Step 2 of the v4 migration. The legacy CLI flag is preserved as a no-op for one release for backward compatibility.
