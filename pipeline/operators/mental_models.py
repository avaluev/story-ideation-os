"""pipeline.operators.mental_models -- deterministic axis-mutators (ADR-0012).

The v4 engine samples each compound seed independently from the variable
pools.  Two ~equally-good seeds may differ on only one decorative axis,
and "ten ideas exploring the same problem" collapses into "the same idea
ten times with cosmetic permutations."

This module ships three pure-Python operators that take a finished
:class:`pipeline.compound_seed.CompoundSeedResult` and produce a small,
*directional* mutation set:

- :func:`scamper_substitute` -- round-robins through five core narrative
  axes and swaps each one to a *low-frequency* alternative (uses
  :mod:`pipeline.diversity` to prefer rare values).  Returns up to 5
  mutants.

- :func:`invert` -- flips ``structural_inversion`` via the pre-built
  :data:`INVERSION_PAIRS_PATH` table, and (when present) swaps the
  protagonist + antagonist archetype slots.  Returns up to 3 mutants.

- :func:`constraint_strip` -- removes one *decorative* axis per mutant
  (``conspiracy_engine``, ``reptile_trigger``, ``open_problem``,
  ``cultural_moment``, ``dark_archetype``) so the concept must stand on
  its core.  Returns up to 5 mutants.

Every mutant inherits its parent's ``scores`` (stale -- the orchestrator
in :mod:`pipeline.evolve.one_shot` recomputes them) and appends one
``"<operator>:<axis>"`` tag to ``lineage``.  This is how the orchestrator
attributes winning concepts back to the operator that produced them.

Pure Python.  No LLM.  No I/O except the one-shot load of
:data:`INVERSION_PAIRS_PATH` (cached at module import).  ADR-0001 +
ADR-0002 + ADR-0012.

MUST NOT be imported from ``pipeline/scoring.py`` (ANOMALY-001).
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, cast

from pipeline import diversity
from pipeline.compound_seed import CompoundSeedResult, CompoundVariables

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

INVERSION_PAIRS_PATH: Final[Path] = _REPO_ROOT / "pipeline" / "data" / "inversion_pairs.json"

# ---------------------------------------------------------------------------
# Axis -> pool name mapping
# ---------------------------------------------------------------------------

#: SCAMPER walks these five core narrative axes in order.  Each axis is
#: paired with the key into :class:`VariablePools` that holds its pool.
_SCAMPER_AXES: Final[tuple[tuple[str, str], ...]] = (
    ("protagonist_archetype", "protagonist_archetypes"),
    ("world_texture", "world_textures"),
    ("structural_inversion", "structural_inversions"),
    ("civilizational_stake", "civilizational_stakes"),
    ("divisiveness_engine", "divisiveness_engines"),
)

#: Decorative axes the ``constraint_strip`` operator can remove.  In the
#: engine, these are all list-typed (length 0..N picks) except
#: ``dark_archetype`` which is ``Optional[dict]``.
_DECORATIVE_AXES: Final[tuple[str, ...]] = (
    "conspiracy_engine",
    "reptile_trigger",
    "open_problem",
    "cultural_moment",
    "dark_archetype",
)


# ---------------------------------------------------------------------------
# VariablePools -- minimal data adapter
# ---------------------------------------------------------------------------


def _empty_pool() -> list[dict[str, Any]]:
    return []


@dataclass(frozen=True)
class VariablePools:
    """Bundle of axis pools the operators need.

    Constructed from the engine's loaded JSON (``_vars`` dict) plus the
    auxiliary archetype pools from ``frameworks/data/``.  Keeping this as
    a tiny standalone dataclass means operator tests can build fixtures
    without instantiating :class:`pipeline.compound_seed.CompoundSeedEngine`.
    """

    structural_inversions: list[dict[str, Any]] = field(default_factory=_empty_pool)
    world_textures: list[dict[str, Any]] = field(default_factory=_empty_pool)
    civilizational_stakes: list[dict[str, Any]] = field(default_factory=_empty_pool)
    divisiveness_engines: list[dict[str, Any]] = field(default_factory=_empty_pool)
    moral_fault_lines: list[dict[str, Any]] = field(default_factory=_empty_pool)
    protagonist_archetypes: list[dict[str, Any]] = field(default_factory=_empty_pool)
    antagonist_archetypes: list[dict[str, Any]] = field(default_factory=_empty_pool)
    dark_archetypes: list[dict[str, Any]] = field(default_factory=_empty_pool)

    def pool_for(self, key: str) -> list[dict[str, Any]]:
        """Return the named pool, or an empty list when absent."""
        return list(getattr(self, key, _empty_pool()))

    @classmethod
    def from_engine_defaults(cls) -> VariablePools:
        """Load the same JSON files the engine reads, without instantiating
        :class:`pipeline.compound_seed.CompoundSeedEngine`.

        Used by :func:`pipeline.single_idea.generate_seed_via_evolve` so the
        orchestrator can build pools without reaching into engine privates.
        """
        repo_root = Path(__file__).resolve().parents[2]
        vars_data = json.loads(
            (repo_root / "pipeline" / "data" / "compound_seed_variables.json").read_text(
                encoding="utf-8"
            )
        )
        frameworks_root = repo_root / "frameworks" / "data"

        def _read(path: Path) -> list[dict[str, Any]]:
            if not path.exists():
                return []
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return cast("list[dict[str, Any]]", data)
            return []

        def _pool(name: str) -> list[dict[str, Any]]:
            raw = vars_data.get(name, [])
            if isinstance(raw, list):
                return cast("list[dict[str, Any]]", raw)
            return []

        return cls(
            structural_inversions=_pool("structural_inversions"),
            world_textures=_pool("world_textures"),
            civilizational_stakes=_pool("civilizational_stakes"),
            divisiveness_engines=_pool("divisiveness_engines"),
            moral_fault_lines=_pool("moral_fault_lines"),
            protagonist_archetypes=_read(frameworks_root / "protagonist_archetypes.json"),
            dark_archetypes=_read(frameworks_root / "dark_archetypes.json"),
        )


# ---------------------------------------------------------------------------
# Module-level inversion-table cache
# ---------------------------------------------------------------------------


def _load_inversion_pairs(path: Path = INVERSION_PAIRS_PATH) -> dict[str, str]:
    """Read the symmetric ``{SI_id: SI_id}`` map from disk; ``{}`` if absent."""
    if not path.exists():
        _log.warning("inversion_pairs.json not found at %s -- invert() returns []", path)
        return {}
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    pairs_obj = raw.get("pairs", {})
    if not isinstance(pairs_obj, dict):
        return {}
    pairs_typed = cast("dict[str, str]", pairs_obj)
    out: dict[str, str] = {}
    for key, value in pairs_typed.items():
        out[str(key)] = str(value)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_id(value: dict[str, Any] | None) -> str | None:
    """Return ``value["id"]`` or ``None`` for absent / shapeless items."""
    if not value:
        return None
    vid = value.get("id")
    return str(vid) if vid else None


def _pick_low_freq(
    pool: list[dict[str, Any]],
    axis: str,
    current_id: str | None,
    freq_table: dict[tuple[str, str], int] | None,
    rng: random.Random,
) -> dict[str, Any] | None:
    """Return a pool item whose ``id`` differs from ``current_id``, weighted
    toward low :func:`pipeline.diversity.penalty` values.

    ``penalty(...)`` is monotone non-increasing in observed frequency, so
    we *invert* it: weight ``= 1 / penalty`` rewards rare values.  When
    ``freq_table`` is ``None`` / empty all weights are 1 -> uniform.

    Returns ``None`` when no eligible alternative exists.
    """
    eligible = [item for item in pool if _resolve_id(item) != current_id]
    if not eligible:
        return None

    if not freq_table:
        return rng.choice(eligible)

    weights: list[float] = []
    for item in eligible:
        item_id = _resolve_id(item) or ""
        # ``penalty`` returns 1.0 for unseen values and decays toward 0 as
        # frequency grows -- so it IS the sampling weight: rare items are
        # weighted at ~1.0, over-sampled items toward 0.
        weights.append(diversity.penalty(axis, item_id, freq_table))
    (chosen,) = rng.choices(eligible, weights=weights, k=1)
    return chosen


def _clone_with(
    candidate: CompoundSeedResult,
    *,
    variables: CompoundVariables,
    lineage_tag: str,
) -> CompoundSeedResult:
    """Return a new :class:`CompoundSeedResult` with mutated variables and an
    extended ``lineage``.  ``scores`` are inherited verbatim from
    ``candidate`` -- the orchestrator re-scores after the mutation pass."""
    return CompoundSeedResult(
        run_id=candidate.run_id,
        themes=list(candidate.themes),
        problems=list(candidate.problems),
        variables=variables,
        scores=candidate.scores,
        intersection_premise=candidate.intersection_premise,
        hidden_attrs=dict(candidate.hidden_attrs),
        commercial_signal_flags=dict(candidate.commercial_signal_flags),
        failure_risks=[dict(r) for r in candidate.failure_risks],
        lineage=[*candidate.lineage, lineage_tag],
    )


def _replace_variable(
    variables: CompoundVariables,
    axis: str,
    new_value: dict[str, Any],
) -> CompoundVariables:
    """Return a new :class:`CompoundVariables` with ``axis`` set to
    ``new_value``.  Uses :func:`dataclasses.replace` -- safe because the
    fields are simple containers."""
    return replace(variables, **{axis: new_value})


def _strip_variable(
    variables: CompoundVariables,
    axis: str,
) -> CompoundVariables:
    """Return a new :class:`CompoundVariables` with ``axis`` removed.

    For list-typed axes (the decorative slots) this means setting the
    field to ``[]``.  For ``Optional[dict]`` axes (``dark_archetype``,
    ``civilizational_stake``, ...) this means setting it to ``None``.
    """
    current = getattr(variables, axis, None)
    if isinstance(current, list):
        return replace(variables, **{axis: []})
    return replace(variables, **{axis: None})


# ---------------------------------------------------------------------------
# Operator 1: SCAMPER substitute
# ---------------------------------------------------------------------------


def scamper_substitute(
    candidate: CompoundSeedResult,
    pools: VariablePools,
    *,
    freq_table: dict[tuple[str, str], int] | None = None,
    rng: random.Random | None = None,
) -> list[CompoundSeedResult]:
    """Return up to 5 mutants -- one per core narrative axis -- each with
    that axis swapped to a low-frequency alternative.

    Axes walked in order: ``protagonist_archetype``, ``world_texture``,
    ``structural_inversion``, ``civilizational_stake``,
    ``divisiveness_engine``.  An axis that has an empty pool, or whose
    pool has no alternative to the current value, contributes no mutant.

    Args:
        candidate: The parent seed.  Its ``scores`` are propagated to the
            mutants verbatim -- the orchestrator re-scores after this
            mutation pass.
        pools: The variable pools the swap selects from.
        freq_table: Optional output of :func:`pipeline.diversity.load_frequency_table`.
            When provided, the swap target is weighted toward low-frequency
            pool entries.  ``None`` falls back to uniform.
        rng: Deterministic RNG override; defaults to a fresh :class:`random.Random`
            seeded from the system clock.

    Returns:
        A new list (possibly empty when no axis can be swapped).  Each
        mutant's ``lineage`` is extended by ``"scamper:<axis>"``.
    """
    if rng is None:
        rng = random.Random()  # noqa: S311 -- not used for cryptography

    mutants: list[CompoundSeedResult] = []
    for axis, pool_key in _SCAMPER_AXES:
        pool = pools.pool_for(pool_key)
        if not pool:
            continue
        current = getattr(candidate.variables, axis, None)
        current_id = _resolve_id(current)
        new_value = _pick_low_freq(pool, axis, current_id, freq_table, rng)
        if new_value is None:
            continue
        mutated_vars = _replace_variable(candidate.variables, axis, new_value)
        mutants.append(
            _clone_with(
                candidate,
                variables=mutated_vars,
                lineage_tag=f"scamper:{axis}",
            )
        )
    return mutants


# ---------------------------------------------------------------------------
# Operator 2: Invert
# ---------------------------------------------------------------------------


def invert(
    candidate: CompoundSeedResult,
    pools: VariablePools,
    *,
    inversion_pairs: dict[str, str] | None = None,
    rng: random.Random | None = None,
) -> list[CompoundSeedResult]:
    """Return up to 3 mutants produced by flipping semantically-paired axes:

    1. ``structural_inversion`` -> partner in :data:`INVERSION_PAIRS_PATH`
       (only when the current SI is in the table).
    2. ``protagonist_archetype`` <-> ``antagonist_archetype`` (only when
       both pools are non-empty and both slots resolve).
    3. ``dark_archetype`` swapped to a different one in the pool (the
       protagonist's shadow flips to a different fear).

    Args:
        candidate: The parent seed.
        pools: The pools used to look up the inversion partner.
        inversion_pairs: Override for the structural-inversion lookup
            table.  ``None`` reloads from :data:`INVERSION_PAIRS_PATH`.
        rng: Deterministic RNG override.

    Returns:
        A new list (possibly empty when no inversion is available).
    """
    if rng is None:
        rng = random.Random()  # noqa: S311
    if inversion_pairs is None:
        inversion_pairs = _load_inversion_pairs()

    mutants: list[CompoundSeedResult] = []

    # 1. Structural-inversion flip.
    si_current = candidate.variables.structural_inversion
    si_id = _resolve_id(si_current)
    if si_id and si_id in inversion_pairs:
        partner_id = inversion_pairs[si_id]
        partner = next(
            (item for item in pools.structural_inversions if _resolve_id(item) == partner_id),
            None,
        )
        if partner is not None:
            mutated = _replace_variable(candidate.variables, "structural_inversion", partner)
            mutants.append(
                _clone_with(candidate, variables=mutated, lineage_tag="invert:structural_inversion")
            )

    # 2. Protagonist <-> antagonist swap.
    prot = candidate.variables.protagonist_archetype
    antag = candidate.variables.antagonist_archetype
    if prot and antag and pools.protagonist_archetypes and pools.antagonist_archetypes:
        mutated = replace(
            candidate.variables,
            protagonist_archetype=antag,
            antagonist_archetype=prot,
        )
        mutants.append(
            _clone_with(
                candidate,
                variables=mutated,
                lineage_tag="invert:protagonist_antagonist",
            )
        )

    # 3. Dark-archetype shadow flip.
    dark_id = _resolve_id(candidate.variables.dark_archetype)
    alternatives = [
        item for item in pools.dark_archetypes if _resolve_id(item) and _resolve_id(item) != dark_id
    ]
    if alternatives:
        new_dark = rng.choice(alternatives)
        mutated = _replace_variable(candidate.variables, "dark_archetype", new_dark)
        mutants.append(
            _clone_with(candidate, variables=mutated, lineage_tag="invert:dark_archetype")
        )

    return mutants


# ---------------------------------------------------------------------------
# Operator 3: Constraint strip
# ---------------------------------------------------------------------------


def constraint_strip(
    candidate: CompoundSeedResult,
    *,
    rng: random.Random | None = None,
) -> list[CompoundSeedResult]:
    """Return one mutant per *populated* decorative axis with that axis
    removed.

    An axis is "populated" when:

    - it's a list field and the list is non-empty (decorative axes
      ``conspiracy_engine``, ``reptile_trigger``, ``open_problem``,
      ``cultural_moment``), OR
    - it's the ``dark_archetype`` ``Optional[dict]`` slot and currently
      not ``None``.

    Stripping an axis that wasn't there in the first place would produce a
    duplicate of the parent, so we never emit a no-op mutant.

    Args:
        candidate: The parent seed.
        rng: Reserved for future tie-breaking; currently unused.

    Returns:
        A new list with at most ``len(_DECORATIVE_AXES) == 5`` entries.
    """
    mutants: list[CompoundSeedResult] = []
    for axis in _DECORATIVE_AXES:
        current = getattr(candidate.variables, axis, None)
        if isinstance(current, list):
            if not current:
                continue
        elif current is None:
            continue
        stripped = _strip_variable(candidate.variables, axis)
        mutants.append(
            _clone_with(
                candidate,
                variables=stripped,
                lineage_tag=f"constraint_strip:{axis}",
            )
        )
    return mutants


__all__ = [
    "INVERSION_PAIRS_PATH",
    "VariablePools",
    "constraint_strip",
    "invert",
    "scamper_substitute",
]
