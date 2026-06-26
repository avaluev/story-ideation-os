# ADR-0004: Synthesis brief's canonical_data is downstream-immutable

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Spec (`Inputs/_ANOMALY_ENGINEv3.0.md` Phase 6 + 7)

## Context

Phase 6 (synthesis-researcher equivalent in our pipeline) merges all upstream phase outputs into a single `canonical_data` block per concept. Downstream agents (deck-assembler in our Phase 4 forger; Phase 5 critic; Phase 6 formatter) often have access to *both* the canonical data AND the underlying upstream files. If they pull numbers from upstream files instead of canonical_data, the engine emits inconsistent values across the same concept's slides/sections.

## Decision

`canonical_data` is the single source of truth for any field present in it. Downstream agents MUST use `canonical_data[field]` verbatim if it exists; only fall back to upstream files for fields canonical_data doesn't carry.

## Consequences

(+) Internal consistency across the A4 output: every audience number, every score, every comparable matches across sections.
(+) Reduces hallucination surface (one number to verify, not 6 versions of it).
(−) Synthesis must be exhaustive — anything missed forces downstream fallback.

## Verifies

CLAUDE.md MUST rule "deck assembly + critic + formatter MUST consult canonical_data first when a field is canonical" (enforced by: `evals/test_canonical_data_provenance.py`).
