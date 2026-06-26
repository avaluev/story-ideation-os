# Repository Structure — Anomaly Engine

> Authoritative, code-verified map of the repository layout and the engine's
> layers. When this document and a legacy map disagree, **this document wins**;
> the older `docs/CODEMAP.md` / `docs/CODEBASE_MAP.md` predate several
> subsystems (`crystallize/`, `veracity/`, `research/`, `select/`).
>
> Last verified against `main` on 2026-06-26.

---

## 1. How to read this repo

The Anomaly Engine is a **file-durable, LLM-orchestrated film/series concept
generator**. Two design rules explain almost every structural choice:

1. **State lives on disk, never only in agent context** (ADR-0001). Each
   pipeline phase reads and writes JSON/JSONL files; an interrupted run resumes
   from those files, not from memory.
2. **LLMs never do arithmetic or pick scores** (ADR-0002). All numeric scoring,
   revenue projection, and gate logic is pure Python. Models draft prose; Python
   decides numbers.

The policy that enforces these (and ten more) is the root **`CLAUDE.md`**
(mirrored byte-for-byte by **`AGENTS.md`**). Every MUST / MUST NOT rule there is
tied to a mechanical enforcer — an ADR, a test, or a lint rule. If you change
behavior, start by reading `CLAUDE.md`.

---

## 2. Top-level layout

```
29.Engine/
├── CLAUDE.md / AGENTS.md     Policy gateway (byte-equal mirrors). Read first.
├── README.md                 Operator quick-start.
├── Makefile                  Entry points: make test | eval | lint | audit | run.
├── pyproject.toml / uv.lock  Python project + locked deps (uv).
├── lefthook.yml              Pre-commit/-push git hooks (gitleaks, tests).
├── .gitleaks.toml            Secret-scan config.
├── .env.example              Documented env vars (the real .env is gitignored).
│
├── pipeline/                 ★ THE ENGINE. All runtime code. See §4.
├── tests/         (179)      Unit/contract tests; many double as MUST enforcers.
├── evals/         (34)       Behavioral eval gates (make eval); investor-surface checks.
├── scripts/       (82)       Operator + maintenance CLIs (corpus fetch, handoff build…).
├── frameworks/    (16)       READ-ONLY creative doctrine (TRIZ/McKee/Polti…). ADR-0005.
├── prompts/       (10)       Agent prompt source (anti-slop, formatters…).
├── config/         (2)       Static engine config.
│
├── docs/          (47)       ★ Documentation. ADRs, C4 architecture, this file. See §6.
├── .planning/                GSD planning state + handoffs (tracked per MEM-11).
│
├── data/                     Corpora, seeds, leaderboard (selective whitelist). See §7.
├── pipeline/data/            Tracked framework data (oblique strategies, vectors…).
├── runs/                     Per-run outputs (curated NARRATOR sessions tracked).
├── outputs/                  Rendered deliverables (portfolio cards, slates).
├── out/         (1479)       v3.1 Path-C batch deliverable (1000+ story corpus).
│
├── Inputs/                   Operator briefs (gitignored except framework contracts).
├── ideas/ seeds/ sources/    Source material + seed CSVs.
├── requirements/             REQUIREMENTS.md + VALIDATION_HARNESS (DoD contracts).
├── _deprecated/   (62)       Quarantined v3 batch pipeline. Dead; kept for reference.
│
├── .claude/                  Claude Code harness: agents, hooks, skills, workflows.
└── .codex/                   Codex CLI harness mirror (agents + hooks). See §8.
```

Counts in parentheses are tracked-file counts at time of writing.

---

## 3. The engine in eight layers

Data flows top-to-bottom; every arrow crosses a file on disk.

| # | Layer | Where | Responsibility |
|---|-------|-------|----------------|
| 1 | **State substrate** | `pipeline/state.py` | Atomic `safe_write` (tmp+fsync+rename), `append_jsonl`, handoff & checkpoint contracts. ADR-0001. |
| 2 | **Dispatch & quota** | `cc_dispatch.py`, `run_cc.py`, `research_dispatch.py`, `quota.py`, `key_manager.py` | Plan Task fan-out manifests; gate Opus on weekly quota (ADR-0008); mask secrets in logs (ADR-0003). Models are called by the orchestrating skill, not by Python (ADR-0007). |
| 3 | **Generation** | `compound_seed.py`, `seed_engine.py`, `seed_picker.py`, `operators/`, `evolve/one_shot.py`, `axes/` | Sample one compound seed from the ~19-trillion-combination space (anti-overfit weighted, ADR-0012); expand into a draftable concept. |
| 4 | **Scoring & gates** | `scoring.py`, `empirical_genius.py`, `schema.py`, `eval_gate.py`, `loop_controller.py`, `template_filter.py` | Pure-Python 5-axis score (ADR-0002); EGI kill-switches; bounded patch loops L1–L5 (ADR-0009); strip internal IDs before any investor file (ADR-0010). |
| 5 | **Economics** | `crystallize/` (`revenue.py`, `comps.py`, `corpus.py`, `score.py`, `board.py`, `html_export.py`) | Match against the film corpus for real comps + ROI; project SOM/SAM/TAM via `revenue.project_revenue` (ADR-0011). |
| 6 | **Evidence & veracity** | `research/` (`evidence_router.py`, `gateways/`, `value_on_page.py`) + `veracity/` (`enumerate → probe → assess → verdict → scorecard`) | Multi-gateway sourcing; reality-check every numeric claim against a primary URL; deep-link verification. |
| 7 | **Selection & feedback** | `select/diversity_select.py`, `leaderboard.py`, `labels.py`, `feedback.py`, `lessons_loader.py` | Cross-run leaderboard, diversity selection, operator-rating ingestion. |
| 8 | **Rendering & output** | `export_html.py`, `index_html.py`, `digest.py`, `quality_report.py`, `crystallize/html_export.py` | Investor-facing markdown/HTML; passes through the §4 output filter. |

---

## 4. `pipeline/` package map

**Two pipelines share these layers:**

- **Single-Idea v4** (`single_idea.py`, `run_single_idea.py`) — the current
  default. Ten phases, recursive patch loops:
  `seed_capture(0) → research(1) → draft_v0(2) → challenge(3) → amplify(4) →
  genius_audit(5) → consistency(6) → investor_narrator(7) → eval_gate(8) →
  lessons_capture(9)`. Phase agents live in `.claude/agents/`; the canonical
  per-phase sidecar is `draft_v0.json` and siblings.
- **Batch v3** (`run.py`) — legacy 5-phase miner→mapper→validator→forger→critic
  writing `data/0X_*.jsonl`. Superseded; retained for the corpus it produced.

**Top-level modules** (grouped by §3 layer):

```
state.py  schema.py                         (1) durability + Pydantic guards
cc_dispatch.py  run_cc.py  research_dispatch.py
quota.py  key_manager.py  llm_client.py  openrouter_client.py
tmdb_client.py  sonar_cache.py             (2) dispatch / quota / clients
compound_seed.py  seed_engine.py  seed_picker.py  seed_moa.py
campaign_goal.py  goal.py  zeitgeist_probe.py  diversity.py   (3) generation
scoring.py  empirical_genius.py  eval_gate.py  loop_controller.py
loop_wedge.py  consistency.py  template_filter.py
evaluate_draft_quality.py  score_postprocess.py  scorecard.py  (4) scoring/gates
audience_amplifier.py  micro_amplify.py  commercial_prescreen.py
evidence_gate.py  metrics.py  phase_timing.py                  (4/6) amplify + evidence
plan_compliance.py  bridge.py  kb.py  lessons_loader.py        cross-cutting
export_html.py  index_html.py  digest.py  quality_report.py    (8) rendering
```

**Subpackages:** `axes/` (per-axis prose scorers), `crystallize/` (economics),
`evolve/` (one-shot evolve loop), `operators/` (MAP-Elites operators — note:
`generate/improve/keep_best/score/validate` are forward-stubs that raise
`NotImplementedError`), `research/` (`gateways/`, `providers/`), `select/`,
`veracity/`, `data/` (tracked framework data).

---

## 5. Governance & enforcement layer

| Artifact | Role |
|----------|------|
| `CLAUDE.md` / `AGENTS.md` | The contract. ≤250 lines; every MUST line names an enforcer (`tests/test_claude_md_*`). |
| `docs/adr/0001–0012` | Architecture Decision Records. The "why" behind each invariant. |
| `scripts/lint_imports.py` | ANOMALY-001 (no LLM imports in `scoring.py`/dispatch), -002 (no `frameworks/` imports), -003 (no orphan modules). `make lint`. |
| `lefthook.yml` | Git hooks: gitleaks pre-push, formatting, fast tests. |
| `.claude/hooks/` (8) | Runtime guardrails: `pre_bash_gate` (blocks `rm -rf` outside data/out/cache, `curl`, `--no-verify`), `pre_protect` (blocks edits to protected config), `stop_verify` (enforces test+eval before "done"). |
| `requirements/VALIDATION_HARNESS.md` | Maps requirement IDs → eval tests (e.g. `MOBILE.md` ≤80 lines is eval-pinned). |

**Stop gate (before declaring work done):** `make test && make eval` must pass,
and `.planning/state/RESUME.md` must be newer than the latest run-log event.

---

## 6. Documentation map (`docs/`)

- **Start here:** `INDEX.md` → this file (`REPOSITORY_STRUCTURE.md`) → `ARCHITECTURE.md`.
- **Decisions:** `adr/` (12 ADRs + README).
- **C4 model:** `architecture/01-c1-system-context` … `06-glossary`.
- **Schema:** `report_v4_schema.md` ↔ `pipeline/schema.py` (kept in sync; the
  v4 report contract).
- **Design history:** `design/v4-lean-single-idea-plan.md` (the plan that
  produced the current pipeline).
- **Operator guides:** `OPENROUTER_GUIDE.md`, `INVESTOR_QUICKSTART.md`,
  `NEXT_SESSION_PLAYBOOK.md`, `quarterly-review-template.md`.

> Known stale docs (tracked as backlog, not yet reconciled): `CODEMAP.md` /
> `CODEBASE_MAP.md` omit the newer subpackages; some investor quick-starts still
> describe OpenRouter as the primary gateway (superseded by ADR-0007). Prefer
> `architecture/03-c3-components.md` and this file for the current shape.

---

## 7. Data, outputs & what is (not) tracked

The engine produces a lot of regenerable artifacts, so `.gitignore` is
**whitelist-shaped**: directories are excluded, then specific durable files are
re-included.

| Tracked (durable / curated) | Gitignored (transient / regenerated) |
|---|---|
| `data/seeds/`, `data/glossary_master.json`, `data/leaderboard.{jsonl,csv}`, `data/top_ideas_*` | `data/*` runtime, `data/state/`, `data/0X_*.jsonl` batch logs |
| `pipeline/data/*` (framework data) | `runs/_cache/`, `runs/research/`, `runs/evolve-*/`, `runs/format-slate/` |
| `runs/portfolio/*-portfolio.json` (curated run history), `runs/<date>-<slug>/` NARRATOR sessions | `outputs/**/_provenance/`, `outputs/**/_widen_dna/` (workflow scratch) |
| `out/concepts/v3.1-pathc*`, `out/index.html` | other `out/*`, `htmlcov/`, caches |

**Secrets:** the only secret-bearing file is `.env` (gitignored). `Inputs/` is
gitignored except the framework contracts. `make test` includes
`test_secret_leak.py`; `lefthook` runs gitleaks on push. **No credential ever
belongs in a tracked file.**

---

## 8. Harness & handoff layers

- **`.claude/`** — the Claude Code harness this repo runs under: 15 phase agents,
  8 guardrail hooks, 3 user skills, 5 workflows, `settings.json` (sandbox/permissions).
- **`.codex/`** — a parallel **Codex CLI** harness: `agents/*.toml` mirrors of the
  Claude agents + `hooks/*.py` ports of the same guardrails, wired by `hooks.json`.
  This lets the same pipeline run under either CLI.
- **External handoff** — the investor/operator deliverable bundle is built by
  `scripts/build_handoff_tarball.sh` to a sibling directory **outside the repo**
  (`../29.Engine-handoff/`). It may carry live credentials and is therefore
  never tracked; `.gitignore` blocks `handoff_vladimir/` and
  `TELEGRAM_FOR_VLADIMIR.txt` as a backstop.

---

## 9. Quick orientation for a new contributor

1. Read `CLAUDE.md` (the rules) and `docs/adr/README.md` (the why).
2. Run `make test && make eval` to confirm a green baseline.
3. To trace a run: `pipeline/single_idea.py` → phase agents in `.claude/agents/`
   → sidecars under `runs/<id>/` → scoring in `pipeline/scoring.py`.
4. Touch numbers only in Python (ADR-0002); touch state only via
   `pipeline/state.py` (ADR-0001); never import from `frameworks/` (ADR-0005).
