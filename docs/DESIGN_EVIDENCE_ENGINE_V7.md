# Design — Systematic Evidence Engine (v7 evidence uplift)

> Operator ask (2026-05-31): "every concept card has low deep-link density — low
> evidence, shallow proofs are not acceptable. Fix the *systematic* evidence
> engine for every number, quote, and conclusion. Design 100% workflows to
> exceed the prior delivery."
>
> Validated by the `evidence-engine-audit` workflow (8 agents, 1.34M tok, 6
> auditors → synthesis → adversarial critic = **SOLID / GO**). Cached digest:
> `/tmp/audit_digest.md`; this doc is the durable contract (ADR-0001).

## 1. The defect (root-caused, code-evidenced)

The veracity scorer can only "see" claims that already carry a markdown link, so
it reports ~100% deep-link coverage while the **true external-claim density on
sampled cards is 31% (Tremor) / 50% (Husbandry) / 40% (Allocate)**.

| # | Root cause | Evidence | Sev |
|---|---|---|---|
| RC1 | `extract_from_markdown` is a *link-harvester*, not a *claim-enumerator* — density is self-referential (links/links≈100%) | `claims.py:206,210-237`; Tremor 30 $-tokens → 4 claims | P0 |
| RC2 | `extract_from_concept` never scans prose; inline-linkless Comparables tables never assessed | `claims.py:99-155`; Tremor/Allocate comp tables have 0 URLs | P0 |
| RC3 | quote can't bind to `claim_id` (id keys on link anchor) → `merge` drops it → SUPPORTED never → VERIFIED | `claims.py:228`,`verdict.py`,`assess.py`; `apply_evidence.py` never called merge | P0 |

**Key insight:** binding already works when keyed by `claim_id`
(`test_veracity.py:242`). The flagship delivery just never used it. Fix is
**additive**, not a rewrite.

## 2. The fix (additive — no working module rewritten; no $ figure touched)

### Movement 1 — `pipeline/veracity/enumerate.py` (offline, TDD)
`enumerate_claims(md, *, concept_id="", concept_title="") -> list[Claim]`
- **Section-aware**: outline-scope walk (heading stack); scan only evidence
  zones (Market & Audience / Audience Sizing / Revenue Thesis / Why Now /
  Comparables / Verified Proof of Demand / Economics). A deeper IN heading
  (`## Comparables` under `# 3. Story`) overrides a shallower OUT one.
- **Economics table first** → learn frozen `{tam, sam, som, lifetime}` so prose
  dollars matching SAM/SOM/lifetime/scenario-bounds classify COMPUTED (excluded
  from the external denominator); TAM is the one EXTERNAL market aggregate.
- **EXTERNAL** = comps (gross/budget/ROI), TAM, every Proof-of-Demand bullet,
  prose demand/cultural stats (%, non-frozen $), and superlative *conclusions*
  ("most durable revenue category"). **COMPUTED** = SAM/SOM/lifetime/bounds.
  **INTERNAL** = anything in out-of-scope sections (skip).
- **Dedup** by normalized claim text (same $ in 3 sections → 1 claim).
- Each Claim gains **optional defaulted** fields `anchor` (sentence/row span for
  the renderer) + `section`. No required field added (landmine).
- **Golden fixture** `tests/fixtures/enumerate_tremor.json` pins the exact
  EXTERNAL count; report surfaces a `claims-found / dollar-tokens` sanity ratio
  so a recall regression is visible.
- Header-split + per-line regex — **NOT** a markdown AST (overreach).

### Movement 2 — density metric + binder + publish gate (TDD)
- `CredibilityScore.evidence_density` = (verified+supported external)/(total
  external), defaulted, surfaced in `CREDIBILITY.md`. Existing fields/weights
  untouched.
- Binder: `claim_id = sha(concept_id|type|normalized_text)[:12]` is
  agent-targetable; `merge_agent_judgments` already promotes when keyed by it.
- `--assert-density FLOOR`: exits nonzero unless **mode==online AND
  density>=floor AND grade>=min AND fabricated==0**. Empty-external-claims card
  handled (no spurious offline fail). Composes with `--assert-grade`.

### Movement 3 — `pipeline/veracity/render_inline.py` (offline, TDD)
- Given a card + bound map `{claim_id: {url, quote, date}}`, insert a citation at
  each external claim's **anchor** (first occurrence per section; anchor on the
  full sentence/row, never the bare value → no mis-attach when $890M repeats).
- Comparables: linkify the title cell (matches Husbandry's existing form) →
  **idempotent**: skip rows already linked (don't double-cite).
- **Byte-identical** every frozen $/SOM/SAM/TAM token (test-guarded). Calls
  `strip_internal_ids` (ADR-0010); no `<url>` auto-link; strip-then-write
  (idempotent: `render(render(x))==render(x)`).

### Movement 5 — guarded live per-claim sourcing (code authored now, **run gated**)
- `.claude/workflows/evidence-sourcing.mjs`: `pipeline()` per card → one
  source-finding agent per claim (CHUNK=4); pass `claim_id` as an **opaque token
  the agent echoes back verbatim**; agent WebFetches, copies a ≤25-word verbatim
  quote, returns `{claim_id,url,quote,supports,date}`; **hard per-claim fetch
  cap** in the prompt. Second **opus adversarial verifier** (refute-by-default)
  per claim → deterministic `probe_url` re-validation → `merge_agent_judgments`
  (validate id ∈ enumerated set, **log misses loudly**, never silent-drop).
- Guardrails: `quota.gate` pre-check + abort if `remaining_fraction<0.20` +
  MAX_AGENTS cap + **per-card incremental `judgments.json` checkpoint**
  (resumable; proven by a unit test before the live run).
- Tiers: sourcing=**sonnet** (20M cap headroom), verify=**opus** (2M cap binds).

### Movement 4 — deliverables (after live evidence)
- Re-render 20 cards inline-cited → regrade `CREDIBILITY.md` + portfolio →
  assert A + density≥0.95 (online gate) → EN/RU/HTML/PROVENANCE/zip.

## 3. Exceed-the-bar targets

| Metric | Today | Prior | **Target** |
|---|---|---|---|
| External deep-link density/card | 31–50% | self-ref | **≥95%** |
| VERIFIED (deep-link+verbatim quote+supports) | 0% | A (185-agent merge) | **≥90%**, rest COMPUTED/dropped |
| Quote coverage | 0% | — | **≥90%** |
| Deep-linked+quote claims/concept | ~4 | 4.4 | **≥15** |
| Distinct primary URLs (slate) | — | 65 | **≥200** |
| Credibility grade (ONLINE gate) | D/60 | A | **A (≥90), 0 fabricated** |
| Combined Y1 SOM | $8.42B | — | **unchanged — frozen `python_executed`** |

## 4. Hard constraints
ADR-0002 (no LLM number/verdict — `enumerate.py` pure parsing; agents return
booleans+quote) · ADR-0011 (never edit a `python_executed` $) · ADR-0010
(`strip_internal_ids`) · ANOMALY-001/002 (no `anthropic`/`httpx`/
`openrouter_client`/`frameworks` imports) · `extract_from_markdown` contract
frozen · Stop gate `make test && make eval` + RESUME mtime · HARN-13 (build vs
live delivery are different stages — different sessions).

## 5. Pre-live conditions (critic)
1. Golden enumerator fixture human/2nd-agent verified → trustworthy denominator.
2. `--assert-density` requires `mode==online` (a structural pass cannot mint an A).
3. Per-card checkpoint proven resumable before the ~280-claim run.

## 6. Operator decisions (checkpoint, with recommendations)
1. **Live-run scope** — all 20 (~280 claims) vs 3–5 card pilot first ▸ *rec: pilot 3 → confirm → full 20.*
2. **VERIFIED bar** — ≥90% VERIFIED, drop unsourceable ▸ *rec: yes.*
3. **SAM provenance** — keep 12%-of-TAM derivation ▸ *rec: keep (re-sourcing = overreach).*
4. **Unsourceable claims** — DROP vs KEEP with "(estimate)" label ▸ *rec: drop.*

## 7. Overreach explicitly cut
No markdown AST · no re-sourcing SAM/SOM/TAM · no new/modified agent types
(use general-purpose) · no claims DB (per-card JSON map) · no rewrite of `claims.py`.
