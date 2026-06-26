"""GoT Validate operator stub.

Filters out thoughts that fail hard constraints (schema, anti-slop, coherence).
Body ships in Phase 7 (GOT-04).

MUST NOT import from frameworks/ (ADR-0005, ANOMALY-002).
"""

from __future__ import annotations

from pipeline.operators.base import Operator


class Validate:
    """GoT Validate operator. Removes invalid thoughts. Body in Phase 7."""

    def __call__(self, thoughts: list[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError("Validate body ships in Phase 7 (GOT-04)")


# Structural conformance check (caught by pyright, not at runtime)
_: Operator = Validate()
del _
