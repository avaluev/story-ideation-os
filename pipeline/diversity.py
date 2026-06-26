"""pipeline.diversity -- cross-run axis-value frequency memory (ADR-0012).

The v4 ``_thematic_weighted_choice`` in ``pipeline/compound_seed.py`` has no
memory of what was sampled in previous runs.  Independent uniform samples
cannot escape a local attractor: once the variable library + scorer prefer
"woman-as-protagonist + institutional cluster", every run drifts back to
that combination.

This module persists per-sample ``(axis, value_id)`` events to a JSONL log,
loads a rolling-window frequency table, and produces a multiplicative
``penalty`` that downweights over-sampled values.

Public surface
==============

- :func:`load_frequency_table` -- read the most recent ``window_runs``
  distinct ``run_id`` rows and return ``{(axis, value_id): count}``.
- :func:`record_sample` -- append one ``(axis, value_id, run_id)`` row.
- :func:`penalty` -- ``1 / (1 + freq) ** alpha`` -- soft, monotone, bounded
  in ``(0, 1]``, with ``alpha`` controlling the decay slope.

Schema-hash invalidation
========================

When the variable library evolves and an old ``value_id`` no longer maps
to a real axis value, counting stale rows would push the sampler away
from currently-valid values.  Every row carries a ``schema_hash``
computed from the canonical axis-name tuple.  ``load_frequency_table``
silently skips any row whose ``schema_hash`` differs from the current
one.  Bumping :data:`SCHEMA_VERSION` is the explicit reset switch.

Pure Python.  No LLM.  No numpy.  ADR-0001 + ADR-0002 + ADR-0012.

MUST NOT be imported from ``pipeline/scoring.py`` (ANOMALY-001).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical axis whitelist + schema hash
# ---------------------------------------------------------------------------

#: Bump when the axis library changes shape (rename, remove, reorder).
#: Older rows in the log are silently ignored when this differs.
#: v5.1.0 — added the ``format`` axis (Feature Film / Limited Series /
#: Returning Series / Animation Feature / Animation Series / Microdrama).
#: Appending it rotates :func:`schema_hash`, which is the deliberate reset
#: of the rolling-window frequency log (old v5.0.0 rows are ignored).
SCHEMA_VERSION: Final[str] = "v5.1.0"

#: The axes the sampler routes through ``_thematic_weighted_choice`` and any
#: future weighted picker.  Listed in stable order so the schema hash is
#: deterministic across processes.
CANONICAL_AXES: Final[tuple[str, ...]] = (
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
    "format",
)

# ---------------------------------------------------------------------------
# Persistence path (ADR-0001)
# ---------------------------------------------------------------------------

#: JSONL log of every ``(axis, value_id, run_id)`` sample event.
DEFAULT_FREQUENCY_PATH: Final[Path] = Path("data/axis_frequency.jsonl")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_RUNS: Final[int] = 20
"""Rolling window over the last N distinct run_id values."""

DEFAULT_PENALTY_ALPHA: Final[float] = 0.8
"""Decay slope for ``penalty``.  alpha=0 => no penalty, alpha=1 => 1/(1+freq).
Raised 0.3 -> 0.8 (R1 activation, 2026-05-29): with a fresh axis-frequency log
the 0.3 penalty left a low-sample, 30%-inclusion axis (``historical_transplant``)
collapsed at 64% over the rolling window (0.6 -> 50%), breaching the ADR-0012
raw-sampler ceiling. 0.8 spreads rare-axis sampling under the 40% ceiling while
still keeping the multiplier above zero for typical fan-out (no rare-axis
starvation; the penalty floor at high freq stays > 0)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def schema_hash() -> str:
    """SHA-256/12 of ``SCHEMA_VERSION + CANONICAL_AXES``.

    Stable across processes.  Truncated to 12 hex chars for compact JSONL.
    """
    payload = SCHEMA_VERSION + "|" + ",".join(CANONICAL_AXES)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def record_sample(
    axis: str,
    value_id: str,
    run_id: str,
    *,
    path: Path | str = DEFAULT_FREQUENCY_PATH,
) -> None:
    """Append one sample event to the frequency log.

    Multiple samples per (axis, value_id, run_id) are legitimate (multi-pick
    axes like ``conspiracy_engine`` sample 1-3 values per run) so this is a
    pure append -- no deduplication.

    Args:
        axis: A name from :data:`CANONICAL_AXES`.  Unknown axes are still
            written (forward-compatible) but get logged at WARNING.
        value_id: The library row's ``id`` field.  Empty / None is rejected.
        run_id: A run identifier that groups samples from the same
            ``CompoundSeedEngine.generate()`` call.
        path: Override for testing.

    Raises:
        ValueError: when any required field is empty.
    """
    if not axis:
        raise ValueError("axis must be a non-empty string")
    if not value_id:
        raise ValueError("value_id must be a non-empty string")
    if not run_id:
        raise ValueError("run_id must be a non-empty string")

    if axis not in CANONICAL_AXES:
        _log.warning(
            "record_sample: axis %r not in CANONICAL_AXES; rows may be "
            "lost on the next SCHEMA_VERSION bump",
            axis,
        )

    row = {
        "ts": datetime.now(UTC).isoformat(),
        "schema_hash": schema_hash(),
        "run_id": run_id,
        "axis": axis,
        "value_id": value_id,
    }
    append_jsonl(path, row)


def load_frequency_table(
    window_runs: int = DEFAULT_WINDOW_RUNS,
    *,
    path: Path | str = DEFAULT_FREQUENCY_PATH,
) -> dict[tuple[str, str], int]:
    """Return ``{(axis, value_id): count}`` over the last ``window_runs`` runs.

    Rows whose ``schema_hash`` differs from the current :func:`schema_hash`
    are silently skipped -- old (axis, value) pairs that no longer exist
    must not bias the sampler.

    Args:
        window_runs: How many of the most-recently-seen distinct
            ``run_id`` values to count.  Default :data:`DEFAULT_WINDOW_RUNS`.
        path: Override for testing.

    Returns:
        A new dict.  Empty dict when the file does not exist, is empty, or
        contains no rows with a matching schema_hash.
    """
    if window_runs <= 0:
        return {}

    file_path = Path(path)
    if not file_path.exists():
        return {}

    current_hash = schema_hash()
    # OrderedDict preserves insertion order -> the most recent N keys.
    run_id_order: OrderedDict[str, None] = OrderedDict()
    # Per-run buckets allow exact "last N runs" semantics.
    per_run_counts: dict[str, dict[tuple[str, str], int]] = {}

    with open(file_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                _log.warning("load_frequency_table: skipping malformed JSONL row")
                continue
            if row.get("schema_hash") != current_hash:
                continue
            run_id = row.get("run_id")
            axis = row.get("axis")
            value_id = row.get("value_id")
            if not run_id or not axis or not value_id:
                continue

            # Track first-seen order; if we see this run_id again, move it
            # to the end so the rolling window picks up the latest activity.
            if run_id in run_id_order:
                run_id_order.move_to_end(run_id)
            else:
                run_id_order[run_id] = None
            bucket = per_run_counts.setdefault(run_id, {})
            key = (axis, value_id)
            bucket[key] = bucket.get(key, 0) + 1

    if not run_id_order:
        return {}

    # Keep only the most recent window_runs run_ids.
    kept_runs = list(run_id_order.keys())[-window_runs:]
    table: dict[tuple[str, str], int] = {}
    for run_id in kept_runs:
        for key, count in per_run_counts[run_id].items():
            table[key] = table.get(key, 0) + count
    return table


def penalty(
    axis: str,
    value_id: str,
    freq_table: dict[tuple[str, str], int] | None,
    alpha: float = DEFAULT_PENALTY_ALPHA,
) -> float:
    """Soft frequency-decay multiplier in ``(0, 1]``.

    Formula::

        penalty = 1 / (1 + freq) ** alpha

    ``freq=0`` returns ``1.0`` (no penalty, brand-new value).
    ``freq=1`` returns ``1 / 2 ** alpha`` (~0.81 at alpha=0.3).
    ``freq=10`` returns ``1 / 11 ** alpha`` (~0.49 at alpha=0.3).

    The penalty is monotone non-increasing in ``freq`` and bounded below
    by 0 (never zero for finite alpha).  ``alpha <= 0`` disables the
    penalty entirely (returns 1.0) -- useful for production-vs-test toggles.

    Args:
        axis: Canonical axis name.
        value_id: Library row id.
        freq_table: Output of :func:`load_frequency_table`.  ``None`` or
            empty disables the penalty (returns 1.0).
        alpha: Decay slope.  Default :data:`DEFAULT_PENALTY_ALPHA` (0.3).

    Returns:
        Float in ``(0.0, 1.0]``.
    """
    if not freq_table or alpha <= 0.0:
        return 1.0
    freq = freq_table.get((axis, value_id), 0)
    if freq <= 0:
        return 1.0
    return 1.0 / ((1.0 + float(freq)) ** alpha)


__all__ = [
    "CANONICAL_AXES",
    "DEFAULT_FREQUENCY_PATH",
    "DEFAULT_PENALTY_ALPHA",
    "DEFAULT_WINDOW_RUNS",
    "SCHEMA_VERSION",
    "load_frequency_table",
    "penalty",
    "record_sample",
    "schema_hash",
]
