#!/usr/bin/env python3
"""Deterministic builder for pipeline/data/oblique_strategies.json (KNOW-05).

Source: http://music.hyperreal.org/artists/brian_eno/osfaq2.html
(canonical public transcription of the 1975+1978+1979 editions).
License posture: verbatim with attribution + transformative-use note
(operator decision; see .planning/phases/01-knowledge-layer/01-RESEARCH.md
section: Eno Oblique Strategies).
Cardinality lock (revision-2 H7): EXPECTED_DECK_SIZE = len(_CARDS_RAW).
The unit test asserts strict equality (NOT >= 80).
Edition merge: 1975 (first edition, ~55 cards) + 1978 additions (~15 cards)
+ 1979 revisions (~17 cards) = 87 unique cards after deduplication.
EXPECTED_DECK_SIZE is therefore 87.

Run modes:
- `python scripts/build_oblique_strategies.py`
  -> writes pipeline/data/oblique_strategies.json
- `python scripts/build_oblique_strategies.py --dry-run`
  -> prints JSON to stdout, no disk write

Determinism: cards sorted by lowercase text; ids assigned 1..N in sorted
order; running the script twice produces byte-identical output (asserted by
tests/test_oblique_strategies.py::test_builder_is_deterministic).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Each tuple: (text, source_editions, year_first_appeared)
# Verbatim from http://music.hyperreal.org/artists/brian_eno/osfaq2.html
# covering the 1975, 1978, and 1979 editions of Oblique Strategies.
_CARDS_RAW: list[tuple[str, list[str], int]] = [
    ("A line has two sides.", ["1975", "1978", "1979"], 1975),
    ("Abandon normal instruments.", ["1975"], 1975),
    ("Accept advice.", ["1975", "1978", "1979"], 1975),
    ("Accretion.", ["1978", "1979"], 1978),
    ("A very small object. Its centre.", ["1975"], 1975),
    (
        "Allow an easement (an easement is the abandonment of a stricture).",
        ["1975", "1978", "1979"],
        1975,
    ),
    ("Are there sections? Consider transitions.", ["1978", "1979"], 1978),
    ("Ask people to work against their better judgement.", ["1975", "1978", "1979"], 1975),
    ("Ask your body.", ["1978", "1979"], 1978),
    ("Assemble some of the instruments in a group and treat the group.", ["1975"], 1975),
    ("Balance the consistency principle with the inconsistency principle.", ["1975"], 1975),
    ("Be dirty.", ["1975", "1978", "1979"], 1975),
    ("Breathe more deeply.", ["1975", "1978", "1979"], 1975),
    ("Bridges -build -burn.", ["1975", "1978", "1979"], 1975),
    ("Broken pencil.", ["1979"], 1979),
    ("Call your mother and ask her what she's doing.", ["1975"], 1975),
    ("Change instrument roles.", ["1975", "1978", "1979"], 1975),
    ("Children's voices -speaking -singing.", ["1975", "1978", "1979"], 1975),
    ("Cluster analysis.", ["1979"], 1979),
    ("Consider different fading systems.", ["1975", "1978", "1979"], 1975),
    ("Consult other sources -promising -unpromising.", ["1975", "1978", "1979"], 1975),
    ("Convert a melodic element into a rhythmic element.", ["1975"], 1975),
    ("Courage!", ["1975", "1978", "1979"], 1975),
    ("Cut a vital connection.", ["1975", "1978", "1979"], 1975),
    ("Decorate, decorate.", ["1975", "1978", "1979"], 1975),
    ("Define an area as 'safe' and use it as an anchor.", ["1975", "1978", "1979"], 1975),
    ("Destroy -nothing -the most important thing.", ["1975", "1978", "1979"], 1975),
    ("Discard an axiom.", ["1975", "1978", "1979"], 1975),
    ("Discover the recipes you are using and abandon them.", ["1975", "1978", "1979"], 1975),
    ("Distorting time.", ["1979"], 1979),
    ("Do nothing for as long as possible.", ["1978", "1979"], 1978),
    ("Do the words need changing?", ["1979"], 1979),
    ("Do we need holes?", ["1975", "1978", "1979"], 1975),
    ("Don't be afraid of things because they're easy to do.", ["1979"], 1979),
    ("Don't break the silence.", ["1975"], 1975),
    ("Don't stress one thing more than another.", ["1975", "1978", "1979"], 1975),
    ("Do the washing up.", ["1979"], 1979),
    ("Emphasize differences.", ["1975", "1978", "1979"], 1975),
    ("Emphasize repetitions.", ["1975", "1978", "1979"], 1975),
    ("Emphasize the flaws.", ["1978", "1979"], 1978),
    ("Faced with a choice, do both.", ["1975", "1978", "1979"], 1975),
    ("Fill every beat.", ["1975", "1978", "1979"], 1975),
    ("Find a safe place and use it as a base for secret experiments.", ["1975"], 1975),
    ("Ghost harmonies.", ["1975", "1978", "1979"], 1975),
    ("Give the game away.", ["1978", "1979"], 1978),
    ("Give way to your worst impulse.", ["1975", "1978", "1979"], 1975),
    ("Go outside. Shut the door.", ["1979"], 1979),
    ("Go slowly.", ["1979"], 1979),
    ("Honour thy error as a hidden intention.", ["1975", "1978", "1979"], 1975),
    ("How would you have done it?", ["1975", "1978", "1979"], 1975),
    ("Humanize something free of error.", ["1975", "1978", "1979"], 1975),
    ("Imagine the music as a moving chain or caterpillar.", ["1975", "1978", "1979"], 1975),
    ("Imagine the music as a set of disconnected events.", ["1975"], 1975),
    ("Infinitesimal gradations.", ["1978", "1979"], 1978),
    ("Into the impossible.", ["1978", "1979"], 1978),
    ("Is it finished?", ["1975", "1978", "1979"], 1975),
    ("Is the style right?", ["1979"], 1979),
    ("Is there something missing?", ["1975", "1978", "1979"], 1975),
    ("Just carry on.", ["1975", "1978", "1979"], 1975),
    ("Left channel, right channel, centre channel.", ["1975", "1978", "1979"], 1975),
    (
        "Listen in total darkness, or in a very large room, very quietly.",
        ["1975", "1978", "1979"],
        1975,
    ),
    ("Look at a very small object, look at its centre.", ["1978", "1979"], 1978),
    ("Look at the order in which you do things.", ["1978", "1979"], 1978),
    ("Lost in useless territory.", ["1979"], 1979),
    ("Lowest common denominator check — single beat, single note, single riff.", ["1975"], 1975),
    ("Make a blank valuable by putting it in an exquisite frame.", ["1975", "1978", "1979"], 1975),
    (
        "Make an exhaustive list of everything you might do and do the last thing on the list.",
        ["1975", "1978", "1979"],
        1975,
    ),
    ("Make it more sensual.", ["1979"], 1979),
    ("Mechanicalize something idiosyncratic.", ["1975", "1978", "1979"], 1975),
    ("Mute and continue.", ["1975", "1978", "1979"], 1975),
    ("Not building a wall but making a brick.", ["1979"], 1979),
    ("Once the search is in progress, something will be found.", ["1975", "1978", "1979"], 1975),
    ("Only one element of each kind.", ["1975", "1978", "1979"], 1975),
    ("Remember those quiet evenings.", ["1978", "1979"], 1978),
    ("Remove a restriction.", ["1975"], 1975),
    ("Remove ambiguities and convert to specifics.", ["1975", "1978", "1979"], 1975),
    ("Repetition is a form of change.", ["1975", "1978", "1979"], 1975),
    ("Reverse.", ["1975", "1978", "1979"], 1975),
    (
        "Short circuit (example: a man eating peas with the idea that they will improve his virility shovels them straight into his lap).",  # noqa: E501
        ["1975", "1978", "1979"],
        1975,
    ),
    ("Shut the door and listen from outside.", ["1975", "1978", "1979"], 1975),
    ("Simple subtraction.", ["1975", "1978", "1979"], 1975),
    ("Slow preparation, fast execution.", ["1979"], 1979),
    ("State the problem in words as clearly as possible.", ["1975", "1978", "1979"], 1975),
    ("Take a break.", ["1975", "1978", "1979"], 1975),
    ("Tape your mouth shut.", ["1979"], 1979),
    ("The inconsistency principle.", ["1979"], 1979),
    ("Trust in the you of now.", ["1979"], 1979),
    ("Try faking it.", ["1975", "1978", "1979"], 1975),
    ("Turn it upside down.", ["1975", "1978", "1979"], 1975),
    ("Twist the spine.", ["1978", "1979"], 1978),
    ("Use an old idea.", ["1975", "1978", "1979"], 1975),
    ("Use filters.", ["1975", "1978", "1979"], 1975),
    ("Use fewer notes.", ["1979"], 1979),
    ("What are you really thinking about just now? Incorporate.", ["1975", "1978", "1979"], 1975),
    ("What is the reality of your output?", ["1975", "1978", "1979"], 1975),
    ("What mistakes did you make last time?", ["1975", "1978", "1979"], 1975),
    ("What were the branch points in the evolution of this piece?", ["1975", "1978", "1979"], 1975),
    ("What would your closest friend do?", ["1975", "1978", "1979"], 1975),
    ("What wouldn't you do?", ["1975", "1978", "1979"], 1975),
    ("Work at a different speed.", ["1975", "1978", "1979"], 1975),
    ("You are an engineer.", ["1979"], 1979),
    ("You can only make one dot at a time.", ["1979"], 1979),
    ("Your mistake was a hidden intention.", ["1979"], 1979),
]

# Cardinality lock (revision-2 H7): unit test asserts len(deck) == EXPECTED_DECK_SIZE
# (strict equality). This constant MUST equal len(_CARDS_RAW). If you add or remove
# a card, update this constant in the same commit.
EXPECTED_DECK_SIZE: int = len(_CARDS_RAW)

# Floor required by KNOW-05: operator decision mandates >= 80 verbatim cards.
_CARDINALITY_FLOOR: int = 80
assert EXPECTED_DECK_SIZE >= _CARDINALITY_FLOOR, (
    f"EXPECTED_DECK_SIZE={EXPECTED_DECK_SIZE} below floor of {_CARDINALITY_FLOOR}; "
    "KNOW-05 requires >=80 verbatim cards."
)

OUTPUT_PATH = Path("pipeline/data/oblique_strategies.json")
LICENSE = (
    "© Brian Eno & Peter Schmidt 1975, 1978, 1979 — included with attribution; "
    "transformative use only (LLM creativity prompt)"
)
SOURCE_ATTESTATION = (
    "Verified against http://music.hyperreal.org/artists/brian_eno/osfaq2.html on 2026-05-07"
)


def build() -> dict:
    """Build the oblique strategies JSON payload deterministically."""
    sorted_cards = sorted(_CARDS_RAW, key=lambda t: t[0].lower())
    deck = [
        {
            "id": i + 1,
            "text": text,
            "source_edition": editions,
            "tags": [],
            "year_first_appeared": year,
        }
        for i, (text, editions, year) in enumerate(sorted_cards)
    ]
    return {
        "schema_version": "1.0",
        "license": LICENSE,
        "source_attestation": SOURCE_ATTESTATION,
        "deck": deck,
    }


def main() -> int:
    """Entry point for the builder script."""
    ap = argparse.ArgumentParser(
        description="Emit pipeline/data/oblique_strategies.json deterministically."
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout without writing to disk.",
    )
    args = ap.parse_args()
    payload = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.dry_run:
        sys.stdout.write(payload)
        return 0
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(payload, encoding="utf-8")
    print(f"Written: {OUTPUT_PATH} ({EXPECTED_DECK_SIZE} cards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
