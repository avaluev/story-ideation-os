# ADR-0005: frameworks/* are read-only references; never imported

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Architecture research (separation of build-time vs runtime; spec implies but doesn't state)

## Context

The 6 framework files (`frameworks/narrative-master-grid.md`, `sdt-spine.md`, `ajtbd-segmentation.md`, `forced-collision.md`, `character-arcs.md`, `cinema-school-doctrines.md`) are domain knowledge that the Forge and Critic agents inject as system context. There is a temptation to "extract" the rules into Python (e.g. translate Polti situations into a Python enum, the cinema-school-checks into Python boolean functions). This would couple runtime code to the doctrine.

## Decision

`frameworks/*.md` are markdown-only. No Python module imports their content programmatically. The agents read them as system-context strings via `pipeline.run.load_framework(path)`. Any rule in a framework file that needs to be enforced in Python (e.g. cinema-school check booleans) is *re-stated* in `pipeline/scoring.py` with a code comment pointing to the framework file's section.

## Consequences

(+) Framework-doctrine evolves freely without breaking the Python pipeline.
(+) Agents and humans can read the same source of truth.
(−) Doctrine drift: a rule changes in the markdown but not in `scoring.py` would silently desync. Mitigated by `tests/test_frameworks_have_integration_section.py` which asserts each framework file ends with §"Operational Integration" listing the Forge fields it produces and the Critic checks that re-evaluate them.

## Verifies

CLAUDE.md MUST rule "frameworks/*.md MUST NOT be imported from Python; rules duplicated in scoring.py MUST cite their framework section" (enforced by: `tests/test_frameworks_no_import.py` + `evals/test_framework_integration_sections.py`).
