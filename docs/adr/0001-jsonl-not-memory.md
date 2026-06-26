# ADR-0001: State lives on disk as JSONL, not in agent context

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Operator (Alexandr Valuev) + Orchestrator

## Context

LLM agent context windows are ephemeral. Subagent transcripts are not visible to the parent. `/clear`, `/compact`, session restarts, and `kill -9` all destroy any state that exists only in context. At ~$0.50/concept the engine cannot afford to lose state. The user explicitly elevated zero-data-loss above any other ergonomic concern on 2026-05-06 mid-workflow.

## Decision

Every piece of state that crosses a session boundary, an agent boundary, a phase boundary, or `/clear` MUST be on disk before the producing agent declares done. State writes use `pipeline.state.safe_write` (atomic via `tmp + fsync + rename`). Phase outputs use append-only JSONL (`data/0X_<phase>.jsonl`); cross-cutting concerns use the run log (`data/run_log.jsonl`).

## Consequences

(+) `kill -9` mid-stage loses no committed state; the next session reads state from files and reconstructs context.
(+) Subagents communicate via handoff files, not via parent context.
(+) Reproducibility: same seed + same checkpoints = byte-identical output.
(−) Every state mutation costs one disk write (~ms; invisible at 30-min runs).
(−) Schema migrations require append-only event-source semantics (cannot rewrite history).

## Verifies

CLAUDE.md MUST rule "All state crossing a session, agent, or phase boundary lives on disk before the producing agent declares done" (enforced by: `tests/test_state.py::test_atomic_write_under_kill`).
