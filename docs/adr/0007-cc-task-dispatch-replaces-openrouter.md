# ADR-0007: Pure-CC Task dispatch replaces OpenRouter HTTP gateway

**Status:** Accepted
**Date:** 2026-05-09
**Decided by:** Operator + Orchestrator (during /effort max planning session)

## Context

Anomaly Engine v3.0 routes every model call through `pipeline/openrouter_client.py`, a 3-key FIFO HTTP gateway over OpenRouter (paid + 2 free). Each 1000-concept Path C run costs $60–$200, and a single drift in `MODELS` rates can blow the daily budget cap (Pitfall 2.1, PITFALLS.md). The operator's Claude Code subscription already includes ample weekly capacity for Opus 4.7, Sonnet 4.6, and Haiku 4.5 — capacity that is currently unused because the runtime pipeline doesn't talk to Claude Code's Task tool.

The operator's intent (2026-05-09): **"only native limits of the subscription, no paid API calls."**

## Decision

The Genius Engine v4.0 introduces a second gateway, `pipeline/cc_dispatch.py`, that plans phase fan-out manifests and merges per-Task JSONL outputs back into the canonical phase JSONL files. The actual model invocations are emitted by the `/genius` skill body (Claude Code main session) as `Task` tool calls, one per row of the manifest. Python never calls a model directly.

The `--gateway` flag selects between the two:

- `--gateway=cc` (default in v4.0): all phase work routes through `cc_dispatch.plan` + `Task` fan-out + `cc_dispatch.merge`. Zero $ external API spend.
- `--gateway=openrouter` (legacy escape during migration; deleted in Step 6 of the v4 migration plan): preserves Step 1–5 backward compatibility.

Per-phase model tier mapping (default routing):

- Phase 1 miner: Sonnet (8–12 parallel Tasks, one per domain bucket)
- Phase 2 mapper: Sonnet (extended thinking; N parallel per asset)
- Phase 3 validator: Sonnet (N parallel per JTBD row)
- Phase 4 forger Generate: Sonnet K=3 (3 × N parallel)
- Phase 4 forger KeepBest: Opus (top-3 only; gated by ADR-0008)
- Phase 4.5 mutation: Sonnet (1 per operator-pair)
- Phase 5 critic: Sonnet (N parallel)
- Phase 5.5 genius-judge: Sonnet (single whole-batch Task)
- Phase 6 formatter: Haiku (deterministic; temp=0)

`pipeline/cc_dispatch.py` MUST NOT import `anthropic`, `httpx`, `openrouter_client`, or anything from `frameworks/` (ANOMALY-001 / ANOMALY-002).

## Consequences

(+) Zero $ external API spend; subscription quota is the only ceiling.
(+) Native parallelism via Claude Code's single-message-N-Task fan-out pattern; orchestrator emits one assistant message containing N parallel `Task` tool calls.
(+) Each Task is a JSONL handoff (input slice + prompt template + output path), preserving ADR-0001 durability.
(+) Subagent context-window saturation is contained per-Task; orchestrator stays small.
(−) Loses streaming feedback (Task is non-streaming); mitigated by heartbeat JSONL every 60s.
(−) Adds an Opus weekly quota state machine (ADR-0008 supersedes ADR-0006's $-budget gate).
(−) Per-Task latency is higher than a direct API call; mitigated by deeper parallelism.

## Migration

Step 1 (this ADR + cc_dispatch.py + quota.py): shim added; openrouter_client.py untouched.
Steps 2–5: --gateway=cc wired; /genius skill + new agents added; side-by-side parity validation.
Step 6: openrouter_client.py deleted; .env paid keys removed; --gateway flag becomes a no-op.

## Verifies

CLAUDE.md MUST rule "MUST route all model calls through pipeline/cc_dispatch.py or pipeline/gemini_dispatch.py" (enforced by: `scripts/lint_imports.py` ANOMALY-001 extension; `tests/test_cc_dispatch.py`; `tests/test_lint_imports.py`).
