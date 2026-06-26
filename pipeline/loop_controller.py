"""Loop controller for the v4 single-idea pipeline recursive loops.

Pure Python. No LLM imports. No network I/O. ADR-0009.

Public API:
  plateau_reached(history, delta_threshold, window) -> bool
  patch_budget(loop_id) -> int
"""

from __future__ import annotations

# ── Loop caps (ADR-0009) ──────────────────────────────────────────────────────

_BUDGETS: dict[str, int] = {
    "L1": 3,  # challenge <-> draft
    "L2": 5,  # amplification plateau
    "L3": 3,  # genius <-> draft
    "L4": 3,  # consistency <-> draft
    "L5": 2,  # narrator redo
}

# Minimum history length needed to evaluate a plateau window.
_MIN_HISTORY_FOR_PLATEAU: int = 2


def plateau_reached(
    history: list[float],
    delta_threshold: float = 0.05,
    window: int = 2,
) -> bool:
    """Return True when the last `window` consecutive relative deltas are all
    strictly below `delta_threshold`.

    A delta of exactly `delta_threshold` is NOT a plateau (strictly less than).
    Returns False when history has fewer than window+1 entries.
    """
    if len(history) < window + 1:
        return False

    for i in range(len(history) - window, len(history)):
        prev = history[i - 1]
        if prev == 0.0:
            continue
        delta = (history[i] - prev) / abs(prev)
        if delta >= delta_threshold:
            return False

    return True


def patch_budget(loop_id: str) -> int:
    """Return the maximum patch rounds allowed for the given loop ID.

    Accepts upper- or lower-case IDs (L1/l1).
    Raises KeyError for unknown loop IDs.
    """
    key = loop_id.upper()
    if key not in _BUDGETS:
        raise KeyError(f"Unknown loop ID {loop_id!r}. Valid: {sorted(_BUDGETS)}")
    return _BUDGETS[key]
