"""Seed picker for the Big Ideas evolutionary loop.

Samples N diverse, resonance-weighted seeds from the conflict ontology.
Each seed is a 4-tuple (BT, PS, PA, US) drawn from a hand-curated
finite space of 44 binary tensions x 36 Polti situations x 12 Pearson
archetypes x 40 unusual spaces = 760,320 cells.

The novelty mechanism that overcomes LLM mode collapse: the LLM never
picks its own coordinate. This module does, mechanically, before the
LLM is invoked.

Reads:
    - sources/conflict_ontology.json (the ontology)
    - sources/resonance_weights.json (live 2026 macro-signal weights)
    - data/cell_history.jsonl (append-only history for diversity penalty)

Exports: pick_seeds(n=5) -> list[SeedPackage]
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_DEFAULT_ONTOLOGY: Final[Path] = _REPO_ROOT / "sources" / "conflict_ontology.json"
_DEFAULT_WEIGHTS: Final[Path] = _REPO_ROOT / "sources" / "resonance_weights.json"
_DEFAULT_HISTORY: Final[Path] = _REPO_ROOT / "data" / "cell_history.jsonl"

_TENSION_COEFF: Final[float] = 0.50
_SPACE_COEFF: Final[float] = 0.30
_NOVELTY_COEFF: Final[float] = 0.20
_HISTORY_PENALTY: Final[float] = 0.3
_HISTORY_WINDOW_DAYS: Final[int] = 30
_MAX_N: Final[int] = 30
_ATTEMPT_FLOOR: Final[int] = 200
_ATTEMPT_PER_N: Final[int] = 50

Json = dict[str, Any]
JsonItem = dict[str, Any]


@dataclass(frozen=True)
class SeedPackage:
    """A single sampled seed for the evolutionary loop."""

    cell_id: str
    bt_id: str
    bt_pole_a: str
    bt_pole_b: str
    ps_id: str
    ps_name: str
    pa_id: str
    pa_archetype: str
    us_id: str
    us_space: str
    resonance_score: float
    novelty_band: str  # "underexplored" | "neutral" | "overdone"


def pick_seeds(
    n: int = 5,
    ontology_path: Path = _DEFAULT_ONTOLOGY,
    weights_path: Path = _DEFAULT_WEIGHTS,
    history_path: Path = _DEFAULT_HISTORY,
    rng_seed: int | None = None,
) -> list[SeedPackage]:
    """Sample n diverse seeds weighted by resonance.

    Diversity: no two seeds share both bt_id AND ps_id.
    History penalty: cells forged in last 30 days get resonance times 0.3.

    Args:
        n: Number of seeds to sample (clamped to [1, 20]).
        ontology_path: Path to conflict_ontology.json.
        weights_path: Path to resonance_weights.json.
        history_path: Path to data/cell_history.jsonl (may not exist).
        rng_seed: Optional integer for deterministic reproduction.

    Returns:
        List of SeedPackage objects, length n.

    Raises:
        FileNotFoundError: If ontology or weights file is missing.
        RuntimeError: If diversity cannot be satisfied within attempt cap.
    """
    n_clamped = max(1, min(int(n), _MAX_N))
    rng = random.Random(rng_seed)  # noqa: S311 - not security-sensitive

    ontology = _load_json(ontology_path)
    weights = _load_json(weights_path)
    state = _PickerState.build(ontology, weights, history_path)

    chosen: list[SeedPackage] = []
    used_pairs: set[tuple[str, str]] = set()
    max_attempts = max(_ATTEMPT_FLOOR, n_clamped * _ATTEMPT_PER_N)

    for _ in range(max_attempts):
        if len(chosen) >= n_clamped:
            break
        pkg = _try_pick_one(state, used_pairs, rng)
        if pkg is None:
            continue
        chosen.append(pkg)
        used_pairs.add((pkg.bt_id, pkg.ps_id))

    if len(chosen) < n_clamped:
        msg = (
            f"seed_picker: could not draw {n_clamped} diverse seeds; "
            f"got {len(chosen)} after {max_attempts} attempts."
        )
        raise RuntimeError(msg)

    return chosen


@dataclass(frozen=True)
class _PickerState:
    """Pre-loaded ontology + weights + history; built once per pick_seeds call."""

    bts: list[JsonItem]
    pss: list[JsonItem]
    pas: list[JsonItem]
    uss: list[JsonItem]
    bt_weights: Json
    us_weights: Json
    overdone: set[str]
    underexplored: set[str]
    recent_cells: set[str]

    @classmethod
    def build(
        cls,
        ontology: Json,
        weights: Json,
        history_path: Path,
    ) -> _PickerState:
        dims = cast(Json, ontology["dimensions"])
        cc_raw = cast("Json | None", ontology.get("cross_consistency"))
        cc: Json = cc_raw if cc_raw is not None else {}
        overdone_entries = cast(list[JsonItem], cc.get("overdone_combinations", []))
        underexplored_entries = cast(list[JsonItem], cc.get("underexplored_combinations", []))
        overdone_bts: set[str] = {
            str(entry["tension"]) for entry in overdone_entries if "tension" in entry
        }
        underexplored_combos: set[str] = {
            f"{entry['tension_a']}+{entry['space']}"
            for entry in underexplored_entries
            if "tension_a" in entry and "space" in entry
        }
        return cls(
            bts=cast(list[JsonItem], dims["binary_tensions"]),
            pss=cast(list[JsonItem], dims["polti_situations"]),
            pas=cast(list[JsonItem], dims["pearson_archetypes"]),
            uss=cast(list[JsonItem], dims["unusual_spaces"]),
            bt_weights=cast(Json, weights["binary_tensions"]),
            us_weights=cast(Json, weights["unusual_spaces"]),
            overdone=overdone_bts,
            underexplored=underexplored_combos,
            recent_cells=_load_recent_cells(history_path),
        )


def _try_pick_one(
    state: _PickerState,
    used_pairs: set[tuple[str, str]],
    rng: random.Random,
) -> SeedPackage | None:
    bt = _weighted_pick(state.bts, state.bt_weights, rng)
    us = _weighted_pick(state.uss, state.us_weights, rng)
    ps: JsonItem = rng.choice(state.pss)
    pa: JsonItem = rng.choice(state.pas)

    bt_id = str(bt["id"])
    ps_id = str(ps["id"])
    pa_id = str(pa["id"])
    us_id = str(us["id"])

    if (bt_id, ps_id) in used_pairs:
        return None

    cell_id = f"{bt_id}_{ps_id}_{pa_id}_{us_id}"
    history_mult = _HISTORY_PENALTY if cell_id in state.recent_cells else 1.0

    combo_key = f"{bt_id}+{us_id}"
    novelty_score, novelty_band = _classify_novelty(
        bt_id, combo_key, state.overdone, state.underexplored
    )

    tension_w = _weight_value(state.bt_weights.get(bt_id, 0.5))
    space_w = _weight_value(state.us_weights.get(us_id, 0.5))
    raw = _TENSION_COEFF * tension_w + _SPACE_COEFF * space_w + _NOVELTY_COEFF * novelty_score
    resonance = round(raw * history_mult, 4)

    us_space = str(us.get("space", us.get("name", us_id)))

    return SeedPackage(
        cell_id=cell_id,
        bt_id=bt_id,
        bt_pole_a=str(bt["pole_a"]),
        bt_pole_b=str(bt["pole_b"]),
        ps_id=ps_id,
        ps_name=str(ps["name"]),
        pa_id=pa_id,
        pa_archetype=str(pa["archetype"]),
        us_id=us_id,
        us_space=us_space,
        resonance_score=resonance,
        novelty_band=novelty_band,
    )


def _classify_novelty(
    bt_id: str,
    combo_key: str,
    overdone_bts: set[str],
    underexplored_combos: set[str],
) -> tuple[float, str]:
    """Underexplored BT+US pairs win over BT-only overdone tags."""
    if combo_key in underexplored_combos:
        return 1.0, "underexplored"
    if bt_id in overdone_bts:
        return 0.2, "overdone"
    return 0.5, "neutral"


def _load_json(path: Path) -> Json:
    with open(path, encoding="utf-8") as f:
        return cast(Json, json.load(f))


def _load_recent_cells(history_path: Path) -> set[str]:
    """Return set of cell_ids forged in the last 30 days (best-effort)."""
    if not history_path.exists():
        return set()
    cells: set[str] = set()
    try:
        with open(history_path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = cast(Json, json.loads(line))
                except json.JSONDecodeError:
                    continue
                cell_id = row.get("cell_id")
                if isinstance(cell_id, str):
                    cells.add(cell_id)
    except OSError:
        return set()
    return cells


def _weight_value(entry: object) -> float:
    """Resonance weights may be {weight, driver} dicts or bare floats."""
    if isinstance(entry, dict):
        entry_dict = cast(Json, entry)
        w = entry_dict.get("weight", 0.5)
        return float(w) if isinstance(w, (int, float)) else 0.5
    if isinstance(entry, (int, float)):
        return float(entry)
    return 0.5


def _weighted_pick(
    items: list[JsonItem],
    weights: Json,
    rng: random.Random,
) -> JsonItem:
    """Weighted choice across items by id-keyed weight dict."""
    ws = [_weight_value(weights.get(str(item["id"]), 0.5)) for item in items]
    total = sum(ws)
    if total <= 0:
        return rng.choice(items)
    return rng.choices(items, weights=ws, k=1)[0]
