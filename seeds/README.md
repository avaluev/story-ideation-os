# seeds/ — operator-curated anomaly inputs

> Each seed is a real-world anomaly with verifiable Tier-1 sources. The
> idea-engine reads ONE seed and produces ONE iterated idea per `/idea-engine` call.

---

## What's pre-loaded

| File | Anomaly | Audience hook |
|---|---|---|
| `01-boeing-barnett.md` | Boeing John Barnett whistleblower death (Mar 2024) + Joshua Dean MRSA (May 2024) | 100M+ US/UK/CA/AU/NZ/IE flyers + 250K Boeing employees |
| `02-norfolk-southern-east-palestine.md` | Norfolk Southern train 32N derailment, vinyl chloride controlled burn (Feb 2023) | 50M+ Ohio River basin + 100M+ rail-corridor + 200M+ chemical-anxious |
| `03-maui-lahaina-hawaiian-electric.md` | Lahaina wildfires + Hawaiian Electric power-line ignition (Aug 2023) | 50M+ Western US wildfire-affected + 1.4M Hawaiians |
| `04-openai-board-coup.md` | OpenAI Nov 2023 board firing of Sam Altman + employee letter | 100M+ ChatGPT users + 50M+ tech-industry |
| `05-adderall-shortage-done-health.md` | Adderall/ADHD stimulant shortage + DEA quotas + Done Health DOJ indictment (Nov 2023) | 30M+ US adults on stimulants + 6M+ households w/ ADHD-diagnosed kids |

(Two legacy YAML files — `audience-segments.yaml`, `domains.yaml` — are
inherited from v3.0 lineage and unused by the v0.5 idea-engine. Safe to
ignore or delete.)

## How to add a new seed

A seed is a markdown file with this structure:

```markdown
# Anomaly {NN} — {short-name}

**Tier-1 PRIMARY sources:** (≥3, ≥2 distinct domains, ≥1 gov/court/peer-review)
- {source 1 with URL}
- {source 2 with URL}
- {source 3 with URL}

**300-word summary:**
{what happened, when, who, what numbers, what's contested, what's verifiable}

**Named entities (Tier-1 verifiable):**
- {Person 1 + role + verification URL}
- {Person 2 + role + verification URL}

**Three potential SECOND-anomaly contradictions (the contradiction engine):**
1. {a contradiction that creates an irreversible bind}
2. {another, different contradiction}
3. {a third option the agent can pick from}

**SDT need amplifier:**
PRIMARY: {autonomy | competence | relatedness}
SECONDARY: {autonomy | competence | relatedness | none}
DEPRIVATION AMPLIFIER: {1.0 or 1.5 — 1.5 if the deprivation is acute and well-documented}

**Audience hook:** {≥30M US/UK/CA/AU/NZ/IE addressable adults — name them with rough estimates and 1 streaming-behavior anchor where possible}

**Why untapped:** {1-2 sentences confirming this hasn't been adapted to major scripted fiction yet — check Letterboxd / IMDb / TMDB}
```

Save as `seeds/{NN}-{short-name}.md` where NN is the next available 2-digit number.

## Hard rules for seed selection

- ✓ Real anomaly with Tier-1 sources (gov filings, court records, peer-reviewed papers, named-investigator news investigations like ProPublica/NYT/Reuters/AP/Bloomberg)
- ✓ ≥30M US/UK/CA/AU/NZ/IE addressable adults
- ✓ Post-2022 currency (or earlier if the anomaly has 2024+ developments)
- ✓ Not yet adapted to major scripted fiction (check TMDB, Letterboxd)
- ✓ Has named human protagonists in the evidence (not just abstract corporate names)
- ✗ NO Soviet / post-Soviet / Russian period framing as primary setting
- ✗ NO anti-Russian framing
- ✗ NO small-people-group anchoring (a 727-person island = setting OK, but conflict must generalize to ≥30M)
- ✗ NO aggregate-population audience claims ("2B Muslims", "1.4B Indians", "world population")

## Where to find new seeds

- **PubMed** for medical case reports + drug shortages
- **CourtListener** for federal court opinions + class actions
- **NTSB / FAA / OSHA / EPA** investigation reports
- **SEC EDGAR** 8-K filings + DOJ indictments
- **ProPublica / Bellingcat / Bureau of Investigative Journalism** investigations
- **NYT / WaPo / Reuters / AP / Bloomberg** named-byline investigations
- **Senate / House committee hearings** transcripts
- **Retraction Watch** for academic-fraud cases

A good seed takes ~1 hour to research and write. The engine then turns it into 1-5 iterated ideas.
