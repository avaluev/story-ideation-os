---
title: C2 — Containers
aliases:
  - C2
  - Containers
tags:
  - architecture
  - c4/c2
  - anomaly-engine
created: 2026-05-30
updated: 2026-05-30
cssclasses:
  - architecture
---

# C2 — Container Diagram

> [!abstract] Level 2 answers
> *What are the runtime units and data stores inside the Anomaly Engine, and how do
> they communicate?* This system has no servers — its "containers" are the
> **CLI orchestrator process**, the **Python engine package**, the **Node Workflow
> harness**, the **provider adapters**, and the **on-disk stores**.

## Container diagram

```mermaid
flowchart TB
    operator(["Operator<br/>[Claude Code CLI]"])

    subgraph engine ["Anomaly Engine"]
        orch["Orchestrator<br/>[Claude Code session + SKILL.md]<br/>drives phases, spawns agents via Task"]
        agents[".claude/agents + skills<br/>[10 agent defs + skills]<br/>researcher · drafter · challenger ·<br/>amplifier · genius · consistency · narrator"]
        pipe["pipeline/ package<br/>[Python 3.12 · 49 modules · LLM-free logic]<br/>orchestration · scoring · gating · generation"]
        cryst["pipeline/crystallize/<br/>[Python · 12 modules]<br/>corpus · comps · revenue · portfolio · embeddings"]
        wf["Workflow harness<br/>[Node .mjs · agent() fan-out]<br/>enrich · review · translate"]
        adapters["Provider adapters<br/>[Python]<br/>cc_dispatch · llm_client ·<br/>openrouter_client · client_302ai · tmdb_client"]
        harness["Quality harness<br/>[pytest + lefthook + Makefile]<br/>tests/ 1575 · evals/ 126"]
    end

    subgraph stores ["On-disk stores (the single source of truth)"]
        dataj[("data/*.jsonl<br/>run_log · leaderboard · quota ·<br/>axis_frequency · goal_history · labels")]
        runs[("runs/<br/>per-run sidecars + outputs/portfolio")]
        planning[("planning/state/<br/>RESUME · PLAN_LEDGER · handoffs")]
        corpus[("pipeline/data/<br/>894-film corpus jsonl +<br/>embeddings .npz + axis JSONs")]
        fw[("frameworks/<br/>read-only doctrine MD + data")]
        cfg[("config/goal.json<br/>learned facet weights")]
    end

    claude["Anthropic Claude"]:::ext
    tao["302.ai"]:::ext
    openrouter["OpenRouter"]:::ext
    sonar["Perplexity Sonar"]:::ext
    tmdb["TMDB"]:::ext
    web["Demand-evidence web"]:::ext

    operator -->|"slash commands"| orch
    orch -->|"Task dispatch"| agents
    orch -->|"imports / calls"| pipe
    orch -->|"runs"| wf
    agents -->|"read/write sidecars"| runs
    pipe --> cryst
    pipe -->|"safe_write JSONL"| dataj
    pipe -->|"reads (never imports)"| fw
    pipe -->|"reads/writes"| planning
    pipe -->|"loads weights"| cfg
    cryst -->|"loads corpus + embeddings"| corpus
    pipe --> adapters
    wf -->|"agent() → Task"| claude
    adapters -->|"Task fan-out"| claude
    adapters -->|"HTTPS chat/research"| tao
    adapters -->|"HTTPS chat"| openrouter
    adapters -->|"HTTPS research"| sonar
    adapters -->|"HTTPS REST"| tmdb
    wf -->|"WebFetch (2xx verify)"| web
    harness -->|"gates"| pipe

    classDef ext fill:#2a2a2a,stroke:#888,color:#ddd;
```

## Containers

> [!info] Each box is a unit that runs or stores
| Container | Tech | Responsibility |
|---|---|---|
| **Orchestrator** | Claude Code session + `SKILL.md` | One pipeline **stage per session** (HARN-13). Drives the 10-phase single-idea flow / WEDGE loop / portfolio build; spawns subagents read-only for fan-out. |
| **Agents** | `.claude/agents/` (10) + skills | Runtime: researcher → drafter → challenger → amplifier → genius → consistency → narrator. Build-time: planner → builder → critic. See [[03-c3-components]] and [[05-adr-registry\|model tiers]]. |
| **`pipeline/` package** | Python 3.12, 49 modules | All **LLM-free** logic: orchestration, scoring, dispatch, gating, generation, state, rendering. The only place arithmetic happens. |
| **`pipeline/crystallize/`** | Python, 12 modules | The **economics + corpus + portfolio** substrate: comp matching, revenue projection, distinct selection. |
| **Workflow harness** | Node `.mjs` via the Workflow tool | Parallel `agent()` fan-out for portfolio **enrich / review / translate** (1 agent per concept; WebSearch + WebFetch). |
| **Provider adapters** | Python | `cc_dispatch` (Claude Task), `llm_client` (factory), `openrouter_client`, `research/client_302ai`, `tmdb_client`. **No LLM client may be imported by scoring/dispatch** (ANOMALY-001). |
| **Quality harness** | pytest + lefthook + Makefile | The **Stop gate**: `make test` (1575) + `make eval` (126). Pre-commit: ruff/pyright/gitleaks. Pre-push: full suite. |

## Data stores

> [!important] State durability ([[05-adr-registry|ADR-0001]])
> Every cross-boundary fact is written to disk with `pipeline.state.safe_write`
> (atomic tmp + fsync + rename). Nothing load-bearing lives only in agent context.

| Store | Contents |
|---|---|
| `data/*.jsonl` | `run_log`, `leaderboard`, `quota`, `axis_frequency` (anti-overfit), `goal_history`, `labels`, `cell_history`, `01_assets`…`05_critiques` phase outputs. |
| `runs/` | Per-run pipeline sidecars (`seed`, `research`, `draft_v0`, `challenge`, `amplification`, `genius`, `consistency`, `eval`, `lessons`) + `outputs/portfolio/` deliverables. |
| `.planning/state/` | `RESUME.md` (recovery), `PLAN_LEDGER.jsonl`, `STATE.md`, agent handoff contracts. |
| `pipeline/data/` | 894-film corpus (`films_corpus_enriched.jsonl`), `films_corpus_embeddings.npz` (894×384), compound-seed axis JSONs. |
| `frameworks/` | Read-only narrative doctrine (SDT spine, AJTBD, McKee/Polti grids) — never imported (ANOMALY-002). |
| `config/goal.json` | Learned `Goal` facet weights (refit from operator ratings). |

## Out of scope at C2

- The modules inside `pipeline/` / `crystallize/` → [[03-c3-components]]
- How a concept flows phase-by-phase → [[04-c4-code-paths]]

## Related
- [[_index|Architecture MOC]] · [[01-c1-system-context]] · [[03-c3-components]] · [[05-adr-registry]]
