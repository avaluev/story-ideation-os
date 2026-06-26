# Challenge Protocol — 3-Phase Concept Interrogation
## Used by: concept-challenger agent
## Sources: Inputs/10May/research/MASTER_QUESTIONS.md, Inputs/10May/research/GREATNESS_CHECKLIST.json

---

## How to Execute

1. Read the completed concept file from `runs/[date]/[slug].md` completely.
2. Run Phase 1 (11 P0 kill-switch questions). **If ANY fails: write CHALLENGE.md with REJECT verdict and STOP.**
3. If Phase 1 passes: run Phase 2 (7 P1 strategic questions). Flag failures as CONDITIONS.
4. Run Phase 3 (5 cross-domain insights). Do not block publication.
5. Write output to `runs/[date]/[slug]-CHALLENGE.md`.
6. Fill Section 15 of the concept file with Phase 1 summary + Final Verdict.

---

## Phase 1 — P0 Kill-Switch Questions
### One FAIL = REJECT. Do not proceed to Phase 2.
### For each: state PASS or FAIL + one sentence of evidence from the concept.

**[EP-Q01] Genre violation test**
Question: Does the idea violate the logical next step of its primary genre?
Operationalization: Compare the logline to 3 recent genre representatives. Is there genuine divergence?
Kill condition: The concept is the logical continuation of an existing franchise or trend, not a departure.

**[EP-Q12] Philosophical weight test**
Question: If execution were mediocre, would the concept still hold philosophical weight?
Operationalization: Remove all character names and plot details. Does the underlying theme survive as an argument?
Kill condition: Concept is execution-dependent with no underlying philosophical claim.

**[CS-Q02] Goldilocks zone test**
Question: Is the associative distance between primary premise elements 0.30–0.50 cosine similarity?
Operationalization: Name the two most distant conceptual elements. Estimate their cosine similarity.
Kill if: < 0.30 (obvious mashup, no surprise) or > 0.50 (bridge unclear, alienating).
Report the estimated value and the named bridge.

**[CS-Q03] Emotional anchor test**
Question: Is the emotional anchor identifiable and sufficient for 90-minute investment?
Operationalization: Strip the plot to its P0 anchor (Family / Grief / Survival). Does it hold without the premise?
Kill condition: Primary driver is premise-curiosity, not universal human need.

**[Q3.3] Family anchor test**
Question: Is the Family / Grief / Survival anchor present at the A-plot level and un-subverted?
Kill condition: The concept destroys the family unit, primary relationship, or survival without a rebirth arc.

**[MD-Q12] 25-word high-concept test**
Question: Can the concept be stated in ≤25 words that a greenlight committee understands without explanation?
Operationalization: Write the 25-word statement. Count the words. Does it require a subordinate clause?
Kill condition: Requires domain knowledge or subordinate clauses to comprehend.
Required output: State the exact ≤25-word version.

**[SC-Q04] Wundt-Berlyne surprise test**
Question: Is the concept in the optimal surprise range — not obvious, not incomprehensible?
Operationalization: Would a general-interest audience orient themselves within 60 seconds of premise exposure?
Kill condition: Under-stimulating (the "so what?" response) OR over-stimulating (the "I don't get it" response).

**[Q6_01] Single failure mode**
Question: If this film has already failed, what is the single most likely point of failure?
Operationalization: Name it explicitly. This is not a kill condition — it is a mandatory diagnostic.
Required output: One sentence naming the failure mode.

**[Q6_04] Protagonist agency test**
Question: Does the protagonist drive the plot, or are they a tour guide for world-building?
Operationalization: List 3 protagonist-initiated actions from the synopsis.
Kill condition: Fewer than 2 protagonist-initiated actions appear in the synopsis before the midpoint.

**[Q6_07] AI slop Jaccard test**
Question: Is this concept indistinguishable from common AI-generated output patterns?
Operationalization: Does the concept share ≥40% of its premise elements with these common AI patterns:
  - "AI goes rogue / learns to feel"
  - "Last humans in a dystopia discover the truth"
  - "Scientist discovers something that changes everything"
  - "Grief journey with magical realism element"
  - "Corporate conspiracy vs. lone whistleblower"
  - "Time travel causes paradox that must be resolved"
Kill condition: ≥40% element overlap with any pattern above AND no structural inversion.

**[ARCH-Q03] TRIZ contradiction resolution test**
Question: Is the TRIZ contradiction in Framework Tags genuinely resolved in Act III, or only described?
Operationalization: Does the Act III resolution offer a non-obvious synthesis that holds BOTH poles?
Kill condition: Protagonist simply "chooses one pole" without the contradiction collapsing into something new.

---

## Phase 2 — P1 Strategic Questions
### Failure = CONDITIONAL (not REJECT). Concept advances with conditions listed.
### For each: state PASS / CONDITIONAL / FAIL + one-sentence finding.

**[EP-Q02]** Is the novelty transformational (restructures the genre's rules) vs. merely combinational (new mashup)?
**[CS-Q11]** Does the concept "find problems" rather than solve plots — does it generate escalating conflict organically?
**[Q3.2]** Does the 70/30 satisfaction/subversion ratio hold — 70% genre expectations met, 30% inverted?
**[MD-Q03]** Is the hook durable in a saturated attention economy — will it still work in 18 months?
**[MD-Q11]** Does the local cultural anchor improve global travelability, or limit it?
**[SC-Q03]** Is the "Adjacent Possible" for this genre clearly mapped — where does this concept sit on the frontier?
**[SC-Q05]** Do the C001–C007 scoring dimensions ensemble (reinforce each other) or cancel?

**Intellectual Framework Integration (Phase 2 extension):**
Read `Inputs/INTELLECTUAL_FRAMEWORK.md`. Select the 3–5 criteria MOST relevant to this specific concept.
Add their assessment here under the label "Domain Analysis."

---

## Phase 3 — Cross-Domain Insights
### Do not block publication. Generate improvement notes for iteration.

Select 5 cross-domain questions (XD-01 through XD-15) from MASTER_QUESTIONS.md that are most relevant to this concept.

For each: "If this concept were iterated, the highest-leverage change based on [XD-NN] would be: [specific change]."

---

## Output Format

Write to `runs/[date]/[slug]-CHALLENGE.md`:

```markdown
# Challenge Report — [Concept Title]
Generated: [ISO timestamp]
Source concept: runs/[date]/[slug].md

## Phase 1 Results — P0 Kill-Switch (11 questions)

| Code | Question | Result | Evidence |
|------|----------|--------|----------|
| EP-Q01 | Genre violation | PASS/FAIL | [one sentence] |
| EP-Q12 | Philosophical weight | PASS/FAIL | [one sentence] |
| CS-Q02 | Goldilocks zone | PASS/FAIL | estimate: [0.XX], bridge: [name] |
| CS-Q03 | Emotional anchor | PASS/FAIL | anchor: [Family/Grief/Survival], [how central] |
| Q3.3 | Family anchor | PASS/FAIL | [one sentence] |
| MD-Q12 | 25-word test | PASS/FAIL | "[exact 25-word statement]" |
| SC-Q04 | Wundt-Berlyne | PASS/FAIL | [one sentence] |
| Q6_01 | Failure mode | REQUIRED | [stated explicitly] |
| Q6_04 | Agency test | PASS/FAIL | actions: [list 3] |
| Q6_07 | AI slop | PASS/FAIL | [what makes it non-generic] |
| ARCH-Q03 | TRIZ resolution | PASS/FAIL | [resolution mechanism] |

Phase 1 Verdict: PASS (proceed) / REJECT (kill-switch failure: [list failed codes])

## Phase 2 Results — P1 Strategic (7 questions + Domain Analysis)

| Code | Question | Result | Finding |
|------|----------|--------|---------|
| EP-Q02 | Transformational? | PASS/CONDITIONAL/FAIL | [one sentence] |
| CS-Q11 | Finds problems? | PASS/CONDITIONAL/FAIL | [one sentence] |
| Q3.2 | 70/30 rule? | PASS/CONDITIONAL/FAIL | [one sentence] |
| MD-Q03 | Hook durability? | PASS/CONDITIONAL/FAIL | [one sentence] |
| MD-Q11 | Travelability? | PASS/CONDITIONAL/FAIL | [one sentence] |
| SC-Q03 | Adjacent possible? | PASS/CONDITIONAL/FAIL | [one sentence] |
| SC-Q05 | Dimensions ensemble? | PASS/CONDITIONAL/FAIL | [one sentence] |

### Domain Analysis (3–5 criteria from INTELLECTUAL_FRAMEWORK.md)
[criterion ID + assessment]

Phase 2 Conditions (if any): [list conditions that must be addressed before pitch]

## Phase 3 — Cross-Domain Insights (5 selected)

[XD-NN]: [improvement note]
[XD-NN]: [improvement note]
[XD-NN]: [improvement note]
[XD-NN]: [improvement note]
[XD-NN]: [improvement note]

## Final Verdict

[STRONG PASS — all P0 tests passed, no P1 conditions]
[CONDITIONAL — all P0 passed, conditions: [list]]
[REJECT — P0 kill-switch failure: [list failed codes with reasons]]
```

---

## How to Fill Section 15 of the Concept File

After writing CHALLENGE.md, update the concept's `## MASTER_QUESTIONS Challenge Results` section:

Copy the Phase 1 table rows verbatim.
Copy the Phase 2 Conditions summary (1–3 sentences).
Copy the Final Verdict line.
Do NOT modify any other section of the concept file.
