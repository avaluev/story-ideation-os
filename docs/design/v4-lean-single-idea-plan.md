# Plan — Anomaly Engine v4 "Lean Single-Idea" Pipeline
  
 Context

 The user has drained Opus quota and needs a SONNET/HAIKU-ONLY pipeline that produces one outstanding investor-grade film concept per run, not batches. Three previous output modes (batch/, runs/, out/concepts/) all leak internal IDs, framework
 labels (TRIZ/JTBD/Booker/McKee), and pipeline metadata into the final markdown — investor-confusing and Russian-translation-hostile. The 29.Engine v3.0 harness is architecturally sound (atomic state, quota gating, 8 ADRs, scoring isolation,
 29-vector amplification engine, plan-compliance hooks) and must be preserved and built on, not rewritten.

 The redesign:
 - Reorganizes orchestration into 10 atomic phases (4 Sonnet, 6 Haiku, deterministic Python in the seams)
 - Embeds amplification + challenge + genius + consistency as recursive loops with plateau detection (capped at 3 patch rounds + 5 amplification iterations per ADR-0009)
 - Introduces a hard template_filter that strips all internal IDs / framework names / iteration metadata before any file reaches the investor surface
 - Enforces a NEW investor template (4 main sections per the user spec) and the $100M SOM revenue threshold as a gate, not a target
 - All 12 attribute fields (Arc Shape, Booker Plot, McKee, Boden, Csikszentmihalyi, etc.) live as hidden sidecar state and shape narrator prose silently — never named in the final .md
 - Final file named after the film title (Station-Tolerance.md), not iter-N.md

 Intended outcome: a sustained Sonnet/Haiku pipeline that outperforms the prior Opus runs by infrastructure leverage (caching, recursive loops, deterministic Python in the math seams) rather than model quality — Pareto-optimal cost/quality,
 ready to execute as ~80 atomic steps in subsequent sessions.

 ---
 Target Architecture (10 phases, model + loops)

                     seed (user theme + 12 hidden attributes)
                               │
    ┌──────────────────────────┼──────────────────────────┐
    │                          ▼                          │
 P0  seed_capture        [HAIKU]      seed.json           │
 P1  research            [SONNET·web] research.json       │  prompt-cache
 P2  draft_v0            [SONNET]     draft.v0.md         │  MASTER_BRIEF +
                           │ ↺                            │  CONCEPT_TEMPLATE_V2
 P3  challenge           [SONNET·thinking] challenge.json │  + STYLE_GUIDE
                           │ ↻ patch ≤3                   │
 P4  amplify             [HAIKU+Py]  amplification.json   │
                           │ ↺ ≤5  (plateau on TAM/SAM/SOM)
 P5  genius_audit        [HAIKU]    genius.json           │
                           │ ↻ patch ≤3 (kill-switch)     │
 P6  consistency_check   [HAIKU]    consistency.json      │
                           │ ↻ patch ≤3 (drift)           │
 P7  investor_narrator   [SONNET·thinking] <Title>.md     │
 P8  eval_gate           [HAIKU+Py] eval.json             │
                           │ ↻ narrator redo ≤2 (ID leak / SOM<100M / template)
 P9  lessons_capture     [HAIKU]    lessons.jsonl (global)
                               │
                               ▼
                   runs/{ts}-{slug}/<Title>.md   (only file shared with investors)

 Per ADR-0007/0008 every model call routes through pipeline/cc_dispatch.py and records into pipeline/quota.py. Per ADR-0001/0002 all state is on disk, all numeric scoring (SOM, plateau delta, drift score) is pure Python in pipeline/scoring.py —
  LLMs never compute numbers.

 ---
 Phase Specifications

 Phase 0 — Seed Capture (Haiku, ~2k tok)

 - Reads: user theme + optional binary tension cell from Inputs/SocraticAMA/research/02_conflict_ontology.md
 - Writes: runs/{ts}-{slug}/seed.json — {theme, binary_tension_id, hidden_attrs:{arc_shape,booker,mckee,emotional_weight,budget_tier,format_justif,boden,flow,timing_risk,retro_fallacy_risk,cultural_specificity,moral_wager}, target_format,
 target_revenue_band}
 - Hidden attrs are internal state, never exposed to the final doc.
 - Reuses: pipeline/seed_picker.py:pick_seed for weighted sampling against macro-signal resonance

 Phase 1 — Research (Sonnet + WebSearch/WebFetch, ~25k tok)

 - Agent: existing .claude/agents/concept-researcher.md (already Sonnet 4.6)
 - Reads: Inputs/RESEARCH_PROTOCOL.md (prompt-cached), Inputs/SocraticAMA/research/{05_market_validation_sources.md, 07_macro_signal_sources.md}
 - Writes: runs/{ts}-{slug}/research.json — {genre_saturation:[...], cultural_moment:[...,verdict:VERIFIED|PARTIAL|FAILED], audience_claims:[{stat,year,url}], comp_films:[{title,year,box_office_ww,url}], status}
 - Gate: ≥3 HTTPS URLs with years for audience, ≥1 cited data point for "Why Now", ≥1 named comp with box office

 Phase 2 — Draft v0 (Sonnet, ~20k tok)

 - NEW Agent: .claude/agents/concept-drafter.md (Sonnet, prompt-cached MASTER_BRIEF)
 - Reads: seed.json + research.json + Inputs/MASTER_BRIEF.md + Inputs/INTELLECTUAL_FRAMEWORK.md
 - Writes: runs/{ts}-{slug}/draft.v0.md — internal-grade long-form draft. Framework labels ALLOWED here (this file is sidecar, never exposed).
 - The 12 hidden attrs from seed.json shape the draft's structure (Booker beat set, Reagan arc inflection points, etc.) but the file is purely internal.

 Phase 3 — Adversarial Challenge (Sonnet + extended thinking, ~15k tok)

 - Agent: existing .claude/agents/concept-challenger.md
 - Reads: Inputs/CHALLENGE_PROTOCOL.md, all phase files so far
 - Writes: runs/{ts}-{slug}/challenge.json — {p0_kill_switches:[{q_id,verdict,evidence}], p1_strategic_gaps:[...], suggested_patches:[...], verdict: REJECT|REWORK|PASS}
 - Loop L1 (challenge ↔ draft): if any P0 fails → invoke concept-drafter with suggested_patches → re-challenge → max 3 rounds. After 3 fails: write verdict=REJECT_FINAL and halt.

 Phase 4 — Audience/Revenue Amplification (Haiku + Python, ~3k tok × N)

 - Reuses: pipeline/audience_amplifier.py + pipeline/data/amplification_vectors.json (29 vectors, 7 synergies — all existing)
 - Reuses: pipeline/commercial_prescreen.py for initial PASS/FAIL gate
 - NEW: pipeline/loop_controller.py:run_amplification_loop(baseline_som) — iterates Haiku to select next-best vector + Python to compute new TAM/SAM/SOM after applying it
 - Writes: runs/{ts}-{slug}/amplification.json — {iter_0:{tam,sam,som,vectors_applied:[]}, iter_1:..., ..., iter_N:..., plateau_at:N, final_som, final_band, decision_trail}
 - Loop L2 termination: stops when (som_n - som_{n-1}) / som_{n-1} < 0.05 for two consecutive iters OR som ≥ $100M AND stable OR n == 5
 - If final_som < $100M → flag concept-drafter with vector-driven patches (e.g., genre hybrid, female lead, IP scaffold) and re-enter Phase 2 once. After that re-entry, gate is HARD.

 Phase 5 — Genius Audit (Haiku, ~5k tok)

 - NEW Agent: .claude/agents/genius-auditor.md (Haiku — checklist work, not deep reasoning)
 - Reads: Inputs/GeniusFilm/GREATNESS_CHECKLIST.json + all phase files
 - Writes: runs/{ts}-{slug}/genius.json — {c001_expert_surprise:{score,evidence}, c002_goldilocks:..., ..., c007_compression:..., kill_switches_tripped:[], overall:0-100}
 - Loop L3: if any kill-switch tripped → invoke concept-drafter with audit feedback → re-audit. Max 3 rounds.

 Phase 6 — Cross-Phase Consistency (Haiku, ~8k tok)

 - NEW Agent: .claude/agents/consistency-checker.md
 - NEW Code: pipeline/consistency.py:detect_drift(phase_outputs) — Python diff of protagonist name, genre, comp set, audience size, format across all 6 prior sidecars. Reports drift > 5% on canonical fields.
 - Writes: runs/{ts}-{slug}/consistency.json — {drift_fields:[], severity, suggested_resolutions, verdict:CONSISTENT|DRIFT}
 - Loop L4: if DRIFT → invoke concept-drafter with reconciliation prompt. Max 3 rounds.

 Phase 7 — Investor Narrator (Sonnet + extended thinking, ~25k tok)

 - Agent: existing .claude/agents/concept-narrator.md (Sonnet 4.6 — modify to point at V2 template + STYLE_GUIDE)
 - Reads: ALL sidecars (research, draft.v0, challenge, amplification, genius, consistency) + Inputs/CONCEPT_TEMPLATE_V2.md (NEW) + Inputs/STYLE_GUIDE.md (NEW) — both prompt-cached
 - Writes: runs/{ts}-{slug}/<Film-Title>.md — investor-facing, strict 4-section template, no IDs, no framework names, translation-friendly
 - The narrator's job: TRANSLATE hidden framework attrs into investor prose (e.g., Booker=Voyage and Return → Story section that embodies outbound→ordeal→return without naming it)

 Phase 8 — Eval Gate (Haiku + Python, ~5k tok)

 - NEW: evals/test_no_internal_ids.py (regex scan for (?:Cell-ID:|Per L\d+|L\d+\b|iter-\d+|BT-\d+|PS-\d+|TRIZ|JTBD\b|Booker|McKee|Boden|Csikszentmihalyi|Reagan|Pearson|Egri|Polti|Haidt|Mednick|Wundt|Simonton|Stanton|SIT Operator|Conceptual
 Blend|Macro Resonance Weight|Anti-slop|ten-school|Lessons consulted|Working title))
 - NEW: evals/test_template_compliance.py (4 H1 sections present: Title, Market & Audience, Concept, Story, Characters; mandatory H2 children all present per V2 template)
 - NEW: evals/test_som_threshold.py (parses SOM line; fails if < $100M)
 - NEW: evals/test_translation_friendly.py (Flesch-Kincaid grade ≤ 12; flags compound clauses > 30 words; no idioms from a small idiom blocklist)
 - REUSES: evals/test_anti_slop.py, evals/test_audience.py, evals/test_citations.py, evals/test_research_verified.py, evals/test_challenge_passed.py
 - Writes: runs/{ts}-{slug}/eval.json — pass/fail per check, with specific line offenders
 - Loop L5: any FAIL → narrator redo with explicit "fix these lines" prompt → re-eval. Max 2 rounds. After: halt with eval.failure_summary.

 Phase 9 — Lessons Capture (Haiku, ~3k tok)

 - Writes: append to global lessons/lessons.jsonl — {run_id, diff_signal, what_worked, what_failed} — used by FUTURE runs (seeded into Phase 2 drafter context), never inline-referenced in any investor doc.

 ---
 File Inventory

 KEEP (foundation — battle-tested)

 - pipeline/state.py — atomic disk writes (ADR-0001)
 - pipeline/scoring.py — pure-Python scoring (ADR-0002)
 - pipeline/quota.py — Haiku/Sonnet weekly cap gating (ADR-0008)
 - pipeline/cc_dispatch.py — Task subagent fan-out (ADR-0007)
 - pipeline/plan_compliance.py — pre/post hooks
 - pipeline/audience_amplifier.py — 29-vector compound multiplier
 - pipeline/commercial_prescreen.py — binary-tension PASS/FAIL gate
 - pipeline/data/amplification_vectors.json — vector registry
 - pipeline/seed_picker.py — macro-signal-weighted sampling
 - Inputs/MASTER_BRIEF.md, Inputs/CONCEPT_TEMPLATE.md, Inputs/RESEARCH_PROTOCOL.md, Inputs/CHALLENGE_PROTOCOL.md, Inputs/INTELLECTUAL_FRAMEWORK.md
 - Inputs/Principles/*, Inputs/SocraticAMA/research/*, Inputs/GeniusFilm/* (all prompt-cached references)
 - .claude/agents/concept-researcher.md, concept-challenger.md, audience-amplifier.md, concept-narrator.md (modify narrator for V2)
 - All ADRs 0001-0008
 - evals/test_anti_slop.py, test_audience.py, test_citations.py, test_research_verified.py, test_challenge_passed.py, test_resume.py, test_score_floor.py

 NEW (lean redesign — to create)

 ┌────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────┬─────────────┐
 │                      Path                      │                           Purpose                            │ Lines (est) │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ pipeline/single_idea.py                        │ 10-phase orchestrator, resumable                             │ ~250        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ pipeline/loop_controller.py                    │ plateau/cap logic for L1–L5                                  │ ~150        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ pipeline/consistency.py                        │ cross-phase drift detector (pure Python)                     │ ~120        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ pipeline/template_filter.py                    │ regex strip + section rewriter (pure Python)                 │ ~180        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ Inputs/CONCEPT_TEMPLATE_V2.md                  │ the user's 4-section investor template                       │ ~120        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ Inputs/STYLE_GUIDE.md                          │ banned-term list, Russian-translation rules, ID-hiding rules │ ~100        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ .claude/agents/concept-drafter.md              │ Sonnet draft.v0 producer                                     │ ~80         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ .claude/agents/genius-auditor.md               │ Haiku C001-C007 scorer                                       │ ~60         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ .claude/agents/consistency-checker.md          │ Haiku drift inspector                                        │ ~60         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ .claude/skills/single-idea/SKILL.md            │ single-shot orchestrator skill (replaces big-idea-batch)     │ ~150        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ tests/test_single_idea_orchestrator.py         │ end-to-end mock                                              │ ~200        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ tests/test_loop_controller.py                  │ plateau math + cap enforcement                               │ ~120        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ tests/test_consistency.py                      │ drift detection                                              │ ~80         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ tests/test_template_filter.py                  │ regex + section pass                                         │ ~150        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ evals/test_no_internal_ids.py                  │ regex scan investor .md                                      │ ~80         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ evals/test_template_compliance.py              │ V2 section structure                                         │ ~100        │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ evals/test_som_threshold.py                    │ parse SOM ≥ $100M                                            │ ~50         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ evals/test_translation_friendly.py             │ FK grade + compound-clause scan                              │ ~80         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ evals/test_amplification_loop_terminates.py    │ plateau detection works                                      │ ~60         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ docs/adr/0009-single-idea-recursive-loops.md   │ new ADR                                                      │ ~80         │
 ├────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┼─────────────┤
 │ docs/adr/0010-no-internal-ids-investor-docs.md │ new ADR                                                      │ ~80         │
 └────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────┴─────────────┘

 ARCHIVE → _deprecated/ (per user decision)

 - batch/ → _deprecated/batch_2026-05-12/
 - .claude/skills/big-idea-batch/, idea-engine/, idea-storm/, anomaly/, genius/ (all evaluated → archive if not referenced by new skill)
 - .claude/agents/phase-1-miner.md, phase-1-miner-cross-domain.md, phase-2-mapper.md, phase-3-validator.md, phase-4-forger.md, phase-5-critic.md, phase-6-formatter.md (replaced by single_idea orchestrator)
 - .claude/agents/persona-*.md (10 files — beautiful but unused in single-idea flow; archive, can resurrect for opt-in pre-seed ideation later)
 - .claude/agents/mutation-engine.md, idea-iterator.md, idea-pivot-wildcard.md, idea-synthesizer.md, idea-eval-judge.md
 - pipeline/path_c_runner.py, path_c_a4_sidecar.py, path_c_llm_runner.py, genius_loop.py, mutation.py, empirical_genius.py, operator_narratives.py, render_pilot.py, story_renderer.py (path-C deprecated)
 - evals/test_pathc_a4_*.py (all 6)
 - evals/test_big_idea_batch_smoke.py, test_mutation_*.py, test_no_recombination_collapse.py, test_school_checks.py (school checks fold into genius audit)
 - All archive moves preserve git history (use git mv).

 MODIFY

 - .claude/agents/concept-narrator.md — point at CONCEPT_TEMPLATE_V2.md + STYLE_GUIDE.md; explicit rule: "do not name TRIZ/JTBD/Booker/McKee/Boden/etc. in output"
 - CLAUDE.md (≤250 lines) — replace pipeline section, add ADR-0009 + ADR-0010 lines, drop references to phase-1..6 miner pipeline
 - Makefile — new targets: make single, make eval-single, make filter-check, make adr-9, make adr-10. Deprecate pathc-a4, pathc-index, pathc-eval.
 - .planning/state/RESUME.md — bump to "v4 lean single-idea pipeline build"

 ---
 Quality Gates (the eval pyramid)

 ┌───────────────────────────────┬─────────────────────────────────────────┬────────────────────────────────────────────────┐
 │             Layer             │                  Check                  │                 Where Enforced                 │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │ Tier 1 (P0 — pipeline halts)  │ SOM ≥ $100M                             │ evals/test_som_threshold.py + loop_controller  │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ No internal IDs in final .md            │ evals/test_no_internal_ids.py                  │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ V2 template structure complete          │ evals/test_template_compliance.py              │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ All ≥3 audience URLs verified           │ evals/test_audience.py + test_citations.py     │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ Challenge P0 kill-switches ≥ 0 failures │ evals/test_challenge_passed.py                 │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │ Tier 2 (P1 — narrator redo)   │ Flesch-Kincaid grade ≤ 12               │ evals/test_translation_friendly.py             │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ Banned terms not present                │ evals/test_anti_slop.py (extended banned list) │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ Cross-phase drift score < 5%            │ evals/test_consistency.py                      │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ Genius C001–C007 score ≥ 70             │ genius.json review                             │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │ Tier 3 (P2 — operator review) │ Quote ≤ 14 words (copyright)            │ evals/test_quotes.py                           │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ Cost within Sonnet+Haiku budget         │ evals/test_cost_health.py                      │
 ├───────────────────────────────┼─────────────────────────────────────────┼────────────────────────────────────────────────┤
 │                               │ Resume works (kill -9 mid-phase)        │ evals/test_resume.py                           │
 └───────────────────────────────┴─────────────────────────────────────────┴────────────────────────────────────────────────┘

 Gate composition: make eval-single runs all Tier-1 + Tier-2; CI runs all three.

 ---
 Hidden-Attribute → Investor-Prose Mapping (the magic step)

 The 12 framework attrs from seed.json shape narrator prose silently. Mapping table lives in Inputs/STYLE_GUIDE.md:

 ┌──────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────┐
 │           Hidden Attribute           │                       Narrator Behavior (no label, no surname)                        │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Arc Shape: Fall-Rise                 │ Emotional Arc section opens dark, pivots, closes with earned hope                     │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Booker: Voyage and Return            │ Synopsis: outbound departure → trial → return changed (no "voyage and return" phrase) │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ McKee: man vs self                   │ Protagonist subsection foregrounds inner contradiction not external villain           │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Emotional Weight: heavy              │ Tonal Contract section signals "demands attention, rewards endurance"                 │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Budget Tier: mid $15-50M             │ Revenue Thesis anchors to mid-budget comps (Whiplash, Promising Young Woman)          │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Boden: transformational              │ Concept→Mass-Appeal Theme section claims a genre-restructuring move in plain English  │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Csikszentmihalyi: high               │ Series Engine section explains the per-episode reorientation mechanic                 │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Timing Risk: zeitgeist-aligned       │ Why Now section leads with the data point, not a generic trend                        │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Retro Fallacy Risk: immediate        │ Comparables section names recent breakout, not a "cult classic" hedge                 │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Cultural Specificity: universal      │ Audience Sizing section names ≥3 territories with cited demand                        │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Moral Wager (McKee controlling idea) │ Mass-Appeal Theme section in one sentence, plain English, no "Controlling Idea" label │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
 │ Format Justification                 │ Format & Genre section: one sentence on why this format, not the alternative          │
 └──────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────┘

 The narrator NEVER writes "Booker plot type: Voyage and Return." It writes a synopsis that embodies that shape. Eval gate enforces absence of the label.

 ---
 Execution Batches (~80 atomic Sonnet/Haiku steps for the NEXT session)

 Each step is small enough for Sonnet/Haiku, follows TDD, and ends with a make lint && make typecheck && make test invocation by the builder-engine. The orchestrator (next session's main thread) dispatches these in waves.

 Wave A — Templates & Rules (5 steps, Sonnet, ~1 hour)

 - A1. Write Inputs/CONCEPT_TEMPLATE_V2.md (the 4-section investor template; verbatim from user spec + per-subsection prose guidance)
 - A2. Write Inputs/STYLE_GUIDE.md (banned-term list, ID regex, Russian-translation rules, hidden-attribute → prose mapping table)
 - A3. Write docs/adr/0009-single-idea-recursive-loops.md
 - A4. Write docs/adr/0010-no-internal-ids-investor-docs.md
 - A5. Update CLAUDE.md with new ADR-9/10 enforcer lines, drop deprecated rules — verify ≤250 lines via tests/test_claude_md_length.py

 Wave B — Tests First (TDD, 10 steps, Sonnet, ~2 hours)

 - B1. tests/test_template_filter.py — input contaminated draft, output clean .md, assert all banned regex removed
 - B2. tests/test_consistency.py — fixture: 6 sidecars with deliberate drift, assert detector flags it
 - B3. tests/test_loop_controller.py — assert plateau detected when delta < 5% twice; assert hard cap at 5 iters; assert L1/L3/L4 cap at 3 patches
 - B4. tests/test_single_idea_orchestrator.py — mocked end-to-end (no LLM calls), assert phase outputs created in correct order, RESUME.md updated
 - B5. evals/test_no_internal_ids.py — fixture: clean .md PASS, contaminated PASS=FAIL with line numbers
 - B6. evals/test_template_compliance.py — assert V2 4-section structure required, missing H2 = FAIL
 - B7. evals/test_som_threshold.py — fixtures: SOM=$50M FAIL, SOM=$120M PASS
 - B8. evals/test_translation_friendly.py — FK grade fixture pass/fail
 - B9. evals/test_amplification_loop_terminates.py — synthetic plateau, assert termination iter
 - B10. Run make test — all NEW tests RED (no implementation yet)

 Wave C — Pure-Python Implementation (TDD GREEN, 8 steps, Sonnet, ~3 hours)

 - C1. pipeline/template_filter.py:strip_internal_ids(md_text) — regex sweep
 - C2. pipeline/template_filter.py:enforce_v2_sections(md_text, template_path) — section reorder + missing-header detection
 - C3. pipeline/consistency.py:detect_drift(phase_paths) — protagonist/genre/comp/audience field diff
 - C4. pipeline/loop_controller.py:plateau_reached(history, delta_threshold) — plateau math
 - C5. pipeline/loop_controller.py:patch_budget(loop_id) — cap enforcement
 - C6. pipeline/single_idea.py — phase orchestrator (loads seed → dispatches each phase via cc_dispatch → writes sidecars → calls loops on demand)
 - C7. Make evals/test_*.py GREEN by running against fixtures
 - C8. Make tests/test_*.py GREEN by running against mocks. make test && make eval exits 0.

 Wave D — Agents & Skill (5 steps, Sonnet, ~1 hour)

 - D1. Write .claude/agents/concept-drafter.md (Sonnet, points at MASTER_BRIEF + INTELLECTUAL_FRAMEWORK; takes seed.json + research.json + optional patch_notes from challenger)
 - D2. Write .claude/agents/genius-auditor.md (Haiku, points at GREATNESS_CHECKLIST.json; outputs genius.json schema)
 - D3. Write .claude/agents/consistency-checker.md (Haiku, calls consistency.py and explains drift in plain English)
 - D4. Modify .claude/agents/concept-narrator.md — point at V2 + STYLE_GUIDE; explicit "never name TRIZ/JTBD/Booker/McKee/Boden/Csikszentmihalyi/Reagan/Pearson/Egri/Polti/Haidt/Mednick/Wundt/Simonton/Stanton/SIT/Conceptual Blend"
 - D5. Write .claude/skills/single-idea/SKILL.md — single-shot skill that takes a --theme arg, calls single_idea.py, returns the final <Title>.md path

 Wave E — Archive Legacy (4 steps, Haiku, ~30 min)

 - E1. git mv batch/ _deprecated/batch_2026-05-12/
 - E2. git mv .claude/skills/{big-idea-batch,idea-engine,idea-storm,anomaly,genius}/ _deprecated/skills_legacy/ (verify none referenced by new code first)
 - E3. git mv .claude/agents/{phase-1-miner.md,phase-1-miner-cross-domain.md,phase-2-mapper.md,phase-3-validator.md,phase-4-forger.md,phase-5-critic.md,phase-6-formatter.md,persona-*.md,mutation-engine.md,idea-*.md} _deprecated/agents_legacy/
 - E4. git mv pipeline/{path_c_runner.py,path_c_a4_sidecar.py,path_c_llm_runner.py,genius_loop.py,mutation.py,empirical_genius.py,operator_narratives.py,render_pilot.py,story_renderer.py} _deprecated/pipeline_legacy/ + git mv
 evals/test_pathc_a4_*.py evals/test_big_idea_batch_smoke.py evals/test_mutation_*.py evals/test_no_recombination_collapse.py evals/test_school_checks.py _deprecated/evals_legacy/

 Wave F — Makefile + Wiring (3 steps, Sonnet, ~30 min)

 - F1. Update Makefile: add single, eval-single, filter-check; deprecate pathc-*
 - F2. Update .planning/state/RESUME.md to point at v4 lean phase
 - F3. Run make lint && make typecheck && make test && make eval — all green

 Wave G — First Live Run + Iterate (5 steps, Sonnet, ~2 hours)

 - G1. Run single-idea skill on theme Station Tolerance (the user's own example) — python -m pipeline.single_idea --theme "Station Tolerance"
 - G2. Inspect all sidecars + final Station-Tolerance.md. Confirm: no IDs, no framework names, 4 sections present, SOM ≥ $100M
 - G3. Fix any eval failures via narrator redo loop
 - G4. Manual diff vs user's template — adjust prose
 - G5. Tag v4-first-run and commit

 Wave H — Polish & Documentation (3 steps, Haiku, ~30 min)

 - H1. Update README.md to point at new skill
 - H2. Update .planning/STATE.md to v4 milestone complete
 - H3. Final git commit with full changelog

 Total: 43 atomic steps grouped into 8 waves. Each step has clear acceptance criteria (test passes, file exists, regex matches). At ~5 min/step average for Sonnet/Haiku, full execution = ~10 hours wall clock, achievable in 2-3 future sessions
 following the ONE-STAGE-PER-SESSION rule (CLAUDE.md).

 ---
 Critical Files to Touch

 ┌────────────────────────────────────────────────┬────────┬───────────────────────────────────────────────────┐
 │                      File                      │ Action │                      Reason                       │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ pipeline/single_idea.py                        │ CREATE │ 10-phase orchestrator                             │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ pipeline/loop_controller.py                    │ CREATE │ L1-L5 recursive loops, plateau detection          │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ pipeline/consistency.py                        │ CREATE │ cross-phase drift detection                       │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ pipeline/template_filter.py                    │ CREATE │ strip IDs, enforce V2 sections                    │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ Inputs/CONCEPT_TEMPLATE_V2.md                  │ CREATE │ new investor 4-section template                   │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ Inputs/STYLE_GUIDE.md                          │ CREATE │ banned terms, hidden-attr→prose mapping           │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ .claude/agents/concept-narrator.md             │ MODIFY │ point at V2, ban framework labels                 │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ .claude/agents/concept-drafter.md              │ CREATE │ new Sonnet draft producer                         │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ .claude/agents/genius-auditor.md               │ CREATE │ Haiku C001-C007 checklist                         │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ .claude/agents/consistency-checker.md          │ CREATE │ Haiku drift inspector                             │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ .claude/skills/single-idea/SKILL.md            │ CREATE │ the new single-shot skill                         │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ evals/test_no_internal_ids.py                  │ CREATE │ regex scan, ADR-0010 enforcer                     │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ evals/test_template_compliance.py              │ CREATE │ V2 structure enforcer                             │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ evals/test_som_threshold.py                    │ CREATE │ $100M gate                                        │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ evals/test_translation_friendly.py             │ CREATE │ FK ≤12 + compound-clause                          │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ docs/adr/0009-single-idea-recursive-loops.md   │ CREATE │ ADR for new loop topology                         │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ docs/adr/0010-no-internal-ids-investor-docs.md │ CREATE │ ADR for output filter                             │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ CLAUDE.md                                      │ MODIFY │ new ADR lines, drop deprecated rules (≤250 lines) │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ Makefile                                       │ MODIFY │ new targets, deprecate pathc-*                    │
 ├────────────────────────────────────────────────┼────────┼───────────────────────────────────────────────────┤
 │ .planning/state/RESUME.md                      │ MODIFY │ bump to v4                                        │
 └────────────────────────────────────────────────┴────────┴───────────────────────────────────────────────────┘

 ---
 Functions to Reuse (don't reinvent)

 ┌───────────────────────────────────────────────┬──────────────────────────────────────────────────────┐
 │           Existing Function/Module            │                      Use in v4                       │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.state.safe_write                     │ every sidecar write                                  │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.state.append_jsonl                   │ run_log.jsonl + lessons.jsonl                        │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.scoring.overall_score                │ already does SDT+AJTBD → 0-100                       │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.scoring.ajtbd_score                  │ SOM derivation seed (existing audience floor logic)  │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.quota.gate                           │ every Sonnet/Haiku call gated before dispatch        │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.quota.record                         │ post-call accounting                                 │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.cc_dispatch.plan_manifest            │ converting phase spec → Task call                    │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.audience_amplifier.apply_vector      │ Phase 4 inner step                                   │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.audience_amplifier.detect_synergies  │ Phase 4 synergy bonus                                │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.commercial_prescreen.verdict         │ Phase 0 PASS/FAIL/MAYBE gate                         │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.plan_compliance.pre_task / post_task │ each phase boundary                                  │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ pipeline.seed_picker.pick_seed                │ Phase 0 if user provides theme but no binary tension │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ Inputs/MASTER_BRIEF.md                        │ prompt-cached in P1, P2, P3, P7                      │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ Inputs/CONCEPT_TEMPLATE.md (legacy)           │ reference only — V2 supersedes for narrator          │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ Inputs/RESEARCH_PROTOCOL.md                   │ prompt-cached in P1                                  │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ Inputs/CHALLENGE_PROTOCOL.md                  │ prompt-cached in P3                                  │
 ├───────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
 │ Inputs/GeniusFilm/GREATNESS_CHECKLIST.json    │ Phase 5 score rubric                                 │
 └───────────────────────────────────────────────┴──────────────────────────────────────────────────────┘

 ---
 Verification (how we know it works)

 End-to-end acceptance test (Wave G):

 1. python -m pipeline.single_idea --theme "Station Tolerance"
 2. Pipeline runs all 10 phases, all 5 loops terminate cleanly
 3. Final file: runs/2026-MM-DD-HHMMSS-station-tolerance/Station-Tolerance.md
 4. Sidecars present: seed.json, research.json, draft.v0.md, challenge.json, amplification.json, genius.json, consistency.json, eval.json
 5. make eval-single PROJECT=2026-MM-DD-HHMMSS-station-tolerance exits 0
 6. grep -E "(Per L|Cell-ID|iter-[0-9]|BT-[0-9]|TRIZ|JTBD|Booker|McKee|Boden|Csikszentmihalyi|Reagan|Pearson|Egri|Polti|Haidt|Mednick|Wundt|Simonton|Stanton|Lessons consulted|Working title)" Station-Tolerance.md returns zero hits
 7. SOM ≥ $100M parsed cleanly from "Audience Sizing → SOM" subsection
 8. All 4 H1 sections present: # Station Tolerance, # 1. Market & Audience, # 2. The Concept, # 3. Story, # 4. Characters (note: per user template, Title is the H1 with logline/tagline beneath; sections 1-4 are H1)
 9. Flesch-Kincaid grade ≤ 12 (translation-ready)
 10. Hidden-attr influence visible: the synopsis shape matches the Booker plot in seed.json — but the words "Booker" / "Voyage and Return" appear nowhere
 11. make test && make eval green
 12. Resume test: kill -9 mid-Phase-4, restart with --resume, completes from Phase 4 forward (existing test_resume.py extended)
 13. Cost recorded in pipeline/data/quota.jsonl — verify Sonnet calls ≤ 6, Haiku calls ≤ 12 for one full run

 Out-of-scope for this plan (future enhancements):
 - Multi-language final output (only English mandated; Russian translation is downstream)
 - HTML/PPTX deck generation (covered by FilmIntel OS contract elsewhere)
 - Resurrection of persona-* agents for opt-in pre-seed ideation
 - Animation / documentary / docs-hybrid format-specific subroutines (V1 covers feature + limited series)

 ---
 Risks & Mitigations

 ┌────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                          Risk                          │                                                                   Mitigation                                                                    │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ Hidden-attr leakage into narrator output               │ evals/test_no_internal_ids.py regex blocks every framework surname; narrator redo loop forces fix                                               │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ Sonnet quota exhausted mid-run                         │ pipeline.quota.gate blocks before dispatch; resume from last sidecar after quota refresh                                                        │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ Amplification loop diverges (vectors fight each other) │ Plateau detector caps at 5 iters; commercial_prescreen blocks non-viable seeds upfront                                                          │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ Drift > 5% on canonical fields                         │ Consistency loop forces draft patch; HARD cap 3 rounds prevents oscillation                                                                     │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ SOM < $100M after all amplification                    │ One drafter re-entry with vector-driven patches; if still <$100M → halt + report (don't fake numbers)                                           │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ User wants a feature, V2 template is series-shaped     │ V2 template marks "Series Engine" as conditional ("series only — omit for features"); narrator agent reads seed.json:target_format              │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ Legacy tests fail after archive                        │ _deprecated/ move uses git mv to preserve history; new test suite includes only NEW + KEEP files; CI runs only tests/test_*.py not _deprecated/ │
 ├────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ Russian translation fidelity                           │ STYLE_GUIDE.md bans idioms + compound clauses > 30 words; evals/test_translation_friendly.py enforces                                           │
 └────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 ---
 Why this plan honors Pareto + lean

 - 80% of value from 20% of new code: 4 new Python modules (~700 LOC) + 2 new templates + 6 new evals deliver the full investor-facing redesign
 - Zero new infrastructure: reuses 9 existing pipeline modules + 8 ADRs untouched
 - No Opus required: all model calls land on Sonnet 4.6 (4 calls/run) or Haiku 4.5 (10 calls/run)
 - Recursive loops compensate for cheaper models: 5 loops cover what a single Opus pass would brute-force — each loop is cheap (Haiku) and each iteration improves a measurable dimension
 - Pure-Python in the math seams (plateau detect, drift, SOM parse, regex strip) — deterministic, fast, no LLM cost
 - Prompt caching on the 6 large reference docs — first call warms cache, subsequent calls run at 90% discount
 - One investor-facing file per run — no batch confusion, no operator triage; final markdown is the deliverable

 Execution can begin immediately after plan approval. First wave (A — templates & rules) is parallelizable across 5 Sonnet calls.

 ---
 Sonnet Execution Playbook (added on Opus follow-up)

 Verdict: Sonnet 4.6 is sufficient. Do not burn Opus quota on orchestration.

 The plan was engineered for the Sonnet/Haiku constraint. Recursive loops, deterministic Python in the math seams, prompt caching, and the existing harness (state.py, scoring.py, quota.py, cc_dispatch.py, plan_compliance.py) are the
 intelligence. Opus on top would add cost and a session boundary without lifting quality. The Sonnet session you already opened confirmed it can read the plan, identified Wave A as immediately executable, and correctly offered to skip a preview
  round — that is good judgment, not a deficit. Proceed.

 Session strategy — ONE STAGE per session (CLAUDE.md HARN-13)

 Map the 8 waves to 4–6 Claude Code sessions. Each session ends with make lint && make typecheck && make test, an updated .planning/state/RESUME.md, and a single atomic commit. Don't cross a wave boundary in one session.

 ┌───────────────┬────────────────────────────────────────────────┬────────────┬────────────┬────────────────────────────────────────────────────────────────┐
 │    Session    │                     Waves                      │ Wall-clock │ Main model │                        Subagent fan-out                        │
 ├───────────────┼────────────────────────────────────────────────┼────────────┼────────────┼────────────────────────────────────────────────────────────────┤
 │ 1             │ A (templates) + D (agents)                     │ ~2 h       │ Sonnet     │ 5 parallel Write calls in Wave A; 5 in Wave D                  │
 ├───────────────┼────────────────────────────────────────────────┼────────────┼────────────┼────────────────────────────────────────────────────────────────┤
 │ 2             │ B (TDD tests RED)                              │ ~2 h       │ Sonnet     │ 10 parallel test scaffolds via builder-engine                  │
 ├───────────────┼────────────────────────────────────────────────┼────────────┼────────────┼────────────────────────────────────────────────────────────────┤
 │ 3             │ C (impl GREEN)                                 │ ~3 h       │ Sonnet     │ sequential builder-engine per module; critic-engine after each │
 ├───────────────┼────────────────────────────────────────────────┼────────────┼────────────┼────────────────────────────────────────────────────────────────┤
 │ 4             │ E (archive) + F (Makefile) + H1-H2 (docs)      │ ~1 h       │ Haiku      │ sequential git mv + Edit                                       │
 ├───────────────┼────────────────────────────────────────────────┼────────────┼────────────┼────────────────────────────────────────────────────────────────┤
 │ 5             │ G (first live run)                             │ ~2 h       │ Sonnet     │ invokes single-idea skill → fans out concept-* agents          │
 ├───────────────┼────────────────────────────────────────────────┼────────────┼────────────┼────────────────────────────────────────────────────────────────┤
 │ 6 (if needed) │ G repeat for second theme to confirm stability │ ~1 h       │ Sonnet     │ same                                                           │
 └───────────────┴────────────────────────────────────────────────┴────────────┴────────────┴────────────────────────────────────────────────────────────────┘

 Between sessions, write a handoff JSON to .planning/state/handoffs/{from}_to_{to}_{ts}.json containing {wave_completed, files_touched, tests_state:{passed,failed,skipped}, next_action, open_questions:[]}.

 Parallel dispatch pattern (the orchestrator's mental model)

 The main Sonnet thread is the orchestrator, not a worker. It should:

 1. Read CLAUDE.md, RESUME.md, this plan
 2. Pick the next wave
 3. For each step in the wave, decide: parallelizable (independent file writes/tests) or sequential (depends on prior step's output)
 4. Dispatch parallel work in a single message with multiple Agent tool calls (this is the Claude Code idiom — multiple Agent blocks in one assistant turn run concurrently)
 5. After each agent returns, run make lint && make typecheck && make test via the orchestrator's Bash
 6. If RED → dispatch build-error-resolver agent with the exact error log
 7. If GREEN → commit, update RESUME, move to next step

 Parallelizable in Wave A (1 message, 5 Agent calls):
 - A1: Write Inputs/CONCEPT_TEMPLATE_V2.md
 - A2: Write Inputs/STYLE_GUIDE.md
 - A3: Write docs/adr/0009-single-idea-recursive-loops.md
 - A4: Write docs/adr/0010-no-internal-ids-investor-docs.md
 - A5: Edit CLAUDE.md

 Parallelizable in Wave B (1 message, 10 Agent calls via tdd-guide): each test file is independent. All 10 can be written concurrently because they only depend on the templates from Wave A and on existing pipeline interfaces.

 Sequential in Wave C: implementation modules depend on each other:
 - C1, C2 (template_filter) ← can run parallel (sibling functions)
 - C3 (consistency) ← independent
 - C4, C5 (loop_controller) ← can run parallel
 - C6 (single_idea orchestrator) ← MUST wait for C1-C5 (imports them)
 - C7, C8 (eval/test GREEN) ← MUST wait for C6

 So Wave C structure: one message dispatching C1+C2+C3+C4+C5 in parallel, then a second message for C6, then a third for C7+C8 in parallel.

 Concrete dispatch prompts (copy-paste ready)

 Orchestrator → builder-engine for a code module:
 PHASE: Wave C, step C4 (loop_controller plateau detector)
 READ: ~/.claude/plans/i-need-you-only-hidden-lollipop.md (sections "Phase 4" + "Execution Batches Wave C" + "Functions to Reuse")
 READ: tests/test_loop_controller.py (test fixtures define the exact behavior)
 CREATE: pipeline/loop_controller.py with these public functions:
   - plateau_reached(history: list[float], delta_threshold: float = 0.05, window: int = 2) -> bool
   - patch_budget(loop_id: str) -> int  # returns 3 for L1/L3/L4, 5 for L2, 2 for L5
   - record_iteration(run_id: str, loop_id: str, iter_n: int, payload: dict) -> None  # appends to runs/{run_id}/loop_log.jsonl via pipeline.state.append_jsonl
 CONSTRAINTS: pure Python, no LLM imports (ANOMALY-001), use pipeline.state.safe_write only
 ACCEPTANCE: tests/test_loop_controller.py all pass via `pytest tests/test_loop_controller.py -v`
 COMMIT: atomic, prefixed `feat(loop_controller):`

 Orchestrator → tdd-guide for a test file:
 PHASE: Wave B, step B7
 READ: ~/.claude/plans/i-need-you-only-hidden-lollipop.md (Phase 4 + Quality Gates Tier-1 sections)
 CREATE: evals/test_som_threshold.py with three test functions:
   - test_som_above_100m_passes (fixture: investor.md with line "**SOM (Year 1):** $145M" → asserts PASS)
   - test_som_below_100m_fails (fixture: "$50M" → asserts FAIL with line number)
   - test_som_missing_fails (fixture: no SOM line at all → asserts FAIL with reason "SOM line not found")
   Helper: parse_som(md_text: str) -> tuple[float, int] | None  # returns (millions_usd, line_no) or None
 EXPECT: tests RED until evals/test_som_threshold.py imports the real parser (Wave C, deferred). For now, the test file itself runs and exits 1 (no implementation found).
 COMMIT: atomic, prefixed `test(som-gate):`

 Orchestrator → critic-engine after Wave C:
 REVIEW: latest commits in feature/single-idea-v4 branch
 CHECK against: CLAUDE.md MUST/MUST NOT rules, ADR-0001 (state on disk), ADR-0002 (no LLM scoring), ANOMALY-001 (no anthropic/httpx in pipeline/), the plan's "Quality Gates" section
 REPORT: violations, missing tests, dead code; one-line per finding with file:line
 DO NOT: write code or commit

 V2 Template — exact skeleton Sonnet should write in Wave A1

 Inputs/CONCEPT_TEMPLATE_V2.md:

 # [Film Title]

 - **Logline:** [25–40 words. Active voice. Protagonist + want + obstacle + stakes. No surnames. No frameworks.]
 - **Tagline:** [5–10 words. Poster line. Marketing register.]

 ---

 # 1. Market & Audience

 ## Revenue Thesis (Anchored to Comps)
 [2–3 sentences. State the target revenue band and the 2–3 named comparable films that justify the projection. Cite year + worldwide gross with URL. No "we believe" or "we estimate" — speak as if presenting to a financier who reads Variety.]

 ## Primary Audience Segment
 ### Who They Are
 [1 sentence demographic anchor + 1 cited statistic, year, URL.]
 ### Job-to-Be-Done
 [Why this audience pays for this story — 1 sentence in their voice, not in framework jargon. Example acceptable: "viewers in their thirties who lived through 2008 want to understand what a corporation actually owes them." Example FORBIDDEN:
 "JTBD Segment: Rehearse-a-Decision."]
 ### Tonal Contract
 [What they expect emotionally. 1 sentence.]
 ### What Loses Them
 [Specific failure modes for THIS segment. 1 sentence.]

 ## Secondary Segment
 ### Who They Are
 ### Job-to-Be-Done
 ### Tonal Contract
 ### What Loses Them

 ## Why Now (Market Timing)
 [1 short paragraph. Lead with a sourced data point (CDC / Pew / FRED / Nielsen / NPD), year, URL. Then connect that data point to the project's emotional question. Banned openers: "In today's world", "In a time when", "Now more than ever".]

 ## Audience Sizing

 ### TAM — Total Addressable Market
 **TAM:** $X.XXB
 [1 sentence derivation. Show the math. Cite the underlying audience-rows from the evidence table.]

 ### SAM — Serviceable Addressable Market
 **SAM:** $XXXM
 [1 sentence derivation.]

 ### SOM — Serviceable Obtainable Market (Year 1 realistic capture)
 **SOM (Year 1):** $XXXM
 [1 sentence derivation. Must be ≥ $100M to pass quality gate.]

 ## Comparables

 ### Financial Comps
 | Title | Year | Format | Budget | WW Revenue | Why Comparable | Source |
 |---|---|---|---|---|---|---|
 | ... | ... | ... | ... | ... | ... | URL |
 | ... | ... | ... | ... | ... | ... | URL |
 | ... | ... | ... | ... | ... | ... | URL |

 ### Tonal Comps
 [3 titles in prose, no surnames, why each is tonally adjacent.]

 ### Structural Comps
 [3 titles in prose, why each is structurally adjacent — e.g., "an episodic procedural where every chapter introduces a new defendant" rather than "Booker Plot: Voyage and Return".]

 ---

 # 2. The Concept

 ## Format & Genre
 [Format declared. Episode count if series. Single sentence on why this format and not the alternative.]

 ## The Contradiction
 [The central narrative tension stated in plain English. 2–3 sentences. No "TRIZ contradiction" label. The contradiction should be the engine that keeps the audience leaning forward.]

 ## Psychological Tension
 [The internal tension carried by the protagonist. 2 sentences. No "man vs self" label.]

 ## Indelible Image
 [The single visual moment a viewer will describe to a friend the next day. 1–2 sentences.]

 ## Mass-Appeal Theme
 [The universal human question the project answers — phrased as a question or a McKee-style controlling idea WITHOUT naming McKee or saying "controlling idea". 1 sentence.]

 ## Fact–Fiction Blend
 [Which true events / real cases / documented studies ground the fiction. ≥1 sourced case from PubMed / CourtListener / Wikipedia / MIT Moral Machine / a named historical record. Include URL.]

 ---

 # 3. Story

 ## Synopsis
 [Act I / Act II / Act III. Ending revealed. 400–600 words. No "Act break:" labels — just three clearly distinct paragraphs. Reveal the ending; investors buy the finished thing.]

 ## Emotional Arc
 [The audience's emotional journey across the runtime. 2 short paragraphs. No "Reagan arc" label — describe the curve in plain English.]

 ## Series Engine
 [OMIT for features. For series: how does each new season/episode generate fresh stakes from the same premise? 2 sentences.]

 ## Cinematic Parallels
 [3 films/series this most resembles, prose. Why each. No "structural comp" label here — that's Section 1.]

 ## Visual Style & Tone
 [The look, palette, sound, pace. 2 short paragraphs. Reference real DPs/directors only if the user explicitly wants — otherwise describe stylistically without surnames.]

 ---

 # 4. Characters

 ## Protagonist
 **Name | Age | One-line identity**
 [3 sentences. Want, wound, why now. No "Pearson archetype" label.]

 ## Antagonist
 **Name | Age | One-line identity**
 [3 sentences. Their want — which overlaps with the protagonist's want (this is what makes them a real antagonist, not a cardboard one). No "Ruler archetype" label.]

 ## Ally / Supporting
 [Brief table or 2–3 short character beats. Each character justified by their dramatic function, not by archetype label.]

 ---

 ## References

 [Numbered list of every URL cited above. Format: `1. [Source name](URL) — context line` — human-readable, no inline footnote IDs.]

 That is what Wave A1 produces. No more, no less.

 STYLE_GUIDE skeleton — exact content for Wave A2

 Inputs/STYLE_GUIDE.md:

 # Style Guide — Investor-Facing Film Concept Documents

 ## Hard Rules (MUST NOT — eval gates block these)

 The following regex patterns, if matched in any final investor `.md`, are eval failures:

 - `\bPer L\d+\b` — internal lesson references
 - `\bCell-ID:` — internal binary-tension cell IDs
 - `\biter-\d+\b` — iteration metadata
 - `\bL\d{3,}\b` (in headers) — lesson IDs in section titles
 - `\bBT-\d+|PS-\d+|PA-\d+|US-\d+\b` — binary-tension component IDs
 - `\bWorking title\b|\(working\)` — draft framing
 - `\bLessons consulted\b` — internal tracking
 - Framework surnames anywhere in body: `\b(TRIZ|JTBD|Booker|McKee|Boden|Csikszentmihalyi|Reagan|Pearson|Egri|Polti|Haidt|Mednick|Wundt-Berlyne|Wundt|Simonton|Stanton|Propp|Truby|Snyder|Fauconnier|Turner|SIT Operator|Conceptual Blend|Macro
 Resonance Weight|Anti-slop|ten-school|Three-Act Skeleton)\b`
 - `\bcontradict(ion|ory)\b.*\b(TRIZ|matrix)\b` — even partial framework references
 - Markdown auto-link `<https?://...>` — use `[text](url)` format

 ## Hard Rules (MUST)

 - Every numeric claim has an inline `[source](URL)` link
 - Flesch-Kincaid grade ≤ 12 (run `textstat.flesch_kincaid_grade` in the eval)
 - Sentences ≤ 30 words on average; no compound clause > 40 words
 - Active voice ≥ 70% of sentences
 - File named `[Film-Title-With-Hyphens].md` — Title Case, hyphens replacing spaces
 - All 4 H1 sections present in order: `# [Title]`, `# 1. Market & Audience`, `# 2. The Concept`, `# 3. Story`, `# 4. Characters`
 - Logline + Tagline appear as bullet items directly under the title H1, before Section 1
 - SOM line matches regex `\*\*SOM \(Year 1\):\*\* \$\d+(\.\d+)?[MB]` and value ≥ $100M

 ## Russian-Translation Friendliness (eval-warned, not blocked)

 Avoid idiom families that machine-translate poorly:
 - Sports metaphors ("home run", "Hail Mary", "moving the goalposts")
 - Military metaphors except direct combat references ("flagship", "ground zero", "in the trenches")
 - Legal-Latin without context ("ipso facto", "de facto" without surrounding explanation)
 - US-culture-specific compound nouns ("Main Street", "Wall Street" if not literal)
 - Wordplay / puns
 - Idiomatic phrasal verbs where a single verb works ("figure out" → "determine"; "bring up" → "raise")

 Prefer:
 - Subject-verb-object sentence order
 - Explicit subjects (avoid pronouns referring across paragraphs)
 - Concrete nouns over abstract gerunds where possible

 ## Hidden-Attribute → Investor Prose Mapping (the magic table)

 The drafter and narrator agents read `seed.json` for the 12 hidden attribute values. They MUST translate each into prose without naming the framework. Examples:

 | Hidden Attribute Value | Prose Behavior |
 |---|---|
 | `arc_shape: Fall-Rise` | Section "Emotional Arc" opens with descent ("the protagonist loses what she came in believing she had"), pivots at midpoint, closes with earned recovery |
 | `arc_shape: Rise-Fall` | Opens with apparent victory, closes with cost; tonal contract signals "tragedy that earns its grief" |
 | `booker: Voyage and Return` | Synopsis paragraphs 1/2/3 map to depart / ordeal / return-changed — never named |
 | `booker: Overcoming the Monster` | Synopsis follows threat-identified / preparation / confrontation / cost — never named |
 | `mckee_conflict: man vs self` | Protagonist subsection foregrounds inner contradiction; antagonist subsection notes shared world, not external villain |
 | `mckee_conflict: man vs society` | Antagonist subsection names a system or institution as the opposing force |
 | `emotional_weight: heavy` | Tonal Contract: "demands attention, rewards endurance" — no "heavy" word |
 | `emotional_weight: light` | Tonal Contract: "moves quickly, lifts the room" |
 | `budget_tier: mid $15-50M` | Revenue Thesis anchors to mid-budget comps (Whiplash, Promising Young Woman, Get Out) |
 | `budget_tier: tentpole $200M+` | Revenue Thesis names blockbusters; SAM expanded for theatrical-first window |
 | `boden: transformational` | Mass-Appeal Theme claims a genre-restructuring move in one sentence ("this story does not adapt the courtroom drama — it dismantles its central assumption") — never named |
 | `boden: combinatorial` | Mass-Appeal Theme positions as fresh combination of known elements |
 | `flow_potential: high` | Series Engine section explicit on per-episode reorientation mechanic |
 | `timing_risk: zeitgeist-aligned` | Why Now section leads with most-recent (≤ 12 months old) data point + URL |
 | `timing_risk: timeless` | Why Now section leads with a structural observation about the audience, not a news event |
 | `retro_fallacy_risk: immediate` | Comparables Section names a 2020–2025 breakout, not a 1990s cult classic |
 | `cultural_specificity: universal` | Audience Sizing names ≥3 territories with cited demand each |
 | `cultural_specificity: bicultural` | Audience Sizing names the 2 anchor territories + their bridge audience |
 | `moral_wager` (controlling idea string) | Embodied in Mass-Appeal Theme in plain English; no "controlling idea" phrase |
 | `format_justification` (one-sentence rationale) | Format & Genre section ends with this exact sentence, no "Format Justification:" label |

 This table is the **most important asset for the narrator**. Compliance with it is what makes the output investor-grade without being technical.

 That is what Wave A2 produces.

 ADR-0009 and ADR-0010 — exact frames

 docs/adr/0009-single-idea-recursive-loops.md covers:
 - Decision: 10-phase single-idea orchestrator with 5 recursive loops (L1 challenge↔draft, L2 amplification plateau, L3 genius↔draft, L4 consistency↔draft, L5 narrator↔eval)
 - Caps: L1=L3=L4=3 patches; L2=5 iters; L5=2 redos
 - Plateau threshold: (score_n - score_{n-1}) / score_{n-1} < 0.05 for 2 consecutive iters
 - Enforcer: tests/test_loop_controller.py::test_caps_enforced + evals/test_amplification_loop_terminates.py

 docs/adr/0010-no-internal-ids-investor-docs.md covers:
 - Decision: every final investor .md must pass evals/test_no_internal_ids.py (regex block list above) before commit
 - Sidecars (seed.json, draft.v0.md, etc.) are NOT subject to this rule
 - The narrator agent is the only writer of the final .md; the template_filter is the post-process belt-and-suspenders
 - Enforcer: evals/test_no_internal_ids.py + evals/test_translation_friendly.py + pre-commit hook .claude/hooks/no_internal_ids_pretool.py (optional belt-and-suspenders, follows the FilmIntel deep-link-evidence hook pattern)

 Handoff JSON format (between sessions)

 .planning/state/handoffs/{from_session}_to_{to_session}_{ISO-8601}.json:

 {
   "schema_version": "1.0",
   "from_session_id": "2026-05-12-session-1-templates",
   "to_session_id": "2026-05-12-session-2-tests",
   "wave_completed": "A",
   "wave_starting": "B",
   "files_touched": [
     "Inputs/CONCEPT_TEMPLATE_V2.md",
     "Inputs/STYLE_GUIDE.md",
     "docs/adr/0009-single-idea-recursive-loops.md",
     "docs/adr/0010-no-internal-ids-investor-docs.md",
     "CLAUDE.md"
   ],
   "tests_state": {"passed": 142, "failed": 0, "skipped": 8},
   "claude_md_lines": 248,
   "next_action": "Wave B — write 10 RED test files in parallel via tdd-guide agent",
   "open_questions": [],
   "git_state": {"branch": "feature/single-idea-v4", "commits_added": 5, "head_sha": "..."},
   "resume_pointer": ".planning/state/RESUME.md"
 }

 The receiving session reads this file FIRST per the CLAUDE.md Recovery Protocol.

 Stop-gates per wave (when to halt and ask user)

 ┌──────┬─────────────────────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ Wave │                                         Halt condition                                          │                                               What to ask user                                               │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ A    │ If any of the 12 hidden-attr → prose mappings feels ambiguous after writing the STYLE_GUIDE     │ "Confirm this specific mapping for boden: exploratory — is the prose direction correct?"                     │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ B    │ If a test fixture requires investor-facing content that doesn't yet exist                       │ "Show me a 100-word example of how Why Now should read for theme X"                                          │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ C    │ If make typecheck fails on a public function signature that contradicts the plan                │ "Plan says plateau_reached(history, delta_threshold, window). Pyright wants list[float]. Confirm signature?" │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ D    │ If concept-narrator.md modifications conflict with the existing audience-amplifier.md schema    │ "Should the narrator read amplification.json directly or via the consistency-checker's reconciled view?"     │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ E    │ NEVER halt — this is mechanical git mv                                                          │ (no question)                                                                                                │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ F    │ If a Makefile target name clashes with FilmIntel project sibling                                │ "Rename single to single-idea to avoid clashing with FilmIntel?"                                             │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ G    │ If the first live run produces a final .md that passes eval gates but feels stylistically wrong │ "Read the output, paste 1–2 lines you would change, and I'll patch the narrator prompt"                      │
 ├──────┼─────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ H    │ NEVER halt — docs only                                                                          │ (no question)                                                                                                │
 └──────┴─────────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 In all other situations, proceed autonomously. Don't ask permission for things the plan already decides.

 Cost budget per full first run (Wave G acceptance test)

 ┌───────────────┬─────────────────┬────────────────┬──────────────┬──────────────────────────┐
 │     Phase     │      Model      │     Calls      │ Tokens (est) │ Cost (subscription view) │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 0 Seed        │ Haiku           │ 1              │ 2k           │ ~$0.001                  │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 1 Research    │ Sonnet          │ 1              │ 25k          │ ~$0.12                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 2 Draft v0    │ Sonnet          │ 1              │ 20k          │ ~$0.10                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 3 Challenge   │ Sonnet+thinking │ 1 (+ ≤3 patch) │ 15k × ≤4     │ ~$0.30                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 4 Amplify     │ Haiku           │ ≤5             │ 3k × 5       │ ~$0.01                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 5 Genius      │ Haiku           │ 1 (+ ≤3 patch) │ 5k × ≤4      │ ~$0.01                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 6 Consistency │ Haiku           │ 1 (+ ≤3 patch) │ 8k × ≤4      │ ~$0.02                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 7 Narrator    │ Sonnet+thinking │ 1 (+ ≤2 redo)  │ 25k × ≤3     │ ~$0.40                   │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 8 Eval        │ Haiku           │ 1              │ 5k           │ ~$0.001                  │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ 9 Lessons     │ Haiku           │ 1              │ 3k           │ ~$0.001                  │
 ├───────────────┼─────────────────┼────────────────┼──────────────┼──────────────────────────┤
 │ Total         │ —               │ ~25 calls      │ ~250k        │ ~$1.00 / run             │
 └───────────────┴─────────────────┴────────────────┴──────────────┴──────────────────────────┘

 Well within weekly Sonnet (20M tokens) and Haiku (100M tokens) caps. The user can run 20+ concepts per week on Sonnet/Haiku alone.

 What to NOT do (the Sonnet trap list)

 1. Don't write speculative "future-proof" abstractions. The plan has 4 new Python modules. Resist creating a fifth "for the future."
 2. Don't add docstrings longer than one line. Code is small and named; comments rot.
 3. Don't add # TODO: comments. Either implement or leave to the next session via RESUME.md.
 4. Don't import anything from frameworks/ in pipeline/* (ADR-0005; scripts/lint_imports.py blocks it).
 5. Don't compute scores in any LLM call (ADR-0002; LLMs may suggest, Python decides).
 6. Don't write batch-mode helpers. The plan is single-idea. If a function name contains "batch", stop.
 7. Don't preview the V2 template structure to the user — the structure is in this playbook. Write Wave A in full and have the user review the finished file.
 8. Don't ask Opus 4.7 to "guide" you. The plan is closed-form. Read it twice, then ship.

 Final check before Sonnet starts Wave A

 Run this single bash one-liner first (read-only):

 ls Inputs/CONCEPT_TEMPLATE.md Inputs/MASTER_BRIEF.md Inputs/RESEARCH_PROTOCOL.md Inputs/CHALLENGE_PROTOCOL.md Inputs/INTELLECTUAL_FRAMEWORK.md docs/adr/0001-jsonl-not-memory.md pipeline/state.py pipeline/scoring.py
 pipeline/audience_amplifier.py pipeline/commercial_prescreen.py .planning/state/RESUME.md CLAUDE.md && wc -l CLAUDE.md

 If all 11 files exist and CLAUDE.md is ≤250 lines, you're cleared to execute Wave A. If anything is missing, stop and surface it before proceeding.

 ---
 Post-Build Audit & Improvement Plan (added 2026-05-13)

 State of the build — 95% shipped, gates green

 Sonnet executed Waves A–H. Result: all 4 new Python modules (449 LOC), all 9 new test/eval files, 4 new agents, 1 new skill, 2 ADRs, the V2 template, the STYLE_GUIDE, CLAUDE.md v4 (99 lines). Legacy archived. make test = 555 green / 1 xfail.
 make eval = 85 green. First live run runs/2026-05-12-171157-station-tolerance/Station-Tolerance.md is investor-grade: 4 H1 sections strict, zero leaked IDs, SOM $432M, hidden-attr influence visible but framework surnames absent.

 Observed gaps (audit-confirmed, ranked by leverage)

 ┌─────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────┬───────────────────────────────────────────────────┬──────────────┐
 │  #  │                                                            Gap                                                             │                Impact                 │                       Files                       │     Cost     │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I1  │ tests/test_loop_controller.py::test_plateau_reached marked xfail while implementation exists and works                     │ False signal in CI — masks real       │ tests/test_loop_controller.py                     │ 5 min Haiku  │
 │     │                                                                                                                            │ regressions if plateau math drifts    │                                                   │              │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I2  │ Second run 2026-05-12-204819-... halted at seed (Phase 0); cause unknown                                                   │ Stability unverified across themes;   │ runs/2026-05-12-204819-*/, data/run_log.jsonl     │ 30 min       │
 │     │                                                                                                                            │ can't claim pipeline is reproducible  │                                                   │ Sonnet       │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │     │                                                                                                                            │ Cannot diagnose "did amplification    │ pipeline/single_idea.py,                          │ 30 min       │
 │ I3  │ No loop_telemetry.json per run — no record of how many L1/L2/L3/L4/L5 iters fired or what terminated them                  │ plateau or hit cap?" without grepping │ pipeline/loop_controller.py                       │ Sonnet       │
 │     │                                                                                                                            │  jsonl                                │                                                   │              │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I4  │ No cost.json per run — quota deltas not snapshotted at phase boundaries                                                    │ Cannot tell which phase cost the most │ pipeline/single_idea.py                           │ 20 min       │
 │     │                                                                                                                            │  without manual jsonl arithmetic      │                                                   │ Sonnet       │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │     │                                                                                                                            │ The magic step is the differentiator; │                                                   │ 30 min       │
 │ I5  │ Hidden-attr → prose embodiment never audited on the one live run                                                           │  if violated nothing else matters     │ runs/2026-05-12-171157-*/seed.json + final .md    │ manual       │
 │     │                                                                                                                            │                                       │                                                   │ Sonnet read  │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │     │ evals/test_template_compliance.py checks 4 H1s but unclear whether it requires all V2 H2/H3 subsections (Who They Are,     │ Narrator can ship a half-template and │ evals/test_template_compliance.py,                │ 30 min       │
 │ I6  │ Job-to-Be-Done, Tonal Contract, What Loses Them × 2, Indelible Image, Psychological Tension, Fact-Fiction Blend, Visual    │  still pass eval                      │ Inputs/CONCEPT_TEMPLATE_V2.md                     │ Sonnet       │
 │     │ Style & Tone)                                                                                                              │                                       │                                                   │              │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I7  │ lessons.jsonl written by Phase 9 but no test confirms Phase 2 of a subsequent run actually reads + uses it                 │ Lessons feature is dead code if not   │ pipeline/single_idea.py:phase_2_draft_v0, new     │ 45 min       │
 │     │                                                                                                                            │ consumed                              │ test fixture                                      │ Sonnet       │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I8  │ No best_attempt.md fallback when SOM<$100M after L2 plateau — current behavior halts with no artifact                      │ Operator loses work on borderline     │ pipeline/single_idea.py:_finalize                 │ 20 min       │
 │     │                                                                                                                            │ themes                                │                                                   │ Sonnet       │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I9  │ No runs/index.html operator dashboard — must ls to see history                                                             │ Slow operator review of multi-day     │ new pipeline/runs_index.py (or reuse              │ 30 min       │
 │     │                                                                                                                            │ output                                │ pipeline/index_html.py)                           │ Sonnet       │
 ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┼───────────────────────────────────────────────────┼──────────────┤
 │ I10 │ evals/test_translation_friendly.py exists but no fixture round-trips through MT to check Russian naturalness               │ The whole RU-friendliness claim is    │ optional — defer to P2                            │ 1 h          │
 │     │                                                                                                                            │ unverified                            │                                                   │              │
 └─────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────┴───────────────────────────────────────────────────┴──────────────┘

 Wave I — Post-build hardening (Pareto P0, ~2 hours Sonnet)

 One session, one wave. Use ONE Claude Code session for all of I1–I5. Do not bundle P1 items (I6–I9) into the same session — that violates ONE-STAGE-PER-SESSION.

 Step I1 — Un-xfail the plateau test (Haiku, 5 min)

 - Open tests/test_loop_controller.py
 - Remove the @pytest.mark.xfail decorator on test_plateau_reached
 - Confirm the test now collects and passes via pytest tests/test_loop_controller.py::test_plateau_reached -v
 - Acceptance: make test → 556 passed / 0 xfail

 Step I2 — Resolve the stalled run (Sonnet, 30 min)

 - ls runs/2026-05-12-204819-*/ — what files exist? what's the last data/run_log.jsonl event for this run_id?
 - If the cause is a transient (quota gate, missing input) → re-run via make single THEME="<original theme>"
 - If the cause is a code bug → file a one-line note in .planning/state/RESUME.md, archive the run to _deprecated/runs_failed/, and re-run
 - Acceptance: a fully populated second run folder with all 8 sidecars + final .md passing eval

 Step I3 — Loop telemetry sidecar (Sonnet, 30 min)

 - Modify pipeline/loop_controller.py to record per-loop: {loop_id, iters_used, terminated_by: "cap"|"plateau"|"gate_passed"|"reject_final", deltas: [..], final_score}
 - Modify pipeline/single_idea.py:_finalize to write runs/<id>/loop_telemetry.json aggregating all 5 loops
 - Add fixture-based test tests/test_loop_controller.py::test_telemetry_emitted that runs a 3-iter mock loop and asserts the JSON shape
 - Acceptance: re-running the Station-Tolerance theme produces a loop_telemetry.json with non-zero iters_used for L2 (amplification) and terminated_by: "plateau"

 Step I4 — Cost sidecar (Sonnet, 20 min)

 - Modify pipeline/single_idea.py to snapshot pipeline.quota.consumed_this_week() BEFORE and AFTER each phase
 - Write runs/<id>/cost.json with per-phase {tokens_in, tokens_out, model} deltas and a total block
 - Acceptance: cost.json exists per run; sum of phase totals matches data/quota.jsonl rows for that run_id

 Step I5 — Hidden-attr embodiment audit (manual + Sonnet, 30 min)

 - Read runs/2026-05-12-171157-station-tolerance/seed.json — extract hidden_attrs
 - For each of the 12 attribute values, find the corresponding prose location in Station-Tolerance.md using the mapping table in Inputs/STYLE_GUIDE.md
 - Score each as EMBODIED / PARTIAL / MISSING / VIOLATED-LABEL-LEAKED
 - Write findings to runs/2026-05-12-171157-station-tolerance/embodiment_audit.md
 - If any attribute is MISSING or VIOLATED, file one specific patch instruction back to .claude/agents/concept-narrator.md (e.g., "if booker=Voyage and Return then synopsis must follow depart→ordeal→return-changed in 3 distinct paragraphs")
 - Acceptance: audit file written; if patches were needed, narrator agent updated; re-run on Station-Tolerance and confirm improvement

 Wave J — Operator ergonomics & test depth (Pareto P1, ~3 hours, separate session)

 Step J1 — Strengthen template compliance eval (Sonnet, 30 min)

 - Open evals/test_template_compliance.py
 - Add assertions for every required V2 H2/H3 subsection (parse Inputs/CONCEPT_TEMPLATE_V2.md, extract each ## and ###, require each as a regex match in the candidate .md)
 - Series-only subsections (Series Engine) are conditional on seed.json:target_format == "series"
 - Add 2 fixtures: a complete .md (PASS) and a 4-H1-only .md (FAIL with specific missing subsections)
 - Acceptance: make eval still green on Station-Tolerance; an intentionally truncated fixture fails with line-level diagnostics

 Step J2 — Lessons.jsonl consumption test (Sonnet, 45 min)

 - Add fixture tests/fixtures/lessons_sample.jsonl with 5 lesson rows
 - Add test tests/test_single_idea_orchestrator.py::test_phase_2_consumes_lessons — invokes Phase 2 with a mocked seed and the fixture in place, asserts the drafter prompt includes at least 1 lesson line
 - If not consuming: patch pipeline/single_idea.py:phase_2_draft_v0 to load top-K lessons from lessons.jsonl and inject into the drafter agent context
 - Acceptance: test passes; running Station-Tolerance twice in a row shows the second run's draft incorporating a lesson signal

     │ - Add fixture-based test tests/test_loop_controller.py::test_telemetry_emitted that runs a 3-iter mock loop and asserts the JSON shape                                                                                                       │
     │ - Acceptance: re-running the Station-Tolerance theme produces a loop_telemetry.json with non-zero iters_used for L2 (amplification) and terminated_by: "plateau"                                                                             │
     │                                                                                                                                                                                                                                              │
     │ Step I4 — Cost sidecar (Sonnet, 20 min)                                                                                                                                                                                                      │
     │                                                                                                                                                                                                                                              │
     │ - Modify pipeline/single_idea.py to snapshot pipeline.quota.consumed_this_week() BEFORE and AFTER each phase                                                                                                                                 │
     │ - Write runs/<id>/cost.json with per-phase {tokens_in, tokens_out, model} deltas and a total block                                                                                                                                           │
     │ - Acceptance: cost.json exists per run; sum of phase totals matches data/quota.jsonl rows for that run_id                                                                                                                                    │
     │                                                                                                                                                                                                                                              │
     │ Step I5 — Hidden-attr embodiment audit (manual + Sonnet, 30 min)                                                                                                                                                                             │
     │                                                                                                                                                                                                                                              │
     │ - Read runs/2026-05-12-171157-station-tolerance/seed.json — extract hidden_attrs                                                                                                                                                             │
     │ - For each of the 12 attribute values, find the corresponding prose location in Station-Tolerance.md using the mapping table in Inputs/STYLE_GUIDE.md                                                                                        │
     │ - Score each as EMBODIED / PARTIAL / MISSING / VIOLATED-LABEL-LEAKED                                                                                                                                                                         │
     │ - Write findings to runs/2026-05-12-171157-station-tolerance/embodiment_audit.md                                                                                                                                                             │
     │ - If any attribute is MISSING or VIOLATED, file one specific patch instruction back to .claude/agents/concept-narrator.md (e.g., "if booker=Voyage and Return then synopsis must follow depart→ordeal→return-changed in 3 distinct           │
     │ paragraphs")                                                                                                                                                                                                                                 │
     │ - Acceptance: audit file written; if patches were needed, narrator agent updated; re-run on Station-Tolerance and confirm improvement                                                                                                        │
     │                                                                                                                                                                                                                                              │
     │ Wave J — Operator ergonomics & test depth (Pareto P1, ~3 hours, separate session)                                                                                                                                                            │
     │                                                                                                                                                                                                                                              │
     │ Step J1 — Strengthen template compliance eval (Sonnet, 30 min)                                                                                                                                                                               │
     │                                                                                                                                                                                                                                              │
     │ - Open evals/test_template_compliance.py                                                                                                                                                                                                     │
     │ - Add assertions for every required V2 H2/H3 subsection (parse Inputs/CONCEPT_TEMPLATE_V2.md, extract each ## and ###, require each as a regex match in the candidate .md)                                                                   │
     │ - Series-only subsections (Series Engine) are conditional on seed.json:target_format == "series"                                                                                                                                             │
     │ - Add 2 fixtures: a complete .md (PASS) and a 4-H1-only .md (FAIL with specific missing subsections)                                                                                                                                         │
     │ - Acceptance: make eval still green on Station-Tolerance; an intentionally truncated fixture fails with line-level diagnostics                                                                                                               │
     │                                                                                                                                                                                                                                              │
     │ Step J2 — Lessons.jsonl consumption test (Sonnet, 45 min)                                                                                                                                                                                    │
     │                                                                                                                                                                                                                                              │
     │ - Add fixture tests/fixtures/lessons_sample.jsonl with 5 lesson rows                                                                                                                                                                         │
     │ - Add test tests/test_single_idea_orchestrator.py::test_phase_2_consumes_lessons — invokes Phase 2 with a mocked seed and the fixture in place, asserts the drafter prompt includes at least 1 lesson line                                   │
     │ - If not consuming: patch pipeline/single_idea.py:phase_2_draft_v0 to load top-K lessons from lessons.jsonl and inject into the drafter agent context                                                                                        │
     │ - Acceptance: test passes; running Station-Tolerance twice in a row shows the second run's draft incorporating a lesson signal                                                                                                               │
     │                                                                                                                                                                                                                                              │
     │ Step J3 — best_attempt.md fallback (Sonnet, 20 min)                                                                                                                                                                                          │
     │                                                                                                                                                                                                                                              │
     │ - Modify pipeline/single_idea.py:_finalize — when eval_gate fails on SOM<$100M after all loops, still emit runs/<id>/best_attempt.md with the highest-SOM draft seen during L2 + a clear eval.failure_summary in the same folder             │
     │ - Acceptance: synthetic test with cap-bounded SOM=$80M produces both best_attempt.md AND eval.json with verdict: HALT_SOM_BELOW_FLOOR; no final <Title>.md produced (correct behavior — investor doc requires gate pass)                     │
     │                                                                                                                                                                                                                                              │
     │ Step J4 — Operator dashboard (Sonnet, 30 min)                                                                                                                                                                                                │
     │                                                                                                                                                                                                                                              │
     │ - Create pipeline/runs_index.py (or extend existing pipeline/index_html.py)                                                                                                                                                                  │
     │ - Generates runs/index.html listing every run folder with: theme, timestamp, status, SOM, link to final .md, link to eval.json                                                                                                               │
     │ - Pure-Python (no LLM, no extra deps beyond stdlib)                                                                                                                                                                                          │
     │ - Wire into Makefile as make runs-index                                                                                                                                                                                                      │
     │ - Run after each make single                                                                                                                                                                                                                 │
     │ - Acceptance: open runs/index.html in browser → see all 2+ runs in a sortable table                                                                                                                                                          │
     │                                                                                                                                                                                                                                              │
     │ Step J5 — Three-theme stability check (Sonnet, 60 min)                                                                                                                                                                                       │
     │                                                                                                                                                                                                                                              │
     │ - Run make single THEME="<theme A>", make single THEME="<theme B>", make single THEME="<theme C>" with three deliberately different premises (e.g., one zeitgeist-aligned, one timeless, one bicultural)                                     │
     │ - For each: confirm eval gate passes, SOM ≥ $100M, template strict, no ID leaks                                                                                                                                                              │
     │ - Compile a 1-page runs/v4_stability_report.md with the 3 outcomes and any cross-run drift observed                                                                                                                                          │
     │ - Acceptance: 3-of-3 pass on Tier-1 evals; report committed                                                                                                                                                                                  │
     │                                                                                                                                                                                                                                              │
     │ Wave K — Deferred (Pareto P2, future)                                                                                                                                                                                                        │
     │                                                                                                                                                                                                                                              │
     │ ┌─────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────┐                                                     │
     │ │ K#  │                                                Improvement                                                 │                              Trigger                              │                                                     │
     │ ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤                                                     │
     │ │ K1  │ Russian translation round-trip with Haiku MT + Sonnet naturalness scorer                                   │ When ≥1 investor in Russian-speaking territory expresses interest │                                                     │
     │ ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤                                                     │
     │ │ K2  │ Resume-mid-amplification test (extend test_resume.py to kill -9 in Phase 4 iter 3)                         │ When a production run actually crashes mid-amplification          │                                                     │
     │ ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤                                                     │
     │ │ K3  │ Animation / documentary / hybrid format-specific subroutines (different V2 template variants)              │ When the user requests a non-feature/non-series concept           │                                                     │
     │ ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤                                                     │
     │ │ K4  │ Concept-narrator extended thinking budget tuning (currently default)                                       │ If Wave J5 detects narrator quality regression on theme C         │                                                     │
     │ ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤                                                     │
     │ │ K5  │ Auto-seed combinatorics from 02_conflict_ontology.md × macro-signal weighting (replace manual --theme arg) │ When operator wants 1-click daily idea generation                 │                                                     │
     │ └─────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────┘                                                     │
     │                                                                                                                                                                                                                                              │
     │ Verification of the improvement plan                                                                                                                                                                                                         │
     │                                                                                                                                                                                                                                              │
     │ After Wave I completes:                                                                                                                                                                                                                      │
     │ - make test && make eval && make eval-single all green                                                                                                                                                                                       │
     │ - runs/<latest>/loop_telemetry.json and runs/<latest>/cost.json exist with non-empty data                                                                                                                                                    │
     │ - runs/2026-05-12-171157-station-tolerance/embodiment_audit.md exists, score per attribute documented                                                                                                                                        │
     │ - Either second run completed OR halted run archived with diagnosis                                                                                                                                                                          │
     │ - RESUME.md updated to "Wave I — post-build hardening complete"                                                                                                                                                                              │
     │                                                                                                                                                                                                                                              │
     │ After Wave J completes:                                                                                                                                                                                                                      │
     │ - make eval enforces every V2 H2/H3 subsection                                                                                                                                                                                               │
     │ - make single twice in a row → second run shows lesson influence                                                                                                                                                                             │
     │ - runs/index.html browsable                                                                                                                                                                                                                  │
     │ - 3-theme stability report shows uniform success                                                                                                                                                                                             │
     │                                                                                                                                                                                                                                              │
     │ Why this improvement set respects Pareto                                                                                                                                                                                                     │
     │                                                                                                                                                                                                                                              │
     │ Five P0 items × ~30 min each = one session, addresses every observed gap that affects QUALITY OR REPRODUCIBILITY. The four P1 items address ergonomics and test depth — high value but not blocking. The five P2 items are explicit "wait    │
     │ for trigger" — don't build until needed.                                                                                                                                                                                                     │
     │                                                                                                                                                                                                                                              │
     │ Total new code estimate: ~250 LOC across loop_controller.py, single_idea.py, runs_index.py. Total new test code: ~200 LOC. No new agents, no new skills, no new ADRs. The system shipped; this hardens it.                                   │
     │                                                                                                                                                                                                                                              │
     │ Sonnet is cleared to execute Wave I immediately in a fresh session by reading this appendix, running steps I1→I5 in order (I1 first because it's a 5-min unblock, then I2 because the second run gives us a second data point for I3–I5).  