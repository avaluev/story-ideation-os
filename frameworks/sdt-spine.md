# SDT Spine — The Three Innate Psychological Needs

## Frame

Self-Determination Theory (SDT) is the psychological spine of the Anomaly Engine. The engine's core thesis — drawn from PROJECT.md "audience deprivation thesis" — is that a film concept generates sustainable commercial interest proportional to the degree it addresses a real, systematic deprivation of one of three innate psychological needs: Autonomy, Competence, or Relatedness. These needs are innate, universal, and cross-cultural; their satisfaction drives wellbeing and their chronic frustration produces restlessness, the emotional precondition for cinema attendance.

Core SDT reference: Ryan, R. M., & Deci, E. L. (2000). "Self-determination theory and the facilitation of intrinsic motivation, social development, and well-being." *American Psychologist, 55*(1), 68–78. [selfdeterminationtheory.org/SDT/documents/2000_RyanDeci_SDT.pdf](https://selfdeterminationtheory.org/SDT/documents/2000_RyanDeci_SDT.pdf) | [selfdeterminationtheory.org/theory/](https://selfdeterminationtheory.org/theory/)

---

## The Three Needs

### Autonomy

**Definition (paraphrased from Ryan & Deci 2000):** Autonomy is the experience of volition — acting from one's own values and choices rather than external pressure. People feel autonomous when their behavior reflects their genuine self rather than coercion.

Film examples demonstrating Autonomy deprivation and its resolution:

1. **The Truman Show** (Peter Weir, 1998) — Truman's entire life is engineered by an external authority; escaping the dome is a literal autonomy reclamation. [imdb.com/title/tt0120382](https://www.imdb.com/title/tt0120382)
2. **Dead Poets Society** (Peter Weir, 1989) — Students suppressed by institutional conformity; Keating's "seize the day" is an autonomy catalyst. [imdb.com/title/tt0097165](https://www.imdb.com/title/tt0097165)
3. **Schindler's List** (Steven Spielberg, 1993) — Jews stripped of every autonomous choice; Schindler's factory represents a pocket of restored autonomy within a totalitarian system. [imdb.com/title/tt0108052](https://www.imdb.com/title/tt0108052)
4. **Spartacus** (Stanley Kubrick, 1960) — Enslaved people pursuing collective self-determination against Rome's absolute authority. [imdb.com/title/tt0054331](https://www.imdb.com/title/tt0054331)
5. **Erin Brockovich** (Steven Soderbergh, 2000) — Single mother asserts agency against corporate and legal systems designed to silence her. [imdb.com/title/tt0195685](https://www.imdb.com/title/tt0195685)
6. **Fight Club** (David Fincher, 1999) — Office worker's psychic rebellion against consumerism and identity erasure; toxic autonomy as cautionary tale. [imdb.com/title/tt0137523](https://www.imdb.com/title/tt0137523)

SDT source: [guilford.com/excerpts/ryan.pdf](https://guilford.com/excerpts/ryan.pdf)

---

### Competence

**Definition (paraphrased from Ryan & Deci 2000):** Competence is the experience of effectiveness — the felt sense of mastery, growth, and the capacity to produce outcomes through skill. People feel competent when challenges stretch without overwhelming them.

Film examples demonstrating Competence deprivation and its resolution:

1. **Whiplash** (Damien Chazelle, 2014) — Drumming student pursues mastery under brutal pressure; explores the dark costs of competence-seeking. [imdb.com/title/tt2582802](https://www.imdb.com/title/tt2582802)
2. **Black Swan** (Darren Aronofsky, 2010) — Ballerina's obsessive pursuit of perfect technical command at the cost of psychological integrity. [imdb.com/title/tt0947798](https://www.imdb.com/title/tt0947798)
3. **The Martian** (Ridley Scott, 2015) — Astronaut's survival through systematic application of scientific competence against impossible odds. [imdb.com/title/tt3659388](https://www.imdb.com/title/tt3659388)
4. **Searching for Bobby Fischer** (Steven Zaillian, 1993) — Child chess prodigy navigating institutional pressure vs. genuine intellectual mastery. [imdb.com/title/tt0108065](https://www.imdb.com/title/tt0108065)
5. **Hidden Figures** (Theodore Melfi, 2016) — Black women mathematicians whose competence is systematically denied recognition by institutional racism. [imdb.com/title/tt4846340](https://www.imdb.com/title/tt4846340)
6. **Million Dollar Baby** (Clint Eastwood, 2004) — A woman builds boxing competence against every structural barrier; competence-tragedy arc. [imdb.com/title/tt0405159](https://www.imdb.com/title/tt0405159)

SDT source: [stial.ie/resources/Ryan%20and%20Deci%202020%20self%20determination%20theory.pdf](https://stial.ie/resources/Ryan%20and%20Deci%202020%20self%20determination%20theory.pdf)

---

### Relatedness

**Definition (paraphrased from Ryan & Deci 2000):** Relatedness is the experience of belonging — feeling genuinely connected to others, cared for, and significant to a social world. Chronic relatedness deprivation produces loneliness, the most corrosive threat to wellbeing across all age groups.

Film examples demonstrating Relatedness deprivation and its resolution:

1. **Up** (Pete Docter, 2009) — Opening sequence depicts the fullness and subsequent loss of a shared life; rest of the film is a relatedness recovery arc. [imdb.com/title/tt1049413](https://www.imdb.com/title/tt1049413)
2. **Lost in Translation** (Sofia Coppola, 2003) — Two strangers in Tokyo form a transient bond that temporarily relieves structural disconnection. [imdb.com/title/tt0335266](https://www.imdb.com/title/tt0335266)
3. **Brokeback Mountain** (Ang Lee, 2005) — Two men whose relatedness need is systematically suppressed by cultural prohibition; unresolved longing as tragedy. [imdb.com/title/tt0388795](https://www.imdb.com/title/tt0388795)
4. **Manchester by the Sea** (Kenneth Lonergan, 2016) — Grief-isolated man's inability to re-enter relatedness after catastrophic loss. [imdb.com/title/tt4209788](https://www.imdb.com/title/tt4209788)
5. **Lady Bird** (Greta Gerwig, 2017) — Mother-daughter relatedness rupture and repair across the rupture of adolescent separation. [imdb.com/title/tt4080728](https://www.imdb.com/title/tt4080728)
6. **Coco** (Lee Unkrich, 2017) — Multi-generational family connection severed by a generations-old mistake; restoration of familial relatedness as resolution. [imdb.com/title/tt2380307](https://www.imdb.com/title/tt2380307)

---

## Cross-Cultural Deprivation Amplifier

When a concept targets an audience that is **systemically deprived** of the primary SDT need — not merely experiencing individual hardship but facing a structural deficit that defines their demographic — the Forge applies a ×1.5 amplifier to the primary need's contribution to `sdt_score`. This amplifier is **gated on cited evidence**: the Forge must emit an `sdt.deprivation_amplifier_evidence_url` that the Critic can HEAD-check.

**Evidence baseline for the amplifier:**

- US Surgeon General Advisory on loneliness (Relatedness deprivation, 2023): [hhs.gov/sites/default/files/surgeon-general-social-connection-advisory.pdf](https://www.hhs.gov/sites/default/files/surgeon-general-social-connection-advisory.pdf)
- Pew Research Center Global Attitudes — diaspora identity data (Relatedness × Autonomy, 2022): [pewresearch.org/global/2022/09/15/diaspora-report](https://www.pewresearch.org/global/2022/09/15/diaspora-report)
- World Economic Forum Future of Jobs Report 2023 — AI-displacement anxiety (Competence deprivation): [weforum.org/reports/the-future-of-jobs-report-2023](https://www.weforum.org/reports/the-future-of-jobs-report-2023)

The amplifier raises the ceiling: `amplified = primary_contrib * 1.5`, but the function is still capped at 70. See §The sdt_score Formula and §The Worked Al-Bukhari Example below for exact computation.

---

## The sdt_score Formula

The following closed-form pseudocode defines the contract. **This is the only definition.** `pipeline/scoring.py::sdt_score` in P3 must implement this formula exactly — verified by the XFAIL golden fixture in `tests/test_sdt_golden_fixture.py`. The LLM MUST NOT compute `sdt_score` directly (ADR-0002).

```python
def sdt_score(
    primary_need: str,          # "autonomy" | "competence" | "relatedness"
    primary_strength: float,    # [0.0, 1.0] — Forge assigns; Critic validates
    secondary_need: str | None, # second need name, or None
    secondary_strength: float,  # [0.0, 1.0] — strength of secondary need
    deprivation_amplifier_active: bool,  # True if cited evidence URL provided
) -> int:
    s1 = primary_strength
    s2 = secondary_strength
    amp = 1.5 if deprivation_amplifier_active else 1.0
    amplified = (50 * s1 * amp) + (20 * s2)
    return min(round(amplified), 70) if s1 >= 0.7 else 0
```

**Coefficients:**
- Primary need: **50 points maximum** (before amplifier)
- Secondary need: **20 points maximum** (not amplified)
- Deprivation amplifier: ×1.5 on primary only
- Hard cap: **70 points** (remaining 30 live in `ajtbd_score`)
- Floor gate: `s1 < 0.7` → returns 0 (concept fails SDT gate)

---

## Why ≤70

The SDT score is capped at 70 out of 100 by design. SDT satisfaction is necessary but not sufficient for a commercially viable high-concept film: a concept about Relatedness that targets no identifiable real-world audience with cited evidence for that audience's size, trend, and geographic spread cannot be financed. The remaining 30 points live exclusively in `ajtbd_score` (see `frameworks/ajtbd-segmentation.md`). A concept's `total_score = sdt_score + ajtbd_score ∈ [0..100]`. The 70/30 split reflects the engine's judgment that psychological resonance (70%) is the harder-to-fake component; audience evidence (30%) is verifiable but secondary to the core emotional logic.

---

## SDT primary-strength ≥0.7 floor

Every concept declares `primary_need ∈ {autonomy, competence, relatedness}` and `primary_strength ∈ [0.0, 1.0]`. A concept with `primary_strength < 0.7` fails the SDT gate and `sdt_score` returns `0` — the concept is ineligible for Forge output regardless of its `ajtbd_score`. This floor exists because a concept where the primary psychological need is only weakly present (strength < 70%) is unlikely to generate sustained audience motivation. PROMPT-02 (P2) enforces the floor at prompt-generation time; `pipeline.scoring.sdt_score` enforces it computationally.

---

## The Worked Al-Bukhari Example

*Al-Bukhari* is a working concept in the Anomaly Engine demo corpus: a young Islamic scholar in 9th-century Khurasan who memorizes 600,000 hadiths — a feat of obsessive Competence — while navigating the loneliness of exile from family (Relatedness as primary). The concept targets global Muslim millennials with college access, a segment experiencing systematic Relatedness deprivation (diaspora disconnection) documented in cited evidence.

**Input table:**

| Parameter | Value |
|---|---|
| `primary_need` | `"relatedness"` |
| `primary_strength` | `0.95` |
| `secondary_need` | `"competence"` |
| `secondary_strength` | `0.7` |
| `deprivation_amplifier_active` | `True` |

**Step-by-step computation:**

```
s1  = 0.95
s2  = 0.7
amp = 1.5   (deprivation_amplifier_active is True)

primary_contrib   = 50 * s1 * amp
                  = 50 * 0.95 * 1.5
                  = 71.25

secondary_contrib = 20 * s2
                  = 20 * 0.7
                  = 14.0

amplified         = primary_contrib + secondary_contrib
                  = 71.25 + 14.0
                  = 85.25

rounded           = round(85.25)
                  = 85

capped            = min(85, 70)
                  = 70

floor check:      s1 = 0.95 >= 0.7  →  pass
```

**Result:**

sdt_score = 70

This is the **golden fixture** for `tests/test_sdt_golden_fixture.py`. The P3 implementation of `pipeline/scoring.py::sdt_score` must return integer `70` (not `70.0`, not `71`) for this exact input set. Any drift surfaces as a strict test failure.

---

## Operational Integration

> This section is load-bearing (KNOW-11). It must be in the last 30% of the file. The cross-plan structure-lint test `tests/test_frameworks_have_integration_section.py` (plan 01-05) enforces this as an integration backstop.

### Forge Fields Produced

```json
{
  "sdt": {
    "primary_need": "autonomy | competence | relatedness",
    "primary_strength": "<float 0.0..1.0>",
    "secondary_need": "autonomy | competence | relatedness | null",
    "secondary_strength": "<float 0.0..1.0>",
    "deprivation_amplifier_evidence_url": "<URL HEAD-checkable or null>"
  }
}
```

### Critic Re-Checks

- `primary_strength >= 0.7` (floor gate; concept is dropped if this fails)
- `deprivation_amplifier_evidence_url` must return HTTP 2xx when HEAD-checked (if not null)
- `secondary_need != primary_need` (cannot declare the same need twice)
- `sdt_score` field in output is `None` until `pipeline/scoring.py::sdt_score` runs — LLM MUST NOT populate it (ADR-0002)

### P3 Target Function

```
pipeline/scoring.py::sdt_score(
    primary_need: str,
    primary_strength: float,
    secondary_need: str | None,
    secondary_strength: float,
    deprivation_amplifier_active: bool,
) -> int
```

Returns integer `0..70`. Cites this file (§The sdt_score Formula) per ADR-0005.

### Cross-References

- **`frameworks/ajtbd-segmentation.md`** — `sdt_score + ajtbd_score = 100` is the total scoring invariant. `ajtbd_score ∈ [0..30]` completes the budget. The two scores are computed independently in `pipeline/scoring.py` and summed to `total_score`.
- **`frameworks/narrative-master-grid.md`** — the Polti situation cluster that best serves each SDT need: Polti 20–Self-Sacrifice for an Ideal (Autonomy); Polti 9–Daring Enterprise (Competence); Polti 35–Recovery of a Lost One (Relatedness). The Forge should prefer Polti IDs from the matching cluster when the SDT primary need is known.
