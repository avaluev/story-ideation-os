# ADR-0003: 3-key FIFO rotation for OpenRouter

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Spec (`Inputs/_ANOMALY_ENGINEv3.0.md` Stage 3 PROMPT 3.1)

## Context

OpenRouter free-tier keys allow ~50 calls/day; the paid key allows ~1,000 calls/day. A single nightly run on `--n 100` exceeds free-tier on either free key alone, but fits comfortably across all 3. Rotation also masks any single-key compromise.

## Decision

`pipeline/openrouter_client.py` exposes `_next_key(paid_required: bool) -> KeyState`. Strategy:
1. If `paid_required` (Phase 3 sonar-deep-research): always return `OPENROUTER_KEY_PAID`.
2. Else: round-robin across all 3 keys with a daily-quota tracker. Skip exhausted keys (HTTP 402/429 marks the key exhausted for the calendar day UTC).
3. If all 3 exhausted: raise `BudgetExceeded`.

Keys are masked to first 8 chars in all log output (`data/run_log.jsonl`) and exception messages.

## Consequences

(+) Free-tier amortization: 1100 calls/day total across the 3 keys before any paid spend.
(+) Compromise of one key has limited blast radius.
(−) Slight latency per call (key selection + atomic-counter update).
(−) `KeyState` becomes shared mutable state; thread-safety required.

## Verifies

CLAUDE.md MUST rule "key prefixes MUST be masked to first 8 chars in all logs" (enforced by: `tests/test_openrouter_client.py::test_log_masks_keys`).
