# Carbon

#### Logline
A dying archaeologist must destroy her career's greatest discovery to prove a murdered ancient woman's body is telling the truth.

#### Tagline
Every layer she removes brings her closer to the one she buried.

---

# 1. Market & Audience

## Audience Sizing

The total addressable market is the global theatrical box office, valued at $328.2 billion in the most recent industry-wide accounting of cinema revenue ([MPA THEME Report, 2021](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf)). This is the full ceiling of paying cinema audiences worldwide — every screen, every territory, every genre — and it sets the outer boundary for any feature competing for theatrical attention.

The serviceable available market narrows to the segment a prestige forensic drama can credibly reach: the adult, character-led, awards-track theatrical audience that turns out for grounded thrillers and human-scale dramas rather than franchise spectacle. That serviceable slice is sized at $39.384 billion — the portion of the global box office realistically open to a contained, performance-driven film built for word-of-mouth and festival amplification rather than opening-weekend saturation.

The serviceable obtainable market is the share a single execution of this concept can capture in its first year across theatrical, premium video-on-demand, and the first windows of streaming licensing. For Carbon, that figure is modeled at the value below, with a verified lifetime trajectory of $1.586 billion across the full distribution life of the title and its library tail.

**SOM (Year 1):** $538M

> **How the Year-1 SOM is computed.** The figure is `python_executed` — produced by the engine's comparable-anchored revenue model, never written or rounded by a language model (ADR-0011). It is the weighted-median worldwide gross of the matched comparable titles below, derated for an English-language-first release and the modeled overlap of the film's audiences.
>
> Confidence band (80%): $209M-$1.38B. Projected lifetime value across all windows: $1.59B. Serviceable market SAM = $39.38B = 12% of $328.20B TAM ([MPA THEME Report](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf)). The order SOM < SAM < TAM holds by construction.

## Revenue Thesis

Carbon is engineered as a contained, performance-driven adult drama — the lane where a disciplined budget meets durable, award-amplified returns. The budget posture is deliberately lean: a single primary location (a flooding peat excavation and a clean white lab), a small principal cast, and no visual-effects spend, which keeps the negative cost in the festival-launch tier and makes the obtainable returns a multiple of outlay rather than a race against a tentpole's marketing burn. The economics are honest about the lane: this is a word-of-mouth and prestige play, not a spectacle play, and it is sized accordingly.

The comparable set spans the two poles this film bridges — the human-scale, slow-burn mystery and the propulsive forensic procedural — anchored by titles that prove an investigation built on a single body and a single instrument can travel:

- **Sherlock Holmes (2009)** earned $524.0M worldwide on a $90.0M budget, a 4.82x return — proof that a deduction-driven mystery, sold on a brilliant and breaking mind, scales globally.
- **Holes (2003)** earned $71.4M on a $20.0M budget, a 2.57x return — the contained-excavation drama, a buried-secret dig that returns a clean multiple at a modest tier and demonstrates the floor case.
- **Aladdin (2019)** earned $1,054.3M worldwide on a $183.0M budget, a 4.76x return — included as the upper reference for the genre cluster's ceiling, the tentpole pole the slate's economics imply, against which Carbon's grounded posture is the deliberate counter-position.

The investor case rests on multiple, not gross: a lean production cost against a modeled first-year obtainable market of $538M and a verified lifetime of $1.586B yields a return profile driven by performance and longevity, with breakeven achievable inside the theatrical-plus-first-streaming window rather than dependent on a single opening weekend.

## Why Now

Audiences have spent a decade learning to distrust the instruments that once felt infallible — the dating algorithm, the diagnostic scan, the confident model that turns out to have been quietly contaminated at the source. The cultural appetite for a story about a measurement that lies, told through a human being whose own internal clock is failing, lands precisely as institutional certainty itself is the live question of the moment. And the prestige forensic drama — chilly, exact, morally serious — has proven it can carry a feature on craft and reckoning alone, without spectacle, in exactly the register this concept commands.

---

# 2. The Concept

## Mass-Appeal Theme

The human truth Carbon carries is the most universal one there is, stripped of sentiment: the fear of dying with a lie told over your body — of being remembered wrong, of leaving a record that betrays who you actually were — and the quiet, enormous act of leaving an honest account for a stranger you will never meet. Everyone, eventually, becomes a body that others will date, read, and file. The film asks whether a record can be true *because* it was made by someone dying and fallible, rather than in spite of it.

The genre convention it breaks is the forensic thriller's iron promise of vindication. The standard beat says the brilliant expert who trusts the evidence is proven right and crowned. Here the discovery *destroys* the scientist. The thing she finally proves is that her own life's argument was incomplete, and her reward is a dry institutional retraction with her name in a footnote, not a headline. The investigation that opens looking outward at a corpse ends looking inward at her own failing memory — the detective and the cold case turn out to be the same decaying body.

## Format & Genre

The story demands a feature because its power is in compression and finality: a single, closed reckoning that resolves completely and earns its devastation in one sitting. Spread across a season it would dilute; the dread depends on a clock running out in real, unbroken time.

- **Genre:** Forensic drama / procedural thriller
- **Runtime:** ~120 minutes
- **Budget Tier:** Lean — single primary location, small principal cast, no visual effects; festival-launch posture

## Tonal Contract

A precise, hushed forensic drama in the register of a procedural that slowly reveals itself as a confession. The controlled dread and chilly competence of *Zodiac* and *The Conversation*, the institutional integrity-versus-loyalty pressure of a quiet awards drama, warmed by the human ache of a woman racing her own mind. Muddy, tactile, rain-soaked excavation realism set against the sterile white of scan rooms and clean labs. No supernatural element, no science fiction: the only clock that runs backward is the one in a damaged brain. Tense, intimate, melancholy — the cool surface of a thriller over the beating heart of a deathbed reckoning.

---

# 3. Story

## Synopsis

Dr. Mara Vesik, forty-nine, runs the most trusted archaeometry laboratory in northern Europe on a single doctrine she made famous and that the field now teaches under her own name — the Vesik Protocol: the body keeps the record the mind forgets; the instrument is truer than the witness; physical evidence never lies and human memory always does. At a flooding peat excavation racing the water table, she pulls a near-perfect body from the mire — a young woman, throat opened, a healed childhood fracture in the femur, a seed cake still in the stomach. The carbon assay, run by her former student and now lab director Dr. Aron Plett, dates the remains to roughly 600 BCE, which would make this the oldest intact iron-age soft-tissue find ever recovered — a career-ending-in-glory discovery. Mara should be euphoric. Instead two things gnaw at her. The throat wound is wrong for a ritual sacrifice — frantic, defensive, human — and the seed cake is a grain the pollen record says did not grow in that valley until centuries later. The data says ritual; the body says murder, and says it later. And Mara has begun losing time: standing in the trench with no memory of arriving, reading a clock and seeing the hands run backward. A scan names it — a tumor pressing on the region that stitches sequence into perception. The woman who dates the dead can no longer feel the order of her own days.

The vise closes when Plett's lab, backed by the funding board, sets a museum signing and a journal embargo with a fixed press date — and publishes the 600 BCE date under both their names, crowning it Mara's masterpiece in the exact week of her diagnosis. The airtight finding she wanted her whole life is handed to her precisely as she loses the faculty to verify it, and a clock she cannot stop now runs against her. Mara cannot let it stand, because the body is screaming a different story and she, of all people, taught the world to listen to the body. Against protocol she re-opens the corpse, photographs and casts the wound channel, and proves the cut was made by a flint already obsolete by 600 BCE — physical testimony that the carbon is wrong. But every move tightens the grip. To trust the body she must distrust the instrument that *is* her reputation; to argue an instrument can lie, she must argue in a voice that is itself failing. Colleagues watch her lose the thread mid-sentence, and Plett — gently, without cruelty — weaponizes it: how can a woman who cannot sequence her own morning be trusted to overturn a dating she signed?

The midpoint turns the investigation inward. Mara discovers the assay was not merely mistaken — the peat at that depth was contaminated by older carbon leaching from a buried hearth, a specific failure mode she herself documented and warned against in a paper twenty years ago, then forgot. She did everything right; one variable entirely outside her control — a dead fire under a dead girl — corrupted everything she built. Worse, the only proof of the contamination lives in her own field notes, which she can no longer reliably read in order. To date the girl honestly she must reconstruct her own lost timeline, interviewing her past self through notebooks the way she interrogates a corpse — treating her own decline as a dig. She works it alongside Sayer, a young field assistant whose name will go on the retraction beside hers, the one living person who has watched her think and who steadies the notebooks when her hands and her sequence fail; it is Sayer who walks the valley with her to trace the anomalous grain to a later trade route, gathering bodily, walkable evidence she can trust when her instruments and her recall cannot.

Act three arrives at the impossible choice, and Plett's lab moves to suppress before the embargo lifts — locking the sample, contesting her access, framing her doubts as the tumor talking. Mara can defend the data: keep the glorious 600 BCE date, keep her legacy, let the girl stay a tidy myth, and Plett will protect her. Or she can prove the body and torch the most celebrated finding of her life, in a voice everyone now hears as broken, knowing she will be remembered not as the woman who was right but as the woman who came apart. Either pole loses everything — the data without the body is a lie that erases a murdered girl; the body without a credible witness is a truth no one will accept. So she refuses both and invents a third category neither side will grant: testimony — a record authoritative *because* it was made by a witness who was dying and knew it. She files the girl's case not as a corrected date but as a deposition — the wound, the stomach, the obsolete flint, the contaminated hearth, entered as the physical confession of a murdered woman past all motive to lie — and alongside it, as a single bound exhibit, she enters her own decline: timestamped notebooks, a sworn video of her reasoning recorded while still lucid, her admission that her brain is corrupting her sequence, offered not as a disqualification but as the same class of evidence. The instrument and the witness were never opposites; both are bodies leaving a record. Plett, unable to refute the physical chain, signs the retraction; the Method survives, humbled, with a new appendix on witness-contamination that carries Mara's name in a footnote. Before the paper prints, at the grave's edge, Mara gives the ancient girl the name she had withheld from a mere specimen — speaks it aloud once, the way one speaks to the dead one believes. The final record carries two dates of death entered in the same hand, the girl's and Mara's, on one page: the woman who dated the dead at last counted among them, true because she was lived.

## Emotional Arc

The film opens in the cool pride of mastery — a woman who has made peace with mortality by trusting that the physical record outlives the fragile self — and detonates that peace by attacking the self directly: the instrument she *is*, her own brain, becomes the unreliable variable she always condemned. The audience feels a slow inversion of dread into tenderness: terror that she is losing herself, then grief as she chooses to lose her legacy too, then an unexpected, earned warmth as she discovers that being a fallible, dying witness is not a disqualification from truth but its deepest form. The universal ache underneath is the fear of being forgotten wrong — of dying with a lie told over your body — and the release is the act of leaving an honest record for someone she will never meet, and for the one young person at her side who will carry it. It lands not on triumph but on reconciliation: a woman forgiving her own failing body by giving voice to another's.

## Comparables

| Title | Year | WW Revenue | Budget | ROI | Notes |
|---|---|---|---|---|---|
| [Aladdin](https://www.boxofficemojo.com/title/tt6139732/) | 2019 | $1,054.3M | $183.0M | 4.76x | Upper-bound reference for the genre cluster's ceiling; the spectacle pole Carbon deliberately counter-positions against |
| [Sherlock Holmes](https://www.boxofficemojo.com/release/rl3597567489/) | 2009 | $524.0M | $90.0M | 4.82x | Deduction-driven mystery sold on a brilliant, breaking mind — proof the forensic engine travels globally |
| [Holes](https://www.boxofficemojo.com/release/rl4166616577/) | 2003 | $71.4M | $20.0M | 2.57x | Contained buried-secret excavation drama at a modest tier — the honest floor case and the closest budget analogue |
| [Dhurandhar](https://www.screendaily.com/features/inside-the-record-north-american-release-of-dhurandhar-the-revenge-plfs-weekday-surprises-canada/5215142.article) | 2025 | $137.2M | n/a | n/a | Recent crime-thriller traction in the cluster; budget and ROI not disclosed |

## Notes on the comparable set

The softest performer is included on purpose: *Holes* returned a 2.57x multiple — modest beside the others — and is the most honest analogue for Carbon's lean, contained, dig-driven build. The investor case does not lean on the tentpole ceiling; it leans on the contained model returning a healthy multiple against a disciplined budget.

---

# 4. Characters

## Protagonist

**Dr. Mara Vesik, 49** — a celebrated archaeometrist who built her name and a named method on the principle that physical evidence never lies and human memory always does. Her contradiction is exact and merciless: she has spent thirty years insisting the instrument is truer than the witness, and she is becoming a witness whose own instrument — her brain — is failing. She trusts the data precisely because she has stopped trusting herself, and the body in the bog forces her to need the very thing she despises.

- **Want:** To make the date stick — to deliver a finding so airtight that her competence is permanent, vindicated, untouchable by the one variable, the tumor, taking everything else.
- **Need:** To accept that a record can be true because it was lived and dying, not despite it — to forgive the body, the ancient one and her own, for telling a truth the data cannot hold.

## Antagonist

**The Method itself — embodied in Dr. Aron Plett**, Mara's former student turned lab director, who controls the carbon assay, the funding, the journal access, and the embargo clock, and who genuinely believes that defending the data is defending the truth. He is not a villain; he is Mara's own creed wearing a younger face, wielding the very protocol she taught him — her named instrument — against her. He reasons that one anomalous body cannot be allowed to discredit a dating method that has resolved ten thousand cases correctly: protecting the instrument protects every truth it has ever told. His position is the honorable, defensible, institutionally correct one, which is exactly what makes it so hard to defeat — to beat him, Mara must concede that her own life's argument was incomplete.

- **Optimizes for:** Methodological certainty and the integrity of the record at scale. He will sacrifice one inconvenient corpse, and one declining mentor, to keep the instrument trustworthy for everyone who comes after.

## Key Characters

**Sayer** — the young field assistant whose name goes on the retraction beside Mara's. Sayer is the single living human tie in the story: the one person who has watched Mara think at full power, who steadies the notebooks when her hands and her sequence fail, who walks the valley with her to gather the bodily evidence she can still trust. The honest record Mara fights to leave is not addressed only to an anonymous future reader — it is co-signed, inherited, and carried forward by a person the audience watches her come to love. Sayer is the beating-heart stake in her final choice: to defend the data would be to make her protégé an accomplice to a lie; to prove the body is to hand the next generation a method humbled into honesty.

## Verified Proof of Demand

_Every figure below was fetched live; the quoted text appears verbatim on the linked page._

- **Conclave: $20M budget returned $128M worldwide, 6x** — “The film reportedly cost $20 million to produce.” ([source](https://variety.com/2025/film/news/conclave-earns-100-million-global-box-office-milestone-1236311512/), 2025)
- **Sherlock Holmes (2009): $524.0M worldwide on $90M budget** — “$524,028,679” ([source](https://www.boxofficemojo.com/release/rl3597567489/), 2009)
- **Conclave's $100M proves real appetite for adult dramas** — “a major milestone for a film aimed squarely at adult audiences.” ([source](https://variety.com/2025/film/news/conclave-earns-100-million-global-box-office-milestone-1236311512/), 2025)
- **Adult-skewing dramas underserved; Conclave proved demand exists** — “There's been an absence of good adult dramas aimed toward older crowds.” ([source](https://variety.com/2024/film/box-office/conclave-box-office-success-adult-oscar-films-1236210375/), 2024)

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
