"""Quality axes for the 5-vector scorecard (Cycle 1 NB.4+).

Each axis exports ``score(concept_dict) -> tuple[float, Evidence]`` where
``Evidence`` is a TypedDict-ish ``dict`` with at least ``signals: list[str]``.

Axes are pure-Python; no LLM, no network, no I/O. They consume already-extracted
attributes from the concept's structured sidecar (draft_v0.json) rather than
parsing freeform prose. Adding a new axis requires only:

1. ``pipeline/axes/<name>.py`` exporting ``score(...)`` + ``SIGNALS`` constant.
2. A row in ``data/axis_selection_rules.jsonl`` once NB.5 ships the composer.

ADR-0001 (state durability): axes only read; they never write.
ADR-0002 (LLMs no arithmetic): axes are the canonical place for numeric scoring.
ADR-0005 (frameworks read-only): axes may NOT import from ``frameworks/``.
"""

from __future__ import annotations

from pipeline.axes import character_depth

__all__ = ["character_depth"]
