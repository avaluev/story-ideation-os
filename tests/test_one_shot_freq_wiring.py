"""Regression: freq_table reaches engine.generate from _generate_base.

Phase A Step 1 of the WEDGE plan. Before this wire, ``pipeline/evolve/one_shot.py``
loaded the ADR-0012 frequency table and then called ``_generate_base(...)`` without
forwarding it -- so the cross-run frequency penalty applied only to mutants, not the
base population that makes up half of every run. The smoking-gun was the leaderboard
showing the same ``world_texture`` / ``moral_fault_line`` / ``A.I. Artificial
Intelligence`` triple across 22 of 49 runs.

These tests pin the contract at the call boundary that previously dropped it:

  1. ``_generate_base(engine, ..., freq_table=table)`` forwards ``table`` *by identity*
     to every ``engine.generate(...)`` call.
  2. ``_generate_base`` defaults ``freq_table`` to ``None`` so existing callers do not
     change behaviour.
  3. ``CompoundSeedEngine.generate`` accepts ``freq_table`` as a kwarg and threads it
     into ``_sample_variables``.
  4. ``_sample_variables`` passes ``freq_table`` + canonical ``axis_name`` into every
     ``_thematic_weighted_choice`` call site (the cross-run memory layer is now alive
     for base sampling, not just mutants).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pipeline.compound_seed as _cs_mod
from pipeline.compound_seed import (
    CompoundScore,
    CompoundSeedEngine,
    CompoundSeedResult,
    CompoundVariables,
)
from pipeline.diversity import CANONICAL_AXES
from pipeline.evolve.one_shot import _generate_base


def _stub_variables() -> CompoundVariables:
    return CompoundVariables(
        themes=["legibility"],
        problems=["algorithmic visibility"],
        tensions=[],
        sdt_wound={"id": "SW_01"},
        psychological_pattern={"id": "PP_01"},
        structural_inversion={"id": "SI_01"},
        moral_fault_line={"id": "MF_01"},
        compression_key={"id": "CK_01"},
        divisiveness_engine={"id": "DE_01"},
        audiences=[],
        world_texture={"id": "WT_01", "name": "urban"},
        protagonist_archetype={"id": "PA_001", "label": "Caregiver"},
        antagonist_archetype={"id": "AA_001"},
    )


def _stub_score() -> CompoundScore:
    return CompoundScore(
        genius_score=0.6,
        associative_distance=0.4,
        goldilocks_score=0.7,
        sdt_intensity=1.0,
        structural_surprise=0.5,
        compression_score=0.5,
        audience_overlap_M=200.0,
        divisiveness_score=5.0,
        organic_marketing_mult=1.5,
        tam_M=150_000.0,
        sam_M=10_000.0,
        som_floor_M=50.0,
        passes_500m_gate=False,
        passes_genius_gate=True,
        thematic_anchor_score=0.6,
        emotional_universality_score=3.5,
        primary_cluster="institutional",
        cluster_coherence=0.7,
        arc_shape_6="Cinderella",
        cultural_field_alignment=0.5,
    )


@dataclass
class _SpyEngine:
    """Minimal engine stub. Records every kwarg passed to ``generate()`` so the
    test can assert that ``freq_table`` propagates through ``_generate_base``."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, **kwargs: Any) -> CompoundSeedResult:
        self.calls.append(kwargs)
        return CompoundSeedResult(
            run_id=f"seed-{len(self.calls)}",
            themes=list(kwargs.get("themes", [])),
            problems=list(kwargs.get("problems", [])),
            variables=_stub_variables(),
            scores=_stub_score(),
            intersection_premise="stub",
            hidden_attrs={},
        )


class TestGenerateBaseWiring:
    """The single regression that proves the WEDGE Step 1 wire is alive."""

    def test_forwards_freq_table_to_every_engine_call(self) -> None:
        engine = _SpyEngine()
        table: dict[tuple[str, str], int] = {("world_texture", "WT_01"): 50}

        _generate_base(engine, problem="x", themes=["t"], n=3, freq_table=table)  # type: ignore[arg-type]

        assert len(engine.calls) == 3
        for call in engine.calls:
            assert call.get("freq_table") is table

    def test_defaults_freq_table_to_none(self) -> None:
        engine = _SpyEngine()

        _generate_base(engine, problem="x", themes=["t"], n=2)  # type: ignore[arg-type]

        assert len(engine.calls) == 2
        for call in engine.calls:
            assert "freq_table" in call
            assert call["freq_table"] is None


class TestSampleVariablesWiring:
    """Verify ``_thematic_weighted_choice`` receives ``freq_table`` + ``axis_name``
    at every base-sampling call site -- the real cross-run memory layer."""

    def test_thematic_weighted_choice_receives_freq_table_and_axis_name(self) -> None:

        engine = CompoundSeedEngine.from_defaults()
        freq_table: dict[tuple[str, str], int] = {("world_texture", "WT_01"): 10}
        spy_calls: list[dict[str, Any]] = []
        real = _cs_mod._thematic_weighted_choice

        def _spy(*args: Any, **kwargs: Any) -> Any:
            spy_calls.append({"args": args, "kwargs": kwargs})
            return real(*args, **kwargs)

        with patch("pipeline.compound_seed._thematic_weighted_choice", side_effect=_spy):
            engine.generate(themes=["x"], problems=["y"], max_attempts=1, freq_table=freq_table)

        assert spy_calls, "expected at least one _thematic_weighted_choice call"

        sampled_axes: set[str] = set()
        for call in spy_calls:
            kwargs = call["kwargs"]
            assert kwargs.get("freq_table") is freq_table, (
                "_thematic_weighted_choice did not receive freq_table at one of its call sites"
            )
            axis = kwargs.get("axis_name")
            assert axis in CANONICAL_AXES, f"unknown axis_name {axis!r} (not in CANONICAL_AXES)"
            sampled_axes.add(axis)

        # The five primary base-sampling axes routed through _sample_variables must all fire.
        expected_axes = {
            "sdt_wound",
            "psychological_pattern",
            "structural_inversion",
            "moral_fault_line",
            "world_texture",
        }
        missing = expected_axes - sampled_axes
        assert not missing, f"base-sampling axes did not receive freq_table: {missing}"
