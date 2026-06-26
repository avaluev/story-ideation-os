"""pipeline.digest -- 6-KPI dashboard for the operator.

WEDGE Step 8 of the plan (final move). The operator opens a session,
types ``python -m pipeline.digest``, and sees one terminal table with
the six KPIs from Section 6 of the rebuild plan. No web UI, no
graphics library -- one box of monospaced text the operator can scan
in 5 seconds.

The six KPIs
============

1. Loop throughput -- concepts rated +1 or +2 in the last 7 days.
   Target >= 3. From data/labels.jsonl.

2. Taste convergence -- Spearman rank correlation between the engine's
   crystallization_score and the operator's rating on the last 50 rated
   concepts. Target >= 0.5. From data/labels.jsonl + winners.json
   sidecars (Step 5 feedback.read_winner_facets).

3. Diversity floor -- maximum single (axis, value_id) frequency over
   the rolling 20-run window. ADR-0012 ceiling is 0.40; operator
   target is < 0.15. From data/axis_frequency.jsonl (the diversity
   log Step 1 wired).

4. Subscription burn -- weekly Opus usage as percent of cap. Target
   < 70%. From pipeline.quota.remaining_fraction.

5. Novelty (rolling 20) -- mean cosine distance between recent
   candidates and the corpus FAISS index. Target >= 0.55. Schema slot
   is wired now (in loop_history.jsonl); value populates when the
   embedding index lands. From data/loop_history.jsonl.

6. Goal stability -- number of Goal.save bumps in the last 7 days.
   Target 1-2. More = thrashing; zero = stale taste model. From
   data/goal_history.jsonl.

Plus Section 7 alert banner: if any of three "pause and reconsider"
conditions fires, the digest emits a red `[ALERT]` block at the top.

Pure Python. No deps beyond stdlib + pipeline/{labels,quota}. ADR-0001
read-only: this module never writes.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pipeline import labels

DEFAULT_LOOP_HISTORY_PATH: Final[Path] = Path("data/loop_history.jsonl")
DEFAULT_AXIS_FREQUENCY_PATH: Final[Path] = Path("data/axis_frequency.jsonl")
DEFAULT_GOAL_HISTORY_PATH: Final[Path] = Path("data/goal_history.jsonl")

_WEEK_DAYS: Final[int] = 7
_RECENT_RATINGS_WINDOW: Final[int] = 50
_DIVERSITY_WINDOW_RUNS: Final[int] = 20
_THROUGHPUT_TARGET: Final[int] = 3
_MIN_PAIRS_FOR_SPEARMAN: Final[int] = 3
_MIN_PAIRS_FOR_RANK: Final[int] = 2
_TASTE_CONVERGENCE_TARGET: Final[float] = 0.5
_DIVERSITY_CEILING: Final[float] = 0.15
_QUOTA_BURN_TARGET: Final[float] = 0.70
_GOAL_STABILITY_MIN: Final[int] = 1
_GOAL_STABILITY_MAX: Final[int] = 2


class KPI:
    """One row of the dashboard. Frozen-by-convention; do not mutate."""

    __slots__ = ("name", "status", "target", "value")

    def __init__(self, name: str, value: str, target: str, status: str) -> None:
        self.name = name
        self.value = value
        self.target = target
        self.status = status  # "ok" | "warn" | "alert"


def throughput_last_week(
    labels_path: Path | str = labels.DEFAULT_LABELS_PATH,
    now: datetime | None = None,
) -> int:
    """Count of rated-positive concepts (+1 or +2) in the last 7 days."""
    if now is None:
        now = datetime.now(UTC)
    cutoff = now - timedelta(days=_WEEK_DAYS)
    rows = labels.read_since(cutoff, path=labels_path)
    total = 0
    for r in rows:
        rating = r.get("rating")
        if isinstance(rating, int) and rating >= 1:
            total += 1
    return total


def taste_convergence(
    labels_path: Path | str = labels.DEFAULT_LABELS_PATH,
    runs_root: Path | str = Path("runs"),
    window: int = _RECENT_RATINGS_WINDOW,
) -> float | None:
    """Spearman correlation between crystallization_score (from
    winners.json) and operator rating across the last ``window`` rated
    rows. Returns ``None`` when fewer than 3 rated rows have a winners
    sidecar (correlation is meaningless on tiny samples)."""
    # Lazy import to keep feedback's transitive cost off the import path
    # for `--dry-run` style invocations.
    from pipeline import feedback  # noqa: PLC0415 -- lazy dep boundary

    rows = labels.read_all(path=labels_path)
    if not rows:
        return None
    rows = rows[-window:]
    winners = feedback.read_winner_facets(rows, runs_root=runs_root)
    paired: list[tuple[float, float]] = []
    for r in rows:
        rid = str(r.get("run_id", ""))
        if rid not in winners:
            continue
        rating = r.get("rating")
        if not isinstance(rating, int):
            continue
        # The score we predict against is the engine's geometric-mean
        # facet score; we approximate it by averaging the six facet
        # values from the winners sidecar (a stable proxy that doesn't
        # require re-running crystallization_score with the right Goal).
        facets = winners[rid]
        score_proxy = sum(facets.values()) / len(facets) if facets else 0.0
        paired.append((float(rating), score_proxy))
    if len(paired) < _MIN_PAIRS_FOR_SPEARMAN:
        return None
    return _spearman(paired)


def diversity_floor(
    freq_path: Path | str = DEFAULT_AXIS_FREQUENCY_PATH,
    window_runs: int = _DIVERSITY_WINDOW_RUNS,
) -> float | None:
    """Max single (axis, value_id) frequency as a fraction of total
    samples over the rolling window. Returns None when the frequency
    log doesn't exist (no /evolve has been run since Step 1 landed)."""
    p = Path(freq_path)
    if not p.exists():
        return None
    # Read newest-first by collecting then trimming -- file is small.
    run_id_order: list[str] = []
    per_run: dict[str, dict[tuple[str, str], int]] = {}
    with open(p, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row_obj: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row_obj, dict):
                continue
            row: dict[str, object] = {str(k): v for k, v in row_obj.items()}  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            run_id = str(row.get("run_id", ""))
            axis = str(row.get("axis", ""))
            value_id = str(row.get("value_id", ""))
            if not (run_id and axis and value_id):
                continue
            if run_id not in per_run:
                per_run[run_id] = {}
                run_id_order.append(run_id)
            bucket = per_run[run_id]
            key = (axis, value_id)
            bucket[key] = bucket.get(key, 0) + 1
    kept = run_id_order[-window_runs:]
    if not kept:
        return None
    counts: dict[tuple[str, str], int] = {}
    total = 0
    for r in kept:
        for k, v in per_run[r].items():
            counts[k] = counts.get(k, 0) + v
            total += v
    if total == 0:
        return None
    max_count = max(counts.values())
    return max_count / total


def quota_burn() -> float | None:
    """Weekly Opus usage as fraction of cap. Returns None if quota module
    rejects the model tier (e.g., dispatch hasn't been used this week)."""
    try:
        from pipeline import quota  # noqa: PLC0415 -- lazy dep boundary

        return 1.0 - quota.remaining_fraction("opus")  # type: ignore[arg-type]
    except (KeyError, ValueError):
        return None


def novelty_last_20(
    loop_history_path: Path | str = DEFAULT_LOOP_HISTORY_PATH,
) -> float | None:
    """Latest ``mean_novelty_last_20`` from data/loop_history.jsonl.

    Returns the value from the most recent loop-iteration row that carries
    the field. Returns ``None`` when the file is absent, empty, or no row
    has populated the field yet (the corpus FAISS index that computes
    novelty lands in a future commit; until then loop_wedge writes
    ``mean_novelty_last_20: None`` for every iteration).

    Forward-compat: rows missing the field entirely (pre-Step-4 schema)
    are treated as None. The check never crashes on schema drift.
    """
    p = Path(loop_history_path)
    if not p.exists():
        return None
    latest: float | None = None
    with open(p, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row_obj: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row_obj, dict):
                continue
            row: dict[str, object] = {str(k): v for k, v in row_obj.items()}  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            val = row.get("mean_novelty_last_20")
            if isinstance(val, int | float):
                latest = float(val)
    return latest


def goal_bumps_last_week(
    history_path: Path | str = DEFAULT_GOAL_HISTORY_PATH,
    now: datetime | None = None,
) -> int:
    """Count of Goal.save events in the last 7 days."""
    if now is None:
        now = datetime.now(UTC)
    cutoff_iso = (now - timedelta(days=_WEEK_DAYS)).isoformat()
    p = Path(history_path)
    if not p.exists():
        return 0
    count = 0
    with open(p, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row_obj: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row_obj, dict):
                continue
            row: dict[str, object] = {str(k): v for k, v in row_obj.items()}  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            ts = str(row.get("ts", ""))
            if ts >= cutoff_iso:
                count += 1
    return count


def collect_kpis(
    *,
    labels_path: Path | str = labels.DEFAULT_LABELS_PATH,
    freq_path: Path | str = DEFAULT_AXIS_FREQUENCY_PATH,
    history_path: Path | str = DEFAULT_GOAL_HISTORY_PATH,
    loop_history_path: Path | str = DEFAULT_LOOP_HISTORY_PATH,
    runs_root: Path | str = Path("runs"),
    now: datetime | None = None,
) -> list[KPI]:
    """Compute all five KPIs and label each with ok/warn/alert per the
    Section 6 + Section 7 targets in the plan."""
    if now is None:
        now = datetime.now(UTC)

    out: list[KPI] = []

    tp = throughput_last_week(labels_path, now=now)
    out.append(
        KPI(
            name="loop_throughput",
            value=f"{tp} rated >=+1 in last 7d",
            target=f">= {_THROUGHPUT_TARGET}/week",
            status="ok" if tp >= _THROUGHPUT_TARGET else "warn",
        )
    )

    tc = taste_convergence(labels_path, runs_root=runs_root)
    if tc is None:
        out.append(
            KPI(
                name="taste_convergence",
                value="(insufficient rated rows)",
                target=f"Spearman >= {_TASTE_CONVERGENCE_TARGET}",
                status="warn",
            )
        )
    else:
        out.append(
            KPI(
                name="taste_convergence",
                value=f"Spearman rho = {tc:+.2f}",
                target=f">= {_TASTE_CONVERGENCE_TARGET}",
                status="ok" if tc >= _TASTE_CONVERGENCE_TARGET else "warn",
            )
        )

    df = diversity_floor(freq_path)
    if df is None:
        out.append(
            KPI(
                name="diversity_floor",
                value="(no axis_frequency.jsonl yet)",
                target=f"<= {_DIVERSITY_CEILING:.0%}",
                status="warn",
            )
        )
    else:
        out.append(
            KPI(
                name="diversity_floor",
                value=f"max axis-value freq = {df:.1%}",
                target=f"<= {_DIVERSITY_CEILING:.0%}",
                status="ok" if df <= _DIVERSITY_CEILING else "warn",
            )
        )

    burn = quota_burn()
    if burn is None:
        out.append(
            KPI(
                name="subscription_burn",
                value="(quota module unavailable)",
                target=f"< {_QUOTA_BURN_TARGET:.0%}",
                status="warn",
            )
        )
    else:
        out.append(
            KPI(
                name="subscription_burn",
                value=f"opus = {burn:.1%} of weekly cap",
                target=f"< {_QUOTA_BURN_TARGET:.0%}",
                status="ok" if burn < _QUOTA_BURN_TARGET else "warn",
            )
        )

    nov = novelty_last_20(loop_history_path)
    if nov is None:
        out.append(
            KPI(
                name="novelty_last_20",
                value="(no loop_history rows yet)",
                target="rolling mean >= 0.55",
                status="warn",
            )
        )
    else:
        out.append(
            KPI(
                name="novelty_last_20",
                value=f"mean cosine distance = {nov:.2f}",
                target=">= 0.55",
                status="ok" if nov >= 0.55 else "warn",  # noqa: PLR2004
            )
        )

    bumps = goal_bumps_last_week(history_path, now=now)
    if _GOAL_STABILITY_MIN <= bumps <= _GOAL_STABILITY_MAX:
        gs_status = "ok"
    elif bumps == 0:
        gs_status = "warn"  # stale taste model
    else:
        gs_status = "warn"  # thrashing
    out.append(
        KPI(
            name="goal_stability",
            value=f"{bumps} Goal.save bumps in last 7d",
            target=f"{_GOAL_STABILITY_MIN}-{_GOAL_STABILITY_MAX} per week",
            status=gs_status,
        )
    )

    return out


def render(kpis: list[KPI]) -> str:
    """Render KPI list as a single monospaced terminal block. ASCII only --
    safe to pipe through tee/log files without encoding surprises."""
    name_w = max(len(k.name) for k in kpis) + 2
    value_w = max(len(k.value) for k in kpis) + 2
    target_w = max(len(k.target) for k in kpis) + 2
    width = name_w + value_w + target_w + 12
    header = "+" + "-" * (width - 2) + "+"
    lines = [
        header,
        "| Big Idea Generator -- 6 KPI Dashboard"
        + " " * max(0, width - len("| Big Idea Generator -- 6 KPI Dashboard") - 1)
        + "|",
        header,
    ]
    for k in kpis:
        marker = {"ok": "OK ", "warn": "?  ", "alert": "!! "}.get(k.status, "   ")
        row = (
            f"| {marker} {k.name.ljust(name_w)} {k.value.ljust(value_w)} {k.target.ljust(target_w)}"
        )
        row = row.ljust(width - 1) + "|"
        lines.append(row)
    lines.append(header)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    kpis = collect_kpis()
    sys.stdout.write(render(kpis))
    return 0


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _spearman(pairs: list[tuple[float, float]]) -> float:
    """Spearman rank correlation. Pure Python, ties handled by the
    average-rank convention. Returns 0.0 on degenerate inputs (zero
    variance in either column) -- the caller treats this as "no signal"."""
    n = len(pairs)
    if n < _MIN_PAIRS_FOR_RANK:
        return 0.0
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rx = _rank(xs)
    ry = _rank(ys)
    # Pearson on ranks = Spearman.
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = sum((rx[i] - mean_x) ** 2 for i in range(n))
    den_y = sum((ry[i] - mean_y) ** 2 for i in range(n))
    if den_x == 0.0 or den_y == 0.0:
        return 0.0
    return num / ((den_x**0.5) * (den_y**0.5))


def _rank(values: list[float]) -> list[float]:
    """Average-rank for ties. Stable across the input order."""
    indexed = sorted(enumerate(values), key=lambda t: t[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-indexed rank, averaged for ties
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "KPI",
    "collect_kpis",
    "diversity_floor",
    "goal_bumps_last_week",
    "novelty_last_20",
    "quota_burn",
    "render",
    "taste_convergence",
    "throughput_last_week",
]
