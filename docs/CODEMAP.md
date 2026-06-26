# Anomaly Engine v4 — Codebase Map

## Directory Structure

```
29.Engine/
│
├── README.md                    ← Start here: quick overview
├── CLAUDE.md                    ← Hard rules (MUST/MUST NOT)
├── AGENTS.md                    ← Byte-equal mirror of CLAUDE.md
│
├── pipeline/                    ← Core orchestration & scoring
│   ├── __init__.py
│   ├── run_single_idea.py       ← Typer CLI entry point (main)
│   ├── single_idea.py           ← 10-phase orchestrator (main logic)
│   ├── loop_controller.py       ← Plateau detection + patch budgeting
│   ├── consistency.py           ← Cross-phase drift detector (pure Python)
│   ├── template_filter.py       ← Internal-ID stripper, section enforcer
│   ├── scoring.py               ← ALL numeric scores computed here (ADR-0002)
│   ├── audience_amplifier.py    ← 29-vector compound multiplier with synergy
│   ├── cc_dispatch.py           ← Task subagent fan-out (ADR-0007)
│   ├── quota.py                 ← Haiku/Sonnet weekly quota gating (ADR-0008)
│   ├── state.py                 ← Atomic disk writes (ADR-0001)
│   ├── openrouter_client.py     ← Direct API to OpenRouter
│   ├── key_manager.py           ← 3-key round-robin rotation (ADR-0003)
│   ├── metrics.py               ← Observability/logging
│   ├── data/
│   │   ├── amplification_vectors.json  ← 29 vectors with synergy rules
│   │   └── __init__.py
│   └── tests/                   ← Unit tests (pytest)
│       ├── test_loop_controller.py
│       ├── test_consistency.py
│       ├── test_scoring.py
│       ├── test_amplifier.py
│       ├── test_state.py
│       └── ...
│
├── frameworks/                  ← Knowledge base (read-only reference)
│   ├── data/
│   │   ├── protagonist_archetypes.json      (254 entries)
│   │   ├── dark_archetypes.json             (158 entries)
│   │   ├── ally_archetypes.json             (206 entries)
│   │   ├── conspiracy_engines.json          (2,057 entries)
│   │   ├── open_problems_science.json       (999 entries)
│   │   ├── cultural_moment_2026.json        (493 entries)
│   │   ├── reptile_triggers.json            (505 entries)
│   │   └── ... (~4.6M total data points)
│   └── README.md
│
├── .claude/                     ← Claude Code harness
│   ├── settings.json            ← Project config, hooks, permissions
│   ├── skills/
│   │   └── single-idea/
│   │       └── SKILL.md         ← /single-idea slash command skill
│   └── agents/
│       ├── concept-drafter.md       ← Phase 0 + 2 + L1/L3/L4 patch
│       ├── concept-researcher.md    ← Phase 1 (3x parallel)
│       ├── concept-challenger.md    ← Phase 3 (L1 loop)
│       ├── genius-auditor.md        ← Phase 5 (L3 loop)
│       ├── consistency-checker.md   ← Phase 6 (L4 loop)
│       └── concept-narrator.md      ← Phase 8 (L5 loop)
│
├── Inputs/                      ← Investor-facing templates (prompt cache)
│   ├── CONCEPT_TEMPLATE_V2.md   ← 4-section investor template
│   ├── STYLE_GUIDE.md           ← Banned terms, translation rules
│   ├── MASTER_BRIEF.md          ← Doctrine (prompt-cached)
│   ├── CHALLENGE_PROTOCOL.md    ← Adversarial P0/P1 interrogation
│   └── GeniusFilm/
│       └── GREATNESS_CHECKLIST.json ← C001-C007 kill-switches
│
├── data/                        ← Audit, state, output tracking
│   ├── 01_assets.jsonl          ← Seeded concepts
│   ├── 02_jtbd.jsonl
│   ├── 03_audience.jsonl
│   ├── 04_concepts.jsonl        ← Archive of all generated concepts
│   ├── 05_critiques.jsonl       ← Eval results
│   ├── cell_history.jsonl       ← Run history
│   ├── glossary_master.json     ← 1,200+ translation terms
│   ├── knowledge_base/
│   ├── themes/
│   │   ├── ai-knowledge-workers/
│   │   ├── climate-refugees-north/
│   │   └── ...
│   ├── audit/                   ← Per-run audit trails
│   ├── runs/                    ← Nightly batch output tracking
│   └── state/
│       └── ... (project state files)
│
├── runs/                        ← Generated concepts (main output)
│   └── 2026-05-12-163202-station-tolerance/
│       ├── seed.json            (internal: theme + 12 attrs)
│       ├── research.json        (genre saturation, comps, URLs)
│       ├── draft.v0.json        (internal: long-form draft)
│       ├── challenge.json       (adversarial P0/P1 results)
│       ├── amplification.json   (29-vector compound results)
│       ├── genius.json          (C001-C007 audit)
│       ├── consistency.json     (drift detection)
│       ├── eval.json            (Tier-1 + Tier-2 gates)
│       ├── lessons.json         (appended to global lessons.jsonl)
│       └── Station-Tolerance.md ← THE DELIVERABLE
│
├── docs/                        ← Documentation
│   ├── system_overview.html     ← Investor-grade visual guide (THIS)
│   ├── ARCHITECTURE.md          ← Technical design deep-dive
│   ├── CODEMAP.md               ← File structure & dependencies (THIS)
│   └── CONTRIBUTING.md
│
├── evals/                       ← Quality gate scripts
│   ├── test_no_internal_ids.py      ← ADR-0010: strip framework labels
│   ├── test_som_threshold.py
│   ├── test_citation_coverage.py    ← Gate 1
│   ├── test_math_integrity.py       ← Gate 2
│   └── ...
│
├── scripts/                     ← Utilities
│   ├── lint_imports.py          ← Enforce ADR-0002, ADR-0005
│   ├── check_gate_compliance.py
│   └── ...
│
├── Makefile                     ← Build targets
├── pyproject.toml               ← Python project config
├── .env.example                 ← Environment template
├── .gitignore
├── uv.lock                      ← Dependency lock file
├── conftest.py                  ← pytest config
└── tests/                       ← Integration tests
    ├── test_claude_md_compliance.py  ← CLAUDE.md rules enforcer
    ├── test_secret_leak.py
    ├── test_log_masking.py
    ├── test_settings_sandbox.py
    ├── hooks/
    │   ├── test_pretool_protect.sh   ← Protect critical files
    │   ├── test_bash_gate.sh          ← Block dangerous commands
    │   └── test_stop_verify.py
    └── ...
```

---

## Key File Roles

### Orchestration (Phase Control)
- **`run_single_idea.py`** — CLI entry point, argument parsing
- **`single_idea.py`** — Main orchestrator loop (Phase 0→9)
- **`cc_dispatch.py`** — Fan out to Claude Code agents
- **`loop_controller.py`** — Detect convergence, manage patch budgets

### Computation (Pure Python)
- **`scoring.py`** — ALL numeric scores (SOM, ROI, franchise score, etc.)
- **`consistency.py`** — Cross-phase drift detection
- **`audience_amplifier.py`** — 29-vector compound multiplier
- **`template_filter.py`** — Strip internal IDs, validate structure

### State & Durability
- **`state.py`** — Atomic writes, resumable execution
- **`quota.py`** — Track token usage against weekly caps
- **`key_manager.py`** — 3-key round-robin rotation

### Knowledge Base
- **`frameworks/data/*.json`** — Static dictionaries (~4.6M points)
  - No imports in production code (ADR-0005)
  - Loaded once at startup
  - Versioning via JSON swaps

### Testing & Compliance
- **`tests/test_claude_md_compliance.py`** — Validate CLAUDE.md rules
- **`evals/test_no_internal_ids.py`** — ADR-0010 enforcement
- **`scripts/lint_imports.py`** — ADR-0002, ADR-0005 enforcement

### Agent Definitions
- **`.claude/agents/*.md`** — LLM agent prompts
  - Concept-drafter (intake, drafting, patches)
  - Concept-researcher (Phase 1 web research)
  - Concept-challenger (adversarial review)
  - Genius-auditor (C001-C007 kill-switches)
  - Consistency-checker (drift detection)
  - Concept-narrator (final markdown)

---

## Data Flow (Phase-by-Phase)

```
INPUT (theme string)
    ↓
Phase 0: concept-drafter agent
    → seed.json (theme + 12 internal attrs)
    ↓ Gate 0: completeness ≥60%
    ↓
Phase 1: 3x concept-researcher agents (parallel)
    → research.json (genre, comps, audience URLs)
    ↓ Gate 1: all numeric claims sourced
    ↓
Phase 2: concept-drafter agent
    → draft.v0.json (4-section internal draft)
    ↓
Phase 3–8: LOOP SYSTEM (L1-L5)
    ├─ L1: concept-challenger (up to 3 patches)
    │  ├─ challenge.json (P0/P1 results)
    │  ↓ Gate: ≥70% pass rate
    ├─ L2: audience-amplifier (up to 5 iters OR plateau)
    │  ├─ amplification.json (29-vector results)
    │  ↓ Gate: SOM ≥$100M
    ├─ L3: genius-auditor (up to 3 patches)
    │  ├─ genius.json (C001-C007 results)
    │  ↓ Gate: ≥2/7 passed
    ├─ L4: consistency-checker (up to 3 patches)
    │  ├─ consistency.json (drift audit)
    │  ↓ Gate: drift ≤0.15
    └─ L5: concept-narrator (up to 2 redo rounds)
       ├─ {Title}.md (final investor markdown)
       ↓ Gate: zero internal-ID leaks
    ↓
Phase 9: Output & Lessons
    → lessons.json appended to global lessons.jsonl
    ↓
OUTPUT: {Title}.md (investor-facing deliverable)
```

---

## Critical Dependencies & ADRs

### ADR-0001: State Durability
- **Files:** `state.py`, `single_idea.py`
- **Rule:** All cross-boundary state written to disk before done
- **Implementation:** `state.safe_write()` for atomic writes
- **Test:** `tests/test_state.py::test_atomic_write_under_kill`

### ADR-0002: Pure Python Scoring
- **Files:** `scoring.py`
- **Rule:** All numeric scores computed here, never by LLM
- **Implementation:** Import nothing from `anthropic`, `openrouter_client`
- **Enforcement:** `scripts/lint_imports.py::ANOMALY-001`

### ADR-0005: Frameworks Read-Only
- **Files:** `frameworks/`, `pipeline/scoring.py`
- **Rule:** Never import from `frameworks/` in production code
- **Implementation:** Load JSON once at startup, cache in memory
- **Enforcement:** `scripts/lint_imports.py::ANOMALY-002`

### ADR-0007: Pure CC Dispatch
- **Files:** `cc_dispatch.py`
- **Rule:** All model calls route through this module
- **Implementation:** Task fan-out, no direct LLM imports
- **Enforcement:** `scripts/lint_imports.py::ANOMALY-001`

### ADR-0010: Output Filtering
- **Files:** `template_filter.py`, `evals/test_no_internal_ids.py`
- **Rule:** Strip all internal IDs before writing to `runs/`
- **Patterns Blocked:** Framework labels, internal codes, run IDs
- **Test:** `evals/test_no_internal_ids.py`

---

## Build & Test

### Make Targets
```bash
make single THEME="..."         # Run pipeline on one theme
make eval-single                # Evaluate last run
make test                       # Fast unit tests
make eval                       # Full eval suite
make filter-check               # Scan runs/ for internal-ID leaks
make lint                       # Linting + type checking
```

### Key Commands
```bash
uv run python -m pipeline.run_single_idea --theme "..." --mode standard
uv run pytest tests/ -v
uv run python scripts/lint_imports.py
```

---

## Scaling Considerations

### For 50–100 Concepts/Week
1. **Batch scheduling:** Cron job runs `make single THEME="..."` for 10–20 themes nightly
2. **Resumable state:** If interrupted, restart picks up mid-pipeline
3. **Cost predictability:** $4–18 per concept × 100 = $400–1,800/week
4. **Knowledge updates:** Swap `cultural_moment_2026.json` between runs, no code changes

### Performance Bottlenecks
- **Phase 1 research:** Parallel agents (market, comp, audience) — already optimized
- **Phase 8 narrator:** Uses Opus 4.7 (most expensive). Consider caching or pre-generation
- **L2 amplification loop:** 5 iterations max, usually converges in 2–3

### Cost Levers
- **Sonnet-only mode:** Strip Opus usage, accept lower positioning quality (~$4–6/concept)
- **Parallel batch:** Fan out 20 themes across 4 agents concurrently (~$80–120 total)
- **Knowledge pruning:** Use smaller dictionaries for early-stage scouting

---

## Common Workflows

### Adding a New Amplification Vector
1. Edit `pipeline/data/amplification_vectors.json`
2. Add entry with `id`, `name`, `category`, `base_multiplier`, `synergy_with`
3. Re-run pipeline (no code changes needed)
4. Verify SOM outcomes via `evals/test_som_threshold.py`

### Updating Cultural Moment Signals
1. Edit `frameworks/data/cultural_moment_2026.json`
2. Add/remove entries as zeitgeist evolves
3. Re-run pipeline (agents will use new signals)
4. Monitor for SOM/concept quality changes

### Patching Framework Definitions
1. Edit `frameworks/data/{archetype|trigger}.json`
2. Commit to `main`
3. Next pipeline run loads new definitions
4. A/B test: run same theme against old vs new framework

### Investigating a Failed Run
1. Check `runs/{timestamp}-{slug}/` directory
2. Read intermediate JSON files (seed → eval)
3. Check `runs/{timestamp}-{slug}/eval.json` for gate failures
4. Read agent decision logs in `challenge.json`, `amplification.json`, etc.
5. Resume or patch locally

---

## Maintenance Checklist

- [ ] Weekly: Update `cultural_moment_2026.json` with current trends
- [ ] Monthly: Audit `conspiracy_engines.json` for outdated patterns
- [ ] Quarterly: Review `frameworks/data/` for accuracy
- [ ] Per-release: Run `make lint && make test && make eval` before ship
- [ ] Per-batch: Check `runs/` for any leaked internal IDs before archiving

---

*Last updated: 2026-05-14*
*Anomaly Engine v4.0 — Single-Idea Pipeline*