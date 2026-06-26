"""Format axis (v5.1.0) — the 20th CANONICAL_AXES entry, routed through the
ADR-0012 diversity penalty.

Mission: the engine must produce ideas across distinct content FORMATS
(Feature Film, Limited Series, Returning Series, Animation Feature,
Animation Series, Microdrama) with the same cross-run anti-clumping memory
that governs every other narrative axis. Adding ``format`` to
``CANONICAL_AXES`` also rotates ``schema_hash`` — the deliberate v5.1.0
reset of the rolling-window frequency log.

Hermetic: tmp_path only, no network (conftest blanks provider keys).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from pipeline import diversity

#: The v5.0.0 axis tuple, frozen here so we can prove the schema_hash rotated
#: when ``format`` was appended. Do NOT import this from diversity — the point
#: is to compare the live hash against the historical one.
_V5_0_0_AXES: tuple[str, ...] = (
    "protagonist_archetype",
    "antagonist_archetype",
    "dark_archetype",
    "structural_inversion",
    "moral_fault_line",
    "psychological_pattern",
    "sdt_wound",
    "divisiveness_engine",
    "world_texture",
    "civilizational_stake",
    "methodology_protagonist",
    "historical_transplant",
    "era_collision",
    "conspiracy_engine",
    "reptile_trigger",
    "open_problem",
    "cultural_moment",
    "ally_archetype",
    "compression_key",
)


def _hash_for(version: str, axes: tuple[str, ...]) -> str:
    payload = version + "|" + ",".join(axes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def test_format_is_a_canonical_axis() -> None:
    assert "format" in diversity.CANONICAL_AXES
    assert len(diversity.CANONICAL_AXES) == 20
    # format is appended last (stable ordering => deterministic schema hash).
    assert diversity.CANONICAL_AXES[-1] == "format"


def test_schema_version_bumped_to_v5_1_0() -> None:
    assert diversity.SCHEMA_VERSION == "v5.1.0"


def test_schema_hash_rotated_off_v5_0_0() -> None:
    """Adding the format axis MUST change the schema hash so every stale
    v5.0.0 row in data/axis_frequency.jsonl is silently ignored (the
    intended cold-start reset)."""
    old_hash = _hash_for("v5.0.0", _V5_0_0_AXES)
    assert diversity.schema_hash() != old_hash
    # And it equals the recomputed v5.1.0 hash over the live axis tuple.
    assert diversity.schema_hash() == _hash_for(diversity.SCHEMA_VERSION, diversity.CANONICAL_AXES)


def test_record_format_sample_no_warning(tmp_path, caplog) -> None:
    """record_sample('format', ...) must NOT warn — format is a known axis."""
    log_path = tmp_path / "freq.jsonl"
    with caplog.at_level("WARNING", logger="pipeline.diversity"):
        diversity.record_sample("format", "FMT_06", run_id="t1", path=log_path)
    assert log_path.exists()
    assert "not in CANONICAL_AXES" not in caplog.text
    # The row carries the current (v5.1.0) schema hash.

    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["axis"] == "format"
    assert row["value_id"] == "FMT_06"
    assert row["schema_hash"] == diversity.schema_hash()


def test_format_penalty_downweights_oversampled_format() -> None:
    """An over-sampled format gets a strictly lower multiplier than a
    brand-new one — the anti-overfit pressure that spreads the slate
    across formats."""
    freq_table = {("format", "FMT_01"): 12, ("format", "FMT_06"): 0}
    over = diversity.penalty("format", "FMT_01", freq_table)
    fresh = diversity.penalty("format", "FMT_06", freq_table)
    assert over < fresh
    assert fresh == pytest.approx(1.0)
    assert 0.0 < over < 1.0
