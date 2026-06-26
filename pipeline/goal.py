"""pipeline.goal -- operator's taste contract (config/goal.json).

WEDGE Step 3 of the plan. The Goal object replaces hardcoded constants
in ``pipeline/crystallize/score.py`` so the operator can edit one JSON
file and watch the leaderboard reshuffle without touching code.

Why this exists
===============

Pre-Step-3, ``pipeline/crystallize/score.py:32-37`` hardcoded six
weights (``_W_GENIUS=0.30, _W_SOM=0.09, ...``). The operator's stated
goal -- "big SAM x unique x revenue-feasible" -- was not represented
in any code object. ``operator_rating`` in ``data/leaderboard.csv``
was a dead column with no reader.

Post-Step-3, ``config/goal.json`` is the single contract. ``Goal`` is
a frozen dataclass loaded by ``crystallize.score.crystallization_score``
when its optional ``goal`` kwarg is supplied; otherwise the v4 hardcoded
constants apply (preserves all pre-Step-3 tests).

Every ``goal.save()`` bumps ``goal_id`` and appends to
``data/goal_history.jsonl`` via ``pipeline.state.safe_write`` /
``append_jsonl`` (ADR-0001). Each ``/evolve`` run will record the
active ``goal_sha`` in its winners.json sidecar so any concept's score
is reproducible against the exact weight vector that produced it.

Constraints
===========

- MUST NOT import from ``pipeline/scoring.py`` (ADR-0002 enforces math
  boundary). ``Goal`` is data only; the math stays in score.py.
- MUST NOT import LLM clients (ANOMALY-001).
- Weights must sum to 1.0 (validated at load); if a future facet is
  added (e.g. Step 5 ``operator_alignment``), the existing weights are
  re-normalised at load to keep the sum invariant -- a forward-
  compatible schema bump rather than a hard break.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pipeline.state import append_jsonl, safe_write

DEFAULT_GOAL_PATH: Final[Path] = Path("config/goal.json")
DEFAULT_GOAL_HISTORY_PATH: Final[Path] = Path("data/goal_history.jsonl")

_WEIGHT_SUM_TOLERANCE: Final[float] = 1e-3

# v4 (pre-Step-3) hardcoded weights -- the fallback returned by
# ``Goal.default()`` when no config/goal.json exists. Mirrors
# crystallize/score.py constants verbatim so behaviour is identical
# to the pre-WEDGE state.
_V4_DEFAULT_WEIGHTS: Final[dict[str, float]] = {
    "genius": 0.30,
    "goldilocks": 0.18,
    "cluster_coherence": 0.17,
    "emotional_universality": 0.13,
    "som_y1": 0.09,
    "derivative_distance": 0.13,
    "standalone_ip": 0.0,
}

#: Operator-tunable v4 defaults, shared by Goal.default and Goal.load so the fallback
#: values live in exactly one place (audit DRY fix).
_DEFAULT_REVENUE_FLOOR_USD: Final[float] = 200_000_000.0
_DEFAULT_SAM_AMBITION_USD: Final[float] = 2_000_000_000.0
_DEFAULT_NOVELTY_FLOOR: Final[float] = 0.55
_DEFAULT_TARGET_SCORE: Final[float] = 0.75


@dataclass(frozen=True)
class VetoedAttractor:
    """One ``(mf_id, de_id, sdt_id)`` triple the operator has flagged as
    'never sample this combination again' (Step 5+ veto loop)."""

    mf_id: str
    de_id: str
    sdt_id: str
    reason: str = ""


@dataclass(frozen=True)
class Goal:
    """Operator's taste contract. Frozen so callers can't mutate in place;
    use :meth:`with_overrides` to derive a runtime variant for a single
    loop iteration."""

    schema_version: int
    goal_id: str
    created_at: str
    definition: str
    revenue_floor_usd: float
    sam_ambition_usd: float
    novelty_floor: float
    target_score: float
    facet_weights: dict[str, float]
    gates: dict[str, Any]
    vetoed_attractors: tuple[VetoedAttractor, ...] = field(default_factory=tuple)
    notes: str = ""

    @classmethod
    def default(cls) -> Goal:
        """Return a Goal carrying the pre-Step-3 hardcoded v4 weights and
        operator-stated defaults. Used as the canonical fallback when no
        config/goal.json exists yet."""
        return cls(
            schema_version=1,
            goal_id="default_v4",
            created_at=_now_iso(),
            definition="v4 fallback -- hardcoded weights, no operator goal yet",
            revenue_floor_usd=_DEFAULT_REVENUE_FLOOR_USD,
            sam_ambition_usd=_DEFAULT_SAM_AMBITION_USD,
            novelty_floor=_DEFAULT_NOVELTY_FLOOR,
            target_score=_DEFAULT_TARGET_SCORE,
            facet_weights=dict(_V4_DEFAULT_WEIGHTS),
            gates={
                "som_y1_usd_min": 150_000_000,
                "passes_genius_gate": True,
                "max_corpus_axis_overlap": 2,
            },
            vetoed_attractors=(),
            notes="",
        )

    @classmethod
    def load(cls, path: Path | str = DEFAULT_GOAL_PATH) -> Goal:
        """Load and validate a Goal from JSON. Returns :meth:`default` when
        the file does not exist (forward-compatible: pipelines that ship
        before the operator creates a goal.json keep working)."""
        p = Path(path)
        if not p.exists():
            return cls.default()
        raw = json.loads(p.read_text())
        weights = dict(raw.get("facet_weights", _V4_DEFAULT_WEIGHTS))
        # Validate weights are positive and sum to ~1.0 (tolerant of float drift).
        if any(w < 0 for w in weights.values()):
            raise ValueError(
                f"Goal {raw.get('goal_id')!r}: facet_weights contains negative value(s): {weights}"
            )
        total = sum(weights.values())
        if total <= 0:
            raise ValueError(
                f"Goal {raw.get('goal_id')!r}: facet_weights sum to {total} "
                "(must be positive) — cannot normalise."
            )
        if not _is_close(total, 1.0):
            # Auto-normalise rather than reject -- forward-compatible with
            # Step 5 adding operator_alignment as a 7th facet.
            weights = {k: v / total for k, v in weights.items()}
        vetoes_raw: list[dict[str, Any]] = list(raw.get("vetoed_attractors", []))
        vetoes = tuple(
            VetoedAttractor(
                mf_id=str(v.get("mf_id", "")),
                de_id=str(v.get("de_id", "")),
                sdt_id=str(v.get("sdt_id", "")),
                reason=str(v.get("reason", "")),
            )
            for v in vetoes_raw
        )
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            goal_id=str(raw.get("goal_id", "unknown")),
            created_at=str(raw.get("created_at", _now_iso())),
            definition=str(raw.get("definition", "")),
            revenue_floor_usd=float(raw.get("revenue_floor_usd", _DEFAULT_REVENUE_FLOOR_USD)),
            sam_ambition_usd=float(raw.get("sam_ambition_usd", _DEFAULT_SAM_AMBITION_USD)),
            novelty_floor=float(raw.get("novelty_floor", _DEFAULT_NOVELTY_FLOOR)),
            target_score=float(raw.get("target_score", _DEFAULT_TARGET_SCORE)),
            facet_weights=weights,
            gates=dict(raw.get("gates", {})),
            vetoed_attractors=vetoes,
            notes=str(raw.get("notes", "")),
        )

    def save(
        self,
        path: Path | str = DEFAULT_GOAL_PATH,
        history_path: Path | str = DEFAULT_GOAL_HISTORY_PATH,
    ) -> Goal:
        """Persist this Goal atomically (ADR-0001) and append a snapshot to
        ``data/goal_history.jsonl``. Returns the saved Goal with a bumped
        ``goal_id`` and refreshed ``created_at`` -- callers should use
        the returned object so the in-memory copy matches disk."""
        new_id = _next_goal_id(self.goal_id)
        bumped = replace(self, goal_id=new_id, created_at=_now_iso())
        payload = json.dumps(bumped.to_dict(), indent=2, ensure_ascii=False) + "\n"
        safe_write(Path(path), payload)
        append_jsonl(
            Path(history_path),
            {"ts": bumped.created_at, "goal_id": bumped.goal_id, "sha": bumped.sha},
        )
        return bumped

    def to_dict(self) -> dict[str, Any]:
        """Plain dict suitable for ``json.dumps``. Vetoed attractors flatten
        from frozen dataclass to dict."""
        d = asdict(self)
        d["vetoed_attractors"] = [asdict(v) for v in self.vetoed_attractors]
        return d

    @property
    def sha(self) -> str:
        """Stable 12-char SHA-256 of the *scoring contract* only.

        Hashes facet_weights + gates + floors + schema_version +
        vetoed_attractors and EXCLUDES ``goal_id``, ``created_at``, ``definition``
        and ``notes``. Consequences (all intended):

        * re-saving an unchanged contract yields the same sha -> the front door
          can dedupe and skip a no-op ``goal_history`` row;
        * two goals with identical weights share a sha regardless of name or
          timestamp -> reproducible winners.json provenance keyed on the contract;
        * editing prose/lineage alone does NOT churn the sha.
        """
        contract = {
            "schema_version": self.schema_version,
            "facet_weights": self.facet_weights,
            "gates": self.gates,
            "revenue_floor_usd": self.revenue_floor_usd,
            "sam_ambition_usd": self.sam_ambition_usd,
            "novelty_floor": self.novelty_floor,
            "target_score": self.target_score,
            "vetoed_attractors": [asdict(v) for v in self.vetoed_attractors],
        }
        canonical = json.dumps(contract, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def with_overrides(self, **kwargs: Any) -> Goal:  # noqa: ANN401 -- dataclass.replace passes through arbitrary field values
        """Return a copy with ``kwargs`` overridden. Used by Step 6 loop
        when plateau detection triggers temperature bump / theme rotation
        -- the runtime Goal differs from the persisted one for that one
        iteration, but the persisted goal_id is preserved so the score
        provenance still points at the operator's chosen baseline."""
        return replace(self, **kwargs)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_goal_id(current: str) -> str:
    """Bump a goal_id to its next version.

    Convention: ``<slug>_v<N>`` -> ``<slug>_v<N+1>``. If the current id
    doesn't match the pattern, append ``_v2`` so the first save creates
    a clear lineage.
    """
    if "_v" in current:
        slug, _, ver = current.rpartition("_v")
        try:
            return f"{slug}_v{int(ver) + 1}"
        except ValueError:
            pass
    return f"{current}_v2"


def _is_close(a: float, b: float, tol: float = _WEIGHT_SUM_TOLERANCE) -> bool:
    return abs(a - b) <= tol


# --------------------------------------------------------------------------- #
# Front door CLI: ``python -m pipeline.goal show|validate|set|diff``.
# The SINGLE lineage-preserving write path for config/goal.json. Deterministic;
# no LLM client (ANOMALY-001). `set` loads the LIVE config first, so every new
# goal_history row carries the active lineage (kills the stale default_v5 rows),
# and writes a weight-only sha. It WARNs-then-normalises a non-unit sum (matching
# Goal.load's forward-compat contract) -- it never silently swallows drift and
# never rejects on sum (only on a negative weight, like load).
# --------------------------------------------------------------------------- #

logger = logging.getLogger("pipeline.goal")

#: Scalar floor fields a ``set`` may override.
_FLOOR_FIELDS: Final[frozenset[str]] = frozenset(
    {"revenue_floor_usd", "sam_ambition_usd", "novelty_floor", "target_score"}
)

#: Hard-gate fields a ``set`` may override (numeric thresholds in goal.gates).
#: Any key that is neither a floor nor a gate is treated as a facet weight.
_GATE_FIELDS: Final[frozenset[str]] = frozenset({"som_y1_usd_min", "max_corpus_axis_overlap"})


def _fmt_goal(g: Goal) -> str:
    lines = [
        f"goal_id:    {g.goal_id}",
        f"sha:        {g.sha}  (weight-only)",
        f"definition: {g.definition}",
        f"floors:     revenue={g.revenue_floor_usd:,.0f}  sam={g.sam_ambition_usd:,.0f}  "
        f"novelty={g.novelty_floor}  target={g.target_score}",
        "facet_weights:",
    ]
    lines.extend(f"  {k:<24} {v:.4f}" for k, v in g.facet_weights.items())
    lines.append(f"  {'(sum)':<24} {sum(g.facet_weights.values()):.4f}")
    return "\n".join(lines)


def _cmd_show(config: Path) -> int:
    print(_fmt_goal(Goal.load(config)))
    return 0


def _cmd_validate(config: Path) -> int:
    if not config.exists():
        logger.error("config not found: %s", config)
        return 2
    raw = json.loads(config.read_text())
    weights = dict(raw.get("facet_weights", {}))
    total = sum(weights.values()) if weights else 0.0
    try:
        g = Goal.load(config)
    except ValueError as exc:
        logger.error("INVALID: %s", exc)
        return 1
    if weights and not _is_close(total, 1.0):
        logger.warning(
            "facet_weights sum to %.4f (not 1.0) -- auto-normalised on load "
            "(forward-compat contract, goal.py:152-155).",
            total,
        )
    print(f"VALID: goal_id={g.goal_id} sha={g.sha}")
    print(_fmt_goal(g))
    return 0


def _parse_assignments(
    assignments: list[str],
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]] | None:
    """Split ``facet=value`` pairs into (facet_weights, floors, gates) overrides.

    Gate thresholds are integer-normalised when whole (the gates block is
    integer-valued in config/goal.json). Returns None on a malformed pair.
    """
    facet_overrides: dict[str, float] = {}
    floor_overrides: dict[str, float] = {}
    gate_overrides: dict[str, Any] = {}
    for kv in assignments:
        key, sep, val = kv.partition("=")
        key, val = key.strip(), val.strip()
        if not sep or not key or not val:
            logger.error("bad assignment %r -- expected facet=value", kv)
            return None
        try:
            num = float(val)
        except ValueError:
            logger.error("bad value in %r -- expected a number", kv)
            return None
        if key in _FLOOR_FIELDS:
            floor_overrides[key] = num
        elif key in _GATE_FIELDS:
            gate_overrides[key] = int(num) if num.is_integer() else num
        else:
            facet_overrides[key] = num
    return facet_overrides, floor_overrides, gate_overrides


def _cmd_set(config: Path, history: Path, assignments: list[str]) -> int:
    parsed = _parse_assignments(assignments)
    if parsed is None:
        return 2
    facet_overrides, floor_overrides, gate_overrides = parsed
    live = Goal.load(config)  # LIVE config -> lineage preserved on save()
    new_weights = {**live.facet_weights, **facet_overrides}
    if any(w < 0 for w in new_weights.values()):
        logger.error("REJECT: a facet weight is negative: %s", new_weights)
        return 1
    total = sum(new_weights.values())
    if total <= 0:
        logger.error("REJECT: facet weights sum to %s (must be positive)", total)
        return 1
    if not _is_close(total, 1.0):
        logger.warning(
            "weights sum to %.4f -- auto-normalising (forward-compat contract, "
            "NOT rejecting). Supply weights summing to 1.0 to avoid this.",
            total,
        )
        new_weights = {k: v / total for k, v in new_weights.items()}
    new_gates = {**live.gates, **gate_overrides} if gate_overrides else live.gates
    candidate = replace(live, facet_weights=new_weights, gates=new_gates, **floor_overrides)
    if candidate.sha == live.sha:
        print(f"no change: scoring contract unchanged (sha {live.sha}); not writing.")
        return 0
    saved = candidate.save(path=config, history_path=history)
    print(f"updated: {live.goal_id} -> {saved.goal_id}   sha {live.sha} -> {saved.sha}")
    print(_fmt_goal(saved))
    return 0


def _cmd_diff(path_a: Path, path_b: Path) -> int:
    ga = Goal.load(path_a)
    gb = Goal.load(path_b)
    print(f"diff  A={path_a} ({ga.goal_id})  ->  B={path_b} ({gb.goal_id})")
    print("facet_weights:")
    for k in sorted(set(ga.facet_weights) | set(gb.facet_weights)):
        va = ga.facet_weights.get(k, 0.0)
        vb = gb.facet_weights.get(k, 0.0)
        flag = "" if _is_close(va, vb) else "  <-- changed"
        print(f"  {k:<24} {va:.4f} -> {vb:.4f}{flag}")
    print("floors:")
    for fld in ("revenue_floor_usd", "sam_ambition_usd", "novelty_floor", "target_score"):
        va = getattr(ga, fld)
        vb = getattr(gb, fld)
        flag = "" if va == vb else "  <-- changed"
        print(f"  {fld:<24} {va} -> {vb}{flag}")
    same = "same" if ga.sha == gb.sha else "DIFFERENT"
    print(f"sha:  {ga.sha} -> {gb.sha}  ({same})")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        prog="pipeline.goal",
        description="Operator taste-contract front door (lineage-preserving, weight-only sha).",
    )
    parser.add_argument("--config", default=str(DEFAULT_GOAL_PATH), help="path to goal.json")
    parser.add_argument(
        "--history", default=str(DEFAULT_GOAL_HISTORY_PATH), help="path to goal_history.jsonl"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print the live taste contract")
    sub.add_parser("validate", help="validate the live contract (warns loudly on a non-unit sum)")
    sp_set = sub.add_parser("set", help="override facet weights / floors (lineage-preserving)")
    sp_set.add_argument("assignments", nargs="+", metavar="facet=value")
    sp_diff = sub.add_parser("diff", help="diff two goal files")
    sp_diff.add_argument("a", metavar="A.json")
    sp_diff.add_argument("b", metavar="B.json")
    args = parser.parse_args(argv)

    config = Path(args.config)
    history = Path(args.history)
    if args.cmd == "show":
        return _cmd_show(config)
    if args.cmd == "validate":
        return _cmd_validate(config)
    if args.cmd == "set":
        return _cmd_set(config, history, args.assignments)
    if args.cmd == "diff":
        return _cmd_diff(Path(args.a), Path(args.b))
    return 2  # pragma: no cover -- argparse 'required=True' prevents this


__all__ = [
    "DEFAULT_GOAL_HISTORY_PATH",
    "DEFAULT_GOAL_PATH",
    "Goal",
    "VetoedAttractor",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
