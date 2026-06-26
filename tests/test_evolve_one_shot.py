# ruff: noqa: S311 -- this is a test module; random.Random is for fixtures, not crypto
"""Tests for pipeline.evolve.one_shot (ADR-0012 Module 6 skeleton).

The skeleton is intentionally light -- it wires the parts whose deps exist
(engine, mental-model operators, revenue projector, diversity-floor
selector, axis-frequency log) and stubs the LLM operators that ship in
Day 4. These tests verify:

  - Public surface: ExploreResult / ScoredCandidate dataclasses exist
    with the expected fields.
  - Input validation: invalid n_base / top_k raises ValueError.
  - End-to-end skeleton run on a stub engine + tiny in-memory corpus:
    artifacts are persisted under runs_root, axis frequencies are
    recorded, ExploreResult.top_k is non-empty, every winner carries the
    ADR-0011 calculation_method marker on its RevenueProjection.

The full CompoundSeedEngine integration test is deferred -- the engine
needs the real frameworks/data fixtures and pulls in heavy deps.  This
test substitutes a minimal stub engine that returns hand-built
CompoundSeedResults so the skeleton's orchestration logic is exercised
in isolation.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pipeline.compound_seed import (
    CompoundScore,
    CompoundSeedResult,
    CompoundVariables,
)
from pipeline.crystallize.corpus import Film, FilmsCorpus
from pipeline.evolve.one_shot import (
    DEFAULT_N_BASE,
    DEFAULT_TOP_K,
    ExploreResult,
    ScoredCandidate,
    explore_and_select,
)
from pipeline.operators.mental_models import VariablePools

# ─── Fixtures ────────────────────────────────────────────────────────────────


def _item(item_id: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": item_id}
    base.update(extra)
    return base


def _score(primary_cluster: str = "institutional", som_M: float = 50.0) -> CompoundScore:
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
        som_floor_M=som_M,
        passes_500m_gate=False,
        passes_genius_gate=True,
        thematic_anchor_score=0.6,
        emotional_universality_score=3.5,
        primary_cluster=primary_cluster,
        cluster_coherence=0.7,
        arc_shape_6="Cinderella",
        cultural_field_alignment=0.5,
    )


def _candidate(
    seed_index: int,
    primary_cluster: str = "institutional",
    archetype_id: str = "PA_001",
    world_texture_id: str = "WT_01",
) -> CompoundSeedResult:
    v = CompoundVariables(
        themes=["legibility"],
        problems=["algorithmic visibility"],
        tensions=[],
        sdt_wound=_item("SW_01"),
        psychological_pattern=_item("PP_01"),
        structural_inversion=_item(f"SI_{(seed_index % 9) + 1:02d}"),
        moral_fault_line=_item("MF_01"),
        compression_key=_item("CK_01"),
        divisiveness_engine=_item("DE_01"),
        audiences=[
            {
                "id": "AUD_GEN_Z",
                "name": "Gen Z",
                "size_M": 70.0,
                "domain_tags": ["youth", "social"],
                "affinity_with": [],
            },
        ],
        world_texture=_item(world_texture_id, name="urban"),
        protagonist_archetype=_item(archetype_id, label="Caregiver"),
        antagonist_archetype=_item("AA_001"),
    )
    return CompoundSeedResult(
        run_id=f"seed-{seed_index}",
        themes=["legibility"],
        problems=["algorithmic visibility"],
        variables=v,
        scores=_score(primary_cluster=primary_cluster),
        intersection_premise=f"Premise seed {seed_index}",
        hidden_attrs={},
    )


@dataclass
class _StubEngine:
    """Stub for ``pipeline.compound_seed.CompoundSeedEngine`` -- only needs
    ``generate(themes=..., problems=...) -> CompoundSeedResult``.  Cycles
    through a small pre-built population so the skeleton sees variety."""

    population: list[CompoundSeedResult]
    _cursor: int = 0

    def generate(
        self,
        themes: list[str],
        problems: list[str],
        freq_table: dict[tuple[str, str], int] | None = None,
    ) -> CompoundSeedResult:
        result = self.population[self._cursor % len(self.population)]
        self._cursor += 1
        # Return a deep-enough copy so the skeleton can mutate lineage
        # without our test fixtures bleeding state.
        return CompoundSeedResult(
            run_id=result.run_id,
            themes=list(result.themes),
            problems=list(result.problems),
            variables=result.variables,
            scores=result.scores,
            intersection_premise=result.intersection_premise,
            hidden_attrs=dict(result.hidden_attrs),
            commercial_signal_flags=dict(result.commercial_signal_flags),
            failure_risks=[dict(r) for r in result.failure_risks],
        )


def _diverse_population() -> list[CompoundSeedResult]:
    clusters = ["institutional", "emotional", "technology", "identity"]
    return [
        _candidate(
            seed_index=i,
            primary_cluster=clusters[i % len(clusters)],
            archetype_id=f"PA_{(i % 4) + 1:03d}",
            world_texture_id=f"WT_{(i % 5) + 1:02d}",
        )
        for i in range(8)
    ]


def _basic_pools() -> VariablePools:
    return VariablePools(
        structural_inversions=[_item(f"SI_{i:02d}") for i in range(1, 10)],
        world_textures=[_item(f"WT_{i:02d}", name=f"world-{i}") for i in range(1, 10)],
        civilizational_stakes=[_item(f"CV_{i:02d}") for i in range(1, 6)],
        divisiveness_engines=[_item(f"DE_{i:02d}") for i in range(1, 6)],
        moral_fault_lines=[_item(f"MF_{i:02d}") for i in range(1, 6)],
        protagonist_archetypes=[_item(f"PA_{i:03d}") for i in range(1, 6)],
        antagonist_archetypes=[_item(f"AA_{i:03d}") for i in range(1, 6)],
        dark_archetypes=[_item(f"DA_{i:03d}") for i in range(1, 6)],
    )


def _film(
    slug: str,
    title: str,
    genres: tuple[str, ...],
    ww: float,
    domestic: float,
    budget: float,
    distributor: str,
    year: int,
) -> Film:
    return Film(
        slug=slug,
        title=title,
        imdb_id=None,
        worldwide_gross_usd=ww,
        domestic_gross_usd=domestic,
        international_gross_usd=ww - domestic,
        budget_usd=budget,
        genres=tuple(g.lower() for g in genres),
        genres_display=genres,
        distributor=distributor,
        release_year=year,
        mpaa=None,
        imdb_url=None,
        boxofficemojo_url=None,
    )


def _tiny_corpus() -> FilmsCorpus:
    """A 4-film corpus is enough to give project_revenue something to
    weight.  The skeleton test only cares that revenue.calculation_method
    is set, not that the projection is statistically meaningful."""
    films = [
        _film("comp-a", "Comp A", ("Drama", "Thriller"), 400e6, 180e6, 60e6, "Netflix", 2022),
        _film("comp-b", "Comp B", ("Drama",), 250e6, 110e6, 40e6, "A24", 2023),
        _film("comp-c", "Comp C", ("Thriller",), 600e6, 280e6, 80e6, "Universal", 2021),
        _film("comp-d", "Comp D", ("Drama", "Thriller"), 180e6, 70e6, 35e6, "Apple TV+", 2020),
    ]
    return FilmsCorpus(films=tuple(films), root=Path("."))


# ─── Public surface ──────────────────────────────────────────────────────────


class TestPublicSurface:
    def test_default_constants(self) -> None:
        assert DEFAULT_N_BASE == 64
        assert DEFAULT_TOP_K == 5

    def test_explore_result_dataclass(self) -> None:
        r = ExploreResult(run_id="x")
        assert r.run_id == "x"
        assert r.top_k == []
        assert r.all_scored == []
        assert r.operator_yield == {}
        assert r.artifacts == []

    def test_scored_candidate_dataclass(self) -> None:
        # ScoredCandidate is frozen -- construction is enough to verify the schema.
        cand = _candidate(0)
        from dataclasses import FrozenInstanceError  # noqa: PLC0415 -- scoped to test

        from pipeline.crystallize.revenue import (  # noqa: PLC0415
            OverlapResult,
            RevenueProjection,
        )

        proj = RevenueProjection(
            p10_usd=None,
            p50_usd=None,
            p90_usd=None,
            som_y1_usd=None,
            sam_usd=None,
            tam_usd=None,
            comp_provenance=(),
            overlap=OverlapResult(
                unique_addressable_M=0.0,
                pairwise_M={},
                triple_M=0.0,
                audience_factor=0.0,
            ),
            assumptions={},
        )
        sc = ScoredCandidate(
            candidate=cand, revenue=proj, crystallization_score=0.4, lineage=["base"]
        )
        with pytest.raises(FrozenInstanceError):
            sc.crystallization_score = 0.5  # type: ignore[misc]


# ─── Input validation ────────────────────────────────────────────────────────


class TestInputValidation:
    def test_n_base_zero_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="n_base"):
            explore_and_select(
                problem="p",
                themes=["t"],
                engine=_StubEngine(_diverse_population()),  # type: ignore[arg-type]
                pools=_basic_pools(),
                corpus=_tiny_corpus(),
                n_base=0,
                top_k=3,
                runs_root=tmp_path,
            )

    def test_top_k_negative_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="top_k"):
            explore_and_select(
                problem="p",
                themes=["t"],
                engine=_StubEngine(_diverse_population()),  # type: ignore[arg-type]
                pools=_basic_pools(),
                corpus=_tiny_corpus(),
                n_base=4,
                top_k=-1,
                runs_root=tmp_path,
            )


# ─── End-to-end skeleton run ─────────────────────────────────────────────────


class TestSkeletonRun:
    def _run(self, tmp_path: Path, n_base: int = 4, top_k: int = 3) -> ExploreResult:
        return explore_and_select(
            problem="the cost of being legible to algorithms",
            themes=["legibility", "agency"],
            engine=_StubEngine(_diverse_population()),  # type: ignore[arg-type]
            pools=_basic_pools(),
            corpus=_tiny_corpus(),
            n_base=n_base,
            top_k=top_k,
            use_llm_operators=False,
            runs_root=tmp_path,
            rng=random.Random(0),
        )

    def test_returns_explore_result(self, tmp_path: Path) -> None:
        r = self._run(tmp_path)
        assert isinstance(r, ExploreResult)
        assert r.run_id.startswith("evolve-")

    def test_top_k_nonempty(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, top_k=3)
        assert 1 <= len(r.top_k) <= 3

    def test_all_scored_includes_base_and_mutants(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, n_base=4)
        # 4 base + some mutants (at least the SCAMPER axes that have pools).
        assert len(r.all_scored) > 4

    def test_operator_yield_keys(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, n_base=4)
        assert set(r.operator_yield.keys()) == {"scamper", "invert", "constraint_strip"}
        assert r.operator_yield["scamper"] > 0

    def test_artifacts_written_to_runs_root(self, tmp_path: Path) -> None:
        r = self._run(tmp_path)
        for path in r.artifacts:
            assert path.exists(), f"{path} was not persisted"
            assert path.stat().st_size > 0

    def test_winners_json_is_valid(self, tmp_path: Path) -> None:
        r = self._run(tmp_path)
        winners_path = next(p for p in r.artifacts if p.name == "winners.json")
        payload = json.loads(winners_path.read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert len(payload) == len(r.top_k)
        for row in payload:
            assert "candidate" in row
            assert "revenue" in row
            assert "crystallization_score" in row
            assert "lineage" in row
            # ADR-0011: every persisted revenue carries the python-executed marker.
            assert row["revenue"]["calculation_method"] == "python_executed"

    def test_seed_top1_written(self, tmp_path: Path) -> None:
        r = self._run(tmp_path)
        seed_path = next(p for p in r.artifacts if p.name == "seed.json")
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
        # Either empty (no winners) or fully-populated.
        if payload:
            assert "candidate" in payload
            assert "revenue" in payload

    def test_lineage_present_on_mutants(self, tmp_path: Path) -> None:
        r = self._run(tmp_path)
        base_lineages = {tuple(sc.lineage) for sc in r.all_scored if sc.lineage == ["base"]}
        mutant_lineages = {tuple(sc.lineage) for sc in r.all_scored if len(sc.lineage) > 1}
        assert base_lineages  # base candidates tagged
        assert mutant_lineages  # operators produced lineage-tagged mutants

    def test_axis_frequency_log_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point the diversity log at a temp file so we can assert its growth.
        from pipeline import diversity  # noqa: PLC0415

        log_path = tmp_path / "axis_frequency.jsonl"
        monkeypatch.setattr(diversity, "DEFAULT_FREQUENCY_PATH", log_path)
        # Patch record_sample to use our temp path (the orchestrator uses defaults).
        original_record = diversity.record_sample

        def _patched_record(axis: str, value_id: str, run_id: str, **kw: Any) -> None:
            return original_record(axis, value_id, run_id, path=log_path)

        monkeypatch.setattr(diversity, "record_sample", _patched_record)
        self._run(tmp_path)
        assert log_path.exists()
        rows = [
            json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line
        ]
        assert rows  # at least one survivor recorded an axis frequency


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-x", "-v"])
