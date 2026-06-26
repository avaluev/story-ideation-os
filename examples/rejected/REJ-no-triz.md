---
concept_id: REJ-no-triz
status: rejected
failure_mode: no_triz_contradiction
failing_checks: ["contradiction_score_lt_15", "no_irreversible_moment"]
---

# REJ-no-triz

## Logline

Two astronauts on the International Space Station discover that their crewmate
has been reading classified mission documents he was not authorized to access.
They must decide whether to report the breach to ground control — which will
end his career — or cover for him, risking their own clearances if the truth
emerges later.

## Why This Failed

**Failure mode:** No TRIZ contradiction, no irreversible moment. The premise
presents a genuine ethical dilemma — report or cover — but a dilemma is not a
TRIZ contradiction. The two choices have different consequences, but neither
choice makes the other worse to execute. Reporting does not simultaneously make
covering harder; covering does not simultaneously make reporting more expensive.
The situation is a fork in the road, not a contradiction.

**Failing checks:**

- `contradiction_score_lt_15`: The adversarial critic assigned a contradiction
  score of 9/25. A TRIZ contradiction requires that improving one parameter of
  a system automatically worsens another parameter of the same system. In this
  concept, "report the breach" and "cover for him" are not linked parameters of
  a single system — they are independent choices with different outcome
  distributions. The critic found no mechanism by which choosing one makes the
  other more costly. Score: 9/25.

- `no_irreversible_moment`: The A4 format requires an irreversible moment — a
  specific event after which the cost of truth-telling has permanently changed.
  In this concept, no such moment exists. The astronauts could report the breach
  at any point during the mission; the cost of reporting does not structurally
  increase as time passes. Without an irreversible moment, there is no ticking
  clock, and without a ticking clock there is no thriller — there is a moral
  debate that could resolve at any time.

**Why the premise cannot be rescued with minor fixes:** Adding a deadline (the
crewmate's report-reading becomes relevant during a mission-critical maneuver)
would create time pressure but still would not create a TRIZ contradiction.
The concept needs a mechanism where the act of covering for him actively makes
reporting harder — for example, if covering requires falsifying a log, which
creates evidence of the cover-up that is more damaging than the original breach.
At that point, the concept is different — it has found its contradiction.

**Stabilization lesson:** Test for TRIZ contradiction with this question: "Does
solving the protagonist's primary goal automatically make the secondary goal
worse?" If the answer is no, there is no contradiction — there is a choice. The
Anomaly Engine requires that the protagonist be trapped by a system, not simply
facing a difficult decision. A difficult decision can be deferred. A TRIZ
contradiction cannot — it operates on the protagonist whether or not they act.
