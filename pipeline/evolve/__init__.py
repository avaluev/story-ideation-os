"""pipeline.evolve -- v5.0 single-pass evolutionary search (ADR-0012).

The v5 orchestrator that runs:

  Base-N -> Python operators (mental_models) -> [LLM operators (Day 4)]
         -> revenue projection -> crystallization score -> diversity-floor select.

See :mod:`pipeline.evolve.one_shot` for the public entry point.

No multi-generation loop in v5.0 -- that ships in v5.1 if (and only if) the
single-pass plateaus on real eval evidence.
"""

from pipeline.evolve.one_shot import ExploreResult, ScoredCandidate, explore_and_select

__all__ = ["ExploreResult", "ScoredCandidate", "explore_and_select"]
