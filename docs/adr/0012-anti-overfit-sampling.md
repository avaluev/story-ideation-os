# ADR-0012: Anti-Overfit Sampling (Frequency Memory + Diversity Floor + Mental-Model Operators)

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Operator (via v5.0 plan, Days 2-4)

## Context

The v4 engine has a 19.2-trillion-combination compound-seed parameter space and a fitness function (`crystallization_score`) that weights six facets geometrically. In theory, every run could find a different local optimum. In practice, ten consecutive runs on the same theme returned ten variations on the same attractor — "woman-as-protagonist + institutional cluster + technology world texture." The same axis values appeared in 70%+ of winners.

Three structural defects compound:

1. **Biased scorer.** `cluster_coherence` weight (0.17) and the v4 `som_floor_M / $300M` factor (0.09) both implicitly reward concepts that look like the corpus median. The scorer rewards the bias.
2. **No cross-run memory.** `_thematic_weighted_choice` (compound_seed.py:1865) samples each call independently. Nothing penalises an axis value that won the last 5 runs.
3. **No directional search.** Random sampling cannot escape a local attractor: any escape mutation is as likely as any other, including the mutations that move *into* the attractor.

The fix is the v5.0 lean architecture: fix the scorer (ADR-0011), add a cross-run frequency memory layer, add deterministic semantic-direction operators (SCAMPER / invert / constraint-strip), add prose-level LLM operators (first-principles / second-order / yes-and), and select with a diversity floor.

## Decision

Six modules under `ADR-0012`, all pure Python where possible:

- **Module 1 — `pipeline/diversity.py`**: per-axis-value frequency memory. Persists `(axis, value_id)` events to `data/axis_frequency.jsonl` via `pipeline.state.append_jsonl`. Schema-hash invalidation prevents stale-axis bias. `penalty(axis, value_id, freq_table, alpha=0.3) = 1 / (1 + freq) ** alpha` — soft, monotone, bounded in `(0, 1]`.
- **Module 3 — `pipeline/operators/mental_models.py`**: three deterministic axis-mutators. `scamper_substitute` walks 5 core axes and swaps each to a low-frequency alternative weighted by `diversity.penalty`. `invert` flips three structurally-paired axes (SI↔SI via `pipeline/data/inversion_pairs.json`, protagonist↔antagonist, dark-archetype shadow). `constraint_strip` removes one populated decorative axis per mutant. Every mutant tags `lineage: list[str]` with `"<operator>:<axis>"`.
- **Module 4 — `pipeline/operators/llm_operators.py`**: three Sonnet-4.6 operators dispatched via the ADR-0007 split (Python writes manifests under `.planning/phase_dispatch/{run_id}/mutation-*.jsonl`; Claude Code dispatches Tasks; Python merges results). Per-call fan-out capped at `loop_controller.patch_budget("L2")`; gated by `quota.gate("sonnet", expected_tokens)`; per-call burn recorded via `quota.record`.
- **Module 5 — `pipeline/select/diversity_select.py`**: top-K with a `cluster_floor`. Greedy fill discounts duplicates of `(cluster, archetype, world_texture)` triples by `alpha**dup_count`. Then a swap-in pass force-promotes the best missing-cluster anchor (above `quality_threshold`) for the weakest survivor in an over-represented cluster.
- **Module 6 — `pipeline/evolve/one_shot.py`**: single-pass orchestrator. Generates Base-N, applies the three Python operators, (optionally) writes LLM-operator manifests, computes `project_revenue` (ADR-0011) + `crystallization_score` for every candidate, selects with the diversity floor, persists per-generation artifacts, feeds winning axis values back into `data/axis_frequency.jsonl` for the next run.

**Surgical wirings into the v4 path** (Day-4):

- `pipeline/compound_seed.py:_thematic_weighted_choice` accepts optional `freq_table` + `axis_name` kwargs. When supplied, each item's weight is multiplied by `diversity.penalty(...)`. None of the v4 call sites pass these arguments (backwards-compat); the v5 orchestrator passes them at every sample.
- `pipeline/single_idea.py:generate_seed_via_evolve(...)` replaces the v4 `engine.generate()` Phase-0 step with `explore_and_select(...)`. Writes top-1 to `seed.json` and the rest to `seed_candidates.jsonl` for operator review.

**Deliberately out of scope for v5.0 (defer to v5.1 with evidence):** multi-generation evolution, NSGA-II Pareto, crossover operators, Six Hats council. Adding any of those before the v5.0 fitness function is verified compounds the bias rather than escaping it.

## Consequences

(+) Cross-run memory breaks the local-attractor cycle: even on the same theme, the second run's sampler is biased *away* from the first run's survivors.
(+) Mental-model operators give the search structured semantic directions, not just random jitter. Day-3 unit tests caught an inverted-weight bug (`1/penalty` instead of `penalty`) before it shipped — proof the operator's intent is testable in isolation.
(+) The diversity-floor selector guarantees that 4 of 8 thematic clusters are represented in the top-10 (or returns best feasible coverage). The "all winners look the same" failure mode becomes a structural impossibility.
(+) Schema-hash invalidation in `diversity.py` means a future axis-library refactor doesn't corrupt the frequency table — stale rows are silently skipped.
(+) Every persisted artifact (mutants.jsonl, projected.jsonl, winners.json) carries the `lineage` field, so operators can attribute winning concepts back to the operator that produced them. This is the data v5.1 needs to decide which operators are worth keeping.

(−) The full v5 orchestrator path (Base-N=64 + 8 mutants per base + revenue projection per candidate) is ~6× slower than the v4 `engine.generate()` single-call (~40s vs ~7s on the dev box). The slowness is dominated by `project_revenue` (which scans all 3000 corpus films per call). Cacheable.
(−) The freq_table read happens on every `explore_and_select` invocation. If `data/axis_frequency.jsonl` grows unbounded, load time degrades linearly. Operator-side `make clean` rotation is the manual mitigation; v5.1 will add automatic ring-buffer rotation.
(−) The LLM operators (Module 4) require operator-side dispatch via the `/single-idea` skill. A future operator who skips the Task dispatch step gets a silent no-op (manifest sits unread). Logged at INFO when `use_llm_operators=True` but no merge runs.

## Verifies

CLAUDE.md MUST rules:
- "MUST pass freq_table to _thematic_weighted_choice when sampling in production mode" (ADR-0012)
- "MUST NOT let any single (axis, value_id) exceed 40% frequency over the rolling 20-run window" (ADR-0012)
