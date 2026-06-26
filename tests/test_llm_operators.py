"""Unit tests for pipeline.operators.llm_operators (ADR-0012 Module 4).

The module never calls a model -- it writes cc_dispatch-shaped manifests
that the /single-idea skill executes as Task invocations.  These tests
verify:

  - Each of first_principles / second_order / yes_and writes a well-shaped
    manifest with the right schema, model tier, and prompt template path.
  - The quota.gate filter drops candidates when the Sonnet cap is exhausted.
  - The loop_controller.patch_budget("L2") cap is respected.
  - The merger handles missing outputs, malformed rows, and empty manifests.
  - The lineage stamp survives the merge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.operators.llm_operators import (
    DEFAULT_EXPECTED_TOKENS,
    DISPATCH_ROOT,
    PROMPT_TEMPLATES,
    ManifestResult,
    MergeResult,
    first_principles,
    merge,
    second_order,
    yes_and,
)


def _cand(idx: int) -> dict[str, Any]:
    return {"id": f"cand-{idx}", "intersection_premise": f"premise {idx}"}


def _winners() -> list[dict[str, Any]]:
    return [{"run_id": "evolve-w1"}, {"run_id": "evolve-w2"}]


# ─── Public surface ──────────────────────────────────────────────────────────


class TestPublicSurface:
    def test_prompt_templates_exist(self) -> None:
        # The three Day-4 prompt files must exist (lint_prompts already gates
        # their format).
        for op, path in PROMPT_TEMPLATES.items():
            assert path.exists(), f"{op}: prompt template missing at {path}"

    def test_default_expected_tokens(self) -> None:
        assert DEFAULT_EXPECTED_TOKENS > 0

    def test_dispatch_root_under_planning(self) -> None:
        # Manifests go under .planning/phase_dispatch/ by default.
        assert DISPATCH_ROOT.parts[0] == ".planning"


# ─── first_principles ───────────────────────────────────────────────────────


class TestFirstPrinciples:
    def test_writes_one_row_per_candidate(self, tmp_path: Path) -> None:
        cands = [_cand(i) for i in range(3)]
        r = first_principles(cands, run_id="evolve-test", dispatch_root=tmp_path)
        assert isinstance(r, ManifestResult)
        assert r.rows_written == 3
        assert r.manifest_path.exists()
        lines = [ln for ln in r.manifest_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_manifest_row_schema(self, tmp_path: Path) -> None:
        r = first_principles([_cand(0)], run_id="evolve-test", dispatch_root=tmp_path)
        row = json.loads(r.manifest_path.read_text().splitlines()[0])
        # Required fields per ADR-0007 cc_dispatch schema:
        for key in (
            "run_id",
            "phase",
            "operator",
            "slice_id",
            "input_slice",
            "output_path",
            "prompt_template_path",
            "model_tier",
            "expected_tokens",
            "produced_at",
            "status",
        ):
            assert key in row, f"missing key {key} in manifest row"
        assert row["model_tier"] == "sonnet"
        assert row["phase"] == "mutation"
        assert row["operator"] == "first_principles"
        assert row["status"] == "PENDING"
        assert row["prompt_template_path"].endswith("first-principles.md")

    def test_empty_candidates_still_writes_manifest(self, tmp_path: Path) -> None:
        r = first_principles([], run_id="evolve-empty", dispatch_root=tmp_path)
        assert r.rows_written == 0
        assert r.manifest_path.exists()
        # File is empty (no rows).
        assert r.manifest_path.read_text() == ""


# ─── second_order ────────────────────────────────────────────────────────────


class TestSecondOrder:
    def test_writes_one_row_per_candidate(self, tmp_path: Path) -> None:
        cands = [_cand(i) for i in range(2)]
        r = second_order(cands, run_id="evolve-test", dispatch_root=tmp_path)
        assert r.rows_written == 2
        assert r.manifest_path.name == "mutation-second_order.jsonl"

    def test_prompt_template_path_correct(self, tmp_path: Path) -> None:
        r = second_order([_cand(0)], run_id="evolve-test", dispatch_root=tmp_path)
        row = json.loads(r.manifest_path.read_text().splitlines()[0])
        assert row["prompt_template_path"].endswith("second-order.md")


# ─── yes_and ─────────────────────────────────────────────────────────────────


class TestYesAnd:
    def test_input_slice_carries_winners(self, tmp_path: Path) -> None:
        r = yes_and([_cand(0)], _winners(), run_id="evolve-test", dispatch_root=tmp_path)
        row = json.loads(r.manifest_path.read_text().splitlines()[0])
        assert "winners" in row["input_slice"]
        assert row["input_slice"]["winners"] == _winners()
        assert "candidate" in row["input_slice"]


# ─── Budget + quota gates ────────────────────────────────────────────────────


class TestBudgetAndQuotaGates:
    def test_l2_budget_caps_fan_out(self, tmp_path: Path) -> None:
        # patch_budget("L2") == 5 per ADR-0009.  Send 8 candidates; expect 5 written, 3 dropped.
        cands = [_cand(i) for i in range(8)]
        r = first_principles(cands, run_id="evolve-test", dispatch_root=tmp_path)
        assert r.rows_written == 5
        assert r.rows_skipped_budget == 3
        assert r.rows_skipped_quota == 0

    def test_quota_gate_drops_when_cap_below_floor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force quota.gate to return False -> every candidate dropped.
        from pipeline import quota  # noqa: PLC0415

        monkeypatch.setattr(quota, "gate", lambda **_: False)
        cands = [_cand(i) for i in range(3)]
        r = first_principles(cands, run_id="evolve-test", dispatch_root=tmp_path)
        assert r.rows_written == 0
        assert r.rows_skipped_quota == 3

    def test_expected_tokens_validation(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="expected_tokens"):
            first_principles(
                [_cand(0)],
                run_id="evolve-test",
                expected_tokens=-1,
                dispatch_root=tmp_path,
            )


# ─── merge ───────────────────────────────────────────────────────────────────


class TestMerge:
    def test_missing_manifest_returns_empty(self, tmp_path: Path) -> None:
        r = merge("first_principles", "no-such-run", dispatch_root=tmp_path)
        assert isinstance(r, MergeResult)
        assert r.mutants == []
        assert r.artifacts == []

    def test_missing_output_files_skipped(self, tmp_path: Path) -> None:
        first_principles([_cand(0)], run_id="evolve-test", dispatch_root=tmp_path)
        # Manifest exists, but no Task wrote any output -> empty merge.
        r = merge("first_principles", "evolve-test", dispatch_root=tmp_path)
        assert r.mutants == []
        assert r.tokens_in == 0

    def test_merges_mutants_and_stamps_lineage(self, tmp_path: Path) -> None:
        first_principles([_cand(0)], run_id="evolve-test", dispatch_root=tmp_path)
        # Hand-write a fake Task output at the manifest's output_path.
        manifest_path = tmp_path / "evolve-test" / "mutation-first_principles.jsonl"
        row = json.loads(manifest_path.read_text().splitlines()[0])
        output_path = Path(row["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "parent_lineage": ["base"],
                    "mutants": [
                        {"intersection_premise": "rebuilt A"},
                        {"intersection_premise": "rebuilt B"},
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        r = merge("first_principles", "evolve-test", dispatch_root=tmp_path)
        assert len(r.mutants) == 2
        for mut in r.mutants:
            assert mut["lineage"] == ["base", "llm:first_principles"]

    def test_malformed_row_tolerated(self, tmp_path: Path) -> None:
        first_principles([_cand(0)], run_id="evolve-test", dispatch_root=tmp_path)
        manifest_path = tmp_path / "evolve-test" / "mutation-first_principles.jsonl"
        row = json.loads(manifest_path.read_text().splitlines()[0])
        output_path = Path(row["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # First line malformed; second line valid.
        output_path.write_text(
            "not-json\n"
            + json.dumps({"parent_lineage": [], "mutants": [{"intersection_premise": "ok"}]})
            + "\n",
            encoding="utf-8",
        )
        r = merge("first_principles", "evolve-test", dispatch_root=tmp_path)
        assert len(r.mutants) == 1
        assert r.mutants[0]["lineage"] == ["llm:first_principles"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-x", "-v"])
