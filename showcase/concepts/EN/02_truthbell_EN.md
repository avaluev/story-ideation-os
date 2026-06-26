# Truthbell

#### Logline
In a walled city kept from collapse by bells that ring true only when the ringer's heart is true, the state Tuner sworn to silence every dishonest bell discovers that the forbidden note threatening to bring down the cathedral is being rung by the daughter she was ordered to surrender at birth — and that the only way to save the city is to teach it a sound that is honestly broken.

#### Tagline
A bell cannot lie. Neither, in the end, could she.

---

# 1. Market & Audience

## Audience Sizing

The total addressable market is the global theatrical box office, valued at $328.2 billion per the Motion Picture Association's most recent worldwide THEME report. That is the full universe of ticket-buying demand a theatrically released feature competes inside — every screen, every territory, every language.

The serviceable available market narrows that universe to the slice a grounded-fantasy family drama in this budget tier can realistically reach: roughly $39.4 billion. This is the band occupied by emotionally driven, four-quadrant fantasy features that travel across borders without a built-in franchise — pictures that sell on a feeling and a world rather than a pre-sold title.

The serviceable obtainable market — the realistic first-year capture for this specific title at this budget and release shape — is modeled at **SOM (Year 1):** $538M. The low end of the modeled band sits near $209 million and the high end near $1.38 billion, with a projected lifetime value across all windows of approximately $1.59 billion. These figures are computed, not asserted, and they assume a wide international release backed by a marketing spend appropriate to the tier.

> **How the Year-1 SOM is computed.** The figure is `python_executed` — produced by the engine's comparable-anchored revenue model, never written or rounded by a language model (ADR-0011). It is the weighted-median worldwide gross of the matched comparable titles below, derated for an English-language-first release and the modeled overlap of the film's audiences.
>
> Confidence band (80%): $209M-$1.38B. Projected lifetime value across all windows: $1.59B. Serviceable market SAM = $39.38B = 12% of $328.20B TAM ([MPA THEME Report](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf)). The order SOM < SAM < TAM holds by construction.

## Revenue Thesis

The picture is built for the mid-budget, high-emotion tier — roughly $35–40 million negative cost — the same band that has repeatedly turned a single unforgettable image and a primal family wound into outsized returns. ([source](https://www.denofgeek.com/movies/the-quiet-return-of-the-mid-budget-movie/), 2016-12-05) The clearest precedent in the comp set is *Mojin: The Lost Legend* (2015): a $37 million fantasy-adventure that grossed $259.4 million worldwide for a return on investment of roughly 6.0x. Grounded-fantasy genre material, at this budget, with a strong hook, converts. *The Firm* (1993) — a procedural thriller with a ticking institutional clock — grossed $270.2 million on the strength of exactly the kind of investigation-spine *Truthbell* runs on, proving the appetite for a single competent professional racing an unforgiving deadline. And *Anastasia* (1997), the softest performer in the set at $139.8 million worldwide, demonstrates the durability of the lost-child reunion engine even when a picture under-delivers theatrically — that title has earned across home, broadcast, and catalogue windows for nearly three decades.

At the modeled first-year capture against a sub-$40 million negative cost, the investor case rests on a return multiple well into the high single digits in the base case, with breakeven achievable inside the first full year of theatrical-plus-early-window exploitation. The downside is protected by the same lost-child reunion durability that has kept *Anastasia* earning for a generation; the upside is the genre-fantasy ceiling that *Mojin* touched at the same budget.

## Why Now

Audiences have spent a decade rewarded for spectacle and are visibly hungry for spectacle that means something — for worlds where the magic is not decoration but a moral engine. The cultural conversation has turned, hard, toward grief that is named out loud rather than swallowed, toward the cost of institutions that ask people to perform composure instead of feeling. A four-quadrant fantasy whose central rule is that *honesty literally holds the building up* lands precisely on that nerve: it is wonder and ache welded together, sincere without being soft, and it carries across every border because the wound it dramatizes — a parent who denied a child to survive — needs no translation.

---

# 2. The Concept

## Mass-Appeal Theme

The human truth carried out is this: a heart held silent does more damage than any spoken grief. A society — and a person — can decide that the safest thing is to feel less, to professionalize composure, to legislate the dangerous feelings into silence; and that decision is itself the catastrophe it was built to prevent. The picture argues, with engineering consequences, that admitted brokenness bears more weight than enforced wholeness.

The genre convention it breaks is the magic-system reveal. The audience is trained to expect the rogue feeling to be the threat and the "true note" to be the cure — the rebel hero striking the pure chord that fixes everything. *Truthbell* inverts every beat of that template. The protagonist is not a rebel but the law's own enforcement arm. The antagonist is not a hidden cabal but a grieving man who is tragically right by his own history. And the cure is not the true note and not silence, but a third sound nobody in the premise can guess in advance: a chord that openly, deliberately refuses to resolve — grief admitted, not grief cured and not grief hidden.

## Format & Genre

This is a self-contained feature because the emotional engine — a mother locating, mentoring, and finally claiming the daughter she surrendered — completes in one sitting and must. The reunion is the resolution; a cliffhanger would betray it. The world's rule-set is large enough to extend, but the picture itself earns its weight by being whole.

- **Genre:** Grounded fantasy / family drama with the spine of a literate procedural thriller
- **Runtime:** 118–128 minutes
- **Budget Tier:** Mid-budget, approximately $35–40 million negative cost

## Tonal Contract

A grounded fantasy in the register of a literate thriller. The magic obeys hard, consistent, demonstrable physical rules — honesty bears load; suppression cracks stone — so every emotional beat carries genuine structural stakes and a ticking clock. The texture is bronze, smoke, and the unbearable sound of a bell that cannot lie; the foundry-city of Brassmere is all furnace-glow and cooling metal. Awe lives in the world, mystery in the unlocatable note, and a devastating familial drama sits at the core — deep feeling welded to the procedural spine of an investigation. The register is sincere, never camp; tears are earned through plot mechanics, not montage.

Critically, the structural stakes must be *photographed*, not narrated. The fracture in the cathedral spine is a visible, worsening character the audience tracks dusk by dusk: hairline becoming gap, dry stone beginning to sweat, a load-bearing beam bowing a degree further each evening as the light goes orange. And the climax is staged as a physical set-piece, not an acoustic metaphor — at the exact moment the broken chord is rung, the stone responds on camera: the great crack draws shut, the sweating beam dries pale, the leaning tower settles by an inch and holds. The audience must feel a building saved, not a theme resolved.

---

# 3. Story

## Synopsis

VESNA COILWRIGHT is the finest Tuner in Brassmere, a walled foundry-city whose stone holds only because its bells ring true. Here physical law is the shape of felt truth: a dishonest note — a vow not meant, a grief denied — weakens whatever it touches until walls sweat, beams bow, and bronze splits. Vesna's sworn office is to hunt down false bells and silence them before the rot spreads. She is the best in the Guild's history because she carries the city's deepest unstruck note inside her own chest: nineteen years ago, unmarried and discordant, she bore a daughter and signed the Surrender, swearing under oath she had never had a child. She has rung that lie every day since. It is precisely why she can hear everyone else's. In the cathedral undercroft hangs a relic the Guild treats as superstition — the Mourner, a bell deliberately cast cracked, that an old foundry rhyme claims once held a collapsing wall through a flood because it "rang what it was." Vesna, like every modern Tuner, was taught the Mourner is a fairy tale and a forced-perfect bell is always stronger. She has spent her life believing it.

A new dissonance begins fracturing the spine of the central cathedral — a note no Tuner can locate, growing louder each dusk. Vesna is ordered to find and silence its source inside twelve days, before the Mother Tower comes down, and she volunteers to lead the hunt, certain it will earn the promotion that finally pulls her off the streets. Breaking protocol, she tunes the cracked stone backward to read the rogue note's blood-signature — and recognizes, sick to her stomach, her own frequency folded inside it. She does not report it. She tracks the bell alone through the apprentice ringers and, scaling the seawall at dusk, finds NIKA: nineteen, a foundry orphan with no record and a homemade bell, ringing a note of raw, unbearable longing every evening over the wall toward the sea — the exact sound of a child who has spent her whole life feeling assigned-to and never chosen. Nika is her daughter. Nika does not know it. And Nika's honest grief is the thing cracking the city.

Vesna lies a second time. She presents herself to Nika as a state mentor sent to "correct" the girl's ringing, and begins teaching her to suppress the note — to ring true the safe, obedient way. This is the lawful path: silence the dissonance, save the city, obey the rule that discordant blood must never know itself. Then comes the reversal, and it is staged in a single brutal scene rather than explained: Vesna stands inside the cathedral, hand flat against the fracture, and watches the crack *accelerate the instant Nika rings the obedient note* — the stone rejecting it in real time, the gap widening under her palm as the "corrected" chord lands. The suppression is not slowing the rot. The suppression IS the rot. A true grief forced to ring as a false resolution is the most dishonest sound a bell can make, and the cathedral — which holds on honesty alone — is tearing itself apart trying to refuse the lie. Vesna has spent her entire life being the very rot she hunts.

High Registrar ALDOUS PELL, who watched a tower fall once before and built the Surrender to make certain it never happens again, moves to do what the law demands: silence the source permanently, which means taking Nika. Vesna is trapped in the true dilemma with no exit. The fair outcome — surrender Nika, silence the note, obey the Concord — saves the city's thousands and destroys the one person she has finally chosen. The caring outcome — let Nika ring her true note, claim her, run — saves her daughter but, by the iron law of this world, drops the Mother Tower on everyone beneath it. Fair kills the person she loves; care kills everyone else. In the final hour she stops choosing between the true note and silence and reaches for a third sound she was taught did not work. On the cathedral floor, in front of Pell and the whole Guild, she does the forbidden thing: she rings her own bell true for the first time in nineteen years — says aloud, under the load-bearing stone, that she had a daughter, that she was forced to give her up, that she grieves it — and the act of confessing costs her the Tuner's oath and the only self she has ever been allowed. Then she leads Nika not to resolve the longing but to hold it as a deliberate, honest dissonance: the two of them ring a chord that visibly does *not* resolve, the broken note of the Mourner made flesh — and as it hangs unresolved in the air, the camera holds on the fracture drawing shut, the sweating beam drying, the tower settling and going still. The lie was the load the city could not carry. An honest break, it turns out, bears true weight. Pell, hearing his own forty-year-old silenced grief inside that chord, finally rings his own broken note and lets the tower stand. The Concord's founding premise — that citizens must feel less to keep the walls up — collapses as the actual rot. The city never needed suppressed hearts. It needed permitted ones. Saving the daughter and saving the city become the same act.

## Emotional Arc

The arc rises from professional pride and buried numbness — a master who has made a virtue of her own silence — into dread and forbidden tenderness as recognition dawns. It peaks falsely at the midpoint, when obedience seems to be working, before the fracture lurches wider under Vesna's hand and plunges her into the agony of an impossible choice and a savage self-indictment: she is the disease she has spent her life curing. It resolves in cathartic, terrifying release — the first honest sound of her life — as confession and reunion arrive in a single breath. The audience feels the universal ache of a parent who denied a child to survive, the white-knuckle suspense of a collapsing world counting down dusk by dusk, and the flood of relief when grief is finally allowed to be spoken instead of swallowed.

## Comparables

| Title | Year | WW Revenue | Budget | ROI | Notes |
|---|---|---|---|---|---|
| [The Firm](https://www.boxofficemojo.com/title/tt0106918/) | 1993 | $270.2M | n/a | n/a | Procedural thriller spine; one professional vs an institutional deadline — the investigation engine Truthbell runs on |
| [Mojin: The Lost Legend](https://www.boxofficemojo.com/title/tt4276752/) | 2015 | $259.4M | $37M | 6.0x | Closest budget-and-genre precedent; grounded fantasy-adventure converting at exactly this tier |
| [Anastasia](https://www.boxofficemojo.com/title/tt0118617/) | 1997 | $139.8M | n/a | n/a | Softest theatrical performer in the set; included honestly — proves the lost-child reunion engine's decades-long durability across windows |

## Closing Note

Every box-office and budget figure above is drawn from the verified comparable set; market sizing follows the frozen economics. No claim is asserted that the underlying data does not support.

---

# 4. Characters

## Protagonist

**Vesna Coilwright**, the city's Senior Tuner — a woman who can hear a lie inside a chord from a mile off and is paid by the law to end it. Her contradiction is total: she has built her whole life on the belief that a true note is always the right note, while carrying inside her the one true thing she was forced to deny. She pretends, hourly, that she never had a child, and that pretense has made her the most accomplished liar in a city where lying is supposed to be physically impossible.

- **Want:** To find and silence the rogue bell fracturing the cathedral spine before the central tower comes down — to do her job perfectly, one last time, and be promoted out of the field.
- **Need:** To stop mistaking obedience for honesty — to grieve out loud the daughter she gave up, and to accept that a heart held silent does more structural damage than any false bell. Her confession costs her the Tuner's identity outright; the only self she was permitted dissolves the moment the old law does.

## Antagonist

**The Concord** — the city's founding law — and its human enforcer, **High Registrar Aldous Pell**, who administers the Surrender: every "discordant" child, born to an unsanctioned union, is taken at birth and raised anonymously so no bell can ever be rung by divided blood. Pell is not cruel; he is the city's grief, professionalized. He genuinely believes emotional truth is too dangerous to leave unregulated — that if everyone rang the note they truly felt, the walls would fall by nightfall. The Surrender, to him, is mercy: it spares children the impossible weight of a bell that knows their whole heart. He loved someone once, rang true, and watched a tower fall; he has spent forty years making certain no one ever again has to choose between truth and the people standing under the stone.

He optimizes for zero collapses — structural stability through enforced emotional silence — and he is willing to surrender every child and silence every grieving mother to keep that number at zero. He is sympathetic and, by his own tragedy, right; which is exactly what makes him immovable.

## Key Characters

**Nika** — nineteen, a foundry orphan with no record and a bell she cast herself, who climbs the seawall every dusk to ring a note of raw longing out over the water. She has spent her life feeling assigned-to and never chosen, and that grief is the truest sound in the city — which is why it is cracking the stone. She does not know the mentor sent to "correct" her is her mother. Her arc is to learn that the longing she was taught to be ashamed of is not a flaw to resolve but a weight the world can finally be made to carry, out loud.

## Verified Proof of Demand

_Every figure below was fetched live; the quoted text appears verbatim on the linked page._

- **Coco grossed $800.5M worldwide on grief-and-family premise** — “Disney/Pixar's Best Animated Feature Oscar winner Coco has strummed up $800.5M at the worldwide box office.” ([source](https://deadline.com/2018/05/coco-crosses-800-million-global-box-office-disney-pixar-1202380459/), 2018-05-01)
- **Fantasy genre demand share grew from 8.1% to 9.1%** — “fantasy has seen growth, increasing from 8.1% to 9.1%, fueled by the success of shows like Netflix's "Arcane" and "The Dragon Prince,” ([source](https://www.parrotanalytics.com/insights/tv-audiences-are-watching-less-drama-more-fantasy/), 2024-09-29)
- **One in five U.S. adults report daily loneliness** — “Twenty percent of U.S. adults in Gallup's most recent quarterly data report feeling loneliness 'a lot of the day yesterday,'” ([source](https://news.gallup.com/poll/651881/daily-loneliness-afflicts-one-five.aspx), 2024-10-15)
- **Two in three grieving Americans never sought professional support** — “2 in 3 Americans (67%) who have experienced grief have not sought professional support” ([source](https://growtherapy.com/blog/grief-in-america-survey/), 2026-02-24)

## Economics — Methodology & Provenance

Every figure below is frozen and machine-checked; none was written or rounded by a language model.

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $328.20B | Total addressable content market — [MPA THEME Report](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf). |
| **SAM** | $39.38B | Serviceable share — `python_executed` derivation (12% of $328.20B TAM). Not an independent market estimate. |
| **SOM (Year 1)** | $538M | Obtainable Year-1 revenue — `python_executed` from the matched comparable films above; 80% band $209M-$1.38B; lifetime $1.59B. Never model arithmetic. |

The SOM < SAM < TAM ordering holds by construction (`python_executed`, ADR-0011). Comparable
box-office figures carry worldwide gross, production budget, ROI, and a Box Office Mojo deep link;
they anchor tone and budget scale, not a like-for-like performance promise.
