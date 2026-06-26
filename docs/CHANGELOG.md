# Anomaly Engine v3.0 — CHANGELOG

## v3.0 — 2026-05-08

### Build

**Architecture:** 6-phase combinatorics pipeline (Asset Miner → JTBD Mapper →
Audience Validator → Concept Forger → Adversarial Critic → A4 Formatter). GoT
operator graph (stub, ships in v1.x). 3-key FIFO OpenRouter rotation.
BudgetExceeded + KeyboardInterrupt graceful stop with per-concept JSONL
checkpointing. Pure-Python scoring (ADR-0002: LLMs MUST NOT compute scores).

**Phases built:**

- P0 — Harness skeleton & durability substrate (ADR-0001..0006; hooks; secret
  management; state write protocols)
- P1 — Knowledge layer (6 frameworks; 3 data source registries; asset miner
  corpus; scoring formula)
- P2 — Prompt registry (6 phase prompts; anti-slop registry; temperature and
  reasoning-level specs)
- P3 — Pipeline code (CLI orchestrator; schema; OpenRouter client; 3-key
  rotation; run.py phases 1–6)
- P4 — Evals + tests + recovery eval (9 evals; 47 tests; golden JSONL fixtures;
  recovery sentinel)
- P5 — Operations & stabilization mechanics (init-project.sh; refresh-prices;
  stabilization queue wire; make stabilize)
- P6 — Stabilization seed & v1 ship (golden A4 fixtures; rejected anchors;
  CHANGELOG; tests)

**17 artifacts shipped:**

1. `prompts/01-asset-miner.md` — Phase 1 prompt (Perplexity Sonar deep-research,
   temp=0.3)
2. `prompts/02-jtbd-mapper.md` — Phase 2 prompt (Claude Sonnet 4.6 extended-
   thinking, temp=1.0 required by Anthropic API)
3. `prompts/03-audience-validator.md` — Phase 3 prompt (Claude Sonnet 4.6;
   system block minimal for Sonar compatibility)
4. `prompts/04-concept-forger.md` — Phase 4 prompt (Claude Sonnet 4.6 default;
   Opus 4.7 Forge on quality+budget two-gate per ADR-0006)
5. `prompts/05-adversarial-critic.md` — Phase 5 prompt (Claude Opus 4.7 critic;
   temp=1.0; stabilization_pattern_to_add_to_anti_slop field wired to queue)
6. `prompts/06-a4-formatter.md` — Phase 6 prompt (Claude Haiku 4.5 formatter;
   temp=0.0 for deterministic rendering; 12-section A4 format)
7. `prompts/anti_slop.md` — Anti-slop registry with 80+ banned patterns across
   5 categories; human-gated via STAB-02 PreToolUse hook
8. `frameworks/narrative-master-grid.md` — 36 Polti dramatic situations × 20
   Tobias master plots collision matrix; forced-combination table
9. `frameworks/sdt-spine.md` — Self-Determination Theory backbone; autonomy /
   competence / relatedness axes; deprivation amplifier; Al-Bukhari worked example
10. `frameworks/ajtbd-segmentation.md` — Audience JTBD segmentation framework;
    50M floor hard requirement; sources_per_claim validation
11. `frameworks/forced-collision.md` — TRIZ contradiction framework; 40
    inventive principles mapped to cinematic situations; irreversibility test
12. `frameworks/character-arcs.md` — 7 canonical character arc patterns with
    SDT mapping; arc-contradiction alignment table
13. `frameworks/cinema-school-doctrines.md` — 12 international cinema school
    doctrines (Soviet, French New Wave, Iranian, Danish Dogme, Korean New Wave,
    etc.) with operational integration notes
14. `pipeline/scoring.py` — Pure-Python scorer; sdt_score, ajtbd_score,
    upstream_score, critic components, total_score; LLMs never write to
    total_score field (ADR-0002 model_validator)
15. `pipeline/run.py` — Typer CLI orchestrator; --n, --seed, --theme, --paid-ok,
    --quality-pass flags; BudgetExceeded + Ctrl-C graceful stop; per-concept
    JSONL flushing; 6-phase dispatch loop; resume from last checkpoint
16. `evals/` — 9 evals: test_citations (EVAL-01), test_quotes (EVAL-02),
    test_audience (EVAL-03), test_anti_slop (EVAL-04), test_rate_limit (EVAL-05),
    test_school_checks (EVAL-06), test_score_floor (EVAL-07), test_cost_health
    (EVAL-08), test_resume (EVAL-09)
17. `scripts/audit.py` — On-demand verifier; 12 checks including anti_slop,
    quotes, citations, polti_threshold, concept format; `make audit` target

### Attributions

- Deep-research orchestration patterns adapted from
  [github.com/liangdabiao/Claude-Code-Deep-Research](https://github.com/liangdabiao/Claude-Code-Deep-Research)
- GoT operator graph inspiration from
  [github.com/spcl/graph-of-thoughts](https://github.com/spcl/graph-of-thoughts)

### Golden Fixtures

Three reference A4 concepts committed to `examples/golden/`:

- `HC-bukhari.md` — Score 96; Al-Bukhari hadith authentication vs AI deepfakes;
  2B Muslim audience; TRIZ inversion principle
- `HC-ostankino.md` — Score 92; Ostankino fire 1991; married journalists in
  elevator; Truth vs Belonging TRIZ contradiction
- `HC-mamontenok.md` — Score 88; Soyuzmultfilm × Yupik ice migration; 95M
  diaspora audience; local-quality TRIZ resolution

Four rejected anchors committed to `examples/rejected/`:

- `REJ-slop-logline.md` — Generic chosen-one sports arc; fails anti-slop + novelty
- `REJ-niche-audience.md` — Medieval astrolabe premise; audience TAM ~5M < 50M floor
- `REJ-no-triz.md` — ISS security dilemma without contradiction mechanism
- `REJ-bad-sourcing.md` — Sound structure; fails on bare-domain citation and
  uncorroborated audience claim

### Scoring Formula (current)

```
sdt_score   = min(round((50 * s1 * amp) + (20 * s2)), 70)  if s1 >= 0.7 else 0
ajtbd_score = 30  if audience_size >= 50_000_000 else 0
upstream    = sdt_score + ajtbd_score   (max 100)
critic_sum  = novelty(0-30) + jtbd(0-25) + contradiction(0-25) + specificity(0-20)
total_score = round(upstream * 0.5 + critic_sum * 0.5) + agreement_bonus
```

Cap: total_score is capped at 70 if cap_at_70_triggered (incompetent forger).
Floor: concepts with total_score < 85 are rejected; only scored by scoring.py
(ADR-0002).
