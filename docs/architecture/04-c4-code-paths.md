---
title: C4 — Critical Code Paths
aliases:
  - C4
  - Code Paths
  - Sequence Diagrams
tags:
  - architecture
  - c4/c4
  - anomaly-engine
created: 2026-05-30
updated: 2026-05-30
cssclasses:
  - architecture
---

# C4 — Critical Code Paths

> [!abstract] Level 4 answers
> *How do the highest-risk paths actually execute over time?* Only the **5 paths**
> with the most coordination, gating, or anti-hallucination risk get a sequence
> diagram — not every function.

---

## C4.1 — Single-Idea pipeline (10 phases + L1–L5 loops)

> [!example] Risk: recursive patch loops must be **Python-bounded**, never LLM-decided.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant Orch as Orchestrator (SKILL.md)
    participant Seed as compound_seed
    participant Ag as Subagents (Task)
    participant LC as loop_controller
    participant St as state.safe_write

    Op->>Orch: /single-idea --theme "X"
    Orch->>Seed: generate(freq_table)
    Seed->>St: seed.json
    Orch->>Ag: Phase 1 researcher → research.json
    Orch->>Ag: Phase 2 drafter → draft_v0.json
    Orch->>Ag: Phase 3 challenger
    alt P0 kill-switch fail
        Orch->>LC: patch_budget("L1")
        LC-->>Orch: rounds left (max 3)
        Orch->>Ag: re-draft (L1)
    end
    Orch->>Ag: Phase 4 amplifier
    loop L2 amplify (max 5)
        Orch->>LC: plateau_reached(window=2, Δ<0.05)?
        LC-->>Orch: stop / continue
    end
    Orch->>Ag: Phase 5 genius-auditor (C001–C008)
    alt kill-switch fail → L3 (max 3)
        Orch->>Ag: re-draft (L3)
    end
    Orch->>Ag: Phase 6 consistency-checker
    alt HIGH/MED drift → L4 (max 3)
        Orch->>Ag: re-draft (L4)
    end
    Orch->>Ag: Phase 7 narrator → [slug]-NARRATOR.md
    Orch->>Orch: Phase 8 eval_gate
    alt eval fail → L5 (max 2)
        Orch->>Ag: re-narrate (L5)
    end
    Orch->>St: Phase 9 lessons.json + RESUME.md
    Orch-->>Op: runs/<run>/[slug]-NARRATOR.md
```

> [!important] All loop caps live in `loop_controller.py` ([[05-adr-registry|ADR-0009]])
> `L1=3, L2=5, L3=3, L4=3, L5=2`. Plateau = last 2 relative deltas both `< 0.05`.

---

## C4.2 — Model dispatch + Opus quota gate

> [!example] Risk: Opus is rate/cost limited; promotion must be **quota-gated**, and the
> dispatcher must never import an LLM client ([[05-adr-registry|ADR-0002/0007/0008]]).

```mermaid
sequenceDiagram
    autonumber
    participant Caller as Orchestrator
    participant CC as cc_dispatch
    participant Q as quota.gate
    participant KM as key_manager
    participant Claude as Anthropic Claude (Task)

    Caller->>CC: dispatch(agent, tier="opus")
    CC->>Q: gate(tier, weekly_remaining)
    alt quota exhausted OR quality floor not met
        Q-->>CC: DENY → fall back to Sonnet K=3
        CC->>Claude: Task(sonnet ×3)
    else promotion allowed
        Q-->>CC: ALLOW (opus)
        CC->>KM: active key (masked to 8 chars in logs)
        CC->>Claude: Task(opus)
    end
    Claude-->>CC: result
    CC->>Q: record(token_burn) → data/quota.jsonl
    CC-->>Caller: agent output (parsed)
```

> [!warning] Enforcers
> `cc_dispatch.py` is lint-blocked from importing `anthropic`/`httpx`/`openrouter_client`
> (ANOMALY-001). Every Task burn is recorded via `pipeline.quota.record`.

---

## C4.3 — Revenue projection (SOM / SAM / TAM)

> [!example] Risk: the #1 fabrication surface. Every number must be python-executed
> ([[05-adr-registry|ADR-0011]]); LLMs may never restate a financial figure.

```mermaid
sequenceDiagram
    autonumber
    participant Concept as concept seed_axes+genres
    participant Comps as comps.match_comps
    participant Corpus as 894-film corpus
    participant Rev as revenue.project_revenue
    participant Out as RevenueProjection

    Concept->>Comps: genres
    Comps->>Corpus: genre-Jaccard similarity
    Corpus-->>Comps: top-K comparable films (WW gross)
    Comps->>Rev: comp grosses + weights
    Rev->>Rev: weighted log-mean
    Rev->>Rev: winsorize outliers @ 0.05
    Rev->>Rev: × audience_factor (reach/300M, cap 1.6)
    Rev->>Rev: × window_factor (theatrical 1.0 … streaming 0.40)
    Rev->>Rev: × geo_factor (us_only 0.45 … global 1.0)
    Rev->>Out: SOM_y1, calculation_method="python_executed"
    Out->>Out: assert SOM < SAM < TAM (TAM default $152B)
```

> [!important] The gate
> `evals/test_revenue_projection.py` asserts `calculation_method == "python_executed"`
> and the SOM<SAM<TAM ordering; any concept failing the invariant is quarantined, not shipped.

---

## C4.4 — Cross-slate distinct selection (the v5.2.1 fix)

> [!example] Risk: look-alike concepts across formats. Distinctness must hold across the
> **whole slate**, not just within a format.

```mermaid
sequenceDiagram
    autonumber
    participant BP as build_portfolio.py
    participant Sel as select_topk_distinct
    participant Seen as claimed_worlds (set)

    BP->>Seen: claimed_worlds = {}
    loop for each of 6 formats
        BP->>Sel: select_topk_distinct(cands, k, seen={"world_texture": claimed_worlds})
        Sel->>Sel: skip any candidate whose axis-id ∈ claimed
        Sel-->>BP: k distinct-world winners
        BP->>Seen: claimed_worlds += winners' world_texture ids
    end
    BP-->>BP: 18 concepts, 18 distinct worlds (guaranteed)
```

> [!note] Regression gate
> `evals/test_portfolio_distinctiveness.py` asserts token-distinct titles, logline
> Jaccard ≤ 0.50, and ≥3 deep-linked comps per concept. Two unit tests pin the
> `seen=` exclusion and its caller-set immutability.

---

## C4.5 — WEDGE autonomous loop

> [!example] Risk: an unattended loop must self-halt and learn only from operator ratings,
> never from its own scores ([[05-adr-registry|ADR-0009/0012]]).

```mermaid
sequenceDiagram
    autonumber
    participant Loop as loop_wedge
    participant Q as quota.gate
    participant Gen as evolve.one_shot
    participant Score as scoring (vs Goal)
    participant Hist as loop_history.jsonl
    participant FB as feedback.refit_weights

    loop until score≥target AND som≥floor
        Loop->>Q: gate(opus weekly quota)
        Q-->>Loop: ok / fall back
        Loop->>Gen: one_shot(freq_table + diversity)
        Gen-->>Loop: candidate
        Loop->>Score: geometric-mean facets
        Score->>Hist: append iteration
        Loop->>Loop: plateau_reached?
        alt plateau AND operator ratings exist
            Loop->>FB: refit_weights(labels) → Goal.save(new id)
        end
    end
    Loop-->>Loop: halt
```

## Related
- [[_index|Architecture MOC]] · [[03-c3-components]] · [[05-adr-registry]] · [[06-glossary]]
