# Anomaly Engine — Anti-Slop Registry

> **Role:** This file is injected into Phase 4 (Concept Forger) and Phase 5 (Adversarial Critic)
> system context as a GENERATION CONSTRAINT. It tells the LLM: do not generate concepts using
> these patterns. This is NOT an output scanner. Output scanning is handled by
> `evals/anti_slop.py` (Phase 4, EVAL-04).
>
> **Human-gate:** Future edits to this file require explicit human approval (Auto-Mode is blocked
> by the STAB-02 PreToolUse hook, installed in Phase 5). This initial seed is written by Phase 2
> plan execution — the human-gate protects future modifications.
>
> **Pattern count:** 84 patterns across 7 categories (lint rule PROMPT-07 enforces the >=80 floor).
>
> **Lint reference:** `scripts/lint_prompts.py` rule 7 counts bullet entries in this file.
> Counter: each `- ` bullet line in a category section counts as one pattern.

---

## Category 1: Forbidden Premises

Premises that signal derivative, overused narrative DNA. Any concept relying on these is
statistically likely to face "too similar to X" rejections and low novelty scores.

- Chosen One — a single character prophesied to save/destroy the world
- Genetic Destiny — protagonist discovers their bloodline determines their role in a conflict
- Prophecy Self-Fulfillment — a character causes the very event they tried to prevent by trying to prevent it
- "Last of Their Kind" sole-survivor significance — the protagonist gains importance solely by being the last survivor of a group
- Redemption Through Sacrifice — a morally compromised character redeems themselves only by dying
- Convenient Parenthood — a tough-but-capable adult is suddenly made responsible for a child who unlocks their emotional core
- Occupation = Personality — a character's profession is their entire identity (the cop who only talks about cops, the chef who relates everything to food)
- "Destiny Over Agency" — the plot is driven by fate/prophecy rather than character choices
- Haunted House Fresh Start — a family moves into a new home to escape grief/trauma; the home has its own plans
- Suburban Horror — ordinary neighborhood concealing a supernatural or criminal secret that only the new resident discovers
- Invasion Plot — an outside force (aliens, government, corporation) threatens a small community who must band together
- Mysterious Object — an ordinary person finds an object with extraordinary powers and must protect/destroy it
- Undead Never Stays Dead — a villain, monster, or threat is destroyed but returns without meaningful narrative justification
- Global Conspiracy — a single shadowy organization controls world events and only one outsider can expose them
- "One More Job" — a retired criminal/soldier/spy is pulled back for one final mission

## Category 2: Forbidden Phrasings / Dialogue Patterns

Dialogue constructions that trained reviewers (and audiences) recognize as inauthentic or lazy.
Every instance reduces the concept's novelty score in the Adversarial Critic.

- Exposition Dump — a character explains the world/backstory directly to another character who already knows it
- Villain Monologue — antagonist pauses to explain their entire plan to the protagonist instead of acting
- "A Wise Person Once Told Me" — character cites a dead mentor's advice at a narratively convenient moment
- "Hello?" entry dialog — character enters an unfamiliar space and announces their presence aloud to an empty room
- Techno-Babble — fictional technical jargon used to explain plot-convenient technology without internal consistency
- "As you know, Bob" exposition dialog — one character explains facts to another character who already knows them, purely for the audience's benefit
- Quippy One-Liner after violence — a character delivers a joke immediately after a killing/injury to defuse tension
- Walking Contradiction — a character states a belief and immediately acts against it with no dramatic justification
- Phoned-In Emotion — a character cries or expresses grief in a scene that has not earned the emotional response
- "I'm getting too old for this" — a veteran character announces their imminent retirement/departure to signal jeopardy
- Gimme a Beer — a character orders a drink in a bar scene purely to have something to do with their hands
- Villain's Throne Dialog — the villain receives a subordinate in a deliberately intimidating setting for exposition delivery
- Reluctant Refusal Followed by Immediate Agreement — a character says no to a mission and then agrees within the same scene with no new information

## Category 3: Forbidden Character Types

Stock character archetypes that reduce the audience's sense of discovery. These are "casting by
template" failures that trained investors and critics immediately flag.

- Trophy Wife — a beautiful but functionally inert partner whose role is to be endangered or mourned
- Psycho Ex-Girlfriend — a previous romantic partner portrayed as dangerous, obsessive, and lacking her own coherent motivation
- Fat Comic Relief — a character whose primary function is humor derived from their body type
- Wise Old Bearded Sage — an elderly male mentor with no flaws who exists to give the protagonist information
- Geek Transformation — a nerdy/unattractive character undergoes a superficial makeover to achieve social acceptance
- Misguided Dad — a father so focused on work/status that he fails his family until a crisis teaches him what matters
- Youthful Wisdom — a child or teenager delivers the moral of the story directly to an adult who should know better
- Terrible Henchman — a villain's lieutenant who is conspicuously, comedically incompetent
- Bad Seed Child — a child character who is inexplicably evil with no psychological grounding
- Generic Love Interest — a romantic partner who exists only to be won and has no story of their own
- Reluctant Mentor — an expert who refuses to help until the protagonist's persistence breaks them down
- Stock Villain — an antagonist whose only motivation is greed, power, or sadism with no contradictory human traits
- Token Diversity Character — a character whose primary function is to represent their demographic group rather than pursue their own story goal
- The Magical Minority — a character from a marginalized group whose role is to use cultural/spiritual knowledge to help the white protagonist

## Category 4: Forbidden Settings

Locations that carry such heavy cultural baggage they trigger "seen this before" responses in
pitches, regardless of story quality.

- Dark Villain Lair — underground or isolated base decorated for intimidation, lacking functional logic
- Seedy Bar — a dive bar where characters exchange information or form alliances, populated by colorful ne'er-do-wells
- Quaint Small Town hiding secrets — an idyllic small community with a shocking secret that an outsider uncovers
- Corporate Sterile Office — a gleaming, personality-free corporate environment used to signify evil or moral emptiness
- Abandoned Building — a derelict structure serving as a final confrontation site or horror location
- Grocery Store Baguettes — a bag of groceries containing a prominent baguette, used as shorthand for "ordinary life" before disruption
- Convenient Safe House — an off-grid location with all necessary supplies that exists purely to give characters a respite scene
- Generic Nightclub — a loud, strobe-lit venue used as a backdrop for a meeting or chase, undifferentiated from any other nightclub in film
- Mansion of Vague Wealth — an ostentatiously large home whose occupants' source of income is never explained
- Mirror Jump Scare — a character opens a medicine cabinet or moves away from a mirror and a threat appears in the reflection

## Category 5: Forbidden Moral Arguments

Thematic positions that collapse the complexity of human behavior into falsifiable axioms. These
produce protagonists who are morally correct from scene one and antagonists who are one-dimensional.

- Love Conquers All — romantic love resolves conflicts that have no realistic romantic dimension
- Evil Requires Incompetence — antagonists can only be defeated because they make inexplicable mistakes at critical moments
- Betrayal Twist — a character who appeared loyal is revealed to be the villain, with the revelation serving the plot rather than the character's arc
- Love Redeems Villain — an antagonist with genuinely harmful convictions abandons them because of romantic or familial love, with no ideological development
- Ends Justify the Means — a protagonist commits atrocities that the narrative frames as justified because they achieved a good outcome
- Magical Minority as Moral Compass — a character from a marginalized group exists to teach moral lessons to the protagonist without having agency of their own
- Bury Your Gays — an LGBTQ+ character is killed or meets a tragic ending as a narrative device
- Inspiration Porn — a disabled or marginalized character exists to inspire non-disabled/majority characters rather than to pursue their own story

## Category 6: Forbidden Visual Hooks

Visual shorthand that has been replicated so many times it now reads as parody rather than
dramatic communication.

- Walking From Explosion — a protagonist walks away from an explosion in slow motion without looking back
- High Heels Horror Chase — a character in impractical footwear runs from a threat, stumbling repeatedly
- Training Montage — a protagonist improves from incompetent to competent through a sequence of time-compressed practice scenes set to inspirational music
- Slow-Motion Artificial Drama — an ordinary action (catching a falling glass, a handshake, walking into a room) is rendered in slow motion for unearned dramatic weight
- Zoom Photo Enhancement — a blurry image is enhanced by typing at a keyboard until a hidden detail becomes implausibly clear
- Zoom/Dolly Shock — a camera technique (Vertigo effect) used to signal a revelation with no narrative justification
- Cliffhanger Rescue — a character in mortal danger is saved in the final seconds by an ally who had no plausible way to arrive in time
- "X Hours Earlier" Opening — the film opens with a dramatic scene and then cuts to "36 hours earlier," using structural novelty as a substitute for narrative structure
- Hero Slow-Walk Toward Camera — a group of protagonists walk toward the camera in a wide shot, establishing their team without context

## Category 7: Audience-Claim Red Flags (Engine-Specific)

Claims about audience size or market opportunity that cannot be mechanically verified against
sourced data. These trigger automatic FAIL in Phase 3 (Audience Validator) and reduce the
Novelty score in Phase 5 (Adversarial Critic).

- Unqualified "global audience" claim without geographic breakdown by country ISO code and sourced population size
- "Billion+ Muslim audience" claim without a cited Pew Research URL and year-of-estimate
- "Diaspora market" claim without a census reference (US Census ACS or Statistics Canada or UK ONS)
- "Universal themes" claim — no theme is universal; every claim requires a specific cultural segment
- "Rising trend" assertion without a cited Google Trends permalink or Statista time-series URL and date
- "No competition" claim — every concept has competition; the claim means the researcher did not look
- "Family-friendly" as audience specification — not a demographic; requires age breakdown and sourced data
- "Fans of [franchise]" as primary audience — derivative positioning that signals lack of original audience analysis
- Unverified box-office reference — citing a box-office figure without a Box Office Mojo or The Numbers deep-path URL
- "Cult following" without a quantified community metric (subreddit subscribers, Letterboxd list count, active fan wikis)
- Vague age-range claim (e.g., "18-49 adults") without a sourced size estimate
- "Underrepresented market" without naming the market and citing a deprivation study
- "Strong social media interest" without a cited platform metric (hashtag volume, engagement rate, date)
- "International co-production appeal" without naming the partner territories and their regulatory co-production criteria
- Audience size estimate below 50,000,000 presented as commercially viable for a studio release without a documented niche-distribution strategy

---

## Stabilization Log

Entries added via the stabilization cycle (docs/stabilization-cycle.md).
New entries MUST go through the STAB-02 human-gate (Phase 5).

| Date | Concept ID | Pattern Added | Category |
|------|-----------|---------------|----------|
| 2026-05-07 | SEED-001 | "Last of Their Kind" sole-survivor significance | Premises |
| 2026-05-07 | SEED-002 | Unqualified "global audience" without geographic breakdown | Audience-Claim Red Flags |
| 2026-05-07 | SEED-003 | "As you know, Bob" exposition dialog | Phrasings |


## Queued Stabilization Patterns

- Self‑sabotaging protagonist undermines the very evidence they are trying to expose without clear motive.  # added 2026-05-08, triggered by a1f9c3e8b7d2
- Cold War relic AI antagonist guarding a secret data vault  # added 2026-05-08, triggered by a1f9c3e4b27d4e5f8a6d9c2b1e7f0a3c
- Hidden archive as a MacGuffin that merely drives exposition.  # added 2026-05-08, triggered by a1f3c9e2b7d44e8fa9d6c3b5e1f2a7c4
- Archivist protagonist leaking classified data from a shadowy intelligence agency  # added 2026-05-08, triggered by c9f2e1
- Self‑destructing artifact used as an irreversible countdown device  # added 2026-05-08, triggered by c13dbe61-9f69-4484-a809-52ead6056bf3-001
- Cold‑war secret data retrieval race  # added 2026-05-08, triggered by d9f1c2a7e5b34c9fa8d6b1e4c7a2f5b3
- Dual‑lead polarity split: concept assigns TRIZ poles to separate characters rather than one protagonist.  # added 2026-05-08, triggered by a1f5c9e2d4b8
- Logline cites a TRIZ contradiction without forcing the hero to embody both poles simultaneously.  # added 2026-05-08, triggered by a1b2c3d4e5f6g7h8i9j0
- Cold‑War artifact retrieval quest as central plot driver  # added 2026-05-08, triggered by a1f3c9e2b7d4
- Unnamed-Collective Antagonist — threat attributed to a nation or organization with no named individual and no concrete goal.  # added 2026-05-08, triggered by ae4-c-coldwar-001-8-f0152a6c
- Antagonist-free dilemma concept — existential stakes framed as solo moral paralysis with no opposing human agent.  # added 2026-05-08, triggered by ae4-c0ldwar002-7f3a9b1c
- Dying Witness Clock — a nameless final witness whose imminent death is the sole irreversibility mechanism, substituting urgency for antagonist specificity.  # added 2026-05-08, triggered by ae4-c-coldwar-003-7f3a9b2e
- Institutional antagonist named without a human agent, personal motive, or named counter-goal.  # added 2026-05-08, triggered by ae3f7c2b1d9e4a5f8b0c6d2e1a7f3b9c
