# ADR-0011: Data-Driven Revenue / SOM / SAM / TAM

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Operator (via v5.0 plan, Day 1)

## Context

Through v4, every TAM / SAM / SOM number a concept carried into the investor narrator was produced by an LLM (typically `perplexity/sonar-deep-research`), then post-hoc "audited" for plausibility. Two problems:

1. **Not defensible.** A reviewer asking "where does the $300M SOM come from?" got "Perplexity said so" — not a corpus-anchored estimate. The same prompt on different days produced different numbers; nothing was reproducible from the repo alone.
2. **Not robust.** When the OpenRouter budget hit $0, the entire research path collapsed. Every concept's SOM became `null` or got stamped with a stale cached value.

The fix is to compute SOM / SAM / TAM **deterministically from the 294-film (now 3000-film) corpus** using comp-similarity weighting plus an explicit Venn-overlap audience model. The output carries a verifiable `calculation_method: "python_executed"` marker so downstream consumers can refuse anything that lacks it.

## Decision

`pipeline/crystallize/revenue.py` (`project_revenue(...)` → `RevenueProjection`) becomes the **single source of truth** for SOM / SAM / TAM:

- **SOM Y1** = `weighted_log_quantiles(comps, similarities, alpha=2.0)` median × `audience_factor` × `window_factor` × `geo_factor`. Comps come from `FilmsCorpus.find_comps_with_similarity()`; weights are `sim ** alpha` (alpha=2 by default); Winsorisation at outlier ±3σ neutralises mega-blockbusters.
- **SAM** = `TAM × genre_slice_fraction(candidate.genres, corpus)` — corpus self-share, not LLM prose.
- **TAM** = `DEFAULT_TAM_USD = $152B` (MPA + Ampere 2023 theatrical + streaming spend), overridable via `ProjectionContext.facts["tam_usd"]` when a fresher fact arrives.
- **Audience overlap**: explicit inclusion-exclusion on `domain_tags` Jaccard with `affinity_with` priors, returns a typed `OverlapResult`.
- **Every projection carries `calculation_method: "python_executed"`** — the deck/narrator hard-rejects any SOM number whose source lacks this marker.

Surgical wirings landed in v5.0 Day-4 to make this the authoritative path:

- `pipeline/compound_seed.py:_compute_audience_overlap` now delegates to `revenue.compute_audience_overlap(...)`. Signature preserved; the v4 30%/15% flat-rate heuristic is gone.
- `pipeline/crystallize/score.py` prefers `scores.get("som_y1_usd")` over the legacy `som_floor_M`, normalised vs $200M instead of $300M (Y1 is post-derate; $200M is the new top-quartile floor).
- `pipeline/evolve/one_shot.py` calls `project_revenue` for every candidate before scoring.

## Consequences

(+) Every numeric SOM / SAM / TAM in a runs/*.md artifact is reproducible from `git checkout` + `make eval` — no API key required, no network.
(+) The narrator's `calculation_method` check makes fabrication a hard fail, not a vibe call.
(+) Eval `evals/test_revenue_projection.py` pins MdAPE ≤ 50% (log-scale, leave-one-out on 294-film corpus), Spearman ρ ≥ 0.30 across genre buckets, and per-projection `calculation_method == "python_executed"`.
(+) Backwards compatibility preserved: `som_floor_M` still works for v4 paths that haven't been wired to the v5 path yet (the score factor falls back gracefully).

(−) A bad corpus expansion (e.g. a TMDB scrape that miscategorises genres) now flows directly into SOM numbers. The corpus build is the new failure surface.
(−) Without `perplexity/sonar-deep-research`, the narrator loses access to *competitive intel prose* (recent industry commentary). It still has all the numbers — but the qualitative colour now comes from a smaller research path (302.ai fallback, see ADR commit 40c717a).
(−) The v5.0 normaliser at $200M is tighter than v4's $300M — concepts that scored 0.7 on the old facet may score 0.55 on the new one. Operators retraining their intuition on the new score is a one-time cost.

## Verifies

CLAUDE.md MUST rules:
- "MUST compute som_y1_usd via pipeline.crystallize.revenue.project_revenue" (ADR-0011)
- "MUST NOT write LLM-suggested SOM/SAM/TAM numbers to runs/*.md without calculation_method: python_executed in the source RevenueProjection" (enforced by: evals/test_revenue_projection.py::test_calculation_method_always_set)
