"""GoT Score operator stub.

Ranks thoughts by calling pipeline.scoring functions; adds a score field to each.
Body ships in Phase 7 (GOT-05).

MUST NOT import from frameworks/ (ADR-0005, ANOMALY-002).
"""

from __future__ import annotations

from pipeline.operators.base import Operator


class Score:
    """GoT Score operator. Assigns numeric scores to thoughts. Body in Phase 7."""

    def __call__(self, thoughts: list[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError("Score body ships in Phase 7 (GOT-05)")


# Structural conformance check (caught by pyright, not at runtime)
_: Operator = Score()
del _
