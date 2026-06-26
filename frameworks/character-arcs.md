# Character Arcs — Truby + McKee + Egri + Jung-Pearson

## Frame

This file is the Anomaly Engine's canonical reference for protagonist and
antagonist construction. The Forge LLM uses these frameworks when generating
the `character` block of every concept; the Critic validates the outputs
against the structural rules defined here; the P3 schema (`pipeline/schema.py`)
enforces word-count constraints on `character.premise` and `character.gap`.

Four frameworks are integrated:
1. **Truby's 7 Must-Haves** — the structural skeleton of every well-formed
   protagonist arc.
2. **McKee's Gap** — the engine of scene-level dramatic tension.
3. **Egri's Premise** — the declarative moral argument that the entire film
   demonstrates.
4. **Jung-Pearson 12 Archetypes** — the psychic vocabulary for protagonist
   and antagonist identity.

The **Antagonist Rule** (drawn from Booker via `frameworks/narrative-master-grid.md`)
connects all four frameworks into a single design test.

---

## Truby's 7 Must-Haves

Source: John Truby, *Anatomy of Story: 22 Steps to Becoming a Master
Storyteller* (Farrar, Straus and Giroux, 2007). Chapters 2-8 establish the
structural elements. Truby's system is not a formula; it is a set of
interlocking requirements each of which creates a distinct narrative function.
A film concept with fewer than all 7 is incomplete at the structural level,
regardless of its aesthetic merit.

---

### Must-Have 1 — Self-Revelation

The protagonist undergoes a self-revelation: a moment of genuine psychological
discovery about who they are and what they have been doing wrong (morally,
psychologically, or practically). The revelation is not a surprise to the
audience (who have been watching the protagonist's blind spot since Act 1);
it is a surprise to the protagonist. Without self-revelation, the character
arc has no destination — the protagonist ends the film in the same psychic
state they began it.

In Truby's system, the self-revelation occurs at or near the climax and must
emerge from the external story action — it cannot be "told" to the protagonist
or delivered by another character as a speech. It must be *discovered* by the
protagonist through the consequences of their choices.

The Forge must specify `character.self_revelation` in one sentence (max 30
words): what the protagonist discovers about themselves, stated as a positive
claim ("She discovers that her need to control was, in fact, a form of fear
that she had been calling love").

---

### Must-Have 2 — Need

The protagonist has a **psychological need** that they are unaware of at the
story's opening. This is distinct from their *desire* (what they think they
want). The need is what they actually require in order to become a fully
functional human being. Truby identifies two categories of need: the moral
need (the change that will make the protagonist a better person in relation
to others) and the psychological need (the internal change that allows the
protagonist to function). In the best films, these are the same change.

The need connects directly to the SDT need framework in
`frameworks/sdt-spine.md`: the audience experiences the protagonist's need
as a deprivation of Autonomy, Competence, or Relatedness. This connection
is the structural reason the Anomaly Engine requires both an SDT primary need
(audience-level) and a Truby Need (character-level) to be specified: they
are the same phenomenon at different scales.

---

### Must-Have 3 — Desire

The protagonist's **desire** is what they consciously pursue — the goal that
organizes the story's events into a sequence of obstacles and attempts. The
desire is visible; the need is hidden. The tension between desire and need is
the dramatic engine of the protagonist's arc: if they achieve the desire
without getting the need, the film is a tragedy of a particular kind (the
protagonist wins and loses simultaneously); if they fail the desire but get
the need, the film is a particular kind of victory.

For Forge use: `character.desire` is a noun phrase (max 15 words) specifying
the protagonist's conscious goal. It must be concrete, external, and
achievable in principle.

---

### Must-Have 4 — Opponent

The **opponent** (antagonist in Egri's and Booker's vocabulary) is the
character who most directly blocks the protagonist from achieving the desire.
In Truby's system, the opponent is not evil for its own sake; the opponent
is the *best possible challenger* — the character who is structured to expose
the protagonist's specific weakness. An opponent that exposes a weakness
the protagonist does not actually have is a structural mismatch and will
produce a dramatically inert second act.

This element connects to the Antagonist Rule below: the best opponent wants
the same thing as the protagonist for the opposite reason, which means the
opponent's desire (and the method of blocking) emerges organically from their
shared goal rather than from random hostility.

---

### Must-Have 5 — Plan

The protagonist makes a **plan** to achieve the desire while overcoming the
opponent. The plan is not the plot; it is the protagonist's strategy. Plans
fail or are revised — the dramatic value of the plan is in the revision:
each failed plan reveals something new about the protagonist's character or
the opponent's strength. A protagonist without a plan is reactive (the world
happens to them); a protagonist with a plan is active (they happen to the world).

For Forge use: `character.plan_description` is a single sentence (max 20
words) stating the protagonist's initial strategy.

---

### Must-Have 6 — Battle

The **battle** is the climactic conflict between protagonist and opponent —
the moment at which all prior choices, plans, and revelations converge in
a single scene or sequence where both characters are fully committed and one
cannot survive the encounter intact. The battle need not be physical; it can
be verbal, legal, economic, or psychological. What makes it a battle is that
both parties are at maximum stake and maximum commitment simultaneously.

Truby's battle is the structural reason the self-revelation (Must-Have 1)
must emerge from action rather than dialogue: only an event of maximum stakes
forces genuine self-knowledge. Lesser confrontations allow the protagonist
to retreat behind prior self-conception; the battle removes all exits.

---

### Must-Have 7 — New Equilibrium

After the battle, a **new equilibrium** is established. The world of the
story has been permanently altered by the events of the narrative; a return
to the prior state is structurally impossible. The new equilibrium documents
what the world looks like after the protagonist's arc is complete — whether
in victory, defeat, or the ambiguous third state that characterizes the best
literary films.

The new equilibrium is not a resolution of all loose ends; it is the
establishment of a new stable state from which a new story could begin.
Its relationship to the self-revelation is causal: the protagonist's internal
change produces or enables the external new equilibrium.

---

## McKee's Gap

Source: Robert McKee, *Story: Substance, Structure, Style, and the Principles
of Screenwriting* (ReganBooks/HarperCollins, 1997). The Gap is defined in
Part 2, Chapter 8 ("Scene Design").

The **Gap** is the discrepancy between the protagonist's expectation of how
the world will respond to their action and how the world actually responds.
The protagonist takes an action expecting outcome X; the world delivers
outcome Y. The Gap is the measure of that discrepancy.

McKee's formulation: "The size of the Gap is the measure of the scene's
dramatic power." A scene with no gap (the world delivers exactly what the
protagonist expected) produces no new information, generates no dramatic
energy, and advances no arc. Every scene without a gap is either exposition
or waste.

In structural terms, the Gap operates at three levels:
1. **Beat-level Gap:** within a single exchange, the response contradicts
   the expectation (character says X, receives Y as a response).
2. **Scene-level Gap:** the protagonist's tactical action produces an outcome
   that reveals new information about the opposition or the world.
3. **Act-level Gap:** the protagonist's strategic plan produces consequences
   that force a fundamental revision of their understanding of the situation.

For Forge use: `character.gap` is a sentence (max 35 words, enforced by
`pipeline/schema.py`) in the form: "[Protagonist] acts to achieve [X] and
discovers [Y] — the gap that reorients the story."

The Gap is the connection between external event and internal revelation.
Without it, the self-revelation (Truby Must-Have 1) has no structural trigger:
the protagonist would change for no external reason, which is psychologically
implausible and dramatically unconvincing.

---

## Egri's Premise

Source: Lajos Egri, *The Art of Dramatic Writing* (Simon & Schuster, 1946;
revised edition 1960). The Premise is defined in Part One, Chapter 1.

Egri's **Premise** is a declarative causal sentence that states the entire
film's moral argument in the form "A leads to B leads to C," where A is
the initiating quality or condition, B is the escalating consequence, and
C is the irreversible resolution. The premise is not the plot; it is the
thesis that the plot demonstrates. Every scene, every character, and every
structural decision must be in service of proving the premise.

Egri's rule: a film with no premise is a film with no argument. It may have
events, but it does not have a point. The audience experiences premise-less
films as vaguely unsatisfying — they remember "something happened" but not
why it mattered.

Format for Forge use: `character.premise` is a single sentence in the form
"[condition] leads to [escalation] leads to [resolution]." Word count <= 30,
enforced by `pipeline/schema.py`. The premise must be falsifiable: a premise
that is true of every film is not a premise at all.

### Worked Moral Arguments from Real Films

The following examples demonstrate how the premise captures the film's moral
argument in a single declarative sentence. Each follows the format required
by the Forge: `**[Film Title]**` — **premise:** "[A] leads to [B] leads to [C]."

**12 Angry Men** (Sidney Lumet, 1957) —
**premise:** "Rigorous doubt leads to genuine examination leads to true conviction."

**Schindler's List** (Steven Spielberg, 1993) —
**premise:** "Moral clarity in extremity leads to disproportionate action leads to irreversible good."

**Casablanca** (Michael Curtiz, 1942) —
**premise:** "Cynical self-protection leads to love's demand leads to heroic self-surrender."

**The Godfather** (Francis Ford Coppola, 1972) —
**premise:** "Family loyalty leads to moral compromise leads to total corruption."

**Whiplash** (Damien Chazelle, 2014) —
**premise:** "Obsessive perfectionism leads to psychological destruction leads to transcendent performance."

**No Country for Old Men** (Joel and Ethan Coen, 2007) —
**premise:** "Random evil leads to systemic moral retreat leads to civilizational loss."

**Parasite** (Bong Joon-ho, 2019) —
**premise:** "Economic desperation leads to systematic deception leads to catastrophic exposure."

**Hidden Figures** (Theodore Melfi, 2016) —
**premise:** "Systematic exclusion leads to demonstrated excellence leads to institutional transformation."

**The Lives of Others** (Florian Henckel von Donnersmarck, 2006) —
**premise:** "Surveillance of beauty leads to moral awakening leads to self-sacrificial protection."

**The Shawshank Redemption** (Frank Darabont, 1994) —
**premise:** "Unjust imprisonment leads to patient interior freedom leads to physical liberation."

**The Pianist** (Roman Polanski, 2002) —
**premise:** "Systematic dehumanization leads to stripped-down survival leads to art as proof of personhood."

**Burning** (Lee Chang-dong, 2018) —
**premise:** "Class resentment leads to obsessive surveillance leads to annihilating violence."

Each of the above instances uses the format `**premise:**` to enable the
Forge and the lint verifier to count qualifying entries (minimum 9 required
by this plan's verification step).

---

## Jung-Pearson 12 Archetypes

Sources:
- Carl Jung, *Man and His Symbols* (Doubleday, 1964), Part 1: "Approaching
  the Unconscious." Jung's treatment of the collective unconscious and
  archetypal images as organizing structures of human experience.
- Carol S. Pearson, *The Hero Within: Six Archetypes We Live By*
  (HarperSanFrancisco, 1986; expanded ed. 1998). URL:
  [carolspearson.com/archetypes/](https://carolspearson.com/archetypes/)
- Carol S. Pearson and Hugh Marr, *What Story Are You Living?* (CAPT, 2003).

Pearson expanded Jung's framework into 12 archetypes relevant to contemporary
narrative. Each archetype has a **core desire**, a **shadow form** (the
archetype under stress or distortion), an **awakening trigger** (the
narrative event that activates the archetype), and a **prototype film**
(a canonical exemplar of the archetype as protagonist). Antagonists operate
as shadow versions of the same or a complementary archetype.

For Forge use: `character.protagonist_archetype` and
`character.antagonist_archetype` are strings from the 12 names below.

---

### The Innocent

Core desire: safety and happiness; to experience paradise.
Shadow form: naivety becomes complicity — the Innocent is used by more
powerful figures precisely because of the refusal to see the world's darkness.
Awakening trigger: the first exposure to genuine evil or loss that cannot
be explained away.
Prototype film: *E.T. the Extra-Terrestrial* (Steven Spielberg, 1982) —
Elliot's innocence is both his asset (he trusts E.T. immediately) and his
liability (he cannot protect what he loves against institutional power).

---

### The Orphan

Core desire: to belong, to connect, to be safe in a community.
Shadow form: the Orphan becomes the Victim — a permanent identity around
loss that prevents the construction of new belonging.
Awakening trigger: betrayal by the community that was supposed to provide
safety; the discovery that the protective structure was illusory.
Prototype film: *Oliver Twist* adaptations; *Leon: The Professional*
(Luc Besson, 1994) — Mathilda's orphan status is literal and the film traces
her construction of substitute belonging with Leon.

---

### The Warrior

Core desire: to win, to prove worth through courage and strength.
Shadow form: ruthlessness — the Warrior who cannot distinguish a worthy
opponent from a necessary one destroys allies in pursuit of victory.
Awakening trigger: defeat or a moral challenge that courage alone cannot
solve; the discovery that force is not always the appropriate instrument.
Prototype film: *Gladiator* (Ridley Scott, 2000) — Maximus's warrior
identity is authentic and also his prison; the film traces the cost.

---

### The Caregiver

Core desire: to protect and care for others; to be needed.
Shadow form: enabling and martyrdom — the Caregiver sacrifices themselves
to people who do not want or cannot accept care, and calls the sacrifice love.
Awakening trigger: the cared-for person refusing the care, or the Caregiver
discovering that their care has been harmful.
Prototype film: *Terms of Endearment* (James L. Brooks, 1983) — Aurora's
caregiving is genuine love and also control; the film tracks both.

---

### The Seeker

Core desire: to search for a better life; to find authenticity and freedom.
Shadow form: alienation — the Seeker who cannot stop seeking never arrives;
every destination becomes a new departure point before it can be inhabited.
Awakening trigger: a destination that might actually be the right one; the
choice between continuing to search and choosing to be found.
Prototype film: *Into the Wild* (Sean Penn, 2007) — McCandless's seeking
is genuine and fatal; the shadow form is the complete refusal to be found.

---

### The Lover

Core desire: to experience intimacy, passion, and connection.
Shadow form: obsession — love becomes possession; intimacy becomes
suffocation; the shadow Lover destroys what they love by demanding total merger.
Awakening trigger: the beloved's need for autonomy; the discovery that love
requires the ability to let go.
Prototype film: *La La Land* (Damien Chazelle, 2016) — the film's final
sequence enacts the difference between the Lover archetype and its shadow.

---

### The Destroyer

Core desire: radical change; tearing down what no longer serves.
Shadow form: nihilism — destruction without purpose; the Destroyer who has
no vision of what should replace what they destroy.
Awakening trigger: the encounter with something worth building; the discovery
that creation requires surviving the destruction phase.
Prototype film: *Fight Club* (David Fincher, 1999) — Tyler Durden is the
shadow Destroyer; the narrator's arc is learning to distinguish productive
from nihilistic destruction.

---

### The Creator

Core desire: to create something of enduring value.
Shadow form: perfectionism — the Creator who cannot release the work because
it is never good enough; endless revision as a refusal of completion.
Awakening trigger: the necessity of completion; the external deadline or
audience that forces the work into the world.
Prototype film: *Amadeus* (Milos Forman, 1984) — Mozart is the natural
Creator; Salieri is the shadow Creator who can recognize but not generate.

---

### The Magician

Core desire: to make dreams come true; to transform reality.
Shadow form: manipulation — the Magician who uses transformation to control
others rather than liberate them.
Awakening trigger: the confrontation between the Magician's vision and the
autonomy of those the vision would transform.
Prototype film: *The Prestige* (Christopher Nolan, 2006) — both protagonists
are Magicians; their shadow forms consume them.

---

### The Ruler

Core desire: to establish order and maintain control.
Shadow form: tyranny — the Ruler who can no longer distinguish between
legitimate order and personal dominance.
Awakening trigger: the discovery that the order being maintained is unjust;
the moment when the legitimacy of authority becomes a live question.
Prototype film: *The Crown* (television; Peter Morgan, 2016-2023) — Elizabeth
II's ruler archetype under perpetual pressure from shadow forms of obligation
and institutional tyranny.

---

### The Sage

Core desire: to discover truth and achieve wisdom.
Shadow form: detachment — the Sage who has achieved wisdom at the cost of
all emotional engagement; truth without compassion.
Awakening trigger: the moment when pure knowledge is insufficient and must
be translated into action; the Sage who must leave the library.
Prototype film: *Good Will Hunting* (Gus Van Sant, 1997) — Sean (Robin
Williams) is the healthy Sage; Will Hunting is the Sage refusing to be
activated.

---

### The Jester

Core desire: to live fully in the moment; to enjoy life and help others do the same.
Shadow form: self-destructive hedonism — the Jester who uses humor and
pleasure to avoid all serious engagement; comedy as armor against growth.
Awakening trigger: the encounter with genuine consequence; the moment when
the joke is no longer sufficient and the stakes are real.
Prototype film: *Groundhog Day* (Harold Ramis, 1993) — Phil Connors begins
as shadow Jester and ends as healthy Jester who has integrated seriousness.

---

## Antagonist Rule

The antagonist must want **the same thing** as the protagonist for the
**opposite reason**. This is not a rule of taste; it is a structural
requirement. An antagonist who wants something different from the protagonist
produces a story in which the conflict is accidental (they happen to be in
each other's way) rather than essential (they cannot both achieve their goals
in the same world at the same time). The collision is maximally inevitable
only when the shared goal makes them competitors rather than strangers.

Source: This rule is derived from Christopher Booker's analysis of narrative
opposition structures in *The Seven Basic Plots: Why We Tell Stories* (2004),
particularly the discussion of "The Shadow" in Chapter 26. The full Booker
grid (all 7 basic plots with role tuples) is documented in
`frameworks/narrative-master-grid.md`.

**Structural test:** A valid antagonist-protagonist pair satisfies all three
conditions simultaneously:
1. Both characters want the same goal (the same object, outcome, or state
   of affairs).
2. Their reasons for wanting it are structurally opposite (not merely
   different in degree but in kind — one wants it for love, the other for
   power; one for preservation, the other for transformation).
3. The world can only deliver the goal to one of them; the protagonist's
   success necessarily prevents the antagonist's success, and vice versa.

**Film exemplars:**

*The Dark Knight* (Christopher Nolan, 2008) — Both Batman and the Joker
want to test Gotham's moral character. Batman wants Gotham to prove that
civilization can survive the presence of evil; the Joker wants Gotham to
prove that civilization is a thin lie that evil strips away in every human
being. The goal is identical (the test). The reason is structurally opposite
(affirmation vs. demolition of the thesis). The world cannot deliver both
outcomes simultaneously.

*Heat* (Michael Mann, 1995) — Both Neil McCauley and Vincent Hanna want the
score that ends all scores: one the job that means retirement on his terms,
the other the arrest that proves his professional identity. The goal is the
same event (the final heist). The reasons are opposite (freedom from the game
vs. mastery of the game). The world cannot deliver both.

*No Country for Old Men* (Joel and Ethan Coen, 2007) — Both Chigurh and
Llewelyn Moss want control over fate as expressed by the bag of money. Moss
wants it as proof that luck can be seized and kept; Chigurh wants it as proof
that fate is an impersonal mechanism that human will cannot override. Both
are making an argument about the same thing (the nature of chance) through
the same object (the money). The world resolves the argument in Chigurh's
favor — but Sheriff Bell's withdrawal is the film's actual argument: some
things cannot be resolved at all.

**Cross-reference:** The Booker plot grid in `frameworks/narrative-master-grid.md`
documents the full role-tuple system (Hero, Threshold Guardian, Helper,
Shadow, Trickster, Herald, Shape-Shifter) from which the antagonist's
structural position is defined. The antagonist-as-Shadow is the Booker grid's
primary opposition archetype.

---

## Operational Integration

This section is the canonical interface between `character-arcs.md` and the
Anomaly Engine pipeline. All fields listed here are produced by the Forge
and validated by the Critic and the P3 schema layer.

### Forge Fields Produced

The character arc framework produces the following fields in the `character`
block of every concept:

| Field | Type | Constraint | Framework Source |
|---|---|---|---|
| `character.protagonist_archetype` | str | one of 12 Jung-Pearson names | Jung-Pearson section |
| `character.antagonist_archetype` | str | one of 12 Jung-Pearson names | Jung-Pearson section |
| `character.premise` | str | word_count <= 30 | Egri section |
| `character.gap` | str | word_count <= 35 | McKee section |
| `character.self_revelation` | str | word_count <= 30 | Truby Must-Have 1 |
| `character.desire` | str | word_count <= 15 | Truby Must-Have 3 |
| `character.plan_description` | str | word_count <= 20 | Truby Must-Have 5 |

### Critic Re-checks

The Critic agent (P5) independently verifies:

1. `character.premise` is a genuine causal sentence ("A leads to B leads to C")
   with three distinct elements, not a description of the plot.
2. `character.antagonist_archetype` produces a valid same-goal-opposite-reason
   test when compared to `character.protagonist_archetype` and the concept's
   stated `desire`.
3. `character.gap` is a genuine gap (expectation vs. reality) rather than
   a description of a scene.
4. `character.self_revelation` is a discovery by the protagonist (not by
   another character on behalf of the protagonist).
5. `character.premise` word count <= 30 (hard schema constraint).
6. `character.gap` word count <= 35 (hard schema constraint).

### P3 Schema Targets

```
pipeline/schema.py — word-count validators:
  - premise: len(premise.split()) <= 30
  - gap: len(gap.split()) <= 35
  - self_revelation: len(self_revelation.split()) <= 30
  - desire: len(desire.split()) <= 15
  - plan_description: len(plan_description.split()) <= 20
```

These validators run at concept ingestion (Phase 3) and reject any concept
whose character fields exceed the word limits.

### Cross-References

- `frameworks/narrative-master-grid.md` — The Booker grid (7 basic plots)
  and the Truby role-tuple system define the structural opposition positions
  from which the antagonist's function is derived. The antagonist-as-Shadow
  maps to Booker's "Dark Power" / "Shadow" figure in plots 1 (Overcoming the
  Monster), 3 (The Quest), and 6 (Tragedy). The full grid with role tuples
  is documented in `narrative-master-grid.md`.
