---
concept_id: REJ-niche-audience
status: rejected
failure_mode: audience_below_50m_floor
failing_checks: ["ajtbd_score_lt_threshold", "cited_audience_lt_50m"]
---

# REJ-niche-audience

## Logline

A restored medieval Arabic astrolabe reveals the coordinates of a lost
tenth-century Islamic observatory in Morocco — but only three scholars in the
world know how to read its notation system, and two of them believe the
discovery would invalidate their life's work.

## Why This Failed

**Failure mode:** Audience below 50M floor. The premise is intellectually
compelling and contains genuine TRIZ elements (the instrument authenticates its
own discovery while threatening the careers of those who can interpret it), but
the addressable theatrical audience — people who would attend a film about
medieval Islamic astronomical instruments — does not meet the minimum threshold.

**Failing checks:**

- `cited_audience_lt_50m`: The Audience Validator identified the primary
  addressable audience as: (a) history-of-science enthusiasts globally,
  estimated 3–5 million theatrical attendees annually; (b) Islamic Golden Age
  scholars and students, estimated 800,000–1.2 million; (c) Moroccan national
  heritage audiences, estimated 1.5–2 million. Combined TAM: approximately
  5–8 million. This is 10–16% of the 50 million floor. The concept fails the
  hard floor regardless of quality on other axes.

- `ajtbd_score_lt_threshold`: When audience_size < 50,000,000, the AJTBD
  component of the upstream score is set to 0 by pipeline/scoring.py (ADR-0002).
  With sdt=62 and ajtbd=0, the upstream score is 62. Even perfect critic scores
  (30+25+25+20=100) cannot push the final score past 81, which is below the
  85-point floor. The concept is structurally unreachable regardless of execution
  quality.

**Why the premise cannot be rescued:** The audience floor is not a taste judgment
— it is a commercial viability requirement. A concept with a 5M TAM requires
festival-only distribution economics, which the Anomaly Engine does not optimize
for. The underlying idea (a discovery that is simultaneously proof and threat
to its interpreters) is strong and could be transplanted into a domain with
larger audience reach — medieval Arabic astronomy as a MacGuffin in a thriller
with a broader human stakes claim.

**Stabilization lesson:** Evaluate audience size before investing in TRIZ
architecture. The engine's scoring formula weights upstream (SDT + AJTBD)
at 100% before critic adjustment. A concept that fails the audience floor cannot
be rescued by specificity or novelty. Build the audience claim first; if the
honest audience is below 50M, either find the universal JTBD that unlocks a
broader audience or reject the concept before spending critic cycles on it.
