"""Tests for pipeline.audience_amplifier."""

from __future__ import annotations

from pathlib import Path

from pipeline.audience_amplifier import (
    AmplificationResult,
    AmplificationVector,
    amplification_loop,
    load_vectors,
    render_trail,
    write_trail,
)

_VECTORS_PATH = (
    Path(__file__).resolve().parent.parent / "pipeline" / "data" / "amplification_vectors.json"
)


class TestLoadVectors:
    def test_loads_without_error(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        assert len(vecs) >= 15

    def test_all_have_positive_multiplier(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        for vid, v in vecs.items():
            assert v.base_multiplier > 1.0, f"{vid} has multiplier <= 1.0"

    def test_ids_match_keys(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        for vid, v in vecs.items():
            assert v.id == vid

    def test_synergy_entries_exist(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        synergy_vecs = [v for v in vecs.values() if v.category == "S_synergy"]
        assert len(synergy_vecs) >= 3

    def test_evidence_non_empty(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        for v in vecs.values():
            assert v.evidence, f"{v.id} has empty evidence"


class TestAmplificationLoop:
    def test_grows_audience(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 30.0, vectors=vecs, target_M=100.0)
        assert result.final_audience_M > result.base_audience_M

    def test_reaches_target(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 30.0, vectors=vecs, target_M=100.0)
        assert result.final_audience_M >= 100.0

    def test_respects_max_iterations(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 30.0, vectors=vecs, max_iterations=2)
        assert len(result.iterations) <= 2

    def test_already_applied_skipped(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result_cold = amplification_loop("test", 30.0, vectors=vecs)
        result_warm = amplification_loop(
            "test", 30.0, vectors=vecs, already_applied=["A2", "B1", "E1"]
        )
        applied_cold = set(result_cold.vectors_applied)
        applied_warm = set(result_warm.vectors_applied)
        # warm should not reapply pre-applied vectors
        assert "A2" in applied_warm
        assert "B1" in applied_warm
        # but new vectors added in loop should differ
        assert applied_warm != applied_cold

    def test_total_multiplier_matches_iterations(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 10.0, vectors=vecs)
        expected = round(result.final_audience_M / result.base_audience_M, 2)
        assert result.total_multiplier == expected

    def test_result_slug_preserved(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("my-slug", 40.0, vectors=vecs)
        assert result.concept_slug == "my-slug"

    def test_revenue_implication_non_empty(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 30.0, vectors=vecs)
        assert result.revenue_implication

    def test_vectors_remaining_shrinks(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 30.0, vectors=vecs, target_M=50.0)
        assert len(result.vectors_remaining) < len(vecs)

    def test_zero_base_does_not_crash(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 0.0, vectors=vecs)
        assert result.total_multiplier == 1.0


class TestRenderTrail:
    def test_renders_without_error(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("signal", 30.0, vectors=vecs)
        trail = render_trail(result)
        assert "signal" in trail
        assert "Base audience" in trail
        assert "Final audience" in trail

    def test_contains_all_applied_vectors(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("signal", 30.0, vectors=vecs, target_M=50.0)
        trail = render_trail(result)
        for vid in result.vectors_applied:
            assert vid in trail

    def test_write_trail_creates_file(self, tmp_path: Path) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("my-concept", 25.0, vectors=vecs)
        out = write_trail(result, tmp_path)
        assert out.exists()
        assert out.name == "my-concept-AMPLIFIED.md"
        assert out.stat().st_size > 100


class TestAmplificationVector:
    def test_dataclass_fields(self) -> None:
        v = AmplificationVector(
            id="X1",
            name="Test vector",
            category="test",
            base_multiplier=1.5,
            conditions=[],
            evidence="test evidence",
        )
        assert v.id == "X1"
        assert v.base_multiplier == 1.5
        assert v.synergy_with == {}

    def test_synergy_with_populated(self) -> None:
        v = AmplificationVector(
            id="X1",
            name="Test",
            category="test",
            base_multiplier=1.5,
            conditions=[],
            evidence="evidence",
            synergy_with={"Y1": 2.5},
        )
        assert v.synergy_with["Y1"] == 2.5


class TestAmplificationResult:
    def test_is_dataclass(self) -> None:
        vecs = load_vectors(_VECTORS_PATH)
        result = amplification_loop("test", 20.0, vectors=vecs)
        assert isinstance(result, AmplificationResult)
        assert isinstance(result.iterations, list)
        assert isinstance(result.vectors_applied, list)
        assert isinstance(result.vectors_remaining, list)
