"""pipeline/research/health.py — Per-run gateway budget/health cache.

Tracks which gateways are alive or dead for the current run.  A gateway that
raises ``BudgetExceeded`` (HTTP 402) is marked dead-for-run and skipped by
:func:`next_live_route` so callers transparently fall through to the next
entry in the route table.

State is persisted to ``data/research_health.json`` via
``pipeline.state.safe_write`` (ADR-0001: cross-boundary state on disk).

Public API
----------
mark_dead(gateway_name)
    Record that *gateway_name* exhausted its quota for this run.

is_dead(gateway_name) -> bool
    Return True if *gateway_name* has been marked dead.

next_live_route(routes) -> Route | None
    Walk *routes* in order and return the first :class:`Route` whose
    ``gateway_name`` is not dead.  Returns None when all routes are dead.

load() -> GatewayHealth
    Load the persisted health state from disk (or return a fresh empty state).

persist(state)
    Atomically write *state* to disk via ``pipeline.state.safe_write``.

reset()
    Clear the in-memory dead set and delete the persisted file.

Design notes
------------
- The in-memory dead set is module-level so all callers within one process
  share the same view without passing a health object around.
- ``persist`` / ``load`` keep the state durable across sub-process boundaries
  (e.g. research agents spawned as subprocesses).
- Thread-safety: a ``threading.Lock`` guards the in-memory set.

ADR-0001: state written via ``pipeline.state.safe_write``.
ADR-0007: this module is pure orchestration — no HTTP.
ADR-0005: MUST NOT import from ``frameworks/``.
ANOMALY-001: MUST NOT import ``httpx``, ``anthropic``, ``openrouter_client``,
  or ``pipeline.run``.
ANOMALY-003: imported by ``pipeline.research.__init__`` — orphan gate stays green.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from pipeline.research.routes import Capability, Route, RouteTable, default_route_table

logger = logging.getLogger(__name__)

# ── Persisted state path ───────────────────────────────────────────────────────

_HEALTH_PATH: Path = Path("data") / "research_health.json"
"""Default path for the persisted health state file."""


# ── In-memory dead set ─────────────────────────────────────────────────────────

_lock: threading.Lock = threading.Lock()
_dead_gateways: set[str] = set()


# ── Health state dataclass ─────────────────────────────────────────────────────


def _empty_str_set() -> set[str]:
    """Typed empty set factory for :class:`GatewayHealth`."""
    return set()


@dataclass
class GatewayHealth:
    """Snapshot of which gateways are currently dead.

    Attributes
    ----------
    dead:
        Set of gateway-name strings that have been marked dead for this run.
    """

    dead: set[str] = field(default_factory=_empty_str_set)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        return {"dead": sorted(self.dead)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GatewayHealth:
        """Deserialise from a dict (as produced by :meth:`to_dict`).

        Args:
            data: Dict with an optional ``"dead"`` key containing a list of
                  gateway-name strings.

        Returns:
            A :class:`GatewayHealth` instance.
        """
        dead_raw: Any = data.get("dead", [])
        dead: set[str] = set(cast("list[str]", dead_raw)) if isinstance(dead_raw, list) else set()
        return cls(dead=dead)


# ── Public API ────────────────────────────────────────────────────────────────


def mark_dead(gateway_name: str) -> None:
    """Mark *gateway_name* as dead for the current run.

    The update is reflected immediately in the in-memory set and persisted to
    ``data/research_health.json`` via ``pipeline.state.safe_write``.

    Args:
        gateway_name: The gateway name string from :class:`~pipeline.research.routes.Route`.
    """
    with _lock:
        _dead_gateways.add(gateway_name)
    logger.warning("health: gateway %r marked dead-for-run (BudgetExceeded)", gateway_name)
    _persist_locked()


def is_dead(gateway_name: str) -> bool:
    """Return True if *gateway_name* has been marked dead this run.

    Args:
        gateway_name: The gateway name to query.

    Returns:
        ``True`` when the gateway is in the dead set; ``False`` otherwise.
    """
    with _lock:
        return gateway_name in _dead_gateways


def next_live_route(routes: list[Route]) -> Route | None:
    """Return the first :class:`Route` in *routes* whose gateway is not dead.

    Iterates *routes* in order, skipping any whose ``gateway_name`` is in the
    dead set.  Logs each skipped entry at DEBUG level.

    Args:
        routes: Ordered list of :class:`~pipeline.research.routes.Route` entries.

    Returns:
        The first live :class:`Route`, or ``None`` when all are dead.
    """
    with _lock:
        dead_snapshot = frozenset(_dead_gateways)

    for route in routes:
        if route.gateway_name not in dead_snapshot:
            return route
        logger.debug(
            "health: skipping dead gateway %r (capability=%s)",
            route.gateway_name,
            route.capability,
        )
    logger.warning(
        "health: all %d route(s) for capability=%s are dead",
        len(routes),
        routes[0].capability if routes else "unknown",
    )
    return None


def live_routes_for(
    capability: Capability,
    *,
    table: RouteTable | None = None,
) -> list[Route]:
    """Return all live (non-dead) routes for *capability* from *table*.

    Convenience wrapper over :func:`next_live_route` that returns the full
    live list rather than just the first entry.

    Args:
        capability: The capability to query.
        table: Route table to use; defaults to :func:`default_route_table`.

    Returns:
        Ordered list of live :class:`Route` entries (may be empty).
    """
    rt = table if table is not None else default_route_table()
    all_routes = rt.for_capability(capability)
    with _lock:
        dead_snapshot = frozenset(_dead_gateways)
    return [r for r in all_routes if r.gateway_name not in dead_snapshot]


def load(path: Path | None = None) -> GatewayHealth:
    """Load persisted health state from *path* (default ``data/research_health.json``).

    Returns a fresh empty :class:`GatewayHealth` when the file does not exist
    or contains invalid JSON — never raises on I/O or parse errors.

    Args:
        path: Override for the default health file path.

    Returns:
        :class:`GatewayHealth` reflecting the persisted dead set.
    """
    target = path or _HEALTH_PATH
    try:
        text = Path(target).read_text(encoding="utf-8")
        raw: Any = json.loads(text)
        if not isinstance(raw, dict):
            return GatewayHealth()
        data: dict[str, Any] = cast("dict[str, Any]", raw)
        return GatewayHealth.from_dict(data)
    except FileNotFoundError:
        return GatewayHealth()
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("health.load: could not read %s — %s", target, exc)
        return GatewayHealth()


def persist(state: GatewayHealth, path: Path | None = None) -> None:
    """Atomically write *state* to *path* via ``pipeline.state.safe_write``.

    Args:
        state: The :class:`GatewayHealth` snapshot to persist.
        path:  Override for the default health file path.
    """
    from pipeline.state import safe_write  # noqa: PLC0415

    target = path or _HEALTH_PATH
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_write(target, json.dumps(state.to_dict(), indent=2))
    logger.debug("health.persist: wrote %s (dead=%s)", target, state.dead)


def reset(path: Path | None = None) -> None:
    """Clear the in-memory dead set and delete the persisted file.

    Safe to call when no file exists.

    Args:
        path: Override for the default health file path.
    """
    with _lock:
        _dead_gateways.clear()
    target = Path(path or _HEALTH_PATH)
    try:
        target.unlink()
        logger.debug("health.reset: deleted %s", target)
    except FileNotFoundError:
        pass


# ── Internal helper ───────────────────────────────────────────────────────────


def _persist_locked() -> None:
    """Persist the current in-memory dead set without holding the lock.

    Called after ``_lock`` has already been released by the caller.
    """
    with _lock:
        dead_snapshot = frozenset(_dead_gateways)
    persist(GatewayHealth(dead=set(dead_snapshot)))


__all__ = [
    "GatewayHealth",
    "is_dead",
    "live_routes_for",
    "load",
    "mark_dead",
    "next_live_route",
    "persist",
    "reset",
]
