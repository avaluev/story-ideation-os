# Architecture Decision Records — Anomaly Engine v3.0

Architecture Decision Records (ADRs) capture significant decisions made during the design and development of the Anomaly Engine. Each ADR is immutable once accepted.

## Numbering Convention

Sequential 4-digit identifiers: `ADR-0001`, `ADR-0002`, …

**Operator decision (2026-05-06):** numbering is strictly sequential. No gaps. No reuse of deprecated numbers.

## Status Legend

| Status | Meaning |
|--------|---------|
| **Accepted** | Active decision; enforced by CI |
| **Superseded** | Replaced by a newer ADR (referenced in body) |
| **Deprecated** | No longer applicable; not replaced |
| **Proposed** | Under discussion; not yet in force |

## Current ADRs

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0001](0001-jsonl-not-memory.md) | State lives on disk as JSONL, not in agent context | Accepted |
| [ADR-0002](0002-llms-no-arithmetic.md) | LLMs MUST NOT compute scores | Accepted |
| [ADR-0003](0003-3-key-rotation.md) | 3-key FIFO rotation for OpenRouter | Accepted |
| [ADR-0004](0004-canonical-data-immutable.md) | Synthesis brief's canonical_data is downstream-immutable | Accepted |
| [ADR-0005](0005-frameworks-readonly.md) | frameworks/* are read-only references; never imported | Accepted |
| [ADR-0006](0006-got-opus-promotion.md) | GoT Opus-4.7 promotion = automatic two-gate (score ≥75 AND budget remaining) | Accepted |

## How to Propose a New ADR

1. Copy `template.md` to `docs/adr/NNNN-<slug>.md` where NNNN is the next sequential number.
2. Fill in all sections: Context, Decision, Consequences, Verifies.
3. Set Status to `Proposed`.
4. Open a PR — the ADR must be reviewed before being set to `Accepted`.
5. Once merged with `Accepted` status, add a row to the index table above.
6. Add a CLAUDE.md MUST rule referencing `(ADR-NNNN)` and ensure `tests/test_claude_md_compliance.py` passes.
