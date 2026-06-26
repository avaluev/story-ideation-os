# ruff: noqa: S311 -- this is a test module; random.Random is for fixtures, not crypto
"""Unit tests for pipeline.operators.mental_models (ADR-0012 Module 3).

Covers:
  - VariablePools construction and pool_for() behaviour.
  - scamper_substitute: per-axis substitution, lineage tags, empty-pool
    skip, freq_table-aware low-frequency preference.
  - invert: structural-inversion table lookup, protagonist<->antagonist
    swap, dark-archetype shadow flip.
  - constraint_strip: removes populated decorative axes only, never
    duplicates the parent.
  - inversion_pairs.json: file exists and is symmetric.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from pipeline.compound_seed import (
    CompoundScore,
    CompoundSeedResult,
    CompoundVariables,
)
from pipeline.operators.mental_models import (
    INVERSION_PAIRS_PATH,
    VariablePools,
    _load_inversion_pairs,
    _resolve_id,
    constraint_strip,
    invert,
    scamper_substitute,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


def _item(item_id: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": item_id}
    base.update(extra)
    return base


def _base_score() -> CompoundScore:
    """Minimal CompoundScore with all required fields zeroed.

    The mental-model operators never read these -- they inherit the parent's
    scores verbatim and the orchestrator (Module 6) re-scores after mutation.
    """
    return CompoundScore(
        genius_score=0.0,
        associative_distance=0.0,
        goldilocks_score=0.0,
        sdt_intensity=0.0,
        structural_surprise=0.0,
        compression_score=0.0,
        audience_overlap_M=0.0,
        divisiveness_score=0.0,
        organic_marketing_mult=0.0,
        tam_M=0.0,
        sam_M=0.0,
        som_floor_M=0.0,
        passes_500m_gate=False,
        passes_genius_gate=False,
        thematic_anchor_score=0.0,
        emotional_universality_score=0.0,
        primary_cluster="institutional",
        cluster_coherence=0.0,
        arc_shape_6="Cinderella",
        cultural_field_alignment=0.0,
    )


def _make_candidate(**vars_overrides: Any) -> CompoundSeedResult:
    """Build a minimal CompoundSeedResult with explicit axis values.

    Tests pass only the axes they exercise; defaults cover the rest.
    """
    defaults: dict[str, Any] = {
        "themes": ["theme"],
        "problems": ["problem"],
        "tensions": [],
        "sdt_wound": _item("SW_01"),
        "psychological_pattern": _item("PP_01"),
        "structural_inversion": _item("SI_06"),
        "moral_fault_line": _item("MF_01"),
        "compression_key": _item("CK_01"),
        "divisiveness_engine": _item("DE_01"),
        "audiences": [],
        "world_texture": _item("WT_01"),
    }
    defaults.update(vars_overrides)
    v = CompoundVariables(**defaults)
    return CompoundSeedResult(
        run_id="test-run",
        themes=["theme"],
        problems=["problem"],
        variables=v,
        scores=_base_score(),
        intersection_premise="premise",
        hidden_attrs={},
    )


def _basic_pools() -> VariablePools:
    return VariablePools(
        structural_inversions=[_item(f"SI_{i:02d}") for i in range(1, 10)],
        world_textures=[_item(f"WT_{i:02d}") for i in range(1, 10)],
        civilizational_stakes=[_item(f"CV_{i:02d}") for i in range(1, 6)],
        divisiveness_engines=[_item(f"DE_{i:02d}") for i in range(1, 6)],
        moral_fault_lines=[_item(f"MF_{i:02d}") for i in range(1, 6)],
        protagonist_archetypes=[_item(f"PA_{i:03d}") for i in range(1, 6)],
        antagonist_archetypes=[_item(f"AA_{i:03d}") for i in range(1, 6)],
        dark_archetypes=[_item(f"DA_{i:03d}") for i in range(1, 6)],
    )


# ─── VariablePools ───────────────────────────────────────────────────────────


class TestVariablePools:
    def test_pool_for_known_key(self) -> None:
        p = _basic_pools()
        assert len(p.pool_for("structural_inversions")) == 9

    def test_pool_for_unknown_key(self) -> None:
        p = _basic_pools()
        assert p.pool_for("nonexistent_pool") == []

    def test_pool_for_returns_copy(self) -> None:
        p = _basic_pools()
        a = p.pool_for("structural_inversions")
        b = p.pool_for("structural_inversions")
        assert a == b
        assert a is not b  # mutation safety


# ─── _resolve_id ─────────────────────────────────────────────────────────────


class TestResolveId:
    def test_none(self) -> None:
        assert _resolve_id(None) is None

    def test_empty_dict(self) -> None:
        assert _resolve_id({}) is None

    def test_no_id_field(self) -> None:
        assert _resolve_id({"name": "x"}) is None

    def test_with_id(self) -> None:
        assert _resolve_id({"id": "SI_01"}) == "SI_01"


# ─── scamper_substitute ──────────────────────────────────────────────────────


class TestScamperSubstitute:
    def test_returns_one_mutant_per_axis_when_pools_complete(self) -> None:
        cand = _make_candidate(
            protagonist_archetype=_item("PA_001"),
            civilizational_stake=_item("CV_01"),
        )
        rng = random.Random(0)
        out = scamper_substitute(cand, _basic_pools(), rng=rng)
        assert len(out) == 5  # all 5 axes succeeded

    def test_each_mutant_tags_one_axis(self) -> None:
        cand = _make_candidate(
            protagonist_archetype=_item("PA_001"),
            civilizational_stake=_item("CV_01"),
        )
        rng = random.Random(0)
        out = scamper_substitute(cand, _basic_pools(), rng=rng)
        tags = sorted(m.lineage[-1] for m in out)
        assert tags == [
            "scamper:civilizational_stake",
            "scamper:divisiveness_engine",
            "scamper:protagonist_archetype",
            "scamper:structural_inversion",
            "scamper:world_texture",
        ]

    def test_swapped_id_differs_from_parent(self) -> None:
        cand = _make_candidate(world_texture=_item("WT_03"))
        rng = random.Random(0)
        out = scamper_substitute(cand, _basic_pools(), rng=rng)
        wt_mutant = next(m for m in out if m.lineage[-1] == "scamper:world_texture")
        assert wt_mutant.variables.world_texture["id"] != "WT_03"

    def test_empty_pool_skips_axis(self) -> None:
        pools = VariablePools(world_textures=[])  # only this axis is populated -> empty
        cand = _make_candidate()
        rng = random.Random(0)
        out = scamper_substitute(cand, pools, rng=rng)
        assert out == []

    def test_singleton_pool_matching_current_returns_no_mutant(self) -> None:
        # Pool has only the current value -> no alternative -> skip.
        pools = VariablePools(world_textures=[_item("WT_01")])
        cand = _make_candidate(world_texture=_item("WT_01"))
        rng = random.Random(0)
        out = scamper_substitute(cand, pools, rng=rng)
        assert out == []

    def test_lineage_appended_not_replaced(self) -> None:
        cand = _make_candidate()
        cand.lineage.append("base")  # parent already tagged
        rng = random.Random(0)
        out = scamper_substitute(cand, _basic_pools(), rng=rng)
        for m in out:
            assert m.lineage[0] == "base"
            assert m.lineage[-1].startswith("scamper:")

    def test_freq_table_biases_toward_low_frequency(self) -> None:
        # Heavily over-sampled WT_02; rare WT_03, WT_04, etc.  With a
        # fixed RNG the chosen swap should overwhelmingly land on a rare
        # value over many trials.
        freq_table = {
            ("world_texture", "WT_02"): 100,
            ("world_texture", "WT_03"): 0,
            ("world_texture", "WT_04"): 0,
            ("world_texture", "WT_05"): 0,
        }
        cand = _make_candidate(world_texture=_item("WT_01"))
        # We only need world_textures populated for this test.
        pools = VariablePools(
            world_textures=[_item("WT_02"), _item("WT_03"), _item("WT_04"), _item("WT_05")]
        )
        # Sample many times to defeat single-pick noise.
        picks: list[str] = []
        for seed in range(200):
            rng = random.Random(seed)
            out = scamper_substitute(cand, pools, freq_table=freq_table, rng=rng)
            wt_mutant = next((m for m in out if m.lineage[-1] == "scamper:world_texture"), None)
            if wt_mutant is None:
                continue
            picks.append(wt_mutant.variables.world_texture["id"])
        # Over 200 trials the over-sampled WT_02 should be a small fraction.
        assert picks  # something was picked
        wt02_share = picks.count("WT_02") / len(picks)
        assert wt02_share < 0.30, f"freq-table bias not respected: {wt02_share=}"


# ─── invert ──────────────────────────────────────────────────────────────────


class TestInvert:
    def test_structural_inversion_flip_when_pair_exists(self) -> None:
        # SI_06 <-> SI_15 per inversion_pairs.json
        cand = _make_candidate(structural_inversion=_item("SI_06"))
        pools = VariablePools(structural_inversions=[_item("SI_06"), _item("SI_15")])
        out = invert(cand, pools, rng=random.Random(0))
        si_flipped = [m for m in out if m.lineage[-1] == "invert:structural_inversion"]
        assert len(si_flipped) == 1
        assert si_flipped[0].variables.structural_inversion["id"] == "SI_15"

    def test_structural_inversion_skipped_when_pair_missing(self) -> None:
        # Use a fake table that has no entry for SI_99.
        cand = _make_candidate(structural_inversion=_item("SI_99"))
        out = invert(
            cand,
            _basic_pools(),
            inversion_pairs={"SI_01": "SI_22"},  # no SI_99
            rng=random.Random(0),
        )
        assert not any(m.lineage[-1] == "invert:structural_inversion" for m in out)

    def test_protagonist_antagonist_swap(self) -> None:
        cand = _make_candidate(
            protagonist_archetype=_item("PA_001"),
            antagonist_archetype=_item("AA_002"),
        )
        out = invert(cand, _basic_pools(), inversion_pairs={}, rng=random.Random(0))
        swapped = [m for m in out if m.lineage[-1] == "invert:protagonist_antagonist"]
        assert len(swapped) == 1
        v = swapped[0].variables
        assert v.protagonist_archetype is not None
        assert v.antagonist_archetype is not None
        assert v.protagonist_archetype["id"] == "AA_002"
        assert v.antagonist_archetype["id"] == "PA_001"

    def test_protagonist_antagonist_skipped_when_either_none(self) -> None:
        cand = _make_candidate(
            protagonist_archetype=_item("PA_001"),
            antagonist_archetype=None,
        )
        out = invert(cand, _basic_pools(), inversion_pairs={}, rng=random.Random(0))
        assert not any(m.lineage[-1] == "invert:protagonist_antagonist" for m in out)

    def test_dark_archetype_flip(self) -> None:
        cand = _make_candidate(dark_archetype=_item("DA_001"))
        out = invert(cand, _basic_pools(), inversion_pairs={}, rng=random.Random(0))
        dark_flipped = [m for m in out if m.lineage[-1] == "invert:dark_archetype"]
        assert len(dark_flipped) == 1
        new_dark = dark_flipped[0].variables.dark_archetype
        assert new_dark is not None
        assert new_dark["id"] != "DA_001"

    def test_no_mutants_when_pools_empty_and_no_pair(self) -> None:
        cand = _make_candidate()
        out = invert(cand, VariablePools(), inversion_pairs={}, rng=random.Random(0))
        assert out == []


# ─── constraint_strip ────────────────────────────────────────────────────────


class TestConstraintStrip:
    def test_strips_each_populated_decorative_axis(self) -> None:
        cand = _make_candidate(
            conspiracy_engine=[_item("CE_01")],
            reptile_trigger=[_item("RT_01")],
            cultural_moment=[_item("CM_01")],
            dark_archetype=_item("DA_01"),
        )
        out = constraint_strip(cand)
        tags = sorted(m.lineage[-1] for m in out)
        assert tags == [
            "constraint_strip:conspiracy_engine",
            "constraint_strip:cultural_moment",
            "constraint_strip:dark_archetype",
            "constraint_strip:reptile_trigger",
        ]

    def test_skips_empty_lists(self) -> None:
        cand = _make_candidate(conspiracy_engine=[], cultural_moment=[])
        out = constraint_strip(cand)
        assert not any(m.lineage[-1] == "constraint_strip:conspiracy_engine" for m in out)
        assert not any(m.lineage[-1] == "constraint_strip:cultural_moment" for m in out)

    def test_skips_none_optionals(self) -> None:
        cand = _make_candidate(dark_archetype=None)
        out = constraint_strip(cand)
        assert not any(m.lineage[-1] == "constraint_strip:dark_archetype" for m in out)

    def test_stripped_axis_is_empty_in_mutant(self) -> None:
        cand = _make_candidate(conspiracy_engine=[_item("CE_01"), _item("CE_02")])
        out = constraint_strip(cand)
        ce_stripped = next(m for m in out if m.lineage[-1] == "constraint_strip:conspiracy_engine")
        assert ce_stripped.variables.conspiracy_engine == []

    def test_dark_archetype_stripped_to_none(self) -> None:
        cand = _make_candidate(dark_archetype=_item("DA_01"))
        out = constraint_strip(cand)
        da_stripped = next(m for m in out if m.lineage[-1] == "constraint_strip:dark_archetype")
        assert da_stripped.variables.dark_archetype is None


# ─── inversion_pairs.json invariants ─────────────────────────────────────────


class TestInversionPairsTable:
    def test_file_exists(self) -> None:
        assert INVERSION_PAIRS_PATH.exists()

    def test_load_returns_nonempty(self) -> None:
        pairs = _load_inversion_pairs()
        assert len(pairs) > 0
        for k, v in pairs.items():
            assert isinstance(k, str) and k
            assert isinstance(v, str) and v

    def test_pairs_are_symmetric(self) -> None:
        pairs = _load_inversion_pairs()
        for a, b in pairs.items():
            assert pairs.get(b) == a, f"asymmetric pair: {a} -> {b}, but {b} -> {pairs.get(b)}"

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "no_such_file.json"
        assert _load_inversion_pairs(missing) == {}

    def test_load_handles_missing_pairs_key(self, tmp_path: Path) -> None:
        p = tmp_path / "no_pairs.json"
        p.write_text(json.dumps({"_meta": {"x": 1}}), encoding="utf-8")
        assert _load_inversion_pairs(p) == {}


# ─── lineage field on CompoundSeedResult ─────────────────────────────────────


class TestLineageField:
    def test_default_empty_list(self) -> None:
        c = _make_candidate()
        assert c.lineage == []

    def test_appears_in_to_dict(self) -> None:
        c = _make_candidate()
        c.lineage.append("base")
        c.lineage.append("scamper:world_texture")
        d = c.to_dict()
        assert d["lineage"] == ["base", "scamper:world_texture"]

    def test_mutation_does_not_affect_parent(self) -> None:
        cand = _make_candidate()
        cand.lineage.append("base")
        out = scamper_substitute(cand, _basic_pools(), rng=random.Random(0))
        assert cand.lineage == ["base"]  # parent untouched
        assert all(len(m.lineage) == 2 for m in out)  # base + one operator tag


if __name__ == "__main__":  # pragma: no cover -- pytest convention
    pytest.main([__file__, "-x", "-v"])
