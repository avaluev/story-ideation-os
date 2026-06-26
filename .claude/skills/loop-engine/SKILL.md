---
name: loop-engine
description: |
  /loop-engine — autonomous big-idea generation against the active /goal.
  Drives one or more iterations of the WEDGE closed loop: quota-gated
  generation, goal-conditional halt, plateau-triggered recalibration from
  operator ratings (data/labels.jsonl), and per-iteration provenance to
  data/loop_history.jsonl. Use when the operator types /loop-engine N
  (run N iterations) or /loop-engine until-goal (run until a candidate
  beats goal.target_score + revenue_floor_usd).
---

# /loop-engine — The Convergent Autonomous Loop

## Why this skill exists

Pre-Steps-4-5-6, the engine generated concepts but never learned from the
operator's reaction. Every run started from the same uniform sample, hit
the same A.I.-shaped attractor, and the operator's rating column stayed
dead. The "infinite circle" the operator complained about.

`/loop-engine` is the closed loop:

1. Read `config/goal.json` (the operator's taste contract, Step 3).
2. Quota-gate Opus burn (ADR-0008 weekly cap).
3. Run one `/evolve` iteration with `freq_table` wired (Step 1, cross-run
   memory) + MMR comp decorrelation (Step 2, no clone dominance) +
   goal-keyed scoring weights (Step 3).
4. Score the top winner against the active goal; record one row to
   `data/loop_history.jsonl` (`ts`, `run_id`, `top_score`, `top_som_y1`,
   `goal_sha`, `strategy`).
5. Goal-conditional halt — exit early if `top.score >= goal.target_score
   AND top.som_y1 >= goal.revenue_floor_usd`.
6. Plateau check via `loop_controller.plateau_reached`. If plateau hit
   AND >= 10 new ratings since the active goal was created, run
   `pipeline.feedback.refit_weights` (Step 5) and save a new Goal (bumps
   `goal_id`). Next iteration runs against the shifted goal.

The key invariant: **plateau triggers diversification (weight refit),
not stopping**. The loop stays alive while the engine learns operator
taste, instead of declaring "done" and going stale.

## Invocation

```bash
# Run N iterations:
uv run python -m pipeline.loop_wedge --iterations 5

# Smoke-test the wiring without burning quota:
uv run python -m pipeline.loop_wedge --iterations 1 --dry-run

# Larger batch per iteration (default 10):
uv run python -m pipeline.loop_wedge --iterations 3 --batch-size 20
```

Hard ceiling: `pipeline.loop_wedge.DEFAULT_MAX_ITERATIONS = 100`. Anti-
runaway guard for autonomous mode — a 100-iteration loop with batch-size
10 = 1000 generated concepts, plenty of headroom inside one weekly Opus
budget.

## Production integration with /evolve (the missing wire)

The Python module's `_real_evolve_run` intentionally raises
`NotImplementedError` -- one_shot.explore_and_select needs `problem`,
`themes`, `engine`, `pools`, `corpus` objects that the project's existing
`/evolve` slash command already wires up. Duplicating that setup inside
`loop_wedge.py` would create a second source of truth.

The integration lives in THIS skill instead. When `/loop-engine` is
invoked, the orchestrator should:

1. For each iteration, shell out to `/evolve` (or its CLI equivalent)
   with `--n-base <batch_size>` and the operator's current theme/problem
   set (which can live in `.planning/state/RESUME.md` or a small
   `config/loop_context.json` -- TODO for the next session).
2. Read the produced `runs/evolve-<ts>/evolve/gen0/winners.json`.
3. Inject as `_evolve_fn` into `pipeline.loop_wedge.run_iteration` so the
   Python loop body sees real top scores and can call into
   `pipeline.feedback` for recalibration.

Until that wire lands, the operator can validate the wiring with
`--dry-run` and run the engine manually with `/evolve` between rating
sessions.

## Constraints (per the rebuild plan)

- MUST honour `pipeline.quota.gate("opus", ...)` before every iteration
  (ADR-0008).
- MUST NOT exceed `DEFAULT_MAX_ITERATIONS=100` per invocation.
- MUST record every iteration outcome (including aborts) to
  `data/loop_history.jsonl` -- Step 8 `/digest` reads this for the
  throughput + taste-convergence KPIs.
- MUST NOT mutate the active Goal in place; recalibration produces a
  NEW Goal via `Goal.save()` which bumps `goal_id`.

## What gets persisted

| File | Written when | Read by |
|---|---|---|
| `data/loop_history.jsonl` | Every iteration | Step 8 /digest, Section 7 KPI alerts |
| `config/goal.json` | Plateau-triggered refit | Every subsequent iteration |
| `data/goal_history.jsonl` | Every Goal.save | Operator audit / rollback |
| `data/labels.jsonl` | Operator types /rate (Step 4) | Step 5 feedback.refit_weights |
| `runs/<run_id>/evolve/gen0/winners.json` | Every /evolve | Step 5 feedback.read_winner_facets |

## How to know it's working

After 5 iterations, run:

```bash
uv run python -c "
import json
rows = [json.loads(l) for l in open('data/loop_history.jsonl').read().splitlines() if l.strip()]
print(f'iterations: {len(rows)}')
print(f'unique goal_shas: {len({r[\"goal_sha\"] for r in rows})}')
print(f'strategies seen: {sorted({r[\"strategy\"] for r in rows})}')"
```

Expect: 5+ iterations, 1-3 distinct goal_shas (one bump per ratings
batch), strategies showing a mix of `climbing` and `plateau:*`. If you
see only `abort:quota`, the weekly Opus burn is exhausted — wait for
ISO-week rollover.
