# Anomaly Engine — Master Brief
## The One Document Every Agent Reads First

> Read this completely before generating any output.
> Every rule here overrides training-data defaults.
> Non-compliance is a pipeline failure.

---

## Output Path Rule (non-negotiable)

Every final concept writes to `runs/YYYY-MM-DD-HHMMSS/[slug].md`.
No sub-folders. No separate reports/ or ideas/ folders.
One file per concept. Treatment + scorecard + evidence merged in CONCEPT_TEMPLATE format.
Three files per concept: `[slug].md` + `[slug]-RESEARCH.md` + `[slug]-CHALLENGE.md`

---

## Required `## Core DNA` Fields

Every concept document must contain a `## Core DNA` section with ALL of these fields:

```
- Format: [feature / limited series Nx~Nmin / short drama / animation / documentary-hybrid]
- Genre (max 2): [genre1 / genre2]
- Runtime: [~N min] OR [N episodes × ~N min]
- Tagline: [5–10 words, marketing-poster style — will this print on a one-sheet?]
- High-Concept Statement: [≤25 words that make an executive call their agent — Katzenberg test]
- Arc Shape (Reagan 2016): [Rise / Fall / Rise-Fall / Fall-Rise / Rise-Fall-Rise / Fall-Rise-Fall]
- Booker Plot: [Overcoming the Monster / Rags to Riches / The Quest / Voyage and Return / Comedy / Tragedy / Rebirth]
- Conflict Type (McKee): [man vs man / vs nature / vs self / vs society / vs fate / vs technology / vs supernatural]
- Emotional Weight: [light / medium / heavy]
- Budget Tier: [micro <$1M / indie $1–15M / mid $15–50M / studio $50–200M / tentpole $200M+]
- Format Justification: [one sentence: why THIS format, not another]
- Boden Creativity Classification: [combinatorial / exploratory / transformational — with evidence]
- Csikszentmihalyi Flow Potential: [high / medium / low — rationale]
- Timing Risk: [zeitgeist-aligned / timeless / potentially dated — cite one data point]
- Retrospective Fallacy Risk: [immediate recognition / needs time / cult trajectory — analogue film cited]
- Cultural Specificity: [universal / bicultural [territories] / monocultural [territory] — reasoning]
- Moral/Philosophical Wager: [McKee Controlling Idea: "[Positive value] through [cause] → [consequence]"]
```

---

## Required `## Framework Tags` Fields

Every concept document must contain a `## Framework Tags` section with ALL of these fields:

```
- Polti Situation: #N — [name] — [Role A] vs [Role B] — [how it manifests in THIS story]
- Booker Beat Structure: [which 5–6 beats apply; label them per the Synopsis section]
- Reagan Arc: [shape name] — [emotional direction per act]
- Haidt Foundations in conflict: [Foundation A] vs [Foundation B] — [moral tension description]
- JTBD Segment: [one of 12 macro-segments from frameworks/ajtbd-segmentation.md] — [job statement ≤20 words]
- Binary Tension Pair: [one of 40 pairs from Inputs/SocraticAMA/research/02_conflict_ontology.md] — [how it manifests]
- SDT Need: [Autonomy / Competence / Relatedness] — deprivation amplifier [1.0 or 1.5] — [evidence claim ≤14 words, cited]
- Egri Premise: "[Character quality] leads to [consequence]" — exact formulation
- Protagonist Archetype: [Pearson name] — Shadow wound: [shadow archetype name] — [how shadow appears in story]
- Antagonist Archetype: [Pearson name] — Shared goal with protagonist: [stated explicitly]
- TRIZ Contradiction #N: [principle name] — [manifestation in plot; which pole chosen; why it backfires]
- Irreversibility Pattern: [one of 12 clock types from frameworks/forced-collision.md] — [the specific clock]
- Mednick Remote Associates: [element A] × [element B] — estimated cosine distance [0.30–0.50] — [named bridge]
- Macro Resonance Signal: [live statistic ≤14 words — source, year, URL]
- Macro Resonance Weight: [0.30 × GDELT_fear + 0.25 × google_trends + 0.25 × pew_polarization + 0.20 × fred_economic = N.NN]
- Simonton Type: [chance-configuration / combinatorial / transformational] — [evidence from concept structure]
- Wundt-Berlyne Position: [under-stimulating / optimal / over-stimulating] — [assessment rationale]
- Boden Classification: [combinatorial / exploratory / transformational] — [which conceptual space?]
- SIT Operator Applied: [Subtraction / Division / Multiplication / Task Unification / Attribute Dependency] — [what was done]
- Conceptual Blend: Input A: [domain] × Input B: [domain] → Generic space: [shared abstract structure] → Emergent: [what exists in neither input alone]
- Stanton Itch: [the un-resolvable compulsion driving the protagonist — not a goal, an itch they cannot name]
- Story Spine Seed: Once upon a time [_]. Every day [_]. One day [_]. Because of that [_]. Until finally [_]. And ever since then [_].
```

---

## Evidence Mandate

`## Audience & Market Evidence`: MUST contain ≥3 rows with real HTTPS URLs and years.
`## The World / Why Now?`: MUST cite ≥1 data point from a named source (year + URL). BANNED openers: "In today's world", "In a time when".
`## Genre Redirect Statement`: MUST cite ≥1 comparable film with year and box office figure.
`## Reality Grounding`: MUST cite ≥1 real database case (PubMed / CourtListener / Wikipedia Unusual / Studs Terkel / Shoah Foundation / MIT Moral Machine). If none found, write "UNGROUNDED" — this is a kill condition.
No bare-domain citations. No population sums posing as addressable audience.
Addressable audience MUST be derived from evidence table rows, not stated independently. Show derivation.

## SocraticAMA Research Activation

Before generating any concept, the agent SHOULD access these live signal sources
(via concept-researcher or directly via WebSearch if not available):

**Macro Resonance Data (for Macro Resonance Weight field):**
- GDELT fear scores: `https://api.gdeltproject.org/api/v2/summary/summary` (theme: [THEME])
- Google Trends 3yr slope: `pytrends` or `trends.google.com` (keywords from conflict pair)
- Pew polarization: latest American Trends Panel on relevant values axis
- FRED economic stress: `https://fred.stlouisfed.org/series/UMCSENT` or SIPOVGINIUSA

**Reality Grounding Sources:**
- PubMed: `https://pubmed.ncbi.nlm.nih.gov/?term=[SYNDROME+OR+WOUND+TYPE]`
- CourtListener: `https://www.courtlistener.com/?q=[LEGAL+EDGE+CASE]&type=o`
- Wikipedia Unusual: `https://en.wikipedia.org/wiki/List_of_unusual_deaths`
- MIT Moral Machine: `https://www.moralmachine.net` (for moral dilemma grounding)

**Combinatorial Operators (from Inputs/SocraticAMA/research/03_combinatorial_systems.md):**
The SIT Framework Tag field must name which operator generated this concept:
- Subtraction: removed a "necessary" story element
- Division: split protagonist role across characters
- Multiplication: duplicated element with altered attribute
- Task Unification: assigned additional role to existing story element
- Attribute Dependency: character trait shifts as function of story pressure

**Conceptual Blend Documentation (Fauconnier & Turner):**
The blend must name both input domains, the generic (shared abstract) space, and the EMERGENT property
— the thing that exists in neither input domain alone. This emergent property IS the concept's core novelty.

---

## Synopsis Rule

Check `## Framework Tags → Booker Plot`. Use the matching beat structure from `Inputs/CONCEPT_TEMPLATE.md`.
Do NOT use generic Act I/II/III if a Booker-specific structure exists for your plot type.
Reveal the ending. Investors buy the finished product, not a ticket.

---

## Characters Rule

Use the 10-field table format from `Inputs/CONCEPT_TEMPLATE.md § Characters`.
"Physical world detail" cell must be falsifiable — a real object, habit, or place. Generic descriptors (weathered hands, distant eyes) are forbidden.
Antagonist row is MANDATORY. They must share the protagonist's goal by opposite method.

---

## No Placeholder Rule

This is an internal document. Write no placeholder text.
Forbidden strings: "Contact placeholder", "Agency placeholder", "TBD", "[to be determined]", "[producer placeholder]".
The Team section uses real named directors, DPs, and composers — working shortlists, explicitly labeled as not attached.

---

## Geopolitical Hard Bans

REJECT any concept that:
- Invokes Soviet/Russian state apparatus as protagonist or sympathetic antagonist
- Uses small indigenous minority groups as sole audience anchor
- Features Cold War era as primary setting
- Presents post-Soviet collapse nostalgia as the "Why Now" hook

These are kill conditions, not preferences.

---

## Format Decision Gate (Fix #4 — required before forger writes Core DNA)

Before choosing a format, evaluate both paths:

**Theatrical feature path:** Budget $15–50M. Revenue ceiling $25–120M typical.
**Limited series path (6–8 eps):** Budget $18–40M. Acquisition $30–80M + streaming.

**Rule:** If the concept's addressable audience estimate exceeds 80M globally, the forger
MUST produce one sentence for each path and choose the higher-revenue option. Write the
chosen format in `## Core DNA → Format` with a one-sentence justification.

Series is often the higher-revenue path for: character-depth stories, true-crime hooks,
legal procedurals, ensemble casts, divisive moral questions. Theatrical wins for:
spectacle, franchise openers, single-revelation premises.

---

## Section Checklist (all 16 required)

- [ ] `## Core DNA` — all 17 fields
- [ ] `## Framework Tags` — all 17 fields
- [ ] `## Logline` — ≤35 words, TRIZ contradiction named
- [ ] `## High-Concept Statement` — ≤25 words
- [ ] `## Genre Redirect Statement` — 2 paragraphs, ≥1 film cited with gross
- [ ] `## The World / Why Now?` — ≥1 cited data point with URL
- [ ] `## Synopsis` — Booker beat structure, ending revealed
- [ ] `## Characters` — 10-field table, 3–5 characters, antagonist mandatory
- [ ] `## Visual Style & Tone` — cinematographic lineage, key visual rule
- [ ] `## Audience & Market Evidence` — ≥3 rows with HTTPS URLs
- [ ] `## Comparable Films` — ≥3 films, ≥1 cautionary, real grosses
- [ ] `## The Team` — real names, labeled "not attached"
- [ ] `## Reality Grounding` — ≥1 real database case with reference and URL
- [ ] `## Project Status & The Ask` — stage, budget with basis, ask with deliverables
- [ ] `## Genius Criteria Scorecard` — C001–C007 with Source and Rationale columns
- [ ] `## MASTER_QUESTIONS Challenge Results` — filled by concept-challenger agent

---

## Agent Reading Order (all agents)

1. This file (`Inputs/MASTER_BRIEF.md`) — always first
2. `Inputs/CONCEPT_TEMPLATE.md` — for format
3. `Inputs/RESEARCH_PROTOCOL.md` — before writing sections 5 and 6
4. `Inputs/CHALLENGE_PROTOCOL.md` — after forging, for the challenger agent
5. `Inputs/INTELLECTUAL_FRAMEWORK.md` — for Phase 2 of the challenge
6. audience-amplifier runs after challenger — produces [slug]-AMPLIFIED.md before narrator starts
7. concept-narrator runs LAST — reads AMPLIFIED.md before constructing Investment Summary Card

## Pipeline Sequence (per concept)

```
concept-researcher → [slug]-RESEARCH.md
       ↓
phase-4-forger → [slug].md (16 sections, CONCEPT_TEMPLATE format)
       ↓
concept-challenger → [slug]-CHALLENGE.md + fills Section 15 of [slug].md
       ↓
audience-amplifier → [slug]-AMPLIFIED.md  ← MANDATORY; runs before narrator
       ↓
concept-narrator → [slug]-NARRATOR.md (Investment Summary Card + investor brief)
```

The narrator reads AMPLIFIED.md for amplified SAM numbers in the Investment Summary Card.
The canonical [slug].md is never touched by narrator.
The investor reads [slug]-NARRATOR.md. The eval runs against [slug].md.

## SOTA Anthropic Recommendations (active)

- **Extended thinking** should be enabled for concept-challenger (11 P0 kill-switches require deep adversarial reasoning). Add `extended_thinking: true` to the agent invocation when routing through cc_dispatch.
- **Prompt caching**: MASTER_BRIEF.md and CONCEPT_TEMPLATE.md are read by every agent. Mark them as ephemeral cache candidates in cc_dispatch Task prompts to reduce token cost 60–80%.
- **Model selection**: concept-narrator uses Sonnet 4.6 (translation work, not deep reasoning). concept-challenger uses Sonnet 4.6 with extended thinking. phase-4-forger uses Sonnet 4.6 with Opus 4.7 gated per ADR-0006.
