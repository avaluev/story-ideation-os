# Research Protocol — Pre-Generation Verification
## Used by: concept-researcher agent
## Purpose: Fact-check genre saturation, cultural moment, and audience claims before the forger writes

---

## When to Run

Run ONCE per concept seed, BEFORE the forger writes Sections 5 and 6.
Results written to: `runs/YYYY-MM-DD-HHMMSS/[slug]-RESEARCH.md`

---

## Step A — Genre Saturation Check
### Input needed: premise type + primary genre
### Output goes to: Research Dossier § Genre Saturation

**Query template (send to Perplexity sonar-pro via Open Router):**

```
How many theatrical or streaming films explored [PREMISE TYPE] in the [PRIMARY GENRE] 
genre between 2020 and 2026? List 3 examples with:
- Film title and year
- Worldwide box office or streaming platform + viewership if available
- Critical reception (Rotten Tomatoes or Metacritic score)
- Whether the premise was considered saturated or novel at release
```

**Accept:** Named films with years and financial/viewership data.
**Reject:** Vague generalities, model-hallucinated titles, refusals.
**On rejection:** Log "Step A PARTIAL" and fall back to WebSearch:
  `site:boxofficemojo.com OR site:the-numbers.com "[PREMISE TYPE]" [PRIMARY GENRE] 2020..2026`

---

## Step B — Cultural Moment Verification
### Input needed: the cultural/technological/historical claim from the "Why Now?" concept
### Output goes to: Research Dossier § Cultural Moment Evidence

**Query template (send to Perplexity sonar-pro via Open Router):**

```
What is the current (2024–2026) statistical evidence for [CULTURAL CLAIM]?
Provide:
1. One primary source (government, academic institution, or major research org)
2. Publication year
3. Specific statistic (number, percentage, or trend direction)
4. Direct URL to the source document
```

**Accept:** Named org + year + specific number + HTTPS URL to primary source.
**Reject:** Percentage without sample size, undated claims, search-engine redirect URLs, bare-domain citations.
**On rejection:** Log "Step B PARTIAL" and fall back to:
  WebSearch: `"[CULTURAL CLAIM]" statistics site:pew.org OR site:gallup.com OR site:census.gov OR site:nih.gov`

---

## Step C — Audience Claim Verification
### Input needed: the addressable audience demographic and behavior pattern
### Output goes to: Research Dossier § Audience Evidence

**Primary method:** WebSearch (Open Router not required for this step)

**Search queries (run in order, stop at first success):**
1. `"[DEMOGRAPHIC]" "[BEHAVIOR PATTERN]" statistics [CURRENT_YEAR] site:pew.org`
2. `"[DEMOGRAPHIC]" "[BEHAVIOR PATTERN]" statistics [CURRENT_YEAR] site:census.gov`
3. `"[DEMOGRAPHIC]" "[BEHAVIOR PATTERN]" statistics [CURRENT_YEAR] site:statista.com`
4. `"[DEMOGRAPHIC]" "[BEHAVIOR PATTERN]" statistics [CURRENT_YEAR] site:gallup.com`

**Accept:** HTTPS URL to primary source + specific figure + year.
**Reject:** Aggregator summaries without primary source, undated figures, population sums without behavioral intersection.

---

## Open Router API Call Syntax

```bash
python -m pipeline.openrouter_client \
  --model perplexity/sonar-pro \
  --query "[YOUR QUERY TEXT]" \
  --phase research \
  --max-tokens 800
```

Falls back to WebSearch if:
- Open Router key exhausted (HTTP 402)
- Rate limit hit (HTTP 429)
- Model unavailable

**Cap:** 2 Open Router calls per concept (Step A + Step B only). Step C uses WebSearch only.

---

## Output Format

Write to `runs/[date]/[slug]-RESEARCH.md`:

```markdown
# Research Dossier — [Concept Title]
Generated: [ISO timestamp]

## Genre Saturation (Step A)
Status: VERIFIED / PARTIAL / FAILED
Findings:
- [Film 1, year, $XXM WW, RT score] — [verdict: saturated/novel]
- [Film 2, year, $XXM WW, RT score] — [verdict]
- [Film 3, year, $XXM WW, RT score] — [verdict]
Implication for concept: [one sentence]

## Cultural Moment Evidence (Step B)
Status: VERIFIED / PARTIAL / FAILED
Claim tested: "[exact claim from concept]"
Evidence:
- Source: [org name]
- Year: [year]
- Statistic: [exact number or percentage with sample size]
- URL: [https://...]
Verdict: VERIFIED / UNVERIFIED / INFERRED

## Audience Evidence (Step C)
Status: VERIFIED / PARTIAL / FAILED
Demographic tested: [description]
Evidence:
- URL: [https://...]
- Claim: [≤14 words]
- Year: [year]
Derivation: [N]M × [%] intersection = [addressable estimate]
Verdict: VERIFIED / UNVERIFIED / INFERRED

## Research Verdict
[SUFFICIENT — all 3 steps verified, forger may proceed]
[PARTIAL — N steps verified, N steps estimated; forger flags unverified claims]
[FAILED — Open Router unavailable AND WebSearch returned no primary sources; forger proceeds with [UNVERIFIED] labels]
```

---

## Labeling Rules for Forger

When incorporating research results into the concept:
- `VERIFIED` claims: cite source + year + URL inline
- `UNVERIFIED` claims: append `[UNVERIFIED]` tag
- `INFERRED` claims: append `[INFERRED — source cited for related data]`
