# Anomaly Engine v4 — Documentation Index

Welcome. This index guides you through the complete system documentation.

---

## For Investors & Decision-Makers

**Start here:** [`system_overview.html`](system_overview.html) (15 min read)

This is a beautifully formatted, browser-viewable guide that covers:
- System overview & key metrics (4.6M data points, 29 amplification vectors, 10 phases)
- Dataset breakdown (conspiracy engines, cultural signals, archetype libraries)
- Scalability drivers (plateau detection, pure Python scoring, synergy detection)
- Quality gates (6 checkpoints from research → investor markdown)
- Performance metrics (30–90 min runtime, $4–18 per concept)
- Competitive advantages (no hallucinations, auditable scoring, reproducible results)

**Then read:** [`ARCHITECTURE.md`](ARCHITECTURE.md) (20 min read)

Technical deep-dive covering:
- All 10 pipeline phases in detail
- 5 recursive loops (challenge, amplification, genius, consistency, narrator)
- Dataset breakdown (~4.6M points across 10 dictionaries)
- Why plateau detection matters (= cost predictability)
- Pure Python scoring (ADR-0002: why no LLM touches financial numbers)
- Model allocation (Sonnet vs Opus strategy)

---

## For Engineers & Architects

**Start here:** [`CODEMAP.md`](CODEMAP.md) (15 min read)

Complete file structure, dependencies, and data flows:
- Directory tree with role explanations
- Key files and what they do
- Phase-by-phase data flow diagram
- Critical ADRs (Architecture Decision Records)
- Build targets and test commands
- Common workflows (adding vectors, updating signals, debugging)

**Then read:** [`ARCHITECTURE.md`](ARCHITECTURE.md) (sections on technical stack & quality gates)

---

## For Operators & DevOps

**Start here:** README.md (top-level project README)

Then:
1. **Check:** `Makefile` for available commands
   ```bash
   make single THEME="..."     # Run one concept
   make eval-single            # Evaluate last run
   make test                   # Run unit tests
   make eval                   # Run full eval suite
   ```

2. **Deploy:** Use `pyproject.toml` + `uv.lock` for reproducible environment
   ```bash
   uv venv
   uv sync
   ```

3. **Batch mode:** Schedule nightly runs
   ```bash
   0 22 * * * cd /path/to/29.Engine && \
     for theme in "Theme 1" "Theme 2" ...; do \
       uv run python -m pipeline.run_single_idea --theme "$theme"; \
     done
   ```

4. **Monitor:** Check `runs/` directory for output; read `eval.json` in each run

---

## For Product Managers

**Key metrics to track:**

| Metric | Target | Current |
|--------|--------|---------|
| SOM ≥ $100M | 100% of runs | ~94% |
| Runtime | ≤90 min | 30–90 min avg |
| Cost/concept | $4–18 | $6–14 avg |
| Citation coverage | 100% | 99.5% |
| Internal-ID leaks | 0 | 0 (100% compliance) |
| Concept archive size | 200+ | 180+ |

**Quality gates:** 6 total. All automated. See `ARCHITECTURE.md` for gate details.

**Scalability:** Currently 1 run at a time. Fully resumable = safe for batch processing 50–100 concepts/week.

---

## For Researchers & Data Scientists

**Knowledge bases** live in `frameworks/data/`:

| Dictionary | Entries | Update Freq | Use Case |
|-----------|---------|------------|----------|
| protagonist_archetypes.json | 254 | Quarterly | Character psychology |
| conspiracy_engines.json | 2,057 | Monthly | Plot structures |
| open_problems_science.json | 999 | Monthly | Innovation themes |
| cultural_moment_2026.json | 493 | Weekly | Zeitgeist signals |
| reptile_triggers.json | 505 | Quarterly | Emotional hooks |
| (+ 5 more) | ~4.6M total | See table | See ARCHITECTURE.md |

**How to experiment:**
1. Create variant: `cultural_moment_2026_v2.json`
2. Update `amplification_vectors.json` to reference variant
3. Re-run pipeline
4. Compare outputs via `evals/`

No code changes needed. Pure data experimentation.

---

## For New Contributors

1. **Read `CLAUDE.md`** at root — hard rules (MUST/MUST NOT with enforcement)
2. **Read [`REPOSITORY_STRUCTURE.md`](REPOSITORY_STRUCTURE.md)** — the current, code-verified layout & layer map
3. **Run tests:** `make test`
4. **Try one run:** `make single THEME="your theme"`
5. **Inspect output:** `runs/{timestamp}-{slug}/`
6. **Check compliance:** `make filter-check` (internal-ID scan)

---

## Document Map

| Document | Purpose | Audience | Read Time |
|----------|---------|----------|-----------|
| [`system_overview.html`](system_overview.html) | Visual investor pitch | Investors, execs | 15 min |
| [`REPOSITORY_STRUCTURE.md`](REPOSITORY_STRUCTURE.md) | Current layout & 8 engine layers | Engineers, contributors | 12 min |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Technical deep-dive | Engineers, architects | 20 min |
| [`CODEMAP.md`](CODEMAP.md) | File structure & flows (legacy — see REPOSITORY_STRUCTURE) | Engineers, operators | 15 min |
| `CLAUDE.md` (root) | Hard rules & ADRs | All | 10 min |
| `README.md` (root) | Quick start | All | 5 min |
| `Makefile` | Build targets | Operators, devs | 5 min |
| `docs/adr/` | Architecture decisions | Architects | As needed |

---

## Key Concepts

### Plateau Detection (Why It Matters)
The system measures convergence in loops instead of fixed iteration counts. Example:
- Challenge loop caps at 3 patches, but usually exits after 1 if the concept passes adversarial review
- Amplification loop caps at 5 iterations, but usually converges in 2–3
- Result: 30–45 min typical, 90 min worst-case (vs. all concepts hitting 90 min)

### Pure Python Scoring (Why It Matters)
All financial numbers come from executed Python code, not LLM outputs. Benefits:
- **Auditable:** `SOM = base_audience_M * total_multiplier * 1000 * revenue_per_viewer_usd`
- **Reproducible:** Same input = same score, always
- **Fast:** Python (ms) vs LLM (seconds)
- **Free:** Doesn't consume model quota

### Compound Amplification Vectors (Why It Matters)
29 audience multipliers with synergy detection. Non-linear multiplication:
- A-Grade Cast alone: 1.4x
- Prestige Director alone: 1.5x
- Together + synergy: **2.73x** (not 2.9x additive)

Better vectors → higher SOM → more compelling investor pitch.

### Atomic State Writing (Why It Matters)
Every phase writes JSON to disk. Resumable execution:
- Crash at Phase 7? Resume from Phase 8, zero re-work
- Batch job interrupted? Continue later with full state preserved
- Debugging: all intermediate outputs saved for inspection

---

## Frequently Asked Questions

**Q: Can I run 10 concepts in parallel?**  
A: Not yet. System is designed for 1 sequential run. But resumable state = safe for nightly batch (run sequentially overnight, 100+ concepts/week).

**Q: Can I customize the 4-section template?**  
A: No. Template is enforced per ADR and `Inputs/CONCEPT_TEMPLATE_V2.md`. But agents have flexibility within sections.

**Q: What if SOM comes out <$100M?**  
A: Hard gate. Pipeline halts with actionable feedback. Either amplify more, accept as early-stage, or abandon concept.

**Q: Where are all the concepts saved?**  
A: `runs/` directory. Each run has a timestamp + slug. Also archived in `data/04_concepts.jsonl`.

**Q: Can I modify knowledge base dictionaries?**  
A: Yes. They're just JSON files. Swap `cultural_moment_2026.json` between runs. No code changes needed.

**Q: What's the cost breakdown?**  
A: ~$4–8 for Sonnet-heavy phases, +$4–10 if using Opus for narrator/positioning. Python/evals are free.

**Q: How do I add a new kill-switch criterion (C008)?**  
A: Edit `Inputs/GeniusFilm/GREATNESS_CHECKLIST.json`, update `genius-auditor.md` agent, re-run pipeline. Gate will enforce new criteria.

---

## Next Steps

- **Decision needed?** Read `system_overview.html`
- **Building something?** Read `CODEMAP.md` + `CLAUDE.md`
- **Running batch?** Check `Makefile` and set up cron
- **Contributing?** Start with `make test`, then pick a task from GitHub issues

---

## Contact & Support

- **Issues:** GitHub (avaluev/big-ideas, private)
- **Questions:** Email or Slack with "Anomaly Engine" in subject
- **Feedback:** Create an issue with detailed context

---

*Last updated: 2026-05-14*  
*Anomaly Engine v4.0 — Single-Idea Pipeline*  
*One theme in. One investor-grade concept out. No hallucinations. No internal IDs.*