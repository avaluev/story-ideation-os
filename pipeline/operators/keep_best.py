"""GoT KeepBest operator stub.

Retains the highest-scoring thoughts from the current thought list.
Body ships in Phase 7 (GOT-02).

MUST NOT import from frameworks/ (ADR-0005, ANOMALY-002).
"""

from __future__ import annotations

from pipeline.operators.base import Operator


class KeepBest:
    """GoT KeepBest operator. Filters to top-K thoughts. Body in Phase 7."""

    def __call__(self, thoughts: list[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError("KeepBest body ships in Phase 7 (GOT-02)")


# Structural conformance check (caught by pyright, not at runtime)
_: Operator = KeepBest()
del _
