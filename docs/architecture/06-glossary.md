---
title: Glossary
aliases:
  - Glossary
  - Terms
tags:
  - architecture
  - glossary
  - anomaly-engine
created: 2026-05-30
updated: 2026-05-30
cssclasses:
  - architecture
---

# Glossary

> [!abstract] Shared vocabulary
> Terms used across [[01-c1-system-context|C1]]–[[04-c4-code-paths|C4]] and the ADRs.

| Term | Meaning |
|---|---|
| **Compound seed** | One sampled point in the ~19.2-trillion narrative-axis space (world texture, wound, fault line, archetype, …). Produced by `compound_seed.py`. |
| **894-film corpus** | The `films_corpus_enriched.jsonl` dataset of real films (genres, WW gross, prose) that anchors every comp and revenue projection. |
| **Comp / comparable** | A real corpus film matched to a concept by genre-Jaccard similarity (`comps.match_comps`); its box office anchors the revenue model. |
| **SOM / SAM / TAM** | Serviceable Obtainable / Available / Total Addressable Market. Computed by `revenue.project_revenue`; the invariant **SOM < SAM < TAM** must hold or the concept is quarantined. |
| **`calculation_method`** | A literal field that must equal `"python_executed"` on every `RevenueProjection` — the anti-hallucination marker for ADR-0011. |
| **Kill-switch (C001–C008)** | Originality/commercial-scale gates in `empirical_genius.py`; any failure routes a single-idea run back to the drafter (L3). |
| **L1–L5** | The five bounded patch/redo loops in the single-idea pipeline (challenge, amplify, genius, consistency, narrator), capped in `loop_controller.py` (ADR-0009). |
| **Plateau** | The amplification stop condition: the last `window=2` relative score deltas are all `< 0.05`. Detected in Python, never by an LLM. |
| **WEDGE** | The autonomous closed loop (`loop_wedge.py`): quota-gated generation → score vs `Goal` → plateau → refit from ratings → halt. |
| **Goal** | The learned facet-weight vector (`config/goal.json`) the WEDGE loop scores against; refit from operator ratings via `feedback.refit_weights`. |
| **Anti-overfit ceiling** | No single `(axis, value)` may exceed **40%** frequency over the rolling 20-run window (ADR-0012); enforced by `diversity.py` (α=0.8). |
| **Deep link / deep path** | An evidence URL with a real path beyond `/` that returns 2xx — bare domains, homepages and search-engine URLs are rejected (`portfolio.is_deep_path`). |
| **`seen=` (cross-slate)** | The exclusion set threaded through `select_topk_distinct` so distinctness holds across the *whole* portfolio, not just within a format (v5.2.1 fix). |
| **cc_dispatch** | The pure-Python Claude Code **Task** fan-out layer (ADR-0007); no LLM client may be imported into it. |
| **Quota gate** | `quota.gate` — blocks Opus promotion unless weekly subscription burn remains (ADR-0008). |
| **`safe_write`** | Atomic write (tmp + fsync + rename) in `state.py`; the only sanctioned way to persist cross-boundary state (ADR-0001). |
| **`strip_internal_ids`** | `template_filter` pass that removes run-IDs and framework labels before any `runs/` write (ADR-0010). |
| **Stop gate** | `make test && make eval` + a fresh `RESUME.md`; the condition for declaring a session done. |
| **Frameworks** | Read-only narrative doctrine under `frameworks/` (SDT spine, AJTBD, McKee/Polti grids); never imported by `pipeline/**` (ANOMALY-002). |
| **302.ai** | The primary external LLM gateway (`research/client_302ai.py`); active when `TAO_AI_PRIMARY=1` or no OpenRouter key. |
| **Single-idea vs Portfolio vs WEDGE** | The three production tracks — one developed concept, an N-concept slate, and unattended batch ideation — over the one shared substrate. |

## Related
- [[_index|Architecture MOC]] · [[01-c1-system-context]] · [[05-adr-registry]]
