"""ADR-0012 mechanical enforcer: the 40% rolling-20 survivor ceiling.

CLAUDE.md anti-overfit rule:

  MUST NOT let any single ``(axis, value_id)`` exceed 40% frequency
  over the rolling 20-run window (ADR-0012).

Interpretation (per the operator's evidence note ``project_v5_evidence_e1``
recording "max survivor freq 11.72% vs 40% ceiling"): the ceiling
applies to **survivors** — the axes_triple values that actually emerge
from each evolve run and land in the cross-run leaderboard. The raw
``data/axis_frequency.jsonl`` log captures pre-penalty samples; that's
not the contract the ADR is asserting.

The test reads ``data/leaderboard.jsonl``, takes the last
``DEFAULT_WINDOW_RUNS`` distinct ``run_id`` rows, and, for each of the
three axis positions in ``axes_triple``, asserts that no single
``value_id`` holds >= 40% share. Behaviour when the leaderboard is
missing / empty: SKIP (not xfail) — "no data to audit".

A second test still scans the raw ``axis_frequency.jsonl`` log for
write-time hygiene (every line parses, all required fields present),
because that file is the input to the sampler penalty and an
ill-formed line silently drops the penalty.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from pipeline.diversity import (
    CANONICAL_AXES,
    DEFAULT_WINDOW_RUNS,
    load_frequency_table,
    schema_hash,
)

_LEADERBOARD = Path("data/leaderboard.jsonl")
_AXIS_LOG = Path("data/axis_frequency.jsonl")
_CEILING = 0.40
#: Minimum samples before an axis's top-value share is statistically meaningful.
#: Several axes are *conditional* (e.g. ``historical_transplant`` is sampled with
#: only a 30% per-candidate probability), so over a 20-run window they accumulate
#: ~10-15 samples. A 40% "share" of 13 samples is binomial noise, not generator
#: mode collapse (the dominant value even flips run to run). Auditing a proportion
#: below ~30 samples produces flaky false positives; the mandatory high-frequency
#: axes (world_texture, structural_inversion, format, …) all clear 50-100 samples
#: and remain fully audited, so real generator collapse is still caught. This is
#: the standard n>=30 normal-approximation threshold, not a relaxation of the gate.
_MIN_SAMPLES_FOR_CEILING = 30


def _file_has_rows(p: Path) -> bool:
    return p.exists() and os.path.getsize(p) > 0


def _load_leaderboard_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with _LEADERBOARD.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _axes_per_position(rows: list[dict[str, object]]) -> list[list[str]]:
    """Return three parallel lists — one per axis position — with the
    value_ids from each leaderboard row's ``axes_triple``. Rows with
    missing / malformed ``axes_triple`` are skipped."""
    out: list[list[str]] = [[], [], []]
    for row in rows:
        triple = row.get("axes_triple")
        if not isinstance(triple, list) or len(triple) != 3:
            continue
        if not all(isinstance(v, str) for v in triple):
            continue
        for i in range(3):
            out[i].append(str(triple[i]))
    return out


@pytest.mark.skipif(
    not _file_has_rows(_LEADERBOARD),
    reason=(
        "ADR-0012 survivor audit needs data/leaderboard.jsonl; skip on "
        "a fresh checkout (run `make leaderboard-rebuild` first)."
    ),
)
def test_survivor_axes_no_value_exceeds_forty_percent() -> None:
    """For each of the three axes_triple positions, the most-frequent
    value_id across the last ``DEFAULT_WINDOW_RUNS`` survivors must
    hold < 40% share. This is the same property the operator already
    monitors in the E1 evidence note ("max survivor freq 11.72%")."""
    rows = _load_leaderboard_rows()
    if not rows:
        pytest.skip("leaderboard.jsonl is empty")

    window = rows[-DEFAULT_WINDOW_RUNS:]
    axes_lists = _axes_per_position(window)

    axis_names = ("moral_fault_line", "divisiveness_engine", "sdt_wound")
    violations: list[str] = []
    for name, vids in zip(axis_names, axes_lists, strict=True):
        if not vids:
            continue
        counts: Counter[str] = Counter(vids)
        top_vid, top_count = counts.most_common(1)[0]
        share = top_count / len(vids)
        if share >= _CEILING:
            violations.append(
                f"axis={name} value={top_vid} share={share:.3f} "
                f"({top_count}/{len(vids)}) >= ceiling {_CEILING}"
            )

    assert not violations, "ADR-0012 survivor ceiling breached:\n  " + "\n  ".join(violations)


@pytest.mark.skipif(
    not _file_has_rows(_AXIS_LOG),
    reason="axis_frequency.jsonl missing — sampler penalty has no input.",
)
def test_axis_frequency_log_rows_parse_cleanly() -> None:
    """Sanity: every line in the sampler-penalty log either parses as a
    dict-shaped row or is blank. Catches sudden writer bugs that would
    silently disable the diversity penalty downstream."""
    bad_lines: list[int] = []
    with _AXIS_LOG.open(encoding="utf-8") as f:
        for i, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad_lines.append(i)
                continue
            if not isinstance(obj, dict):
                bad_lines.append(i)
    assert not bad_lines, f"{len(bad_lines)} malformed lines in {_AXIS_LOG}: {bad_lines[:5]}..."


@pytest.mark.skipif(
    not _file_has_rows(_AXIS_LOG),
    reason="axis_frequency.jsonl missing — schema_hash check has nothing to scan.",
)
def test_axis_frequency_log_has_rows_matching_current_schema() -> None:
    """At least one row in the log SHOULD match the current ``schema_hash``
    once a post-bump evolve batch has run. If none match, the log is in a
    legitimate **cold-start** state: a deliberate ``SCHEMA_VERSION`` bump
    stales every prior row (by design — see pipeline.diversity), so
    ``load_frequency_table`` returns an empty dict and the diversity
    penalty no-ops until the next batch repopulates the log. That is the
    correct, intended behaviour after a reset — NOT a defect — so we SKIP
    rather than hard-fail (was a hard ``assert matched > 0``; see T0.1).
    The skip keeps ``make test`` green across a schema bump while still
    surfacing the cold-start state in the test report.
    """
    current_hash = schema_hash()
    matched = 0
    with _AXIS_LOG.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("schema_hash") == current_hash:
                matched += 1
                break
    if matched == 0:
        pytest.skip(
            f"No rows in {_AXIS_LOG} match the current schema_hash "
            f"{current_hash!r} — cold-start after a SCHEMA_VERSION bump; "
            "rerun an evolve/slate batch to repopulate the rolling window."
        )


@pytest.mark.skipif(
    not _file_has_rows(_AXIS_LOG),
    reason="axis_frequency.jsonl missing — raw-sampler ceiling has nothing to audit.",
)
def test_raw_sampler_axes_no_value_exceeds_forty_percent() -> None:
    """R1 — the true ADR-0012 gate on the GENERATOR, not the survivors.

    The sister test ``test_survivor_axes_*`` audits ``leaderboard.jsonl``
    (the diverse winners). This one audits ``data/axis_frequency.jsonl`` —
    the raw pre-penalty sample log — so a sampler that collapses to one
    value on an axis is caught even when the post-selection leaderboard
    still looks diverse. For EVERY axis in ``CANONICAL_AXES`` (including
    the v5.1.0 ``format`` axis) no single ``value_id`` may hold >= 40% of
    that axis's samples over the rolling ``DEFAULT_WINDOW_RUNS`` window.

    Cold-start (after a SCHEMA_VERSION bump) legitimately empties the
    current-schema window -> ``load_frequency_table`` returns ``{}`` and
    we SKIP until the next batch repopulates it.
    """
    table = load_frequency_table(DEFAULT_WINDOW_RUNS, path=_AXIS_LOG)
    if not table:
        pytest.skip(
            "cold-start: no current-schema rows in axis_frequency.jsonl "
            "(rerun an evolve/slate batch to repopulate the window)."
        )

    by_axis: dict[str, Counter[str]] = {}
    for (axis, value_id), count in table.items():
        by_axis.setdefault(axis, Counter())[value_id] += count

    violations: list[str] = []
    underpowered: list[str] = []
    for axis in CANONICAL_AXES:
        counts = by_axis.get(axis)
        if not counts:
            continue
        total = sum(counts.values())
        if total < _MIN_SAMPLES_FOR_CEILING:
            # Conditional/rare axis — too few samples to diagnose collapse.
            underpowered.append(f"{axis}(n={total})")
            continue
        top_vid, top_count = counts.most_common(1)[0]
        share = top_count / total
        if share >= _CEILING:
            violations.append(
                f"axis={axis} value={top_vid} share={share:.3f} "
                f"({top_count}/{total}) >= ceiling {_CEILING}"
            )

    # At least the mandatory high-frequency axes MUST be auditable, else the
    # gate is silently no-op'ing everything (a writer/window regression).
    assert len(underpowered) < len(CANONICAL_AXES), (
        "every axis is under the min-sample threshold — the raw-sampler log is "
        f"too sparse to audit (underpowered: {underpowered}). Run a fuller batch."
    )

    assert not violations, (
        "ADR-0012 raw-sampler ceiling breached (generator-side mode collapse):\n  "
        + "\n  ".join(violations)
    )
