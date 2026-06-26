"""GoT Operator structural Protocol (PIPE-12).

Defines the single abstract interface that all Graph-of-Thought operators
must satisfy. Uses typing.Protocol with @runtime_checkable so that
isinstance(op, Operator) works in tests without class inheritance.

MUST NOT import from frameworks/ (ADR-0005, ANOMALY-002).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Operator(Protocol):
    """Structural protocol for GoT operators.

    All GoT operators must implement __call__(thoughts) -> thoughts.
    No class hierarchy required (PIPE-12) — structural duck typing only.
    Bodies ship in Phase 7 (GOT-01..05).
    """

    def __call__(self, thoughts: list[dict[str, object]]) -> list[dict[str, object]]:
        """Transform a list of thought dicts and return the updated list."""
        ...
