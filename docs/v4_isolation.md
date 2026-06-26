# v4 Isolation Protocol

> **Status:** canonical (V4A-004, 2026-05-10)
> **Purpose:** Prevent the v4 alternative pipeline from polluting paths
> the v3.1 (production) workflow reads or writes.
>
> The repo houses two parallel pipelines:
>
> 1. **v3.1 — main / production flow.** Powered by
>    `pipeline/openrouter_client.py` + `pipeline/path_c_a4_sidecar.py`.
>    Outputs land under `out/concepts/v3.1-*` and `data/runs/v3.1-*`.
>    137 audience-validated briefs already exist; another 1067-brief forge
>    is operator-pending.
>
> 2. **v4 — alternative / pure-CC flow.** Powered by `pipeline/run_cc.py`
>    + `pipeline/cc_dispatch.py` + Task subagents (subscription only, $0
>    external API). Built across V4A-001 → V4A-003e (cc_dispatch + quota
>    + 8 cross-domain catalogs + mutation engine + 10 personas + 14-section
>    A4 spec).
>
> The two pipelines read overlapping framework + prompt + sources files
> READ-ONLY. They MUST NOT share writable state. This document defines
> the hard partition; `scripts/v4_preflight.py` enforces it; the test in
> `tests/test_v4_isolation.py` is the CI guard rail.

## Path Partition (canonical)

| Concern | v3.1 (main) | v4 (alternative) |
|---|---|---|
| **Concept briefs (markdown)** | `out/concepts/v3.1-pathc-a4/<concept_id>.md` | `out/concepts/v4-genius-cc/<concept_id>.md` |
| **Per-run state dir** | `data/runs/v3.1-pathc-a4/<run_id>/` | `data/runs/v4-genius-cc/<run_id>/` |
| **Phase JSONL** (mining/JTBD/audience/concept/critique) | `data/runs/v3.1-pathc-a4/<run_id>/0X_*.jsonl` | `data/runs/v4-genius-cc/<run_id>/0X_*.jsonl` |
| **Manifest** (concept_id × score × cost) | `data/runs/v3.1-pathc-a4/<run_id>/manifest.jsonl` | `data/runs/v4-genius-cc/<run_id>/manifest.jsonl` |
| **Per-Task chunk dir (Task fan-out)** | n/a (uses OpenRouter, no chunks) | `data/_chunks/<run_id>/<phase>/slice_*.jsonl` |
| **Concept ID prefix** (recommended) | hex-only (e.g. `35f86cae8bfab15a`) | `v4-` prefix (e.g. `v4-35f86cae8bfab15a`) |
| **Reports** | `outputs/v3.1-pathc-a4/...` | `outputs/v4-genius-cc/...` |
| **Comparison reports** | `outputs/comparisons/v3-vs-v4-*.md` (read-only on both inputs) | same |

## Shared Read-Only Surface

Both pipelines read the same files. NEITHER pipeline may write to them at
runtime:

- `frameworks/*.md` — narrative-master-grid, sdt-spine, forced-collision,
  character-arcs, cinema-school-doctrines, anti_slop. (ADR-0005:
  frameworks are read-only at runtime.)
- `prompts/*.md` — Phase 1..6 system prompts.
- `sources/*.yaml` + `sources/data-sources.yaml` — registry of mining
  endpoints (categories A..J for v3 + K..R for v4 cross-domain).
- `pipeline/data/*.json` — Eno cards, Polti×Tobias coherence matrix.

## Hard Rules (MUST NOT)

- **MUST NOT** write to any `out/concepts/v3.1-*` path from any v4 module
  (enforced by: `scripts/v4_preflight.py` + `tests/test_v4_isolation.py`).
- **MUST NOT** write to any `data/runs/v3.1-*` path from any v4 module
  (enforced by: same).
- **MUST NOT** import `pipeline.openrouter_client` from any v4 module
  (already enforced by: `scripts/lint_imports.py:ANOMALY-001` for
  `cc_dispatch`, `gemini_dispatch`, `quota`, `scoring`; expand the scan
  list as v4 modules grow).
- **MUST NOT** mutate `data/03_audience.jsonl` or `data/04_concepts.jsonl`
  at the repo root from a v4 run; those are v3-era staging files.
  v4 runs write to per-run state under `data/runs/v4-genius-cc/<run_id>/`.

## Hard Rules (MUST)

- **MUST** call `scripts/v4_preflight.py --run-id <run_id>` before
  invoking any v4 forge / mine / dispatch. The pre-flight verifies
  the destination directory is on the v4 partition and creates it if
  missing.
- **MUST** stamp every v4 phase JSONL row with a `pipeline_version:
  "v4"` field (already standard via `Phase4Concept.forge_meta`).
- **MUST** use `concept_id` prefix `v4-` when forging in v4 to make the
  origin self-evident in the merged manifest (v3 ids are bare hex).
- **MUST** route every v4 model call through `pipeline.cc_dispatch`
  (ADR-0007). v4 NEVER calls OpenRouter.

## Pre-Flight Gate

`scripts/v4_preflight.py` runs before every v4 forge. It:

1. Validates the proposed run-id matches `^[0-9]{8}T[0-9]{6}Z$`.
2. Confirms the destination tree is `data/runs/v4-genius-cc/<run_id>/`
   (or `out/concepts/v4-genius-cc/<run_id>/`); fails if either is in a
   v3.1-* tree.
3. Creates the destination directories if absent.
4. Asserts the most recently committed file does NOT mix v3.1 + v4 paths.
5. Emits a JSON envelope to stdout that the orchestrator pipes into
   `data/runs/v4-genius-cc/<run_id>/preflight.json`.

The pre-flight is non-destructive: re-running on the same run-id is a no-op.

## CI Gate

`tests/test_v4_isolation.py` is the mechanical guard rail. It:

1. Scans every Python module under `pipeline/run_cc.py`,
   `pipeline/cc_dispatch.py`, and any future v4 entry points for
   string literals matching `out/concepts/v3.1-` or `data/runs/v3.1-`.
   Hits = test fail.
2. Asserts that `scripts/v4_preflight.py` exists and is invokable.
3. Asserts the path-partition table in this document matches the
   actual tree layout (no orphaned v4 paths).

## Comparison Harness

`scripts/compare_pipelines.py` is the only module that may read both
v3.1 and v4 trees in the same invocation. It is READ-ONLY on both
inputs and writes its reports to `outputs/comparisons/`. The parity
gate `evals/test_pipeline_parity.py` mirrors this read-only contract.

## Operator Override

Two scenarios let an operator bypass the pre-flight:

- **Manual cleanup.** Set `V4_PREFLIGHT_BYPASS=1` and write a one-line
  rationale to `data/runs/v4-genius-cc/<run_id>/preflight.bypass`.
  CI still scans for cross-pipeline writes; bypass is for the gate
  not the lint.
- **Force re-run.** Pass `--force` to recreate a run-id directory that
  already exists. Idempotent on top of an empty directory; refuses if
  any phase JSONL has rows.

Neither override permits writing to a v3.1 path.

## Rollback

If a v4 run accidentally writes to a v3.1 path:

1. **Halt** the run immediately. Do NOT continue dispatching Tasks.
2. **Diff** `git status` to identify the polluted path.
3. **Revert** the polluted file via `git checkout HEAD -- <path>`.
4. **Quarantine** the v4 chunks that produced the bad write under
   `data/runs/v4-genius-cc/<run_id>/_quarantine/`.
5. **File** an extras-row in `.planning/state/PLAN_LEDGER.jsonl` describing
   the incident and the fix; reference this rollback procedure.

A pre-flight failure is preferable to any of the above. Treat the
pre-flight as load-bearing.

## Cross-References

- `pipeline/run_cc.py` — v4 dispatch CLI
- `pipeline/cc_dispatch.py` — v4 plan/merge/record helpers
- `pipeline/quota.py` — v4 weekly-token quota tracker
- `pipeline/openrouter_client.py` — v3 LLM client (READ from v3 only)
- `pipeline/path_c_a4_sidecar.py` — v3 sidecar that produces v3.1-pathc-a4 briefs
- `scripts/lint_imports.py` — ANOMALY-001 / ANOMALY-002 import lints
- `docs/adr/0007-cc-task-dispatch-replaces-openrouter.md`
- `docs/adr/0008-quota-gated-opus-promotion.md`

*Last updated: 2026-05-10 (V4A-004).*
