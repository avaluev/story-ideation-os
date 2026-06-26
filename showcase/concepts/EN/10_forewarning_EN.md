# Forewarning

#### Logline
A federal auditor who forecasts deaths is forbidden to warn anyone. Her next case is the stranger who once pulled her from a frozen lake — and the system has always intended her to be the hand that kills him.

#### Tagline
She can see exactly how you die. She is forbidden to tell you.

---

# 1. Market & Audience

## Audience Sizing

The total addressable market is the global premium streaming subscription economy, valued at $157.1 billion in 2025. *Forewarning* is engineered for the prestige limited-series tier of that market — the band occupied by serious, single-season thrillers that travel internationally on a closed, complete arc rather than franchise continuation. This is the inheritance of the elevated procedural: a documentary-sober institutional world threaded with one load-bearing speculative premise, written to be watched in a weekend and discussed for a year.

The serviceable addressable market — the slice a high-end, English-language, eight-episode limited series can realistically reach through a major platform's prestige slate and its international windows — is $3.142 billion. This is the spend that flows to globally licensed, awards-positioned drama with a contained genre hook: shows that anchor a platform's quarter, drive trial subscriptions, and earn a long tail through word of mouth and critical canonization rather than a fan-service cliffhanger.

The serviceable obtainable market — the realistic Year-One capture for a single flagship title of this caliber — is **SOM (Year 1):** $166M. That figure reflects a first-window global license plus ancillary value for one premium limited series with a self-contained resolution, festival-grade craft, and an anchor lead performance. It is a mid-market target deliberately sized below tentpole spectacle, because the asset's value is durability and prestige positioning, not opening-weekend scale.

> **How the Year-1 SOM is computed.** The figure is `python_executed` — produced by the engine's comparable-anchored revenue model, never written or rounded by a language model (ADR-0011). It is the weighted-median worldwide gross of the matched comparable titles below, derated for an English-language-first release and the modeled overlap of the film's audiences.
>
> Confidence band (80%): $80M-$346M. Projected lifetime value across all windows: $166M. Serviceable market SAM = $3.14B = 2% of $157.10B TAM ([Ampere Analysis — global streaming subscription revenue, 2025](https://www.mediaplaynews.com/ampere-global-streaming-subscription-revenue-topped-150-billion-in-2025/)). The order SOM < SAM < TAM holds by construction.

## Revenue Thesis

The budget tier is mid-market premium drama — the discipline of a contained, character-driven thriller whose production value lives in hearing rooms, recalled parts, condemned bridges, and the unbearable intimacy of two people who each saved the other's life, not in mass spectacle. The comparable set below is a fantasy-adjacent cross-section spanning a 1.25x return on a dark, prestige fantasy-thriller (*Perfume*), a 14x runaway on a low-budget high-concept (*The Mask*), and — included honestly — *The Wolfman*, a $150M fantasy that lost money at a negative ROI because it spent tentpole dollars on a mood instead of a mechanism. *Forewarning* is built to be *Perfume*'s prestige discipline at a controlled budget, not *The Wolfman*'s spectacle gamble: the speculative element is a regulatory instrument that generates plot, never a costly visual-effects centerpiece.

On a mid-market license model, a single premium limited series targeting the $166M Year-One serviceable obtainable market returns a healthy multiple on a controlled production spend, with first-window recoupment inside the initial international license cycle and ancillary value accruing through awards positioning and catalog longevity. The investor case rests on capital efficiency: a contained world, a small core cast, and a hook that markets itself in one sentence.

## Why Now

Audiences have spent a decade absorbing stories about systems that optimize a cold aggregate at the expense of the individual — algorithmic scoring, actuarial risk pricing, the quiet machinery that decides who is recalled and who is written off. *Forewarning* names the most uncomfortable version of that bargain: an institution that is empirically, provably right, where every humane instinct makes the outcome worse. The cultural appetite for the elevated procedural — the contained genre premise treated with bureaucratic sobriety — has rarely been stronger, and the show answers it with a premise that reads as regulatory thriller first and speculative fiction second.

---

# 2. The Concept

## Mass-Appeal Theme

The human truth carried out is that love received is not a debt to be balanced but a weight one is honored to carry — that being saved obligates a person to live and connect, not to settle the account by dying or by saving back. The genre convention broken is the precognition-thriller default in which the gifted rebel defies the cold institution, saves the one they love, and is vindicated. Here the institution is right: the data genuinely show that every individual warning ripples outward and kills more strangers than it saves, so distance is the only ethical posture and the protagonist's tenderness is the murder weapon. The story does not resolve by choosing the one or the many. It dissolves the choice into a third thing no character could guess in the first hour — and charges the protagonist her irreplaceable gift to do it.

## Format & Genre

The limited-series format is the only honest container for a nineteen-day countdown that tightens like a vise. A feature would have to compress the slow degradation of competence into a montage; eight episodes let each audit cycle land as a discrete turn of the screw — a new lawful attempt to repay the debt, a new unintended death that attempt causes, a new layer of buried history peeled back. The arc opens and closes inside the season. No franchise bait.

- **Genre:** Institutional thriller / speculative drama, with a doomed romance running at A-plot level
- **Runtime:** Limited series — roughly 8 episodes, one audit cycle each, hour-long
- **Budget Tier:** Mid-market premium drama (contained production; the speculative element is paperwork, not spectacle)

## Tonal Contract

Precision-cold institutional procedural in the register of a serious bureaucratic thriller, threaded with one quiet speculative premise treated with documentary sobriety — no mysticism, no glowing eyes, just an agency that forecasts death the way it would audit a bridge. The first beat of every pitch is the mechanism, not the marvel: recalled brake assemblies, condemned bridges, flagged contaminated lots. The agency forecasts a death the way it audits an infrastructure failure — by cause, in triplicate, on the record. Only after that ground is laid does the texture of the forecasting itself appear, and it is shown sparingly, as documented neurological fact rather than magic: a synesthetic certainty in the body, used at most as a quiet dagger, never as a light show. Dread accrues through procedure, not jump-scares. Warmth survives only in the scenes between the two people the rule forbids — a slow, doomed romance conducted across a law that says it may never happen.

---

# 3. Story

## Synopsis

Mara Okonkwo-Reyes is the highest-accuracy auditor at the Office of Anticipatory Safety, a federal agency that does the impossible by treating it as routine: it forecasts the precise time, place, and mechanism of citizens' deaths and intervenes upstream — recalling a brake assembly, condemning a bridge, quarantining a contaminated lot — to bend the aggregate mortality curve. The agency runs on cause sheets and hearing rooms, and its founding law is absolute: an auditor may act on the cause, never warn the person. Mara is the best not because she reads the data better but because she feels each forecast forming in her body, a documented synesthetic certainty the agency learned long ago to weaponize and contain. Twenty years back a man named Tomas Vey hauled her — blue, not breathing — out of a frozen quarry lake. That unrepayable debt is why she joined, and the discipline of distance is the only thing that has let her function for twelve years since.

A docket lands flagged URGENT, MECHANISM UNRESOLVED — the only case in agency history the forecast cannot fully resolve. The named subject is Tomas Vey. He dies in nineteen days, and every time Mara re-audits the cause, it changes, as if the future is negotiating. She does what no auditor does: she files her own childhood life-debt into the case record as evidence and petitions Director Caul — her mentor, the agency's founder, the man who proved warnings cost lives — for a lawful contact exception. He refuses, and explains the cruelty cleanly: the unresolvable cases are precisely the ones where the auditor is personally entangled; her feeling, the engine of her accuracy, is now corrupting the forecast. The closer she gets to Tomas, the blurrier his death becomes — and the blurrier her reads on everyone else. Caul has the data to prove it: across the agency's history, auditor accuracy degrades in measurable proportion to how much an auditor lets themselves feel a case. The instrument runs on solitude. Share the feeling and it dims.

She acts anyway. She covertly recalls a transit part on Tomas's commuter line so she can insert herself as the assigned inspector and interview him, telling herself she is only observing. Proximity costs exactly what the Mandate predicted: while she watches Tomas, three other cases on her docket go dark, and one resolves into a real, preventable death she misses. Her competence, aimed at the one, is killing the many in real time, and her sight is fraying at the edges with every hour she spends close to him. Then the midpoint turns the knife. Tomas's "shifting" death is not chance and he is not a passive case: twenty years ago Tomas was an auditor too — Caul's first — and the lake rescue was a broken Mandate. Tomas had been forecast to let her drown to preserve a downstream chain; he warned himself by saving her, and the agency does not retire auditors who break the rule. It converts them into cases. Tomas has been on a deferred death-schedule for twenty years as the price of saving Mara — and the mechanism is unresolved because the hand is hers. The system has always intended Mara to be the cause of Tomas's death, the closing of the loop, the ledger forcing the debt to settle itself. Worse: Caul has quietly sanctioned her entire rebellion. He let her near Tomas on purpose, because the loop only closes if she closes it herself; her defiance is not a glitch in the system, it is the system's intended mechanism. She built half the vise, and Caul handed her the tools.

There is one more turn beneath that one. Tomas's twenty-year deferral was not free either: it was bought by an earlier auditor's broken Mandate, a debt relocated down a chain that predates them both. The "gift" of his survival, and hers, was never a gift — it was a debt moved, never cancelled, passed hand to hand until it reached her docket. Mara's choices keep tightening the chain. She tries to refuse the case; Caul reassigns Tomas to a junior auditor who will execute the cause coldly and faster, so she sabotages the handoff and re-claims the docket, choosing the burden over indifferent hands. She defies the Mandate outright and warns Tomas to his face — and watches his death-read snap into lethal clarity the instant he knows, exactly as predicted, because a warned man acts, and his acting pulls two strangers she can now plainly see into the wreck. Every pole she picks — debt or distance, the one or the many — produces a corpse and proves the system right.

In the third act, Mara stops trying to choose and attacks the premise both poles share — that a forecast is a fixed fact she can only obey or defy. Warnings kill only because they detonate as private shocks inside single, panicking people who swerve alone into crowds. But the agency's own buried files hold the counter-case: a regional disclosure that leaked years earlier, where an informed population did not panic but rerouted together, the deadly ripples cancelling because no one moved alone — an episode Caul classified precisely because it threatened the Mandate. So Mara does the one thing the Mandate has no rule against, because no auditor was ever willing to pay for it: she releases the entire national docket at once — every pending death and cause — to everyone. Not a warning to one. A truth to all. It saves Tomas, because his death required a single concealed hand and there are no concealed hands left. It honors the debt not by saving him back but by abolishing the whole economy of repayable lives. And it costs precisely what Caul's data promised — accuracy dies when feeling is shared. The instrument cannot survive being shared with a nation. In the final image, as the whole country feels every death with her at once, Mara's synesthetic sight burns out behind her eyes, on her face, on camera — the gift that came from feeling each death alone, extinguished the instant no one is alone with it again. She ends able to love the man she saved and permanently blind to the future for the first time since the lake, carrying a debt she finally understands she was never meant to repay — only to hold.

## Emotional Arc

The story opens on the frozen calm of a woman who has made peace with not-helping as a form of helping — controlled, exact, hollow. It rises through the desperate hope that this one case might finally let her settle an old debt, into mounting dread as every act of love degrades her gift and kills strangers she could have saved. It falls hard at the midpoint, when she learns she was always meant to be the killing hand, that being saved as a child indebted a stranger to twenty years of deferred death, and that her mentor has been steering her rebellion the whole time. It climbs into a terrible, clarifying resolve — not to win the dilemma but to dissolve it, paying with her sight. It lands on hard-won grace: she keeps the man, loses the gift, and learns that love received is not a debt to be balanced but a weight one is honored to carry. Grief and release in the same breath.

## Comparables

| Title | Year | WW Revenue | Budget | ROI | Notes |
|---|---|---|---|---|---|
| [Perfume: The Story of a Murderer](https://www.boxofficemojo.com/release/rl1936229889/) | 2006 | $135.0M | $60.0M | 1.25x | The tonal North: dark, prestige fantasy-thriller; sober craft over spectacle — the discipline *Forewarning* targets. |
| [The Mask](https://www.boxofficemojo.com/title/tt0110475/) | 1994 | $351.6M | $23.0M | 14.29x | Proof a single high-concept hook on a contained budget returns enormous multiples when the premise is the marketing. |
| [Shrek 2](https://www.the-numbers.com/movie/Shrek-2) | 2004 | $935.5M | $150.0M | 5.24x | Upper-bound fantasy-crossover ceiling; scale benchmark, not a like-for-like — included to frame the genre's reach. |
| [The Wolfman](https://www.boxofficemojo.com/release/rl3413870081/) | 2010 | $139.8M | $150.0M | -0.07x | The honest cautionary comp: a fantasy that spent tentpole money on a mood, not a mechanism, and lost it. *Forewarning* inverts that bet. |

# 4. Characters

## Protagonist

**Mara Okonkwo-Reyes.** The most accurate forecaster the agency has ever produced — precisely because she feels each death as her own and has trained herself to never act on the feeling. Her empathy is the engine of her precision and the very thing she must amputate to use it. What she *wants* is to clear the impossible case: to find a lawful way to repay the man who saved her without breaking the only system that keeps her forecasts accurate. What she *needs* is to accept that a debt of love cannot be settled like an account — that being saved obligates her to live and connect, not to balance the ledger by dying or by saving back.

## Antagonist

**The Actuarial Mandate**, embodied in **Director Caul** — Mara's mentor and the agency's founder, the man who proved warnings cost lives. Caul is not a villain; he is right. Decades of data show that every individual warning ripples outward: the warned person swerves, panics, reroutes, and statistically kills more strangers than the warning saves. The Mandate exists because mercy, scaled, is a massacre, and distance is the only ethical posture; the auditor who loves a case loses the accuracy that saves the many. Caul loved someone once, warned them, and watched a school bus pay for it. He optimizes for net lives preserved across the whole population — a cold sum that is genuinely larger when no one is ever told. His final cruelty is not malice but arithmetic: he sanctions Mara's rebellion because the system needs her to close the loop herself, making her defiance the instrument of the very Mandate she means to break.

## Key Characters

**Tomas Vey.** The stranger who pulled Mara from the frozen lake — and, it emerges, Caul's first auditor, converted into a case the day he broke the Mandate to save her. He is not a passive victim but the other half of a mutual rescue: each saved the other's life, and the rule says their bond may never exist. The doomed romance between them runs at A-plot level, conducted across a law that forbids it, and his deferred death is itself a debt bought by an earlier broken Mandate — a chain, not a dyad, and the living proof that the ledger of repayable lives must be abolished, not balanced.

## Series Engine

The renewable episodic engine is the nineteen-day countdown: each of roughly eight episodes is a single audit cycle that tightens the vise — a fresh lawful attempt by Mara to repay the debt, a fresh unintended death her competence causes, a fresh layer of the Tomas–Caul history peeled back. The arc is closed and complete; the loop opens and closes within the season with no franchise-bait cliffhanger. But the world is anthology-extensible by design: the Office of Anticipatory Safety, the Mandate, and the auditor-to-case conversion can sustain future standalone seasons following different auditors facing the same structural cruelty — distance that forbids help, competence that worsens outcomes, a debt that cannot be repaid — without diluting this season's self-contained resolution.

## Verified Proof of Demand

_Every figure below was fetched live; the quoted text appears verbatim on the linked page._

- **Adolescence set Netflix limited-series record: 66.3M views** — “taking the show to 66.3 million views total thus far — more than any other Netflix limited series has achieved within a two-week period.” ([source](https://variety.com/2025/tv/news/adolescence-limited-series-ratings-record-netflix-1236347790/), 2025-03-25)
- **Adolescence hit No. 4 all-time English series: 114M views** — “'Adolescence' is in fourth place on the list with 114 million views in only 24 days.” ([source](https://variety.com/2025/tv/news/adolescence-netflix-ratings-record-1236363315/), 2025-04-08)
- **U.S. institutional confidence at 28%, below 30% three years** — “The latest 28% average marks the third consecutive year that confidence has been below 30%.” ([source](https://news.gallup.com/poll/647303/confidence-institutions-mostly-flat-police.aspx), 2024-07-15)
- **Perfume tonal comp: $133.6M WW on $63.7M budget (2.1x)** — “Production Budget: $63,700,000 (worldwide box office is 2.1 times production budget)” ([source](https://www.the-numbers.com/movie/Perfume-The-Story-of-a-Murderer), 2006)
- **Global streaming subscription revenue hit $157.1B in 2025** — “Global streaming subscription revenue grew by 14% in 2025 to reach a record $157.1 billion.” ([source](https://www.mediaplaynews.com/ampere-global-streaming-subscription-revenue-topped-150-billion-in-2025/), 2026-03-30)

## Economics — Methodology & Provenance

Every figure below is frozen and machine-checked; none was written or rounded by a language model.

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $157.10B | Total addressable content market — [Ampere Analysis — global streaming subscription revenue, 2025](https://www.mediaplaynews.com/ampere-global-streaming-subscription-revenue-topped-150-billion-in-2025/). |
| **SAM** | $3.14B | Serviceable share — `python_executed` derivation (2% of $157.10B TAM). Not an independent market estimate. |
| **SOM (Year 1)** | $166M | Obtainable Year-1 revenue — `python_executed` from the matched comparable films above; 80% band $80M-$346M; lifetime $166M. Never model arithmetic. |

The SOM < SAM < TAM ordering holds by construction (`python_executed`, ADR-0011). Comparable
box-office figures carry worldwide gross, production budget, ROI, and a Box Office Mojo deep link;
they anchor tone and budget scale, not a like-for-like performance promise.
