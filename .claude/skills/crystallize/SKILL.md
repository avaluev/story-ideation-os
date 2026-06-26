---
name: crystallize
description: |
  Crystallize — operator-facing batch ideation over the 19.2-trillion-combination
  compound_seed engine. Generates N candidate compound seeds from a problem +
  themes, matches each against the 294-film corpus for real comps + ROI,
  applies the C001-C007 GREATNESS_CHECKLIST rubric, clusters them into the
  8 thematic clusters that already exist in the engine, and renders a terminal
  table + a self-contained HTML "crystal board". Implements the wikibook
  "Crystallization of the Idea" methodology: chance-driven generation →
  systematic selection → moment of crystallization. Offline-resilient —
  works without OpenRouter credits.
  Use when the operator types /crystallize or asks to explore the parameter
  space before committing to one concept.
---

# /crystallize — See the Power of 19.2 Trillion Parameters

## Why this skill exists

The compound_seed engine in `pipeline/compound_seed.py` exposes a parameter
space of ~19.2 trillion combinations across 12 narrative-variable lists plus
7 framework banks (sdt_wound, psychological_pattern, structural_inversion,
moral_fault_line, compression_key, divisiveness_engine, world_texture,
civilizational_stake, archetypes, conspiracy_engine, reptile_trigger,
open_problem, cultural_moment, …). The default `/single-idea` flow only
materialises **one** point in that space per run.

`/crystallize` materialises **N points** (default 1000), scores them all,
matches each to the 294-film corpus at `Inputs/10May/.../films/`, scores
each against the C001-C007 rubric from `Inputs/GeniusFilm/GREATNESS_CHECKLIST.json`,
clusters them into 8 thematic groups, and surfaces everything in a sortable
HTML "crystal board" the operator opens in a browser.

The methodology comes from the wikibook *Crystallization of the Idea*:

1. **Where to Start** — set the problem + themes (operator types --problem, --themes)
2. **Realm of Chance** — generate N candidates from the 19.2T space
3. **Inventor's Tools** — (v2) force-pin dimensions + re-roll
4. **Expanding the Toolbox** — (v2) mutate / crossover variations
5. **Crystallization** — operator picks the winner, feeds it to `/single-idea`

## Invocation

```bash
uv run python -m scripts.crystallize.explore \
    --problem "AI surveillance vs human autonomy" \
    --themes  "Korean fertility crisis,climate cascade" \
    --n       1000
```

| Flag | Default | Role |
|------|---------|------|
| `--problem STR` | required | The operator's problem statement |
| `--themes STR` | required | Comma-separated themes that bias the engine |
| `--n INT` | 1000 | Number of candidates to sample |
| `--output-root PATH` | `runs` | Root directory for the board |
| `--workers INT` | min(8, cpu_count) | Parallel process pool size |
| `--no-html` | off | Skip the HTML render (faster smoke tests) |
| `--max-attempts INT` | 20 | Per-candidate engine attempt cap |
| `--verbose` | off | Show INFO-level engine logs |

## Deliverables

All files land in `runs/<board_id>/` where `<board_id>` is
`<ISO timestamp>-<problem-slug>`:

| File | Role |
|------|------|
| `crystal_board.json` | Full board: N candidates, 8 clusters, comps, greatness, scores |
| `crystal_board.html` | Self-contained offline HTML (open in any browser; no CDN) |

## What the operator sees

**Terminal** (immediate, while HTML opens in browser):

```
🎲 Crystal Board — board_id=2026-05-22T1700-ai-surveillance-vs-human-autonomy
   Problem:   AI surveillance vs human autonomy
   Themes:    Korean fertility crisis | climate cascade
   Sampled:   1000/1000 candidates in 87.3s
   Corpus:    294 films loaded
   Checklist: v1.0 (7 criteria, 4 kill switches)

Top-10 by crystallization_score:
  rank cand   cluster        cryst   grtn   C001  deriv  div  som    closest comps
   1   c0427  civilizational 0.81    0.74   0.91  0.91   9.0  400    Children of Men (1.8×) · …
   2   c0118  technology     0.78    0.71   0.83  0.85   8.0  385    Ex Machina (4.7×) · Her (5.1×) · …
   ...

Clusters (k=8):
   institutional   128 candidates  cryst 0.43  corpus_roi 1.21×
   emotional       103             cryst 0.51  corpus_roi 1.85×
   …

Kill-switch failures: 47 candidates flagged (C003: 18, C006: 22, C001: 7)
HTML crystal board: runs/<board_id>/crystal_board.html
```

**HTML** (opened with `open runs/<board_id>/crystal_board.html`):

- SVG scatter plot: x = goldilocks_score, y = genius_score, colour = cluster,
  dot radius = derivative_distance. Click any dot to inspect.
- Side panel per candidate: full compound_seed JSON, top-5 comp films with
  ROI numbers + IMDb / Box Office Mojo links, C001-C007 mini bar chart with
  kill-switch failures painted red.
- Sortable table with all candidates, every key score column.
- Cluster summary panel with 8 rows.
- Kill-switch lane listing all candidates with any failed kill-switch criterion.

## The 8 clusters

These are the engine's existing thematic clusters (`_CLUSTER_NAMES` in
`pipeline/compound_seed.py`):

| ID | Name | Centre of gravity |
|----|------|-------------------|
| 0 | institutional | Bureaucracy, courts, procedure, authority |
| 1 | emotional | Family, grief, intimacy, attachment |
| 2 | technology | AI, surveillance, biotech, infrastructure |
| 3 | identity | Self, role, memory, gender, ancestry |
| 4 | nature | Climate, wilderness, biology, ecology |
| 5 | economic | Capital, labour, scarcity, debt, status |
| 6 | temporal | Memory, prediction, generations, decline |
| 7 | civilizational | Species, sovereignty, large-scale fate |

KMeans is fixed at k=8 so the visualisation maps 1:1 to these names.

## crystallization_score formula

A single scalar in [0, 1] per candidate. Geometric mean of six facets
multiplied by a gate factor (see `pipeline/crystallize/score.py`):

```
crystallization_score(s, derivative_distance=1.0) =
    s.genius_score                                      ** 0.30
  × s.goldilocks_score                                   ** 0.18
  × s.cluster_coherence                                  ** 0.17
  × min(1, s.emotional_universality_score / 5.0)         ** 0.13
  × min(1, s.som_floor_M / 300.0)                        ** 0.09
  × derivative_distance                                   ** 0.13
  × (1.0 if both gates pass else 0.5)
```

Any near-zero facet collapses the total — matches the "crystal" intuition
(every facet must be present). `derivative_distance` defaults to 1.0 when
the corpus is absent so the factor is a no-op.

## C001-C007 rubric (GREATNESS_CHECKLIST)

| C-id | Criterion | Engine proxy | Kill switch |
|------|-----------|---------------|:---:|
| C001 | Expert Surprise Delta | derivative_distance vs corpus | 🛑 |
| C002 | Associative Goldilocks | goldilocks_score | — |
| C003 | Emotional Anchor Stability | emotional_universality_score / 5.0 | 🛑 |
| C004 | Narrative Arc Congruence | thematic_anchor_score | — |
| C005 | Homework Coefficient | cultural_field_alignment | 🛑 |
| C006 | Agency-to-Lore Ratio | 1 − min(1, n_decorative_tags/5) | 🛑 |
| C007 | Compression Progress | compression_score | — |

Sub-scores below 0.4 on a kill-switch criterion flag the candidate in
the HTML with a red border. Weighted total = Σ (weight × sub-score) with
weights pulled directly from the JSON file (0.25 / 0.15 / 0.20 / 0.10 /
0.10 / 0.10 / 0.10 = 1.00).

## Hand-off to /single-idea

A chosen candidate's `compound_seed` block is structurally identical to
the dict written by `pipeline/run_single_idea.py:_write_seed` when
`use_moa=True`. To commit a winner:

```python
import json
from pathlib import Path

board = json.load(open("runs/<board_id>/crystal_board.json"))
chosen = next(c for c in board["candidates"] if c["candidate_id"] == "c0427")
seed = chosen["compound_seed"]
seed["theme"] = board["themes"][0]   # operator picks which theme to commit to
seed["target_format"] = "feature"
out = Path("runs/<single_idea_run_id>")
out.mkdir(parents=True, exist_ok=True)
json.dump(seed, open(out / "seed.json", "w"), indent=2)
```

Then:

```bash
uv run python -m pipeline.run_single_idea \
    --resume --run-id <single_idea_run_id>
```

## Offline resilience

- `CompoundSeedEngine` has a template-fallback path for the LLM-polished
  `intersection_premise` field when Haiku is unreachable.
- `seed_moa.generate` falls back to `_python_judge` when Sonnet is unreachable.
- `FilmsCorpus` and `Checklist` are local JSON — no network calls.
- The HTML is self-contained — no external CDN, no fonts beyond the system
  default stack.

When OpenRouter PAID key is exhausted (HTTP 402), the engine still produces
a full 30-dimension compound seed per candidate; only the LLM-polished
premise text degrades to the template fallback (the structured dimensions
remain unchanged).

## Verification

```bash
# Unit tests
uv run pytest tests/test_crystallize_*.py -v

# End-to-end smoke with n=16 (~45s offline)
uv run pytest tests/test_crystallize_explore_smoke.py -v

# Full run on a real problem (~1-3 min depending on CPU count)
uv run python -m scripts.crystallize.explore \
    --problem "AI surveillance vs human autonomy" \
    --themes  "Korean fertility crisis,climate cascade"
```

## v2 / v3 follow-ons

- v2: corpus expansion to 3000+ films via TMDB
  (`scripts/corpus/expand_from_tmdb.py`) — operator-supplied
  `TMDB_READ_ACCESS_TOKEN` env var.
- v2: split `explore.py` into 5 stage scripts mirroring the wikibook stages.
- v2: additive `force_*` engine kwargs for operator pinning + re-roll.
- v2: variation operators in `pipeline/crystallize/operators.py`:
  `mutate_one_axis`, `crossover(parent_a, parent_b)`.
- v3: lineage tree in the HTML; star/bury fields; zeitgeist re-scoring.
- v3: hand-off automation — `crystallize/05_crystallize.py` writes
  `seed.json` directly into a new `runs/<id>/` for `/single-idea --resume`.
