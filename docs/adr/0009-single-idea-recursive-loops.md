# ADR-0009: Single-Idea Recursive Loops with Plateau Detection

**Status:** Accepted
**Date:** 2026-05-12
**Decided by:** Operator (via lollipop plan)

## Context

The batch pipeline (`big-idea-batch`) produced 30 concepts per run but required operator triage of every output before one ship-worthy idea emerged. Quality was diffuse — no concept received enough recursive improvement to reach investor-grade. The core problem: a single LLM pass (even Opus) cannot simultaneously satisfy adversarial challenge, commercial viability, cross-phase consistency, and output hygiene. These are four separate failure modes that require four separate verification passes.

The redesign introduces a **single-idea orchestrator** (`pipeline/single_idea.py`) that runs one concept through five recursive loops, each targeting a specific failure mode. The loops run cheap models (Haiku for verification, Sonnet for patching) rather than expensive models (Opus). The loop topology — not the model power — is the quality multiplier.

## Decision

Five loops, each with a hard cap to prevent oscillation:

| Loop | Name | Trigger | Patch Agent | Cap | Termination |
|---|---|---|---|---|---|
| L1 | Challenge ↔ Draft | Any P0 kill-switch fails | concept-drafter | 3 rounds | REJECT_FINAL after cap |
| L2 | Amplification plateau | Phase 4 starts | Haiku + Python | 5 iterations | Δ < 5% for two consecutive iters OR SOM ≥ $100M AND stable |
| L3 | Genius audit | C001–C007 kill-switch tripped | concept-drafter | 3 rounds | Halt if still failing at cap |
| L4 | Consistency drift | Drift score ≥ 5% on canonical field | concept-drafter | 3 rounds | Halt if still drifting at cap |
| L5 | Eval gate (narrator redo) | Any Tier-1 eval fails | concept-narrator | 2 rounds | Halt with eval.failure_summary |

**Plateau definition (L2):** `(som_n - som_{n-1}) / som_{n-1} < 0.05` for two consecutive iterations. Implemented in `pipeline/loop_controller.py:plateau_reached()`. LLMs never compute this — pure Python on the numbers from `amplification.json`.

**Single-idea per run:** Each invocation of `pipeline/single_idea.py` produces exactly one investor-facing markdown. No batch fan-out. Output goes to `runs/{ts}-{slug}/{Film-Title}.md`.

**Model allocation per loop:**
- L1/L3/L4 patches: Sonnet 4.6 (concept-drafter)
- L2 vector selection: Haiku 4.5 (audience-amplifier)
- L2 math: pure Python (pipeline/audience_amplifier.py)
- L5 narrator redo: Sonnet 4.6 (concept-narrator with extended thinking)

## Consequences

(+) Five independent verification passes catch failure modes a single Opus pass misses.
(+) Plateau detection prevents amplification from running past diminishing returns.
(+) Hard caps prevent infinite loops — every run terminates in bounded time.
(+) Haiku handles all verification (cheap); Sonnet handles all generation (still cheap vs. Opus).
(+) Full resume support: every loop iteration writes a sidecar to disk before the next iteration starts.

(−) A single run now takes longer wall-clock than a single-pass Opus call (~45 min vs. ~8 min).
(−) L2 loop can waste 5 Haiku calls if the seed is non-viable — `pipeline/commercial_prescreen.py` must run before Phase 0 to gate out non-viable seeds early.
(−) Cap-and-halt behavior means some concepts reach the cap without passing — operators receive a `verdict=REJECT_FINAL` file, not a polished concept.

## Verifies

CLAUDE.md MUST rules:
- "MUST cap challenge loop (L1) at 3 patch rounds before REJECT_FINAL" (enforced by: pipeline/loop_controller.py:patch_budget)
- "MUST cap amplification loop (L2) at 5 iterations OR plateau-detected" (enforced by: pipeline/loop_controller.py:plateau_reached)
- "MUST cap genius (L3) and consistency (L4) loops at 3 patches each" (enforced by: pipeline/loop_controller.py:patch_budget)
- "MUST cap narrator-redo loop (L5) at 2 rounds before halt" (enforced by: pipeline/loop_controller.py:patch_budget)
- "MUST implement plateau detection in pipeline/loop_controller.py not in LLM prompt" (enforced by: tests/test_loop_controller.py::test_plateau_reached)
