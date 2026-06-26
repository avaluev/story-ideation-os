---
name: single-idea
description: |
  Single-Idea Pipeline v4.0 — 10-phase orchestrator (seed_capture → research →
  draft_v0 → challenge → amplify → genius_audit → consistency_check →
  investor_narrator → eval_gate → lessons_capture) for one film/series concept.
  Implements L1/L3/L4 patch retry loops capped by loop_controller.patch_budget(),
  L2 plateau-checked amplification, and L5 narrator-redo (max 2 rounds).
  Use when the operator types /single-idea or asks to run the single-idea pipeline.
---

# /single-idea — Single-Idea Pipeline v4.0

## Invocation

```
/single-idea --theme "..."
/single-idea --theme "..." --run-id 2026-05-12-110000-custom
/single-idea --resume --run-id 2026-05-12-110000-custom
```

| Flag | Default | Role |
|------|---------|------|
| `--theme STR` | required | Film/series pitch sentence |
| `--run-id STR` | auto (timestamp-slug) | Stable run identifier |
| `--resume` | off | Resume from last completed phase |

## Deliverables

All files land in `runs/{run_id}/`:

| File | Phase | Contents |
|------|-------|----------|
| `seed.json` | 0 | theme, target_format, conflict_axes |
| `research.json` | 1 | audience sizing, comps, cultural moment |
| `{title-slug}.md` | 2 | investor concept (V2 template) |
| `draft_v0.json` | 2 | structured draft sidecar |
| `challenge.json` | 3 | 11 P0 kill-switch audit |
| `amplification.json` | 4 | compound SOM multiplier trail + som_history |
| `genius.json` | 5 | C001–C007 originality audit |
| `consistency.json` | 6 | cross-sidecar drift check |
| `{title-slug}-NARRATOR.md` | 7 | investor companion |
| `eval.json` | 8 | eval gate results |
| `lessons.json` | 9 | session learnings |

## Loop Topology (ADR-0009)

| Loop | Trigger | Agents | Cap |
|------|---------|--------|-----|
| L1 | challenge.json verdict == FAIL | concept-drafter (l1_patch) → concept-challenger | 3 rounds |
| L2 | amplifier runs | audience-amplifier (internal) | 5 iters or plateau <5% |
| L3 | genius.json verdict == FAIL | concept-drafter (l3_patch) → genius-auditor | 3 rounds |
| L4 | consistency.json severity == HIGH or MEDIUM | concept-drafter (l4_patch) → consistency-checker | 3 rounds |
| L5 | eval.json verdict == FAIL (Tier-1 gates) | concept-narrator (redo) | 2 rounds |

---

## Algorithm (12 steps)

### STEP 1 — INIT

Run the init CLI to create the run directory and write seed.json:

```bash
uv run python -m pipeline.run_single_idea --theme "{theme}" {--run-id {run_id}} {--resume}
```

Read the JSON printed to stdout. Extract `run_dir`, `run_id`, `current_phase`, `current_phase_name`.

Print to operator:
```
Run ID:    {run_id}
Run dir:   {run_dir}
Resume:    {current_phase_name} (phase {current_phase})
```

### STEP 2 — PHASE 0: seed_capture

If `current_phase > 0`: skip (seed.json already exists).

Verify seed.json was created:
```bash
cat {run_dir}/seed.json
```

The CLI wrote seed.json with `theme` and `target_format`. The concept-drafter will derive
hidden attributes from `Inputs/STYLE_GUIDE.md Section 2` when it runs.

### STEP 3 — PHASE 1: research (concept-researcher)

If `current_phase > 1`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 1 --phase-name research
```


**3a — Pre-fetch sonar evidence (cached, Cycle 1 Option A).**

Run the Python dispatcher to fetch cached sonar evidence BEFORE invoking the agent.
First run hits perplexity/sonar-pro and writes `{run_dir}/research_raw.json`;
subsequent runs with the same theme_slug within the same ISO week return cached
in ~0s. Skip entirely if `{run_dir}/research_raw.json` already exists from a prior
attempt of the same phase.

```bash
if [ ! -f "{run_dir}/research_raw.json" ]; then
  uv run python -c "
import json, sys
from pathlib import Path
from pipeline.research_dispatch import fetch_research_for_theme
seed = json.loads(Path('{run_dir}/seed.json').read_text(encoding='utf-8'))
# theme_slug: derive from run_id (timestamp+theme tail) or seed_slug if present
slug = seed.get('seed_slug') or '{run_id}'.split('-', 5)[-1] or 'anon'
try:
    fetch_research_for_theme(run_dir=Path('{run_dir}'), theme_slug=slug,
                             theme_text=seed['theme'])
    print('research_dispatch: OK')
except Exception as exc:
    # Soft-fail: agent will fall back to its own research path.
    print(f'research_dispatch: DEGRADED ({exc})', file=sys.stderr)
"
fi
```

**3b — Invoke the researcher agent.**

```
Task(subagent_type="concept-researcher",
     prompt="""Run the research protocol for the single-idea pipeline.

Run dir: {run_dir}
Theme: {theme}

1. Read {run_dir}/seed.json
2. **If {run_dir}/research_raw.json exists, READ IT FIRST.** It is the cached
   sonar-pro evidence (genre saturation, cultural moment, audience sizing) and
   is your primary source. Use its values verbatim. Only supplement with
   WebSearch for fields that are absent or null in research_raw.json.
3. Research audience sizing (global, ≥3 countries, cited source URL)
4. Research 3–5 comparable films (title, WW gross in USD, source URL)
5. Verify the cultural moment (one concrete data point, source URL)
6. Write {run_dir}/research.json with fields:
   - theme (str)
   - audience_size_global (int, ≥50M required)
   - audience_countries (list[str], ≥3 ISO-2 codes)
   - audience_source_url (str, deep-path URL)
   - comps (list of {title, ww_gross_usd_millions, source_url})
   - cultural_moment (str)
   - cultural_moment_source_url (str)
   - produced_at (ISO-8601)
""")
```

Wait for Task. Verify `{run_dir}/research.json` exists.

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 1 --phase-name research
```

### STEP 4 — PHASE 2: draft_v0 (concept-drafter, initial mode)

If `current_phase > 2`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 2 --phase-name draft_v0
```
 Read `{run_dir}/draft_v0.json` and extract `slug` for later steps.

```
Task(subagent_type="concept-drafter",
     prompt="""Generate the initial concept draft.

Mode: initial
Run dir: {run_dir}

Mandatory reads (in order):
1. Inputs/CONCEPT_TEMPLATE_V2.md — exact section structure and all fill rules
2. Inputs/STYLE_GUIDE.md — banned terms, FK ceiling, hidden-attribute prose mapping
3. {run_dir}/seed.json — theme, target_format
4. {run_dir}/research.json — audience sizing, comps, cultural moment

Map every hidden attribute from seed.json to its prose rule per STYLE_GUIDE Section 2.
These attributes shape your prose silently — never appear as labels.

Outputs:
- {run_dir}/{title-slug}.md (investor-facing markdown, V2 template)
- {run_dir}/draft_v0.json (structured sidecar with slug, logline, som_usd_millions, mode="initial", patch_round=0)
""")
```

Wait for Task. Read `{run_dir}/draft_v0.json`. Extract `slug` (use it as `{title_slug}` for all subsequent steps).

Evaluate draft quality (NB.11 — 5-vector sidecar gate):
```bash
uv run python -m pipeline.evaluate_draft_quality --run-dir {run_dir}
```


```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 2 --phase-name draft_v0
```

### STEP 5 — PHASE 3: challenge + L1 patch loop

If `current_phase > 3`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 3 --phase-name challenge
```


Get L1 budget:
```bash
uv run python -c "from pipeline.loop_controller import patch_budget; print(patch_budget('L1'))"
```

**Initial challenge pass:**
```
Task(subagent_type="concept-challenger",
     prompt="""Run the adversarial challenge (single-idea pipeline mode).

Run dir: {run_dir}

1. Read {run_dir}/{title_slug}.md
2. Read {run_dir}/draft_v0.json
3. Apply all 11 P0 kill-switches (structural, audience, commercial, originality, craft)
4. Write {run_dir}/challenge.json:
   - verdict: PASS | FAIL | REJECT_FINAL
   - failures: list[str] (empty on PASS)
   - conditions: list[str] (passed with caveats)
   - patch_notes: str (what to fix on FAIL)
   - produced_at: ISO-8601
""")
```

Read `{run_dir}/challenge.json`.

If `verdict == "REJECT_FINAL"`: **HALT** — concept cannot be salvaged. Reason: `challenge.failures`.

**L1 patch loop (verdict == "FAIL"):**
```
l1_round = 0
loop while challenge.verdict == "FAIL" AND l1_round < L1_budget:
    l1_round += 1

    Task(subagent_type="concept-drafter",
         prompt="""Apply an L1 patch (challenge failure fix).

Mode: l1_patch
Patch round: {l1_round}
Run dir: {run_dir}

1. Read {run_dir}/draft_v0.json (current draft + sections)
2. Read {run_dir}/challenge.json (failures + patch_notes)
3. Read Inputs/CONCEPT_TEMPLATE_V2.md and Inputs/STYLE_GUIDE.md
4. Fix ONLY the listed failures — surgical edits, do not rewrite unaffected sections
5. Overwrite {run_dir}/{title_slug}.md
6. Update {run_dir}/draft_v0.json: set mode="l1_patch", patch_round={l1_round}
""")

    Task(subagent_type="concept-challenger",
         prompt="""Re-run the adversarial challenge after L1 patch round {l1_round}.

Run dir: {run_dir}
Patch round: {l1_round}
Same kill-switch protocol as initial. Overwrite {run_dir}/challenge.json.
""")

    Read updated {run_dir}/challenge.json.

    if challenge.verdict == "REJECT_FINAL":
        HALT: "REJECT_FINAL at L1 round {l1_round}. Failures: {challenge.failures}"

if l1_round >= L1_budget AND challenge.verdict == "FAIL":
    HALT: "L1 budget exhausted ({L1_budget} rounds). Final failures: {challenge.failures}"
```

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 3 --phase-name challenge
```

### STEP 6 — PHASE 4: amplify + L2 plateau verification

If `current_phase > 4`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 4 --phase-name amplify
```


Get L2 budget:
```bash
uv run python -c "from pipeline.loop_controller import patch_budget; print(patch_budget('L2'))"
```

```
Task(subagent_type="audience-amplifier",
     prompt="""Run the compound amplification loop (single-idea pipeline mode).

Run dir: {run_dir}

1. Read {run_dir}/{title_slug}.md (extract current SOM estimate from Section 1)
2. Read {run_dir}/research.json (audience evidence)
3. Read pipeline/data/amplification_vectors.json (periodic table of vectors)
4. Run the compound multiplier loop: at each iteration select the highest-value
   unapplied vector, check synergy reactions, apply, update SOM estimate.
   Stop when: (a) Δ < 5% for 2 consecutive iterations, OR (b) {L2_budget} iterations reached.
5. Write {run_dir}/amplification.json:
   - som_initial_usd_millions: float
   - som_final_usd_millions: float
   - som_history: list[float] (one per iteration including initial, used for L2 plateau check)
   - vectors_applied: list[{id, name, multiplier}]
   - concept_modifications: list[str] (instructions for concept-drafter to apply)
   - produced_at: ISO-8601
""")
```

Wait for Task. Then verify L2 loop compliance:
```bash
uv run python -c "
import json
from pathlib import Path
from pipeline.loop_controller import plateau_reached, patch_budget

data = json.loads(Path('{run_dir}/amplification.json').read_text())
history = data.get('som_history', [])
budget = patch_budget('L2')
iters = max(0, len(history) - 1)

if len(history) <= 1:
    print('WARNING: amplifier produced no iteration history')
elif iters > budget:
    print(f'WARNING: {iters} iters exceeds L2 cap {budget}')
else:
    reached = plateau_reached(history)
    capped = iters >= budget
    status = 'plateau' if reached else ('capped' if capped else 'incomplete')
    print(f'L2: {iters} iters, termination={status}, SOM {history[0]:.1f}M -> {history[-1]:.1f}M')
"
```

Print the SOM trajectory. Continue to Phase 5 regardless (the amplifier handles its own termination).

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 4 --phase-name amplify
```

### STEP 7 — PHASE 5: genius_audit + L3 patch loop

If `current_phase > 5`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 5 --phase-name genius_audit
```


Get L3 budget:
```bash
uv run python -c "from pipeline.loop_controller import patch_budget; print(patch_budget('L3'))"
```

**Initial genius audit:**
```
Task(subagent_type="genius-auditor",
     prompt="""Run the genius audit (single-idea pipeline mode).

Run dir: {run_dir}

1. Read {run_dir}/draft_v0.json
2. Read {run_dir}/challenge.json
3. Read {run_dir}/amplification.json
4. Apply C001–C007 kill-switches (originality, not commercial viability)
5. Write {run_dir}/genius.json:
   - verdict: PASS | FAIL
   - kill_switches: dict[C001..C007 → {result, evidence, patch_note}]
   - failures: list[str]
   - patch_notes: str
   - produced_at: ISO-8601
""")
```

Read `{run_dir}/genius.json`.

**L3 patch loop (verdict == "FAIL"):**
```
l3_round = 0
loop while genius.verdict == "FAIL" AND l3_round < L3_budget:
    l3_round += 1

    Task(subagent_type="concept-drafter",
         prompt="""Apply an L3 patch (genius audit failure fix).

Mode: l3_patch
Patch round: {l3_round}
Run dir: {run_dir}

1. Read {run_dir}/draft_v0.json + {run_dir}/genius.json
2. Read Inputs/CONCEPT_TEMPLATE_V2.md and Inputs/STYLE_GUIDE.md
3. Apply only the genius.patch_notes — surgical fix of originality weaknesses
4. Overwrite {run_dir}/{title_slug}.md
5. Update {run_dir}/draft_v0.json: set mode="l3_patch", patch_round={l3_round}
""")

    Task(subagent_type="genius-auditor",
         prompt="""Re-run genius audit after L3 patch round {l3_round}.

Run dir: {run_dir}. Patch round: {l3_round}.
Same C001–C007 protocol. Overwrite {run_dir}/genius.json.
""")

    Read updated {run_dir}/genius.json.

if l3_round >= L3_budget AND genius.verdict == "FAIL":
    Print WARNING: "L3 budget exhausted after {l3_round} rounds. Proceeding with FAIL genius verdict — eval gate may catch it."
```

Note: L3 budget exhaustion is a warning, not a halt. The eval gate (Phase 8) is the final arbiter.

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 5 --phase-name genius_audit
```

### STEP 8 — PHASE 6: consistency_check + L4 patch loop

If `current_phase > 6`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 6 --phase-name consistency_check
```


Get L4 budget:
```bash
uv run python -c "from pipeline.loop_controller import patch_budget; print(patch_budget('L4'))"
```

**Initial consistency check:**
```
Task(subagent_type="consistency-checker",
     prompt="""Run the consistency check (single-idea pipeline mode).

Run dir: {run_dir}

Read all sidecars that exist in {run_dir}/:
  seed.json, research.json, draft_v0.json, challenge.json, amplification.json, genius.json

Use pipeline.consistency.detect_drift() to identify cross-sidecar drift.

Write {run_dir}/consistency.json:
  - verdict: OK | DRIFT
  - drift_fields: list[str]
  - severity: LOW | MEDIUM | HIGH
  - suggested_resolutions: list[str]
  - manual_checks: dict (5 boolean fields)
  - produced_at: ISO-8601
""")
```

Read `{run_dir}/consistency.json`.

**L4 patch loop (trigger: severity == HIGH or MEDIUM):**
```
l4_round = 0
loop while consistency.severity in ["HIGH", "MEDIUM"] AND l4_round < L4_budget:
    l4_round += 1

    Task(subagent_type="concept-drafter",
         prompt="""Apply an L4 patch (consistency drift fix).

Mode: l4_patch
Patch round: {l4_round}
Run dir: {run_dir}

1. Read {run_dir}/draft_v0.json + {run_dir}/consistency.json
2. Read Inputs/CONCEPT_TEMPLATE_V2.md and Inputs/STYLE_GUIDE.md
3. Apply exactly the suggested_resolutions from consistency.json
4. Overwrite {run_dir}/{title_slug}.md
5. Update {run_dir}/draft_v0.json: set mode="l4_patch", patch_round={l4_round}
""")

    Task(subagent_type="consistency-checker",
         prompt="""Re-run consistency check after L4 patch round {l4_round}.

Run dir: {run_dir}. Patch round: {l4_round}.
Same detect_drift protocol. Overwrite {run_dir}/consistency.json.
""")

    Read updated {run_dir}/consistency.json.
```

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 6 --phase-name consistency_check
```

### STEP 9 — PHASE 7: investor_narrator (concept-narrator)

If `current_phase > 7`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 7 --phase-name investor_narrator
```


**9a — Pre-fetch market sizing evidence (cached, NB.2).**

Run the Python dispatcher to fetch live TAM/SAM evidence BEFORE invoking the
narrator. Mirrors STEP 3a: first run hits perplexity/sonar-deep-research and
writes `{run_dir}/market_raw.json`; subsequent runs return cached in ~0s.
Skip entirely if `{run_dir}/market_raw.json` already exists.

```bash
if [ ! -f "{run_dir}/market_raw.json" ]; then
  uv run python -c "
import json, sys
from pathlib import Path
from pipeline.research_dispatch import fetch_market_for_concept
seed = json.loads(Path('{run_dir}/seed.json').read_text(encoding='utf-8'))
slug = seed.get('seed_slug') or '{run_id}'.split('-', 5)[-1] or 'anon'
try:
    fetch_market_for_concept(run_dir=Path('{run_dir}'), theme_slug=slug)
    print('market_dispatch: OK')
except FileNotFoundError as exc:
    # draft_v0.json missing — fatal upstream; skip and let narrator degrade.
    print(f'market_dispatch: SKIPPED ({exc})', file=sys.stderr)
except Exception as exc:
    # Soft-fail: narrator falls back to amplification.json TAM/SAM figures.
    print(f'market_dispatch: DEGRADED ({exc})', file=sys.stderr)
"
fi
```

**9b — Invoke narrator.**

```
Task(subagent_type="concept-narrator",
     prompt="""Write the investor companion document (single-idea pipeline mode).

Run dir: {run_dir}

Primary reads (Single-Idea Pipeline Mode):
- {run_dir}/draft_v0.json — concept body and structured fields
- {run_dir}/challenge.json — challenge verdict and conditions
- {run_dir}/amplification.json — SOM/SAM/TAM figures and compound multiplier trail
- {run_dir}/seed.json — hidden attributes for STYLE_GUIDE Section 2 prose mapping
- {run_dir}/market_raw.json — pre-fetched perplexity/sonar-deep-research TAM/SAM
  evidence (NB.2). If absent, use amplification.json figures and mark as
  'projection' in prose; never fabricate.

Output path: {run_dir}/{title_slug}-NARRATOR.md

All numeric claims must trace verbatim to one of the sidecar files above.
Do NOT fabricate any figure. If a field is absent, write 'data unavailable'.
""")
```

Wait for Task. Verify `{run_dir}/{title_slug}-NARRATOR.md` exists.

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 7 --phase-name investor_narrator
```

### STEP 10 — PHASE 8: eval_gate + L5 narrator-redo loop

If `current_phase > 8`: skip.
```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 8 --phase-name eval_gate
```


Get L5 budget:
```bash
uv run python -c "from pipeline.loop_controller import patch_budget; print(patch_budget('L5'))"
```

**Run eval gate (Tier-1 + Tier-2 checks via pipeline.eval_gate):**
```bash
uv run python -m pipeline.eval_gate --run-dir {run_dir}
```

Read `{run_dir}/eval.json`.

**L5 split-dispatch loop (verdict == "FAIL"):**

Eval failures route to the patcher agent that owns the failing artifact.
`eval.patcher_routing.drafter` lists codes rooted in the concept md
(`{slug}.md`); `eval.patcher_routing.narrator` lists codes rooted in the
narrator companion (`{slug}-NARRATOR.md`). The L5 budget is shared across
both branches (ADR-0009: max 2 rounds total — a round may invoke both
branches, but the counter advances once).

```
l5_round = 0
loop while eval.verdict == "FAIL" AND l5_round < L5_budget:
    l5_round += 1

    drafter_codes  = eval.patcher_routing.drafter   // list of failure codes
    narrator_codes = eval.patcher_routing.narrator  // list of failure codes

    Print: "Eval gate failed (L5 round {l5_round}/{L5_budget}). " +
           "drafter_codes={drafter_codes}, narrator_codes={narrator_codes}."

    if drafter_codes:
        Print: "L5 → concept-drafter patch pass for codes {drafter_codes}"
        Task(subagent_type="concept-drafter",
             prompt="""Patch the concept markdown (L5 round {l5_round}, drafter branch).

Run dir: {run_dir}
Concept md path: {run_dir}/{title_slug}.md
Eval failure codes to fix: {drafter_codes}
Eval per-file diagnostics: {eval.per_file}

For each failure code apply a surgical fix to {run_dir}/{title_slug}.md:

  - INTERNAL_IDS         → remove every framework label leaked into prose
                           (TRIZ, JTBD, Booker, McKee, Boden, Csikszentmihalyi,
                           Reagan, Pearson, Egri, Polti, Haidt, Mednick, Wundt,
                           Simonton, Stanton, and any C00N / K00N / G00N codes).
                           Replace with the equivalent plain-English term.
  - SOM_BELOW_100M       → ensure Market & Audience contains a canonical
                           SOM line `**SOM (Year 1):** $NNNM` (or `$N.NNB`)
                           with value >= $100M. Re-cite an existing amplification
                           figure; do NOT invent.
  - TEMPLATE_NONCOMPLIANT → add the missing V2 template sections from
                           Inputs/CONCEPT_TEMPLATE_V2.md (eval.per_file
                           `template_failures` lists the exact missing sections).
  - QUALITY_GATE_FAIL    → strengthen drafter sections (characters/story/market)
                           so the 5-vector axes' prose-resolver picks up the
                           missing signals — see {run_dir}/quality.json for
                           per-axis reasons.

After the patch the file MUST still pass pipeline.template_filter.strip_internal_ids
and remain the canonical {slug}.md (no rename, no run-ID leak).
""")

    if narrator_codes:
        Print: "L5 → concept-narrator redo for codes {narrator_codes}"
        Task(subagent_type="concept-narrator",
             prompt="""Re-write the investor companion (L5 round {l5_round}, narrator branch).

Run dir: {run_dir}
Eval failure codes to fix: {narrator_codes}

Re-read all sidecar files and rewrite {run_dir}/{title_slug}-NARRATOR.md.
Pay special attention to: no internal framework IDs in prose, SOM >= $100M cited,
full V2 template section structure preserved.
""")

    Re-run the eval gate:
    `uv run python -m pipeline.eval_gate --run-dir {run_dir}`

    Read updated {run_dir}/eval.json.

if l5_round >= L5_budget AND eval.verdict == "FAIL":
    Read eval.json and print the failure summary.
    HALT: "L5 budget exhausted ({L5_budget} rounds). Eval gate still failing.
Final failures: {eval.failures}
Patcher routing on final attempt: drafter={eval.patcher_routing.drafter}, narrator={eval.patcher_routing.narrator}
Run dir: {run_dir}
To debug: uv run python -m pipeline.template_filter {run_dir}/{title_slug}.md"
```

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 8 --phase-name eval_gate
```

### STEP 11 — PHASE 9: lessons_capture

```bash
uv run python -m pipeline.phase_timing start --run-dir {run_dir} --phase-index 9 --phase-name lessons_capture
```

Write `{run_dir}/lessons.json` from the sidecar data:

```bash
uv run python -c "
import json
from pathlib import Path
from datetime import datetime, timezone

run_dir = Path('{run_dir}')

def _load(name):
    p = run_dir / name
    return json.loads(p.read_text()) if p.exists() else {}

challenge     = _load('challenge.json')
genius        = _load('genius.json')
consistency   = _load('consistency.json')
eval_data     = _load('eval.json')
amplification = _load('amplification.json')

lessons = {
    'run_dir': str(run_dir),
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'final_verdict': eval_data.get('verdict', 'UNKNOWN'),
    'challenge_verdict': challenge.get('verdict', 'UNKNOWN'),
    'genius_verdict': genius.get('verdict', 'UNKNOWN'),
    'consistency_verdict': consistency.get('verdict', 'UNKNOWN'),
    'consistency_severity': consistency.get('severity', 'UNKNOWN'),
    'som_initial_usd_millions': amplification.get('som_initial_usd_millions'),
    'som_final_usd_millions': amplification.get('som_final_usd_millions'),
    'som_history': amplification.get('som_history', []),
    'vectors_applied': [v.get('id') for v in amplification.get('vectors_applied', [])],
    'key_failures': (
        challenge.get('failures', []) +
        genius.get('failures', []) +
        consistency.get('drift_fields', []) +
        eval_data.get('failures', [])
    ),
    'patch_rounds': {
        'l1': challenge.get('patch_round', 0),
        'l3': genius.get('patch_round', 0),
        'l4': consistency.get('patch_round', 0),
    },
}

(run_dir / 'lessons.json').write_text(json.dumps(lessons, indent=2))
print(json.dumps(lessons, indent=2))
"
```

```bash
uv run python -m pipeline.phase_timing end --run-dir {run_dir} --phase-index 9 --phase-name lessons_capture
```

### STEP 12 — COMPLETE

Print deliverables summary:

```
╔══════════════════════════════════════════════════════════╗
║       Single-Idea Pipeline v4.0 — Complete               ║
╠══════════════════════════════════════════════════════════╣
║  Run ID:  {run_id}                                       ║
║  Theme:   {theme}                                        ║
╠══════════════════════════════════════════════════════════╣
║  DELIVERABLES → {run_dir}/                               ║
║  📄 {title_slug}.md          — Investor concept          ║
║  📄 {title_slug}-NARRATOR.md — Investor companion        ║
║  📊 eval.json                — Eval gate: {verdict}      ║
║  📋 lessons.json             — Pipeline learnings        ║
╚══════════════════════════════════════════════════════════╝
```

Print the per-axis quality dashboard (NB.11 — 5-vector report):
```bash
uv run python -m pipeline.quality_report --run-dir {run_dir}
```

## Resume Protocol

If the pipeline is interrupted mid-run:

```
/single-idea --resume --run-id {run_id} --theme "{theme}"
```

Or if you only have run_id:
```bash
# Read theme from seed.json
python -c "import json; d=json.load(open('runs/{run_id}/seed.json')); print(d['theme'])"
```

Then pass the extracted theme to `--theme`. The CLI detects existing sidecar files and
advances `current_phase` to the first incomplete phase automatically.
