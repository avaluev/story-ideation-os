"""GoT Improve operator stub.

Applies an improvement pass to each thought in the list.
Body ships in Phase 7 (GOT-03).

MUST NOT import from frameworks/ (ADR-0005, ANOMALY-002).
"""

from __future__ import annotations

from pipeline.operators.base import Operator


class Improve:
    """GoT Improve operator. Refines each thought. Body in Phase 7."""

    def __call__(self, thoughts: list[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError("Improve body ships in Phase 7 (GOT-03)")


# Structural conformance check (caught by pyright, not at runtime)
_: Operator = Improve()
del _
