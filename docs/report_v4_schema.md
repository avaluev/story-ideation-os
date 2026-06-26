# A4 Investor Report — v4 14-Section Canonical Schema

> **Status:** canonical (V4A-003e, 2026-05-10)
> **Source of truth for:** `prompts/06-a4-formatter.md`,
> `tests/fixtures/golden_phase6_v4.md`,
> `pipeline/schema.py:Phase4Concept`,
> `pipeline/path_c_a4_sidecar.py` (when migrated)
>
> **Backward compatibility:** when both `mutation_provenance` and
> `closing_image` are `None`, the formatter renders the v3 12-section
> schema unchanged. This keeps the existing 1067 v3.1-pathc-a4 outputs
> stable and lets a single forge population mix v3 and v4 documents.

## Bifurcation Rule

The v4 formatter inspects two fields on the input `Phase4Concept`:

| `mutation_provenance` | `closing_image` | Output |
|---|---|---|
| `None` | `None` | **v3 12-section** (Score at §12) |
| any value | any value | **v4 14-section** (§12 = Mutation Provenance, §13 = Closing Image, §14 = Score) |

Mixing — e.g. `mutation_provenance` populated but `closing_image=None` —
still triggers v4 14-section rendering with `[DATA NOT AVAILABLE]` in the
missing slot. This preserves stable section numbering for downstream
audit tooling that scans by `## ` header position.

## Canonical Section Order (v4 14-section)

| § | Header | Source field | Contract |
|---|---|---|---|
| 1 | `# [TITLE]` (H1) | `Phase4Concept.title` | one line, ≤8 words |
| 2 | `## High-Concept Logline` | `Phase4Concept.logline` | 25–35 words; protagonist + central tension + stakes |
| 3 | `## Audience Size & Evidence` | `Phase3Audience.cited_audience`, `target_countries`, `audience_size_source_url`, `trend_direction` | one absolute number ≥50M; ≥3 ISO2 country codes; ≥1 source URL |
| 4 | `## JTBD` | `Phase2JTBD.jtbd_segment_id`, `job_statement`, `deprivation_lens` | macro-segment label + ferocious-specificity job statement + deprivation phrase |
| 5 | `## Asset` | `Phase1Asset.name`, `asset_type`, `emotional_charge` | named historical/cultural anchor + emotional core |
| 6 | `## TRIZ Contradiction` | `Phase4Concept.triz_contradiction_id`, `collision_contradiction` | both poles named; ≤30 words for the collision phrase |
| 7 | `## Narrative Grid` | `polti_id`, `tobias_id`, `booker_plot_id`, `stc_genre_id`, `truby_archetype_id` | 5-row table (Polti / Tobias / Booker / STC / Truby) |
| 8 | `## Key Roles` | `Phase4Concept.key_roles` | protagonist / antagonist / ally / mentor lines (`name — goal — method`); mentor may be null |
| 9 | `## Cinema-School Floor` | `Phase4Concept.ten_school_self_check` | 10-row table (School / Passes); ≥7 must be true |
| 10 | `## SDT Analysis` | `Phase2JTBD.primary_need`, `primary_strength`, `deprivation_lens` | primary need + strength ≥0.7; secondary need optional; deprivation echo |
| 11 | `## Critic Verdict` | `Phase5Critique.axis_scores`, `cross_checks`, `final_decision` | 4-row axis table + 5-row cross-checks table + investment_readiness verdict |
| **12** | **`## Mutation Provenance`** | `Phase4Concept.mutation_provenance` | operator label + parent concept_ids; intruder/transpose details when applicable |
| **13** | **`## Closing Image`** | `Phase4Concept.closing_image` | ≤30-word final visual beat |
| 14 | `## Score` | placeholder; populated post-format by `pipeline/scoring.py` | `**[SCORE_PLACEHOLDER]/100**` (literal, replaced after) |

## §12 Mutation Provenance — Render Rules

The `mutation_provenance` field is a dict shaped like:

```json
{
  "op": "SWAP" | "CROSSOVER" | "INVERT" | "INTRUSION" | "TRANSPOSE" | "DISTILL",
  "parents": ["concept-id-1", "concept-id-2"?],
  "intruder_asset_id": "asset-..."?,        // INTRUSION only
  "transpose_to": [["geography","..."], ...] // TRANSPOSE only
}
```

Render template:

```markdown
## Mutation Provenance
**Operator:** {op}
**Parent concept(s):** {parents joined by `, `}
{op == "INTRUSION" ⇒ "**Intruder asset:** {intruder_asset_id}"}
{op == "TRANSPOSE" ⇒ "**Transpose to:** {key1: value1; key2: value2}"}
```

When `mutation_provenance is None`, the §12 header is replaced by
`## Mutation Provenance` followed by `[DATA NOT AVAILABLE]` (v4-only;
v3 outputs do not render this header at all).

## §13 Closing Image — Render Rules

The `closing_image` field is a single ≤30-word string carrying the final
visual beat — what the audience sees as the credits roll. The validator
in `pipeline/schema.py` enforces the 30-word cap. The formatter renders:

```markdown
## Closing Image
{closing_image string verbatim}
```

When `closing_image is None` and the document is v4 (because
`mutation_provenance` was set), the §13 body is `[DATA NOT AVAILABLE]`.

## §14 Score — Identical to v3

The score section MUST contain ONLY the literal text:

```
**[SCORE_PLACEHOLDER]/100**
```

The pipeline replaces the placeholder post-format using
`pipeline/scoring.py` output (ADR-0002: scores are computed in Python,
never by an LLM). v3 and v4 share this contract.

## Validators

| Field | Validator | Constraint |
|---|---|---|
| `closing_image` | `validate_closing_image_word_count` | ≤30 words (`CLOSING_IMAGE_MAX_WORDS` in `pipeline/schema.py`) |
| `mutation_provenance.op` | `validate_mutation_provenance_op` | one of {SWAP, CROSSOVER, INVERT, INTRUSION, TRANSPOSE, DISTILL} |
| `mutation_provenance.parents` | `validate_mutation_provenance_op` | non-empty list/tuple |

## Eval Coverage (V4A-003d)

The mutated population in `data/04_concepts.jsonl` is checked by three
runtime evals that activate only when `mutation_provenance != null`:

- `evals/test_mutation_doctrine_preserved.py` — 7-school cinema floor
  preserved on every mutated row
- `evals/test_mutation_diversity.py` — unique
  `(asset_id, polti_id, tobias_id)` tuples / total ≥ 0.6 floor
- `evals/test_no_recombination_collapse.py` — concept_id uniqueness +
  `(title, logline)` pair ratio ≥ 0.9 + ≥3 distinct operators per round

All three skip cleanly on a fresh clone (no pipeline output yet).

## Migration Notes

- **2026-05-10 — V4A-003e** introduces the 14-section v4 spec. Existing
  outputs continue rendering as 12-section because both new fields default
  to `None`.
- **Forward path:** the v4 formatter is wired in `prompts/06-a4-formatter.md`
  as a header-conditional render block. No code change in the renderer
  pipeline (Haiku formatter consumes the prompt verbatim, follows the
  bifurcation rule).
- **Backwards path:** if a v4-mutated concept must be downgraded to v3,
  set `mutation_provenance=None` and `closing_image=None` and re-format.
  The 14-section content is purely additive — no v3 section is rewritten.

## Cross-References

- `prompts/06-a4-formatter.md` — formatter prompt (renderer)
- `tests/fixtures/golden_phase6_v4.md` — 14-section golden fixture
- `tests/fixtures/golden_phase6.md` — 12-section golden (v3 backward-compat)
- `pipeline/schema.py:Phase4Concept` — Pydantic model with v4 fields
- `pipeline/mutation.py:MutationProvenance` — frozen dataclass for the
  ConceptRow joined view (V4A-003b)
- `~/.claude/plans/i-need-you-to-crystalline-tower.md` — approved plan
  (sha 7ec6bb37...)

*Last updated: 2026-05-10 (V4A-003e).*
