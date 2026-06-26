# ADR-0010: No Internal IDs or Framework Labels in Investor Documents

**Status:** Accepted
**Date:** 2026-05-12
**Decided by:** Operator (via 12May.Plan.md requirements)

## Context

All prior output modes (`batch/`, `runs/`, `out/concepts/`) leaked internal pipeline metadata into the final markdown: Cell-IDs (`BT-001_PS-020`), iteration markers (`iter-2`, `Per L008`), framework author surnames (Booker, McKee, TRIZ, JTBD, Boden, Csikszentmihalyi), and agent decision trails. This caused two problems:

1. **Investor confusion.** A pitch document containing "TRIZ Contradiction #7 — Matryoshka Nesting" or "Per L008" is unprofessional. Investors are not expected to know these frameworks; naming them adds confusion without adding persuasion.
2. **Russian translation hostility.** Framework surnames and internal codes produce untranslatable artifacts in Cyrillic rendering and break the register uniformity required for professional translation.

## Decision

A two-layer filter enforces clean output:

**Layer 1 — Narrator behavioral rule:** `concept-narrator` is instructed never to name framework authors, theory labels, or internal pipeline state in any output file. The hidden attributes from `seed.json` shape prose *implicitly* (see `Inputs/STYLE_GUIDE.md` Section 2).

**Layer 2 — Deterministic regex filter:** `pipeline/template_filter.py:strip_internal_ids(md_text)` runs as a post-processing step on the narrator's raw output before the file is written to `runs/`. The regex catches any label that slipped through the behavioral rule.

**The banned regex (applied to every `runs/` file):**

```
(?x)
Cell-ID:                   | Per\ L\d+              | L\d+\b               |
iter-\d+                   | BT-\d+                 | PS-\d+               |
PA-\d+                     | US-\d+                 | TRIZ                 |
JTBD\b                     | Booker\b               | McKee\b              |
Boden\b                    | Csikszentmihalyi\b     | Reagan\ (2016|arc)\b |
Pearson\ archetype\b       | Egri\ premise\b        | Polti\ situation\b   |
Haidt\ foundation\b        | Mednick\ remote\b      | Wundt-Berlyne\b      |
Simonton\ type\b           | Wundt\b                | Simonton\b           |
Stanton\ itch\b            | SIT\ Operator\b        | Conceptual\ Blend\b  |
Macro\ Resonance\ Weight   | Anti-slop\b            | ten-school\b         |
Lessons\ consulted         | Working\ title         | run-id:              |
Run\ ID:
```

**Sidecar convention:** All internal framework data lives in sidecar files (`seed.json`, `draft.v0.md`, `challenge.json`, `genius.json`, `consistency.json`). These files are not shared with investors. They are not linked from the investor markdown. They exist only for pipeline debugging and lesson extraction (Phase 9).

**File naming rule:** Every investor markdown is named after the film title slug: `Station-Tolerance.md`, not `iter-2.md`, `concept-001.md`, or `{run_id}.md`.

## Consequences

(+) Investor documents are readable by non-technical partners, co-producers, and translators.
(+) Russian translation quality improves: no untranslatable codes, no academic register intrusions.
(+) Eval gate is deterministic: `evals/test_no_internal_ids.py` regex scan returns zero ambiguity.
(+) Framework authors' insights are preserved — they shape the work, they just don't appear in it.

(−) Two-layer approach requires maintaining both the narrator prompt AND the regex blocklist. When a new framework is added to `seed.json`, both `Inputs/STYLE_GUIDE.md` Section 1 and this ADR's regex must be updated.
(−) The regex can produce false positives on film titles that happen to contain a banned word. Mitigation: `strip_internal_ids()` only matches banned terms when they appear as standalone words or with their specific context patterns (e.g., `Booker\b` not `Booker Prize`). Review the filter output in `eval.json` before shipping.

## Verifies

CLAUDE.md MUST rules:
- "MUST strip all internal IDs and framework labels via `pipeline.template_filter.strip_internal_ids` before writing investor files to `runs/`" (enforced by: evals/test_no_internal_ids.py)
- "MUST NOT expose TRIZ, JTBD, Booker, McKee, Boden, Csikszentmihalyi, Reagan, Pearson, Egri, Polti, Haidt, Mednick, Wundt, Simonton, or Stanton in any `runs/` markdown file" (enforced by: evals/test_no_internal_ids.py)
- "MUST name each investor markdown file after the film title slug" (enforced by: evals/test_no_internal_ids.py)
