"""Unit tests for pipeline.diversity (ADR-0012 Module 1).

Covers:
    - load_frequency_table: empty, post-record, schema-hash invalidation,
      rolling window_runs semantics, malformed-row tolerance.
    - record_sample: append-only semantics, multi-pick rows, input validation.
    - penalty: monotone decay, alpha=0 / freq=0 / empty-table guards, bound.
    - schema_hash: stability across processes (deterministic).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import diversity
from pipeline.diversity import (
    CANONICAL_AXES,
    DEFAULT_PENALTY_ALPHA,
    SCHEMA_VERSION,
    load_frequency_table,
    penalty,
    record_sample,
    schema_hash,
)

# ─── schema_hash ─────────────────────────────────────────────────────────────


class TestSchemaHash:
    def test_returns_12_hex_chars(self) -> None:
        h = schema_hash()
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self) -> None:
        assert schema_hash() == schema_hash()

    def test_changes_when_version_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = schema_hash()
        monkeypatch.setattr(diversity, "SCHEMA_VERSION", "test-bumped")
        after = schema_hash()
        assert before != after


# ─── record_sample ───────────────────────────────────────────────────────────


class TestRecordSample:
    def test_writes_one_jsonl_row(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        record_sample("structural_inversion", "SI_001", "run-A", path=log)
        text = log.read_text(encoding="utf-8")
        assert text.count("\n") == 1
        row = json.loads(text.strip())
        assert row["axis"] == "structural_inversion"
        assert row["value_id"] == "SI_001"
        assert row["run_id"] == "run-A"
        assert row["schema_hash"] == schema_hash()
        assert "ts" in row  # ISO-8601 timestamp present

    def test_append_only_no_dedup(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        for _ in range(3):
            record_sample("conspiracy_engine", "CE_007", "run-X", path=log)
        assert log.read_text(encoding="utf-8").count("\n") == 3

    def test_unknown_axis_warns_but_writes(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        with caplog.at_level("WARNING", logger="pipeline.diversity"):
            record_sample("nonexistent_axis", "X_1", "run-X", path=log)
        assert log.exists()
        assert any("CANONICAL_AXES" in r.message for r in caplog.records)

    @pytest.mark.parametrize(
        ("axis", "value_id", "run_id"),
        [
            ("", "v", "r"),
            ("a", "", "r"),
            ("a", "v", ""),
        ],
    )
    def test_rejects_empty_inputs(
        self,
        tmp_path: Path,
        axis: str,
        value_id: str,
        run_id: str,
    ) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        with pytest.raises(ValueError):
            record_sample(axis, value_id, run_id, path=log)
        assert not log.exists()


# ─── load_frequency_table ────────────────────────────────────────────────────


class TestLoadFrequencyTable:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_frequency_table(path=tmp_path / "absent.jsonl") == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        assert load_frequency_table(path=p) == {}

    def test_window_runs_zero_returns_empty(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        record_sample("structural_inversion", "SI_001", "run-A", path=log)
        assert load_frequency_table(window_runs=0, path=log) == {}

    def test_counts_roll_up_within_run(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        record_sample("structural_inversion", "SI_001", "run-A", path=log)
        record_sample("structural_inversion", "SI_001", "run-A", path=log)
        record_sample("world_texture", "WT_03", "run-A", path=log)
        table = load_frequency_table(path=log)
        assert table[("structural_inversion", "SI_001")] == 2
        assert table[("world_texture", "WT_03")] == 1

    def test_counts_roll_up_across_runs(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        record_sample("structural_inversion", "SI_001", "run-A", path=log)
        record_sample("structural_inversion", "SI_001", "run-B", path=log)
        record_sample("structural_inversion", "SI_001", "run-C", path=log)
        table = load_frequency_table(path=log)
        assert table[("structural_inversion", "SI_001")] == 3

    def test_window_limits_to_last_n_runs(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        # 5 distinct runs, same axis-value sampled once each.
        for i in range(5):
            record_sample("structural_inversion", "SI_001", f"run-{i}", path=log)
        table = load_frequency_table(window_runs=2, path=log)
        # Only the last 2 runs counted.
        assert table[("structural_inversion", "SI_001")] == 2

    def test_window_keeps_most_recent_runs(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        # Older runs include a value the newer runs don't.
        record_sample("world_texture", "WT_OLD", "run-old", path=log)
        record_sample("world_texture", "WT_NEW", "run-new1", path=log)
        record_sample("world_texture", "WT_NEW", "run-new2", path=log)
        table = load_frequency_table(window_runs=2, path=log)
        assert ("world_texture", "WT_OLD") not in table  # dropped
        assert table[("world_texture", "WT_NEW")] == 2

    def test_skips_rows_with_mismatched_schema_hash(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        # Hand-write a row with a stale schema_hash.
        stale = {
            "ts": "2026-01-01T00:00:00+00:00",
            "schema_hash": "DEADBEEFCAFE",  # not current
            "run_id": "run-old",
            "axis": "structural_inversion",
            "value_id": "SI_GONE",
        }
        log.write_text(json.dumps(stale) + "\n", encoding="utf-8")
        # Add a fresh row that uses the current hash.
        record_sample("structural_inversion", "SI_001", "run-new", path=log)
        table = load_frequency_table(path=log)
        assert ("structural_inversion", "SI_GONE") not in table
        assert table[("structural_inversion", "SI_001")] == 1

    def test_tolerates_malformed_rows(self, tmp_path: Path) -> None:
        log = tmp_path / "axis_frequency.jsonl"
        log.write_text("not-json\n\n{}\n", encoding="utf-8")
        record_sample("structural_inversion", "SI_001", "run-A", path=log)
        # Two malformed + one empty + one missing-fields + one valid -> only valid counts.
        table = load_frequency_table(path=log)
        assert table == {("structural_inversion", "SI_001"): 1}


# ─── penalty ─────────────────────────────────────────────────────────────────


class TestPenalty:
    def test_returns_1_when_freq_table_none(self) -> None:
        assert penalty("a", "v", None) == 1.0

    def test_returns_1_when_freq_table_empty(self) -> None:
        assert penalty("a", "v", {}) == 1.0

    def test_returns_1_when_key_missing(self) -> None:
        table = {("other", "x"): 99}
        assert penalty("a", "v", table) == 1.0

    def test_returns_1_when_alpha_zero(self) -> None:
        table = {("a", "v"): 10}
        assert penalty("a", "v", table, alpha=0.0) == 1.0

    def test_returns_1_when_alpha_negative(self) -> None:
        table = {("a", "v"): 10}
        assert penalty("a", "v", table, alpha=-0.5) == 1.0

    def test_freq_one_returns_half_power_alpha(self) -> None:
        table = {("a", "v"): 1}
        # 1 / (1+1)^0.3 = 0.5^0.3 ≈ 0.8123
        result = penalty("a", "v", table, alpha=0.3)
        assert result == pytest.approx(2.0**-0.3, rel=1e-6)
        assert 0.0 < result < 1.0

    def test_freq_ten_decays_further(self) -> None:
        table = {("a", "v"): 10}
        # 1 / 11^0.3 ≈ 0.487
        result = penalty("a", "v", table, alpha=0.3)
        assert result == pytest.approx(11.0**-0.3, rel=1e-6)
        assert result < 0.5

    def test_monotone_decreasing_in_freq(self) -> None:
        prev = 1.0
        for f in [1, 2, 5, 10, 100]:
            table = {("a", "v"): f}
            cur = penalty("a", "v", table)
            assert cur < prev
            prev = cur

    def test_never_returns_zero(self) -> None:
        table = {("a", "v"): 10_000}
        # With alpha=0.8, 1 / 10001^0.8 > 0 strictly.
        assert penalty("a", "v", table) > 0.0

    def test_default_alpha_is_08(self) -> None:
        # R1 activation (2026-05-29): raised 0.3 -> 0.8 so the raw-sampler
        # ceiling holds for low-sample axes (see pipeline/diversity.py).
        assert pytest.approx(0.8) == DEFAULT_PENALTY_ALPHA


# ─── canonical-axes invariants ───────────────────────────────────────────────


class TestCanonicalAxes:
    def test_axes_are_unique(self) -> None:
        assert len(set(CANONICAL_AXES)) == len(CANONICAL_AXES)

    def test_axes_non_empty(self) -> None:
        assert len(CANONICAL_AXES) > 0
        for a in CANONICAL_AXES:
            assert isinstance(a, str) and a

    def test_schema_version_set(self) -> None:
        assert SCHEMA_VERSION.startswith("v")
