# Anomaly Engine v4 — Codebase Reference Map

**Purpose:** This document maps the v4 single-idea pipeline architecture for Opus model-driven design improvements.

---

## 1. Pipeline Overview

```
PHASE 0: Seed Capture (Phase 0)
    ↓ [orchestrator writes seed.json]
    ↓
PHASE 1: Research (sonnet) — concept-researcher
    ↓ [reads seed.json, outputs research.json]
    ↓
PHASE 2: Draft (sonnet) — concept-drafter
    ↓ [reads seed + research, outputs draft_v0.json + {title}.md]
    ↓
    ├─→ LOOP L1: Challenge (3 max patches) [concept-challenger]
    │   ↓ outputs challenge.json
    │   ↓ [if failures: concept-drafter L1_PATCH mode]
    │
PHASE 4: Amplify (haiku) — audience-amplifier (L2 loop)
    ↓ [reads draft + research, applies 11 multiplier vectors]
    ↓ [plateau or 5-iter max; outputs amplification.json + {title}-AMPLIFIED.md]
    ↓
PHASE 5: Genius Audit (sonnet) — genius-auditor
    ↓ [kill-switch gates C006/C007; outputs genius.json]
    ↓
    ├─→ LOOP L3: Genius patches (3 max) [concept-drafter L3_PATCH mode]
    │
PHASE 6: Consistency Check (haiku) — consistency-checker
    ↓ [detect cross-sidecar drift; outputs consistency.json]
    ↓
    ├─→ LOOP L4: Consistency patches (3 max) [concept-drafter L4_PATCH mode]
    │
PHASE 7: Investor Narrator (sonnet) — concept-narrator
    ↓ [reads all prior phases + sonar-deep-research]
    ↓ [outputs {title}-NARRATOR.md + HTML investor deck]
    ↓
PHASE 8: Eval Gate (pure Python)
    ↓ [scoring.py + empirical_genius.py compute final scores]
    ↓ [evidence_gate.py validates URLs]
    ↓ [outputs eval.json]
    ↓
    ├─→ LOOP L5: Narrator redo (2 max) [concept-narrator re-run]
    │
PHASE 9: Lessons Capture
    ↓ [orchestrator writes lessons.json]
    ↓
    END ✓ (or HALT if unrecoverable)
```

**Loop architecture (ADR-0009):**
- **L1** (challenge): 3 patches max; concept-challenger → draft-patcher cycle
- **L2** (amplify): 5 iterations max OR plateau (Δ < 5% for 2 consecutive iters)
- **L3** (genius): 3 patches max; kill-switch failures trigger drafting
- **L4** (consistency): 3 patches max; drift detection → drafting
- **L5** (narrator): 2 rounds max; eval failures trigger narrator re-run

---

## 2. Entry Points

| Command | What It Runs | Key Flags |
|---------|-------------|-----------|
| `uv run python -m pipeline.run_single_idea --theme "..."` | Phase 0 + Phase 1 setup; creates runs/{run_id}/, writes seed.json, outputs JSON summary for /single-idea skill | `--run-id` (custom), `--resume` (restore interrupted run), `--use-moa` (Mixture-of-Experts seed generation: 3 biased seeders + pure-Python judge) |
| `uv run python -m pipeline.run_cc plan --phase X --run-id Y` | Slices JSONL input into dispatch manifest (one row per Task slice) | `--slice-size`, `--model-tier`, `--expected-tokens` |
| `uv run python -m pipeline.run_cc merge --phase X --run-id Y` | Merges per-Task JSONL outputs back into canonical phase JSONL | `--target-path` (output file) |
| `uv run python -m pipeline.run_cc record --phase X --run-id Y --slice-id N` | Records Task completion + quota burn | `--tokens-in`, `--tokens-out`, `--model-tier` |
| `uv run python -m pipeline.run_cc status --run-id Y` | Prints per-status row counts of manifest (used for progress tracking) | — |
| `make single` | User-facing alias; invokes /single-idea skill | `THEME=...` |
| `make eval-single` | Runs scoring + evidence_gate on most recent run | — |

---

## 3. Pipeline Modules (pipeline/*.py)

| File | Purpose | Key Functions | Inputs | Outputs |
|------|---------|----------------|--------|---------|
| **single_idea.py** | State machine orchestrator (10 phases, 5 loops); zero LLM calls | `SingleIdeaOrchestrator.__init__()`, `_restore_phase()`, `halt()`, `_mark_phase_complete()` | run_dir, theme | Phase tracking state |
| **run_single_idea.py** | CLI for Phase 0 init + state summary; seed.json writer | `main(--theme, --run-id, --resume, --use-moa)`, `_write_seed(use_moa=False)`, `_make_run_id()` | Theme string | runs/{run_id}/seed.json, JSON status |
| **run_cc.py** | Typer CLI for dispatch planning/merging/quota tracking (pure Python) | `plan()`, `merge()`, `status()`, `record()`, `quota()` | JSONL input_path, manifest_path | Manifest JSONL, per-Task output dirs |
| **cc_dispatch.py** | Dispatch manifest builder; slices JSONL into Task fan-out rows | `plan()`, `merge()`, `record_task_completion()`, `cost_estimate()`, `log_dispatch_event()` | input_path, slice_size, model_tier | `.planning/phase_dispatch/{run_id}/{phase}.jsonl` |
| **schema.py** | Pydantic v2 models for all phase outputs (5 models); total_score guard (ADR-0002) | `Phase1Assets`, `Phase2JTBD`, `Phase3Audience`, `Phase4Concept`, `Phase5Critique` + `_reject_llm_total_score()` | Incoming LLM JSON | Validated objects |
| **scoring.py** | Pure-Python numeric scoring (ONLY place scores are computed; ADR-0002) | `sdt_score()`, `ajtbd_score()`, `polti_tobias_coherence()`, `overall_score()` | Phase outputs, audience data, novelty metrics | scores dict with total_score, sdt, ajtbd, egi |
| **empirical_genius.py** | 5th scoring axis (novelty + emotional shape + premortem survival); kill-switch gates C006/C007 | `score_concept()`, `embedding_novelty()`, `_check_c006()`, `_check_c007()`, `premortem_survival()` | draft_v0.json, GREATNESS_CHECKLIST.json | egi_score [0..25], kill_switch verdict |
| **loop_controller.py** | Loop budget enforcement + plateau detection (pure Python; ADR-0009) | `plateau_reached(history, delta_threshold, window)`, `patch_budget(loop_id)` | Score history list, loop ID | bool (plateau?), int (max patches) |
| **consistency.py** | Cross-phase drift detection; checks canonical field consistency | `detect_drift(phase_paths)` | Dict of phase JSON paths | verdict (CONSISTENT/DRIFT), drift_fields, severity, suggested_resolutions |
| **template_filter.py** | Output sanitization; strips internal IDs + framework labels (ADR-0010) | `strip_internal_ids()`, `scan_for_internal_ids()`, `check_template_compliance()`, `parse_som()` | Markdown text | Sanitized text, compliance report |
| **evidence_gate.py** | URL validation via HTTP HEAD requests; allow-lists legitimate bot-blocks | `validate_urls()` (CLI main) | research.json file path | evidence_gate.json with per-URL verdicts, exit code |
| **state.py** | State durability interface (ADR-0001); atomic writes, append-only JSONL (P0 stubs → P3 implementation) | `safe_write()`, `append_jsonl()`, `write_handoff()`, `write_checkpoint()` | File paths, data objects | Atomically-written disk files |
| **quota.py** | Subscription-quota tracking; weekly Opus/Sonnet/Haiku token budgets (ADR-0008) | `record()`, `consumed_this_week()`, `remaining_fraction()`, `gate()`, `print_status()` | Model tier, token counts, run_id | quota.jsonl, status string |
| **seed_engine.py** | 25-axis deterministic combinatorial sampler (deprecated for v4 but kept for Path C) | `AxisRow`, `SeedPackage`, `sample_seed()` | seed_int, seed CSVs | SeedPackage (frozen dataclass) |
| **seed_moa.py** | Mixture-of-Experts seed generator: runs 3 biased seeders (conspiracy_mind, open_science_mind, reptile_fear_mind) in parallel threads, selects best by SOM floor + genius_score | `generate(themes, problems, max_attempts)`, `_run_seeder()` | Theme list, problem list | MoASeedResult (selected, candidates, judge_rationale, seeder_names) |
| **lessons_loader.py** | Scans runs/ for lessons.json files and returns the most-recent unique key_failures strings for use as Phase 0 negative constraints | `load_failures(run_root, max_items=5)`, `_find_lesson_files()`, `_read_failures()` | runs/ directory | list[str] of failure summaries (newest-first, deduplicated) |
| **micro_amplify.py** | Single-shot Haiku micro-amplification applied after phases 2/3/5/6; enriches a sidecar JSON with additional audience or commercial details | `apply(sidecar, phase_name, enabled)` | Phase sidecar dict | Updated sidecar dict with micro_amplification key |
| **zeitgeist_probe.py** | Pre-seed sonar-pro cultural moment evidence fetcher with 24h cache; runs before CompoundSeedEngine to inject current macro signals | `probe(theme)`, `_cached_fetch()` | Theme string | ZeitgeistProbeResult (signals, cached_at, source_urls) |
| **seed_picker.py** | Selects best seed from batch (legacy; unclear current role in v4) | `pick_best_seed()` | Scored seeds | Selected seed ID |
| **audience_amplifier.py** | TAM amplification loop (L2); applies 11 multiplier vectors iteratively | `run_amplification_loop()`, `apply_vector()` | draft_v0.json, amplification_vectors.json, sonar research | amplification.json with SOM/SAM funnel trail |
| **compound_seed.py** | Multi-variable compound seed generator (25+ axes). Generates the intersection premise via Haiku. Supports force_* axis flags (force_conspiracy, force_reptile, force_open_problem, force_cultural_moment, force_dark_archetype). Appends prior-run failure modes from lessons_loader as AVOID constraints. | `CompoundSeedEngine.generate(force_*)`, `_sample_variables()`, `_generate_intersection_prompt()`, `_call_haiku_for_premise()` | Theme, conflict axes | seed.json with enriched premise |
| **export_html.py** | Markdown → HTML converter for investor deck (cinematic dark theme). Extracts hero grid metrics (TAM/SAM/SOM/why_sentence) from NARRATOR.md dynamically. Supports --organize flag to move non-HTML artifacts to _trail/ after conversion. | `convert(md_path, organize=False)`, `_extract_hero_data()`, `_hero_section()`, `reorganize_run(run_dir)` | Markdown concept file, slide specs | Single-file HTML presenter |
| **index_html.py** | Batch run index HTML generator (lists all runs with metadata) | `generate_index_html()` | runs/ directory | index.html |
| **commercial_prescreen.py** | Commercial viability heuristic (SOM floor $100M, audience floor 50M) | `prescreen_commercial()` | Amplification data | pass/fail + reason |
| **plan_compliance.py** | Pre-task / post-task verification against .planning/PLAN_LEDGER.jsonl (unclear role in v4) | `pretask()`, `posttask()` | Task ID, plan ledger | Compliance pass/fail |
| **openrouter_client.py** | HTTP shim to OpenRouter (perplexity/sonar-pro-search, sonar-deep-research); replaced by cc_dispatch in Phase 1+ | `query()`, `cost_estimate()` | Query string, model, max_tokens | JSON response |
| **key_manager.py** | API key rotation + masking (masks prefixes to first 8 chars in logs) | `mask_key()`, `rotate_key_if_expired()` | API key | Masked key, rotation status |
| **metrics.py** | Metrics collection (unclear current use; may be telemetry) | `record_metric()`, `emit_summary()` | Metric name, value | metrics.jsonl |
| **bridge.py** | Unclear; possibly legacy bridge to old run.py or test harness | — | — | — |
| **kb.py** | Knowledge base interface (unclear current use) | — | — | — |

---

## 4. Agent Roster (.claude/agents/*.md)

| Agent | Model | Phase | Reads | Writes | Key Constraints |
|-------|-------|-------|-------|--------|-----------------|
| **concept-researcher** | sonnet | 1 (research) | seed.json | research.json | Must request 2025-2026 data by default; flag sources older than 12 months with [LAGGED — published YYYY]; Step C requires CAGR trend projection (Trailing YYYY: NM \| CAGR: +X% \| Projected 2026: NM); cite every claim with deep-path URL |
| **concept-drafter** | sonnet | 2, L1, L3, L4 (draft + patches) | seed.json, research.json, + fail sidecars on patch | draft_v0.json, {title}.md | Follow CONCEPT_TEMPLATE_V2.md exactly; strip framework labels; no SOM inflation |
| **concept-challenger** | sonnet | L1 (challenge loop) | draft_v0.json | challenge.json | 11 P0 kill-switch checks; return failures only |
| **audience-amplifier** | haiku | 4 (amplify loop) | draft_v0.json, amplification_vectors.json, sonar market data | amplification.json, {title}-AMPLIFIED.md | Apply 11 vectors iteratively; detect plateau (Δ < 5%); cap at 5 iters |
| **genius-auditor** | sonnet | 5 (genius audit) | draft_v0.json, GREATNESS_CHECKLIST.json | genius.json | Kill-switch C006/C007 gates; trigger L3 patches if failures |
| **consistency-checker** | haiku | 6 (consistency) | draft_v0.json, challenge.json, genius.json, amplification.json | consistency.json | Detect drift in protagonist_name, genre, theme; suggest resolutions |
| **concept-narrator** | sonnet | 7 (investor_narrator) | {title}.md, challenge.json, research.json, {title}-AMPLIFIED.md | {title}-NARRATOR.md, {title}-INVESTOR.html | Call sonar-deep-research for TAM; Investment Summary Card required; no framework labels |

---

## 5. Data Schema (Sidecars)

| File (in runs/{run_id}/) | Produced By | Consumed By | Key Fields |
|--------------------------|-------------|------------|------------|
| **seed.json** | Phase 0 (orchestrator) | research, drafter | theme, target_format, conflict_axes, hidden_attributes; when use_moa=True: hidden_attributes.moa_candidates (seeder names), hidden_attributes.moa_judge_rationale |
| **research.json** | concept-researcher (Phase 1) | drafter, amplifier, narrator | audience_size, comp_revenue, cultural_moment, genre_saturation, sources (citations) |
| **draft_v0.json** | concept-drafter (Phase 2, patches) | challenger, amplifier, genius-auditor, consistency-checker, narrator | logline, tagline, sections (Market, Concept, Story, Characters), sdt_primary/secondary, ajtbd_claims |
| **challenge.json** | concept-challenger (L1) | drafter (L1_patch mode), consistency-checker, narrator | failures (list), verdict (PASS/FAIL), conditions (remediation) |
| **amplification.json** | audience-amplifier (Phase 4) | genius-auditor, consistency-checker, narrator | tam_base, som_base, vectors_applied (list), final_som, final_funnel (TAM/SAM/SOM trail), plateau_iter |
| **genius.json** | genius-auditor (Phase 5) | consistency-checker | egi_score, c006_pass, c007_pass, embedding_novelty, emotional_shape, premortem_survival, kill_switch_verdict |
| **consistency.json** | consistency-checker (Phase 6) | drafter (L4_patch mode), narrator | drift_fields (list), severity, suggested_resolutions |
| **eval.json** | scoring.py + empirical_genius.py (Phase 8) | narrator (if failures trigger L5), final report | sdt_score, ajtbd_score, egi_score, total_score, passes_85_floor, polti_tobias_coherent, url_validity_pct |
| **lessons.json** | Phase 9 (orchestrator) | compound_seed Phase 0 (negative prompt constraints via lessons_loader), next run's research agent | lessons_found (list), anti_patterns (list) |

**Investor-facing outputs (Markdown + HTML):**
- **{title}.md** — Concept document (Section 1–4); follows TEMPLATE_V2.md exactly; no framework labels
- **{title}-CHALLENGE.md** — Challenge verdict + remediation
- **{title}-AMPLIFIED.md** — Amplification trail (SOM funnel breakdown)
- **{title}-NARRATOR.md** — Investor pitch (Investment Summary Card, story, commercial model, risks)
- **{title}-INVESTOR.html** — Single-file HTML presenter (cinematic dark theme)

---

## 6. Amplification Vectors

**11 base multiplier vectors across 5 categories:**

| Category | Vectors | Highest Multiplier | Total Vectors | Notes |
|----------|---------|-------------------|----------------|-------|
| **A_format** | A1 (film→series 2x), A2 (standalone→franchise 3x), A3 (domestic→global 1.8x), A4 (single→multi-platform 1.4x) | A2: 3.0x | 4 | Format pivots; A2 has strongest synergies |
| **B_protagonist** | B1 (female lead in thriller 1.8x), B2 (A-list attachment 2.5x), B3 (solo→found family 1.4x) | B2: 2.5x | 3 | Casting & ensemble architecture |
| **C_narrative** | C1 (genre hybrid 1.4x), C2 (niche→universal stakes 1.6x), C3 (reactive→active protagonist 1.3x), C4 (fiction→true-events 1.5x) | C2: 1.6x | 4 | Narrative depth; C2 (universal stakes) has strong synergies |
| **D_timing** | D1 (generic→cultural moment 1.3x), D2 (low→high divisiveness 1.4x), D3 (domestic→universal setting 1.5x) | D3: 1.5x | 3 | Market timing + cultural resonance |
| **E_reach** | E1 (single→3-funnel audience 2.5x), E2 (passive→active community 1.5x) | E1: 2.5x | 2 | Audience architecture; E1 has strongest synergies (2.8x with A1) |
| **S_synergy** | S1 (female lead + universal stakes 2.8x), S2–S5 (documented cross-vector boost) | S1: 2.8x | 5+ | Cross-vector multiplicative effects |

**Amplifier rules:**
- Max L2 budget: 5 iterations or plateau (Δ < 5% for 2 consecutive score improvements)
- Vectors chosen by audience-amplifier (haiku) based on draft_v0 content
- Each application updates SOM estimate; funnel trail logged in amplification.json
- Synergies documented per vector (e.g., A2 + B3 = 3.5x boost)
- micro_amplify runs after each of phases 2/3/5/6; enriches the sidecar with additional audience detail without re-invoking the full amplifier loop

---

## 7. Quality Gates

| Gate | File | What It Blocks | Pass Condition |
|------|------|----------------|----------------|
| **Phase 0 (seed)** | single_idea.py | Invalid theme or empty run_dir | seed.json exists, theme ≠ empty |
| **L1/Phase 2 (draft)** | template_filter.py | Internal IDs, framework labels, non-compliant sections | No banned terms, all H1–H4 present, SOM ∈ [$100M, $1B] |
| **L1 (challenge)** | schema.py + loop_controller.py | Incomplete adversarial review | ≥11 kill-switch checks documented |
| **Phase 4 (amplify) plateau** | loop_controller.py | Runaway scoring | Δ < 5% for 2 iters OR 5 iters max |
| **Phase 5 (genius)** | empirical_genius.py | Kill-switch failures C006/C007 | c006_pass ∧ c007_pass = True |
| **Phase 6 (consistency)** | consistency.py | Cross-sidecar drift | drift_fields = [] OR all resolutions applied |
| **Phase 8 (eval)** | scoring.py | Score integrity | sdt_score ∈ [0..70], ajtbd_score ∈ [0..30], total ≥ 85 for pass |
| **URL evidence** | evidence_gate.py | Dead links | ≥90% of cited URLs return 2xx or allow-listed 401/403 |
| **L5 (narrator)** | concept-narrator task | Investment Summary Card missing | Card present with TAM/SAM/SOM, comps, ask |
| **Output filter** | template_filter.py | Framework labels leak to investor | Zero occurrences of banned terms in runs/*.md |

---

## 8. Known Constraints & Hard Rules

**Seed Data Files (frameworks/data/):**

| File | Rows | Description |
|------|------|-------------|
| conspiracy_engines.json | 150 | Conspiracy narrative lenses (CC_001–CC_150) |
| reptile_triggers.json | 40 | Primal fear triggers (RT_001–RT_040) |
| open_problems_science.json | 80 | Unsolved science problems (OP_001–OP_080) |
| cultural_moment_2026.json | 30 | Current cultural tension moments (CM_001–CM_030) |
| dark_archetypes.json | (existing) | Dark character archetypes |

**ADR-0001 (State Durability):**
- All cross-boundary state written to disk via `pipeline.state.safe_write()` before declaring done
- Per-phase outputs appended to `data/0X_<phase>.jsonl`
- Context-only state is forbidden

**ADR-0002 (Scoring):**
- Scoring only in `pipeline/scoring.py` — never in LLM prompts
- LLMs MUST NOT populate `total_score` field; raises ValueError if attempted
- Pydantic `model_copy()` (post-validation bypass) used to set scores after validation

**ADR-0003 (Key Rotation + Secrets):**
- API keys masked to first 8 chars in logs (enforced by key_manager.py)
- Keys stored only in .env (gitignored)
- Gitleaks runs before every `git push`

**ADR-0004 (Canonical Data):**
- `synthesis_brief.canonical_data` (Phase 6 output) is immutable downstream
- Downstream agents MUST consult canonical_data first; never pull from upstream files

**ADR-0005 (Frameworks Read-Only):**
- No imports from `frameworks/` in Python modules (enforced by ANOMALY-002 lint)
- Scoring formulas cite their framework source via comment

**ADR-0006 (Forge Promotion):**
- Default Phase 4 to Sonnet 4.6; promote to Opus only if quality_pass_floor met

**ADR-0007 / ADR-0008 (Pure-CC Dispatch):**
- All v4 model calls routed through `pipeline/cc_dispatch.py` (manifest-based Task fan-out)
- Opus weekly quota gated via `pipeline.quota.gate()` (ADR-0008)
- Task dispatch quota recorded in `data/quota.jsonl`

**ADR-0009 (Loop Budgets):**
- L1 (challenge): 3 patches max before REJECT_FINAL
- L2 (amplify): 5 iterations OR plateau (Δ < 5% for 2 consecutive iters)
- L3 (genius): 3 patches max
- L4 (consistency): 3 patches max
- L5 (narrator): 2 rounds max

**ADR-0010 (Output Filter):**
- `pipeline.template_filter.strip_internal_ids()` applied before writing runs/*.md
- Banned terms: TRIZ, JTBD, Booker, McKee, Boden, Csikszentmihalyi, Reagan, Pearson, Egri, Polti, Haidt, Mednick, Wundt, Simonton, Stanton
- Investor files named after film title slug (not iter-N or run-IDs)

**Sandbox + Config Protection:**
- MUST NOT edit `pyproject.toml`, `lefthook.yml`, `.claude/settings.json`, `Makefile`, `uv.lock` from agent context
- MUST NOT run shell commands: `curl`, `wget`, `sudo`, `chmod 777`, destructive `rm`
- MUST NOT read `.env*` post-Phase 0

**ONE STAGE per session (HARN-13):**
- Each Claude Code session = one pipeline phase
- Subagents fan-out for read-only work only; no cross-stage boundary crossing in single session

---

## 9. Output Artifacts

**Per run (runs/{run_id}/):**
- 9 JSON sidecars (seed, research, draft_v0, challenge, amplification, genius, consistency, eval, lessons)
- 4 Markdown concept files ({title}.md, -CHALLENGE.md, -AMPLIFIED.md, -NARRATOR.md)
- 1 HTML investor deck ({title}-INVESTOR.html)

**Batch artifacts:**
- `.planning/phase_dispatch/{run_id}/{phase}.jsonl` — dispatch manifests (one row per Task slice)
- `.planning/state/RESUME.md` — recovery entry point (mtime must > latest data/run_log.jsonl event)
- `.planning/state/PLAN_LEDGER.jsonl` — plan compliance log (pre/post-task checkpoints)
- `.planning/state/handoffs/*_to_<agent>_*.json` — inter-agent context contracts
- `data/quota.jsonl` — token burn log (append-only, ADR-0001)
- `data/run_log.jsonl` — all phase events + exit codes (append-only)
- `data/0X_<phase>.jsonl` — phase-specific append-only JSONL (archive of all per-phase outputs)

**Final deliverable for investor:**
- runs/{run_id}/{title}-INVESTOR.html (5-minute read; Investment Summary Card → story → commercial → risks)
- runs/{run_id}/{title}.md (full concept template for feedback/iteration)

---

## 10. Test Coverage

| Path | Purpose |
|------|---------|
| `tests/test_claude_md_compliance.py` | CLAUDE.md rule enforcement: recovery protocol, one-stage-per-session, every MUST has enforcer |
| `tests/test_state.py` | Atomic write (`safe_write`) survival under kill-9; JSONL append idempotence |
| `tests/test_loop_controller.py` | Plateau detection (Δ threshold, window); patch budget lookups |
| `tests/test_plan_compliance.py` | Pre-task / post-task ledger sync; stale-resume detection |
| `tests/test_quota.py` | Token burn recording; weekly ISO boundary detection |
| `tests/test_secret_leak.py` | Gitleaks detection; no API keys in source (outside .env) |
| `tests/hooks/test_bash_gate.sh` | Forbidden commands blocked; no `--force`, `--no-verify` |
| `evals/test_no_internal_ids.py` | Framework label filter (ADR-0010); investor markdown cleanliness |
| `evals/test_resume.py` | Full kill-9 recovery path against live pipeline |
| `tests/test_run_single_idea.py` | _write_seed() with use_moa=False/True; MoA result merging; fallback when seed_moa unavailable |
| `tests/test_lessons_loader.py` | load_failures() with empty dir, missing files, malformed JSON, _trail/ location, max_items cap, deduplication |
| `tests/test_export_html_hero.py` | Hero grid: why_sentence extraction, dynamic vs. fallback rendering, reorganize_run idempotence |

---

## 11. Key Dependencies

- **Pydantic v2** — schema validation (schema.py)
- **httpx** — HTTP client for evidence_gate.py
- **sentence-transformers** — embedding novelty (empirical_genius.py; graceful degradation if missing)
- **Typer** — CLI framework (run_single_idea.py, run_cc.py)
- **PyYAML** — handoff contract parsing (state.py)
- **Rich** — colored console output (run_cc.py)

**Optional:**
- **OpenRouter client** — sonar-pro-search, sonar-deep-research (fallback WebSearch if unavailable)
- **Anthropic SDK** — not imported in pipeline/ (routed via cc_dispatch Task fan-out instead)

---

## 12. Known Unknowns / Unclear

- **bridge.py** — Purpose unclear; possibly legacy compatibility or test harness
- **kb.py** — Knowledge base interface; current use unclear
- **metrics.py** — Telemetry collection; consumer unclear
- **seed_picker.py** — Seed selection logic; role in v4 unclear (seed_engine.py for Path C only)
- **plan_compliance.py** — Pre/post-task verification; role in v4 vs. legacy PLAN.md unclear
- **index_html.py** — Batch run index; consumer unclear

