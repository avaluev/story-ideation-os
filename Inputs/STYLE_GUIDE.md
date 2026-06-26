# Style Guide — Investor-Facing Output (v4 Single-Idea Pipeline)
## Enforced by evals/test_no_internal_ids.py and evals/test_translation_friendly.py.
## Every rule here has a corresponding eval gate. No decoration.

---

## 1. Banned Terms (Regex Pattern)

The following regex MUST return zero matches in any file under `runs/`:

```
(?x)
Cell-ID:                   |
Per\ L\d+                  |
L\d+\b                     |
iter-\d+                   |
BT-\d+                     |
PS-\d+                     |
PA-\d+                     |
US-\d+                     |
TRIZ                       |
JTBD\b                     |
Booker\b                   |
McKee\b                    |
Boden\b                    |
Csikszentmihalyi\b         |
Reagan\ (2016|arc|plot)\b  |
Pearson\ archetype\b       |
Egri\ premise\b            |
Polti\ situation\b         |
Haidt\ foundation\b        |
Mednick\ remote\b          |
Wundt-Berlyne\b            |
Simonton\ type\b           |
Wundt\b                    |
Simonton\b                 |
Stanton\ itch\b            |
SIT\ Operator\b            |
Conceptual\ Blend\b        |
Macro\ Resonance\ Weight   |
Anti-slop\b                |
ten-school\b               |
Lessons\ consulted         |
Working\ title             |
iter-[0-9]+                |
run-id:                    |
Run\ ID:
```

No exceptions in `runs/` output. The drafter and genius-auditor sidecars (internal) may use these terms freely.

---

## 2. Hidden Attribute → Investor Prose Mapping

The 12 hidden attributes from `seed.json` shape the narrator's prose **without naming the framework or its author**. This table is the narrator agent's instruction set.

| Hidden Attribute (seed.json) | What the Narrator Writes (no label, no surname) |
|---|---|
| `arc_shape: Fall-Rise` | Emotional Arc section opens dark, pivots at a specific choice, closes with earned change — not false resolution |
| `arc_shape: Rise-Fall` | Emotional Arc opens with competence and confidence; the fall is caused by the protagonist's own strength used wrong |
| `arc_shape: Rise-Fall-Rise` | Emotional Arc names three distinct audience states without using "act" language |
| `booker: Voyage and Return` | Synopsis: outbound departure → trial in an unfamiliar world → return changed. No "voyage and return" phrase. |
| `booker: Tragedy` | Synopsis: protagonist's fatal flaw is also their best quality. The fall is structural, not unlucky. |
| `booker: Rebirth` | Synopsis: antagonist or dark force loses power when protagonist chooses differently at the final decision point. |
| `mckee: man vs self` | Protagonist subsection: inner contradiction drives plot, not external villain. The enemy is the protagonist's own belief. |
| `mckee: man vs society` | Protagonist subsection: the institution is the antagonist. The protagonist's personal virtue is the story's moral spine. |
| `emotional_weight: heavy` | Tonal Contract: "This asks the audience to endure [X] — and rewards that endurance with [Y]." Never says "heavy." |
| `emotional_weight: light` | Tonal Contract: comedic register named via the experience it produces, not its mood label. |
| `budget_tier: mid $15-50M` | Revenue Thesis anchors to mid-budget documented comps. Whiplash ($49.6M WW, $8.5M budget), Promising Young Woman ($21M WW, $2M budget). |
| `budget_tier: indie $1-15M` | Revenue Thesis: streaming acquisition comps. Awards-circuit trajectory named. |
| `boden: transformational` | Mass-Appeal Theme: "This concept changes what [genre] can do" — stated in plain English as the specific rule that breaks. |
| `boden: combinatorial` | Mass-Appeal Theme: names the two familiar elements and the specific angle that makes the combination feel inevitable. |
| `csikszentmihalyi: high` | Series Engine: explains the per-episode or per-season reorientation mechanic that maintains forward tension. |
| `timing_risk: zeitgeist-aligned` | Why Now section: leads with the cited data point, then the mechanism. Never "audiences are hungry for." |
| `timing_risk: timeless` | Why Now section: anchors to a structural human constant, cites a long-run data source (census, demographic trend). |
| `retro_fallacy_risk: immediate` | Comparables: names a recent breakout (≤5 years), not a cult classic or a "this is the new [prestige title]" hedge. |
| `cultural_specificity: universal` | Audience Sizing: names ≥3 territories with independently cited demand data. |
| `cultural_specificity: bicultural` | Audience Sizing: names the 2 primary territories, explains the cultural transfer mechanism. |
| `moral_wager` | Mass-Appeal Theme: one sentence stating the controlling idea in plain English. No "Controlling Idea" label. |
| `format_justification` | Format & Genre section: one sentence on why this format. The alternative format is named and dismissed in ≤10 words. |

---

## 3. Russian-Translation Rules

The final investor markdown must survive Russian translation without idiom loss. The narrator agent applies these rules at write time; `evals/test_translation_friendly.py` enforces them.

| Rule | Why |
|---|---|
| Flesch-Kincaid grade ≤12 | Russian literary register is formal; over-complex English produces machine-translation artifacts |
| No compound clause > 30 words | Split into two sentences. Long English compounds become syntactically ambiguous in Russian. |
| No phrasal verbs as idioms | "run with an idea" → "develop an idea". Every phrasal verb must be replaceable with a single verb. |
| No sports idioms | "move the goalposts", "in the ballpark" → plain equivalents |
| No legal register idioms | "pursuant to", "whereas" → plain English |
| Numbers: always write the full number | "$100 million" not "$100M" in prose (though tables may use $100M) |
| Avoid em-dash as clause joiner | Use period + new sentence instead. Em-dash is poorly handled in some Cyrillic typesetting. |

Blocklist (expand as failures are found):
- "move the needle" → "make a measurable difference"
- "on the table" → "under consideration"
- "in the weeds" → "in the technical details"
- "a slam dunk" → "a certain success"
- "low-hanging fruit" → "the easiest opportunity"
- "circle back" → "return to"
- "bandwidth" (non-technical) → "capacity" or "time"
- "double-down" → "commit further"

---

## 4. Narrator Agent Rules

These apply exclusively to the `concept-narrator` agent's system prompt. They are not prose requirements — they are agent-level behavioral rules.

1. **Read `seed.json` first.** Map every hidden attr using Section 2 of this guide before writing a single word.
2. **Never name a framework author or theory label in output.** The prose must embody the principle, not cite it.
3. **Never reference internal pipeline state.** No "the challenger found…", no "iteration 2 improved…", no "the amplifier calculated…".
4. **Every numeric claim in the output must appear verbatim in a sidecar file.** Do not compute new numbers. Pull from `amplification.json` for SOM/SAM/TAM, from `research.json` for comp revenues.
5. **The film title is the document title.** Not "Working Title: X". Not "Concept: X". Just `# X`.
6. **All four H1 sections must be present.** The eval gate rejects any document missing `# 1. Market & Audience`, `# 2. The Concept`, `# 3. Story`, or `# 4. Characters`.
7. **Series Engine section is conditional.** Write it for series (`target_format: series`). Omit it entirely for features (`target_format: feature`). The eval checks `seed.json:target_format` before requiring it.
