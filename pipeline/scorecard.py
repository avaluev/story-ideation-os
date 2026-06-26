"""Runtime scorecard composer (Cycle 1 NB.5).

Wires :mod:`pipeline.axes.character_depth` (NB.4) into the 5-vector gating
decision and is the generic substrate for every future axis. Composition is
**additive** (anti-overengineering rule #2): each fired rule contributes a
``weight_delta`` and/or ``threshold_delta`` on top of the base scorecard.

Rules are *data*, not code (HANDOFF_SESSION_3 §"ANTI-PATTERNS BANNED"):

- No hardcoded format taxonomy — predicates compare measured attributes only
  (e.g. ``cast_size_principal <= 2``), never category labels.
- No silent feature flags — every code path is reachable.
- Rules are emitted by ``scripts/discover_axis_rules.ipynb`` from the S4
  Tier-1 archetype-by-success parquet, never authored by hand. Cycle 1 ships
  with an *empty* ``data/axis_selection_rules.jsonl``; the composer is
  generic and ready for rule emission.

The 5-vector roll-up follows the master plan §"Desired Quality":

    overall_pass = all(vector_pass[q] is not False for q in Q1..Q5)
    vector_pass[q] = min(axis_pass for axes in q) — None when q has no axes

Threshold semantics: defaults in ``BASE_AXIS_THRESHOLDS`` are Cycle-1
placeholders (40th-percentile heuristic). They are designed to be overridden
by ``data/calibration/thresholds.jsonl`` once S0 lands; until then a single
constant per axis is acceptable per anti-overengineering rule #2.

ADR-0001: composer is pure-Python; no I/O at compose time. ``load_rules``
reads disk explicitly when invoked.
ADR-0002: numeric scoring lives here, not in any LLM prompt.
ADR-0005: composer must not import from ``frameworks/``.
ADR-0007: composer does not call any model.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.axes import agency_ratio, character_depth

_log = logging.getLogger(__name__)

# ── Cycle-1 base scorecard ────────────────────────────────────────────────────

# Weight per axis; rules add ``weight_delta`` on top. Sum-to-1 normalization is
# applied at compose time AFTER all deltas fold in.
BASE_AXIS_WEIGHTS: dict[str, float] = {
    "character_depth": 1.0,
    "agency_ratio": 1.0,
}

# Pass threshold per axis. axis_score >= threshold → axis_pass=True.
# Cycle 1 placeholder; overridden by data/calibration/thresholds.jsonl when S0 lands.
# agency_ratio: 0.50 → CIE Agency Ratio ≥ 1.0 (active ≥ passive); the spec's
# canonical >2.0 threshold maps to score 1.0.
BASE_AXIS_THRESHOLDS: dict[str, float] = {
    "character_depth": 0.50,
    "agency_ratio": 0.50,
}

# Which Qi each axis belongs to. See master plan §"Desired Quality — 5-Vector".
AXIS_TO_VECTOR: dict[str, str] = {
    "character_depth": "Q2",  # Critical Merit
    "agency_ratio": "Q2",  # Critical Merit — second Q2 axis (S4.3)
}

_ALL_VECTORS: tuple[str, ...] = ("Q1", "Q2", "Q3", "Q4", "Q5")

# Predicate operator parsing: ``"<=2"``, ``">=0.6"``, ``"<7"``, ``">0.5"``,
# ``"==human"``. Anything without a prefix is treated as equality.
_PREDICATE_RE = re.compile(r"^(?P<op><=|>=|==|<|>)(?P<val>.+)$")


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rule:
    """One IF-THEN rule emitted by the discovery notebook.

    Fields:
        rule_id: stable identifier (e.g. ``"RX-001"``).
        if_: predicate dict keyed on attribute name; value is either a raw
            scalar (equality) or a stringified comparison (``"<=2"``, ``">=0.6"``).
        then_: ``{"axes": {axis_id: {"weight_delta": float,
            "threshold_delta": float}}}``. Missing keys default to 0.
        evidence_id: parquet row reference (e.g. ``"parq:archetype_success#rows[12,17]"``).
        method: statistical test name (e.g. ``"GBDT+SHAP N=23"``).
    """

    rule_id: str
    if_: dict[str, Any]
    then_: dict[str, dict[str, Any]]
    evidence_id: str
    method: str


@dataclass(frozen=True)
class Scorecard:
    """Per-concept scorecard after rule composition.

    Frozen — composer cannot leak mutable state to the caller.
    """

    axis_weights: dict[str, float]
    axis_thresholds: dict[str, float]
    axis_to_vector: dict[str, str]
    fired_rules: tuple[str, ...]


def _empty_evidence() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class EvalResult:
    """Per-concept evaluation result against a Scorecard."""

    axis_scores: dict[str, float]
    axis_pass: dict[str, bool]
    vector_pass: dict[str, bool | None]
    overall_pass: bool
    fired_rules: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=_empty_evidence)


# ── Predicate matching ────────────────────────────────────────────────────────


def _coerce_number(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _compare(op: str, lhs: float, rhs: float) -> bool:
    if op == "<=":
        return lhs <= rhs
    if op == ">=":
        return lhs >= rhs
    if op == "<":
        return lhs < rhs
    if op == ">":
        return lhs > rhs
    return lhs == rhs  # "==", final fallthrough


def _predicate_matches_one(spec: object, value: object) -> bool:
    """Return True if ``value`` satisfies ``spec``.

    ``spec`` may be a stringified operator+number (``"<=2"``), a list (membership),
    or a raw scalar (equality). Heterogeneous input is unavoidable here because
    rule predicates come from JSONL data, not Python code — ``object`` is the
    pyright-friendly stand-in for "JSON scalar or container".
    """
    if isinstance(spec, list):
        return value in spec
    if not isinstance(spec, str):
        return value == spec
    m = _PREDICATE_RE.match(spec)
    if m is None:
        return value == spec
    op = m.group("op")
    rhs_raw = m.group("val")
    rhs_num = _coerce_number(rhs_raw)
    if rhs_num is not None and isinstance(value, int | float):
        return _compare(op, float(value), rhs_num)
    if op == "==":
        return str(value) == rhs_raw
    return False


def _rule_matches(rule: Rule, attrs: dict[str, Any]) -> bool:
    """All predicates in ``rule.if_`` must match; missing attributes never match."""
    for key, spec in rule.if_.items():
        if key not in attrs:
            return False
        if not _predicate_matches_one(spec, attrs[key]):
            return False
    return True


# ── Public surface ────────────────────────────────────────────────────────────


def load_rules(path: Path | str) -> list[Rule]:
    """Load a JSONL rules file. Empty / missing file → empty list."""
    p = Path(path)
    if not p.exists():
        return []
    rules: list[Rule] = []
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            _log.warning("Skipping malformed rule line in %s: %s", p, exc)
            continue
        try:
            rules.append(
                Rule(
                    rule_id=str(row["rule_id"]),
                    if_=dict(row.get("if", {})),
                    then_=dict(row.get("then", {})),
                    evidence_id=str(row.get("evidence_id", "")),
                    method=str(row.get("method", "")),
                )
            )
        except (KeyError, TypeError) as exc:
            _log.warning("Skipping invalid rule row in %s: %s", p, exc)
    return rules


def compose(attrs: dict[str, Any], rules: list[Rule]) -> Scorecard:
    """Apply all matching rules to the base scorecard.

    Args:
        attrs: measured concept attributes (e.g. ``cast_size_principal``).
            Never contains category labels.
        rules: rule list, typically from :func:`load_rules`.

    Returns:
        Frozen :class:`Scorecard` with merged weights, thresholds, and
        the rule-IDs that fired.
    """
    weights = dict(BASE_AXIS_WEIGHTS)
    thresholds = dict(BASE_AXIS_THRESHOLDS)
    fired: list[str] = []

    for rule in rules:
        if not _rule_matches(rule, attrs):
            continue
        fired.append(rule.rule_id)
        for axis_id, deltas in rule.then_.get("axes", {}).items():
            if axis_id not in BASE_AXIS_WEIGHTS:
                # Cycle-1 axes are explicitly allowlisted; rules referencing
                # not-yet-implemented axes are tolerated (forward-compat) but
                # produce no effect until that axis ships.
                continue
            w_delta = float(deltas.get("weight_delta", 0.0))
            t_delta = float(deltas.get("threshold_delta", 0.0))
            if w_delta:
                weights[axis_id] = weights.get(axis_id, 0.0) + w_delta
            if t_delta:
                thresholds[axis_id] = thresholds.get(axis_id, 0.0) + t_delta

    return Scorecard(
        axis_weights=weights,
        axis_thresholds=thresholds,
        axis_to_vector=dict(AXIS_TO_VECTOR),
        fired_rules=tuple(fired),
    )


def _axis_score(axis_id: str, concept: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Dispatch to the wired axis module. Add new axes here as they land."""
    if axis_id == "character_depth":
        return character_depth.score(concept)
    if axis_id == "agency_ratio":
        return agency_ratio.score(concept)
    raise KeyError(f"unknown axis_id: {axis_id!r}")


def evaluate(concept: dict[str, Any], scorecard_obj: Scorecard) -> EvalResult:
    """Run every axis in ``scorecard_obj`` against ``concept`` and roll up to 5 vectors.

    Roll-up rule (per master plan §"Desired Quality — 5-Vector Construct"):
        ``vector_pass[q] = min(axis_pass for axes mapped to q)``
        — ``None`` if no axes are mapped to that vector yet.

    Overall pass: ``True`` iff no measured vector_pass is False. Unmeasured
    vectors (``None``) do not veto — they are silent until calibrated.
    """
    axis_scores: dict[str, float] = {}
    axis_pass: dict[str, bool] = {}
    evidence: dict[str, Any] = {}

    for axis_id in scorecard_obj.axis_weights:
        score_val, axis_evidence = _axis_score(axis_id, concept)
        axis_scores[axis_id] = float(score_val)
        threshold = scorecard_obj.axis_thresholds.get(axis_id, 0.5)
        axis_pass[axis_id] = float(score_val) >= float(threshold)
        evidence[axis_id] = axis_evidence

    vector_pass: dict[str, bool | None] = {q: None for q in _ALL_VECTORS}
    vector_buckets: dict[str, list[bool]] = {q: [] for q in _ALL_VECTORS}
    for axis_id, passed in axis_pass.items():
        q = scorecard_obj.axis_to_vector.get(axis_id)
        if q in vector_buckets:
            vector_buckets[q].append(passed)
    for q, bucket in vector_buckets.items():
        if bucket:
            vector_pass[q] = all(bucket)

    overall = all(v is not False for v in vector_pass.values())

    return EvalResult(
        axis_scores=axis_scores,
        axis_pass=axis_pass,
        vector_pass=vector_pass,
        overall_pass=overall,
        fired_rules=scorecard_obj.fired_rules,
        evidence=evidence,
    )


__all__ = [
    "AXIS_TO_VECTOR",
    "BASE_AXIS_THRESHOLDS",
    "BASE_AXIS_WEIGHTS",
    "EvalResult",
    "Rule",
    "Scorecard",
    "compose",
    "evaluate",
    "load_rules",
]
