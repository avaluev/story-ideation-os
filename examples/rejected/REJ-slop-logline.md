---
concept_id: REJ-slop-logline
status: rejected
failure_mode: generic_logline_slop
failing_checks: ["anti_slop_category_1_chosen_one", "novelty_score_lt_15"]
---

# REJ-slop-logline

## Logline

A determined young athlete overcomes adversity to lead their underdog team to
victory and inspire their community.

## Why This Failed

**Failure mode:** Generic logline slop — the logline contains no specific
historical asset, no named location, no named time period, no TRIZ contradiction,
and no irreversible moment. It describes a genre arc (underdog sports triumph)
that has been executed in approximately 200 studio films since 1970.

**Failing checks:**

- `anti_slop_category_1_chosen_one`: The logline centers a "determined young"
  protagonist whose defining trait is determination — a Category 1 anti-slop
  violation. The Anomaly Engine's anti_slop.md registry flags any concept whose
  protagonist is defined primarily by willpower/grit/determination without a
  specific historical or psychological anchor. The "inspires their community"
  closure is a Category 1 Community Uplift ending, doubly blocked.

- `novelty_score_lt_15`: The critic assigned a novelty score of 8/30. No
  untapped historical asset. No cultural specificity. No collision between
  incompatible systems. The logline could describe Hoosiers (1986), Cool Runnings
  (1993), Miracle (2004), or any of their successors. Novelty requires that the
  specific combination be unavailable to prior art; this combination is the
  prior art.

**Why the premise cannot be rescued:** The failure is architectural, not
executional. A more specific setting (name the sport, name the city) would
improve the logline but would not address the structural problem: there is no
TRIZ contradiction, no irreversible moment, and no untapped asset. A determined
young athlete overcoming adversity is a character; it is not a collision. Without
a collision, there is no Anomaly Engine concept — there is a pitch.

**Stabilization lesson:** The logline is the TRIZ contradiction expressed in one
sentence, not the character's emotional arc. If the logline describes the
protagonist's journey, it is a genre film. If it describes the system-level
collision that forces the irreversible choice, it is an Anomaly Engine concept.
Reject any concept whose logline could plausibly have been written without
knowing the specific historical asset.
