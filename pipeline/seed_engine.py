"""25-axis deterministic combinatorial sampler for the v3.1 redesign.

Reads ``data/seeds/*.csv`` and produces a ``SeedPackage`` for every integer
``seed_int``. Same seed_int -> byte-identical SeedPackage; different seeds
sample distinct combinations across all 25 axes.

The sampler uses Python's ``random.Random(seed_int)`` for reproducibility.
Each axis draws independently with replacement so the combinatoric space
is the product of axis sizes (~10^30 for the bootstrap data).

Used by ``pipeline/seed_picker.py`` and ``pipeline/commercial_prescreen.py``
to drive concept sampling.
"""

from __future__ import annotations

import csv
import random
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

SEEDS_DIR = Path("data/seeds")


@dataclass(frozen=True)
class AxisRow:
    """One row from a seed CSV. Stored verbatim from the CSV."""

    id: int
    name: str
    label: str
    gloss: str
    extra: dict[str, str]


@dataclass(frozen=True)
class SeedPackage:
    """The deterministic 25-axis sample for one concept."""

    seed_int: int
    tension: AxisRow
    space: AxisRow
    polti: AxisRow
    tobias: AxisRow
    booker: AxisRow
    stc: AxisRow
    truby: AxisRow
    archetype: AxisRow
    arc_shape: AxisRow
    time_period: AxisRow
    geography: AxisRow
    philosophical_school: AxisRow
    sensory_key: AxisRow
    color_palette: AxisRow
    sound_register: AxisRow
    pacing_register: AxisRow
    body_axis: AxisRow
    class_layer: AxisRow
    faith_axis: AxisRow
    technology_layer: AxisRow
    family_config: AxisRow
    nonhuman_presence: AxisRow
    mutation_operator: AxisRow
    irreversibility_pattern: AxisRow

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"seed_int": self.seed_int}
        for axis_name, value in asdict(self).items():
            if axis_name == "seed_int":
                continue
            assert isinstance(value, dict)
            out[axis_name] = value
        return out


# ---------------------------------------------------------------------------
# CSV cell coercion (handles list-valued cells from unquoted commas).
# ---------------------------------------------------------------------------


def _stringify(value: str | list[str] | None) -> str:
    """Coerce a CSV cell value into a stripped string.

    csv.DictReader returns list values when a row has more fields than
    the header (typically caused by an unquoted comma inside a cell).
    Joining list cells preserves the original prose.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value).strip()
    return str(value).strip()


def _row_id(raw: dict[str | None, str | list[str] | None]) -> int:
    s = _stringify(raw.get("id"))
    return int(s) if s.isdigit() else 0


# ---------------------------------------------------------------------------
# CSV loaders (one per shape).
# ---------------------------------------------------------------------------


@lru_cache(maxsize=32)
def _load_axis(filename: str) -> tuple[AxisRow, ...]:
    """Standard shape: id, name, label?, gloss, ...rest."""
    path = SEEDS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Seed CSV not found: {path}")
    rows: list[AxisRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            name = _stringify(raw.get("name"))
            label = _stringify(raw.get("label")) or name
            gloss = _stringify(raw.get("gloss"))
            extra = {
                k: _stringify(v)
                for k, v in raw.items()
                if k is not None and k not in {"id", "name", "label", "gloss"}
            }
            rows.append(
                AxisRow(
                    id=_row_id(raw),
                    name=name,
                    label=label,
                    gloss=gloss,
                    extra=extra,
                )
            )
    if not rows:
        raise ValueError(f"Seed CSV has no rows: {path}")
    return tuple(rows)


@lru_cache(maxsize=32)
def _load_tensions() -> tuple[AxisRow, ...]:
    path = SEEDS_DIR / "tensions.csv"
    rows: list[AxisRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            pole_a = _stringify(raw.get("pole_a"))
            pole_b = _stringify(raw.get("pole_b"))
            gloss = _stringify(raw.get("gloss"))
            label = f"{pole_a} vs {pole_b}"
            extra = {"pole_a": pole_a, "pole_b": pole_b}
            for k, v in raw.items():
                if k is not None and k not in {"id", "pole_a", "pole_b", "gloss"}:
                    extra[k] = _stringify(v)
            rows.append(
                AxisRow(
                    id=_row_id(raw),
                    name=label,
                    label=label,
                    gloss=gloss,
                    extra=extra,
                )
            )
    return tuple(rows)


@lru_cache(maxsize=32)
def _load_geography() -> tuple[AxisRow, ...]:
    path = SEEDS_DIR / "geography.csv"
    rows: list[AxisRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            name = _stringify(raw.get("name"))
            region = _stringify(raw.get("region"))
            gloss = _stringify(raw.get("gloss"))
            extra = {"region": region}
            for k, v in raw.items():
                if k is not None and k not in {"id", "name", "region", "gloss"}:
                    extra[k] = _stringify(v)
            rows.append(
                AxisRow(
                    id=_row_id(raw),
                    name=name,
                    label=name,
                    gloss=gloss,
                    extra=extra,
                )
            )
    return tuple(rows)


@lru_cache(maxsize=32)
def _load_spaces() -> tuple[AxisRow, ...]:
    path = SEEDS_DIR / "spaces.csv"
    rows: list[AxisRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            name = _stringify(raw.get("name"))
            gloss = _stringify(raw.get("gloss"))
            rows.append(
                AxisRow(
                    id=_row_id(raw),
                    name=name,
                    label=name,
                    gloss=gloss,
                    extra={},
                )
            )
    return tuple(rows)


@lru_cache(maxsize=32)
def _load_mutation_operators() -> tuple[AxisRow, ...]:
    path = SEEDS_DIR / "mutation_operators.csv"
    rows: list[AxisRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            name = _stringify(raw.get("name"))
            label = _stringify(raw.get("label")) or name
            prompt = _stringify(raw.get("prompt"))
            active = _stringify(raw.get("active_day1")).lower() == "true"
            extra = {"prompt": prompt, "active_day1": str(active)}
            rows.append(
                AxisRow(
                    id=_row_id(raw),
                    name=name,
                    label=label,
                    gloss=prompt,
                    extra=extra,
                )
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------


def sample(seed_int: int) -> SeedPackage:
    """Draw one deterministic 25-axis sample for ``seed_int``."""
    rng = random.Random(seed_int)  # noqa: S311 -- deterministic reproducibility

    def pick(rows: tuple[AxisRow, ...]) -> AxisRow:
        return rows[rng.randrange(len(rows))]

    operators = _load_mutation_operators()
    active_operators = tuple(op for op in operators if op.extra.get("active_day1") == "True")
    operators_pool = active_operators if active_operators else operators

    return SeedPackage(
        seed_int=seed_int,
        tension=pick(_load_tensions()),
        space=pick(_load_spaces()),
        polti=pick(_load_axis("polti.csv")),
        tobias=pick(_load_axis("tobias.csv")),
        booker=pick(_load_axis("booker.csv")),
        stc=pick(_load_axis("stc.csv")),
        truby=pick(_load_axis("truby.csv")),
        archetype=pick(_load_axis("archetypes.csv")),
        arc_shape=pick(_load_axis("arc_shapes.csv")),
        time_period=pick(_load_axis("time_periods.csv")),
        geography=pick(_load_geography()),
        philosophical_school=pick(_load_axis("philosophical_schools.csv")),
        sensory_key=pick(_load_axis("sensory_keys.csv")),
        color_palette=pick(_load_axis("color_palettes.csv")),
        sound_register=pick(_load_axis("sound_registers.csv")),
        pacing_register=pick(_load_axis("pacing_registers.csv")),
        body_axis=pick(_load_axis("body_axis.csv")),
        class_layer=pick(_load_axis("class_layer.csv")),
        faith_axis=pick(_load_axis("faith_axis.csv")),
        technology_layer=pick(_load_axis("technology_layer.csv")),
        family_config=pick(_load_axis("family_config.csv")),
        nonhuman_presence=pick(_load_axis("nonhuman_presence.csv")),
        mutation_operator=pick(operators_pool),
        irreversibility_pattern=pick(_load_axis("irreversibility_patterns.csv")),
    )


# ---------------------------------------------------------------------------
# Coherence guard
# ---------------------------------------------------------------------------

# Tech ages incompatible with pre-modern philosophical traditions when the
# concept must be set during the listed time period. (e.g. agentic-AI in
# the Sufism + 9th-century Mecca register reads as fantasy, not concept.)
_PRE_MODERN_SCHOOLS: frozenset[str] = frozenset(
    {
        "sufism",
        "kabbalah",
        "vedanta",
        "buddhism_chan",
        "confucianism",
        "stoicism",
        "neoplatonism",
        "scholasticism",
        "hermeticism",
    }
)
_MODERN_TECH_LAYERS: frozenset[str] = frozenset(
    {"agentic_ai", "post_collapse", "networked", "industrial"},
)
_PRE_MODERN_TECH_LAYERS: frozenset[str] = frozenset(
    {"pre_electric", "pre_industrial", "primitive", "agrarian"},
)
_MODERN_TIME_PERIODS: frozenset[str] = frozenset(
    {"present", "near_future", "networked_2000s", "post_internet", "smartphone_era"},
)


def is_coherent(pkg: SeedPackage) -> tuple[bool, str]:
    """Return ``(True, "")`` if the seed package is internally coherent.

    Otherwise return ``(False, reason)`` so callers can log + advance the seed.

    The denylist names axis-pair combinations whose collision produces
    incoherent (rather than productive) tension. e.g. an agentic-AI tech
    layer paired with a Sufism-as-philosophical-school anchor in a pre-modern
    geographic register reads as anachronism, not concept.
    """
    school = pkg.philosophical_school.name.lower()
    tech = pkg.technology_layer.name.lower()
    period = pkg.time_period.name.lower()
    if school in _PRE_MODERN_SCHOOLS and tech in _MODERN_TECH_LAYERS:
        return (
            False,
            f"pre-modern school '{school}' paired with modern tech '{tech}'",
        )
    if period in _MODERN_TIME_PERIODS and tech in _PRE_MODERN_TECH_LAYERS:
        return (
            False,
            f"modern period '{period}' paired with pre-modern tech '{tech}'",
        )
    if pkg.faith_axis.name == "atheist" and school in _PRE_MODERN_SCHOOLS:
        return (
            False,
            f"atheist faith register paired with religious school '{school}'",
        )
    return (True, "")


def axis_sizes() -> dict[str, int]:
    return {
        "tensions": len(_load_tensions()),
        "spaces": len(_load_spaces()),
        "polti": len(_load_axis("polti.csv")),
        "tobias": len(_load_axis("tobias.csv")),
        "booker": len(_load_axis("booker.csv")),
        "stc": len(_load_axis("stc.csv")),
        "truby": len(_load_axis("truby.csv")),
        "archetypes": len(_load_axis("archetypes.csv")),
        "arc_shapes": len(_load_axis("arc_shapes.csv")),
        "time_periods": len(_load_axis("time_periods.csv")),
        "geography": len(_load_geography()),
        "philosophical_schools": len(_load_axis("philosophical_schools.csv")),
        "sensory_keys": len(_load_axis("sensory_keys.csv")),
        "color_palettes": len(_load_axis("color_palettes.csv")),
        "sound_registers": len(_load_axis("sound_registers.csv")),
        "pacing_registers": len(_load_axis("pacing_registers.csv")),
        "body_axis": len(_load_axis("body_axis.csv")),
        "class_layer": len(_load_axis("class_layer.csv")),
        "faith_axis": len(_load_axis("faith_axis.csv")),
        "technology_layer": len(_load_axis("technology_layer.csv")),
        "family_config": len(_load_axis("family_config.csv")),
        "nonhuman_presence": len(_load_axis("nonhuman_presence.csv")),
        "mutation_operators": len(_load_mutation_operators()),
        "irreversibility_patterns": len(_load_axis("irreversibility_patterns.csv")),
    }
