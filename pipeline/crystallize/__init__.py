"""pipeline.crystallize — operator-facing batch ideation over the compound_seed engine.

The Crystallization workflow generates N candidate compound seeds from a problem
+ themes, scores each, matches each against the 294-film corpus for real-world
comps, applies the C001-C007 GREATNESS_CHECKLIST rubric, clusters them into the
8 thematic clusters that already exist in the engine, and surfaces everything
through a terminal table + standalone offline HTML "crystal board".

Maps onto the wikibook "Crystallization of the Idea" framework:
    Stage 1: Where to Start — operator types --problem + --themes
    Stage 2: Realm of Chance — engine samples N candidates from 19.2T space
    Stage 3: Inventor's Tools — (v2) force-pin dimensions + re-roll
    Stage 4: Expanding the Toolbox — (v2) mutate / crossover variations
    Stage 5: Crystallization — operator picks a winner; hand-off to /single-idea

MUST NOT import LLM clients (ADR-0002 in spirit — keep this module offline-resilient).
MUST NOT import from frameworks/ (ANOMALY-002).
"""

from __future__ import annotations

__all__: list[str] = []
