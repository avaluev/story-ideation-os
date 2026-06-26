"""Cross-run leaderboard for the Anomaly Engine (v7.0 Stage F0 — the mirror).

Walks ``runs/evolve-*/evolve/gen0/winners.json``, extracts the top-1 winner
from each run, and emits two artifacts that give the operator a single-pane
view across every evolve run ever produced:

- ``data/leaderboard.jsonl`` — one row per top-1 winner, append-only history.
- ``out/leaderboard.html``   — sortable HTML table with Chart.js SOM /
  crystallization trends and a flashing mode-collapse alarm.

Mode collapse is detected when the same ``(moral_fault_line.id,
divisiveness_engine.id, sdt_wound.id)`` triple appears two or more times in
the last ``window`` runs (default 10). This is the v7 plan's diagnostic for
the v5 anti-overfit window being too short for sustained day-long cadence.

ADR-0001  state durability: every persisted artifact uses ``safe_write``.
ADR-0002  no arithmetic of its own — surfaces values composed elsewhere
          (revenue.som_y1_usd, candidate.scores.genius_score, top-level
          crystallization_score).
ADR-0005  no imports from ``frameworks/``.
ADR-0007  no LLM clients — read-only over already-persisted artifacts.

Reuses ``pipeline.state.safe_write`` for the JSONL and HTML writes. The
HTML mirrors the dark-cinematic palette from ``pipeline.export_html`` so
the operator sees a consistent aesthetic across artifacts.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pipeline.state import safe_write

_log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
RUNS_ROOT: Path = REPO_ROOT / "runs"
DATA_ROOT: Path = REPO_ROOT / "data"
OUT_ROOT: Path = REPO_ROOT / "out"
DEFAULT_JSONL_PATH: Path = DATA_ROOT / "leaderboard.jsonl"
DEFAULT_HTML_PATH: Path = OUT_ROOT / "leaderboard.html"
DEFAULT_CSV_PATH: Path = DATA_ROOT / "leaderboard.csv"

DEFAULT_TOP_K: int = 100
DEFAULT_MODE_COLLAPSE_WINDOW: int = 10
_MIN_REPEAT_FOR_ALARM: int = 2
_LOGLINE_MAX_CHARS: int = 160
_WORLD_CELL_MAX_CHARS: int = 56
_HOOK_CELL_MAX_CHARS: int = 110
_TRIPLE_LEN: int = 3  # (moral_fault_line, divisiveness_engine, sdt_wound)
_COMP_TOP_K: int = 3
_TS_RE = re.compile(r"^evolve-(\d{8}T\d{6}Z)$")
_CDN_CHART_JS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"

# Type aliases — kept local; mypy/pyright resolve via the function signatures.
AxesTriple = tuple[str | None, str | None, str | None]


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompRef:
    """One comparable film cited by the revenue projection.

    The revenue model emits a ranked list of similar real films (with their
    WW gross) — the leaderboard surfaces the top few so the operator can see
    where in the commercial landscape each concept actually lands.
    """

    title: str
    similarity: float | None
    ww_gross_usd: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "similarity": self.similarity,
            "ww_gross_usd": self.ww_gross_usd,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CompRef:
        return cls(
            title=str(d.get("title", "")),
            similarity=_float_or_none(d.get("similarity")),
            ww_gross_usd=_float_or_none(d.get("ww_gross_usd")),
        )


@dataclass(frozen=True)
class LeaderboardRow:
    """One top-1 winner row, derived from a single evolve run.

    Core fields (always set on a successful parse) carry the headline
    metrics; the ``world / moral_wager / protagonist / antagonist / wound /
    conflict / compression / divisiveness / top_comps`` fields carry the
    *idea essence* — the engine's creative output, not the operator's input
    theme — so the operator can review a run without opening winners.json.
    """

    # Core identity + headline metrics.
    run_id: str
    produced_at: str  # ISO-8601 UTC; derived from the run-id timestamp
    top1_logline: str  # synthesized "world: moral wager" preview line
    som_y1_usd: float | None
    crystallization_score: float | None
    genius_score: float | None
    cluster_label: str | None
    axes_triple: AxesTriple
    winners_path: str  # repo-relative

    # Idea-essence fields (v7.0 F0.1) — every one is optional so older
    # leaderboard.jsonl rows round-trip cleanly.
    world: str | None = None
    moral_wager: str | None = None
    protagonist: str | None = None
    antagonist: str | None = None
    wound: str | None = None
    conflict: str | None = None
    compression: str | None = None
    divisiveness: str | None = None
    top_comps: tuple[CompRef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view (tuples → lists)."""
        d = asdict(self)
        d["axes_triple"] = list(self.axes_triple)
        d["top_comps"] = [c.to_dict() for c in self.top_comps]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LeaderboardRow:
        """Inverse of :meth:`to_dict`. Defensive about missing optional fields."""
        triple_raw_obj = d.get("axes_triple") or [None] * _TRIPLE_LEN
        triple_list = list(triple_raw_obj) + [None] * _TRIPLE_LEN
        triple = (
            _str_or_none(triple_list[0]),
            _str_or_none(triple_list[1]),
            _str_or_none(triple_list[2]),
        )
        comps_raw_obj: Any = d.get("top_comps")
        comps_raw: list[Any] = (
            cast("list[Any]", comps_raw_obj) if isinstance(comps_raw_obj, list) else []
        )
        comps: tuple[CompRef, ...] = tuple(
            CompRef.from_dict(cast("dict[str, Any]", c)) for c in comps_raw if isinstance(c, dict)
        )
        return cls(
            run_id=str(d["run_id"]),
            produced_at=str(d["produced_at"]),
            top1_logline=str(d.get("top1_logline", "")),
            som_y1_usd=_float_or_none(d.get("som_y1_usd")),
            crystallization_score=_float_or_none(d.get("crystallization_score")),
            genius_score=_float_or_none(d.get("genius_score")),
            cluster_label=_str_or_none(d.get("cluster_label")),
            axes_triple=triple,
            winners_path=str(d.get("winners_path", "")),
            world=_str_or_none(d.get("world")),
            moral_wager=_str_or_none(d.get("moral_wager")),
            protagonist=_str_or_none(d.get("protagonist")),
            antagonist=_str_or_none(d.get("antagonist")),
            wound=_str_or_none(d.get("wound")),
            conflict=_str_or_none(d.get("conflict")),
            compression=_str_or_none(d.get("compression")),
            divisiveness=_str_or_none(d.get("divisiveness")),
            top_comps=comps,
        )

    @classmethod
    def from_winners_json(cls, run_dir: Path) -> LeaderboardRow | None:
        """Parse the top-1 winner from ``run_dir/evolve/gen0/winners.json``.

        Returns ``None`` when the run is malformed or missing the canonical
        path. This is the read-only ingest used by :func:`build_leaderboard`.
        """
        winners_path = run_dir / "evolve" / "gen0" / "winners.json"
        if not winners_path.exists():
            return None
        try:
            raw_any: Any = json.loads(winners_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("leaderboard: cannot parse %s: %s", winners_path, exc)
            return None
        if not isinstance(raw_any, list) or not raw_any:
            return None
        raw: list[Any] = cast("list[Any]", raw_any)

        top1 = _pick_top1(raw)
        if top1 is None:
            return None
        candidate_obj = top1.get("candidate")
        if not isinstance(candidate_obj, dict):
            return None
        candidate: dict[str, Any] = cast("dict[str, Any]", candidate_obj)

        rev_obj = top1.get("revenue")
        rev: dict[str, Any] = cast("dict[str, Any]", rev_obj) if isinstance(rev_obj, dict) else {}
        scores_obj = candidate.get("scores")
        scores: dict[str, Any] = (
            cast("dict[str, Any]", scores_obj) if isinstance(scores_obj, dict) else {}
        )

        run_id = run_dir.name
        produced_at = _produced_at_from_run_id(run_id)
        rel_path = _relativize(winners_path)

        return cls(
            run_id=run_id,
            produced_at=produced_at,
            top1_logline=_synthesize_logline(candidate),
            som_y1_usd=_float_or_none(rev.get("som_y1_usd")),
            crystallization_score=_float_or_none(top1.get("crystallization_score")),
            genius_score=_float_or_none(scores.get("genius_score")),
            cluster_label=_str_or_none(scores.get("primary_cluster")),
            axes_triple=_axes_triple(candidate),
            winners_path=rel_path,
            world=_nested_str(candidate, "world_texture", "name"),
            moral_wager=_nested_str(candidate, "hidden_attrs", "moral_wager"),
            protagonist=_nested_str(candidate, "protagonist_archetype", "label"),
            antagonist=_pick_antagonist(candidate),
            wound=_nested_str(candidate, "sdt_wound", "description"),
            conflict=_nested_str(candidate, "moral_fault_line", "description"),
            compression=_nested_str(candidate, "compression_key", "description"),
            divisiveness=_nested_str(candidate, "divisiveness_engine", "description"),
            top_comps=_extract_top_comps(rev),
        )


# ── Parsing helpers ─────────────────────────────────────────────────────────


def _pick_top1(arr: list[Any]) -> dict[str, Any] | None:
    """Return the element with the highest ``crystallization_score`` (defensive).

    Falls back to ``arr[0]`` when no entry has a numeric score. Stable on ties
    via the original list order.
    """
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        entry_d: dict[str, Any] = cast("dict[str, Any]", entry)
        score = _float_or_none(entry_d.get("crystallization_score"))
        cmp_score = score if score is not None else float("-inf")
        if cmp_score > best_score:
            best_score = cmp_score
            best = entry_d
    if best is not None:
        return best
    first = arr[0]
    if isinstance(first, dict):
        return cast("dict[str, Any]", first)
    return None


def _axes_triple(candidate: dict[str, Any]) -> AxesTriple:
    return (
        _axis_id(candidate, "moral_fault_line"),
        _axis_id(candidate, "divisiveness_engine"),
        _axis_id(candidate, "sdt_wound"),
    )


def _nested_str(parent: dict[str, Any], outer_key: str, inner_key: str) -> str | None:
    """Pull a string field out of a nested sub-object, defensively.

    Returns ``None`` when the outer key is absent / non-dict, or when the
    inner key is absent / non-string / empty. Used for one-line excerpts of
    the engine's creative output (world name, moral wager, etc.).
    """
    outer = parent.get(outer_key)
    if not isinstance(outer, dict):
        return None
    outer_d: dict[str, Any] = cast("dict[str, Any]", outer)
    val = outer_d.get(inner_key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _pick_antagonist(candidate: dict[str, Any]) -> str | None:
    """Prefer ``antagonist_archetype.label`` then ``dark_archetype.label``.

    The engine emits both fields — antagonist for the explicit foil and
    dark_archetype for the protagonist's shadow. Either is informative on
    the leaderboard; antagonist is the primary signal.
    """
    label = _nested_str(candidate, "antagonist_archetype", "label")
    if label:
        return label
    return _nested_str(candidate, "dark_archetype", "label")


def _extract_top_comps(rev: dict[str, Any]) -> tuple[CompRef, ...]:
    """Return the top ``_COMP_TOP_K`` comparable films, sorted by similarity desc.

    Each row in ``revenue.comp_provenance`` has ``title``, ``similarity``, and
    ``ww_gross_usd``. We surface the highest-similarity comps because those
    are what the revenue projection actually weighted most heavily.
    """
    raw = rev.get("comp_provenance")
    if not isinstance(raw, list):
        return ()
    raw_list: list[Any] = cast("list[Any]", raw)
    comps: list[CompRef] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        entry_d: dict[str, Any] = cast("dict[str, Any]", entry)
        comps.append(
            CompRef(
                title=str(entry_d.get("title", "")),
                similarity=_float_or_none(entry_d.get("similarity")),
                ww_gross_usd=_float_or_none(entry_d.get("ww_gross_usd")),
            )
        )
    comps.sort(key=lambda c: c.similarity if c.similarity is not None else -1.0, reverse=True)
    return tuple(comps[:_COMP_TOP_K])


def _axis_id(candidate: dict[str, Any], key: str) -> str | None:
    val = candidate.get(key)
    if isinstance(val, dict):
        val_d: dict[str, Any] = cast("dict[str, Any]", val)
        axis_id = val_d.get("id")
        if isinstance(axis_id, str) and axis_id:
            return axis_id
    return None


def _synthesize_logline(candidate: dict[str, Any]) -> str:
    """Compose a one-line essence from the engine's actual creative output.

    The evolve runs do not emit a polished logline — that is downstream in
    the /single-idea pipeline.

    History: F0 used the operator's input theme+problem (identical across
    every run). F0.1 switched to ``hidden_attrs.moral_wager`` — but the
    F0.2 post-mortem found ``_derive_moral_wager`` to be a 3-string
    hardcoded lookup, not a generated hook. F0.3 switches to
    ``compression_key.description`` — real per-axis prose with 10 distinct
    values, e.g. "the moment of maximum competence is the moment of
    maximum failure".

    Composition: ``"{world}: {compression}"``. Falls back to themes/problems
    when the axes are missing (older runs).
    """
    world = _nested_str(candidate, "world_texture", "name") or ""
    compression = _nested_str(candidate, "compression_key", "description") or ""

    if world and compression:
        composed = f"{world}: {compression}"
    elif compression:
        composed = compression
    elif world:
        composed = world
    else:
        composed = _legacy_theme_logline(candidate)

    if len(composed) > _LOGLINE_MAX_CHARS:
        composed = composed[: _LOGLINE_MAX_CHARS - 1].rstrip() + "…"
    return composed


def _legacy_theme_logline(candidate: dict[str, Any]) -> str:
    """Fallback: synthesize from operator themes + problems when axes are missing."""
    themes_raw = candidate.get("themes")
    themes: list[str] = (
        [str(t) for t in cast("list[Any]", themes_raw) if isinstance(t, str)]
        if isinstance(themes_raw, list)
        else []
    )
    problems_raw = candidate.get("problems")
    problems: list[str] = (
        [str(p) for p in cast("list[Any]", problems_raw) if isinstance(p, str)]
        if isinstance(problems_raw, list)
        else []
    )
    theme_str = " / ".join(themes) if themes else ""
    problem_str = problems[0] if problems else ""
    if theme_str and problem_str:
        return f"{theme_str} — {problem_str}"
    return theme_str or problem_str


def _relativize(path: Path) -> str:
    """Return ``path`` relative to the repo root when possible, else absolute.

    Tests run in pytest ``tmp_path`` which lives outside ``REPO_ROOT``; falling
    back to the absolute string keeps the row valid without leaking the
    irrelevant ``runs/.../`` link target.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _produced_at_from_run_id(run_id: str) -> str:
    """Convert ``evolve-YYYYMMDDTHHMMSSZ`` to ISO-8601 UTC.

    Returns the empty string when the run-id doesn't match the timestamp
    convention (e.g., a hand-named run); callers sort defensively.
    """
    m = _TS_RE.match(run_id)
    if not m:
        return ""
    raw = m.group(1)
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_or_none(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _str_or_none(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw if raw else None
    return str(raw)


# ── Public API ──────────────────────────────────────────────────────────────


def build_leaderboard(
    runs_root: Path | None = None, *, top_k: int | None = None
) -> list[LeaderboardRow]:
    """Walk ``runs_root`` for ``evolve-*/evolve/gen0/winners.json`` files.

    Returns the rows sorted by ``produced_at`` descending (newest first). When
    ``top_k`` is provided the list is truncated. Missing or malformed runs
    are silently skipped — :meth:`LeaderboardRow.from_winners_json` already
    logs the cause.
    """
    root = runs_root if runs_root is not None else RUNS_ROOT
    if not root.exists():
        return []
    rows: list[LeaderboardRow] = []
    for run_dir in sorted(root.glob("evolve-*")):
        if not run_dir.is_dir():
            continue
        row = LeaderboardRow.from_winners_json(run_dir)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r.produced_at, reverse=True)
    if top_k is not None and top_k > 0:
        rows = rows[:top_k]
    return rows


def write_jsonl(rows: list[LeaderboardRow], path: Path | None = None) -> Path:
    """Serialize ``rows`` to JSONL via :func:`pipeline.state.safe_write`.

    Idempotent — re-running yields the same bytes when the inputs are
    identical. The atomic write means an interrupted invocation never leaves
    a partial file at the target path (ADR-0001).
    """
    dest = path if path is not None else DEFAULT_JSONL_PATH
    payload = "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in rows)
    if payload:
        payload += "\n"
    safe_write(dest, payload)
    return dest


# Columns are ordered operator-first: rating + notes near the front so the
# operator can annotate without horizontal scrolling, then essence + headline
# metrics, then engine internals + comps. Derived columns (top_comp_ww_m /
# mean_comp_ww_m / max_comp_similarity) answer "what's the commercial ceiling
# of the comps?" without spreadsheet formulas.
CSV_HEADERS: tuple[str, ...] = (
    "run_id",
    "produced_at",
    "date_only",
    "operator_rating",  # empty placeholder — fill 1-5 in Google Sheets
    "operator_notes",  # empty placeholder — free-text in Google Sheets
    "world",
    "moral_wager",
    "som_y1_m",
    "crystallization_score",
    "cluster",
    "genius_score",
    "protagonist",
    "antagonist",
    "wound",
    "conflict",
    "compression",
    "divisiveness",
    "mf_id",
    "de_id",
    "sdt_id",
    "axes_triple",
    "comp1_title",
    "comp1_similarity",
    "comp1_ww_gross_m",
    "comp2_title",
    "comp2_similarity",
    "comp2_ww_gross_m",
    "comp3_title",
    "comp3_similarity",
    "comp3_ww_gross_m",
    "top_comp_ww_m",
    "mean_comp_ww_m",
    "max_comp_similarity",
    "som_y1_usd",
    "winners_path",
)


def write_csv(rows: list[LeaderboardRow], path: Path | None = None) -> Path:
    """Serialize ``rows`` to a Google-Sheets-friendly CSV.

    Uses ``csv.QUOTE_MINIMAL`` so commas/quotes/newlines inside the
    essence prose are escaped correctly.

    WEDGE Step 4 (2026-05-27): the previously-dead ``operator_rating``
    and ``operator_notes`` columns now mirror the most recent rating
    per run_id from ``data/labels.jsonl`` (written by
    ``python -m scripts.rate``). The mirror is read-only -- the CSV
    is regenerated from the labels log, not the other way around --
    so editing the CSV in Google Sheets does NOT round-trip back into
    the engine. Use the ``rate`` CLI for any signal you want the
    engine to learn from (Step 5 feedback refit).

    Idempotent -- same rows + same labels.jsonl -> same bytes. Atomic
    via ``safe_write``.
    """
    dest = path if path is not None else DEFAULT_CSV_PATH
    # Load latest rating per run_id once per CSV write so each row can
    # mirror in O(1) without re-reading the labels log. Read the module
    # attribute at CALL time (not via the default arg) so tests can
    # monkeypatch labels.DEFAULT_LABELS_PATH and have it take effect.
    from pipeline import labels as _labels  # noqa: PLC0415 -- lazy to avoid import cycle in tests

    latest_ratings = _labels.latest_by_run_id(path=_labels.DEFAULT_LABELS_PATH)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADERS)
    for row in rows:
        writer.writerow(_csv_row_values(row, latest_ratings))
    safe_write(dest, buffer.getvalue())
    return dest


def _csv_row_values(
    row: LeaderboardRow,
    latest_ratings: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    """Project one ``LeaderboardRow`` into the ``CSV_HEADERS`` order.

    ``latest_ratings`` is the ``{run_id: row}`` mapping returned by
    :func:`pipeline.labels.latest_by_run_id`. When supplied, the
    most-recent rating + note for this run mirrors into the
    operator_rating / operator_notes columns. When None (older call
    sites that haven't been updated), those columns stay blank.
    """
    comps = list(row.top_comps)
    comp_grosses_m = [c.ww_gross_usd / 1e6 for c in comps if c.ww_gross_usd is not None]
    top_comp_ww_m = max(comp_grosses_m) if comp_grosses_m else None
    mean_comp_ww_m = sum(comp_grosses_m) / len(comp_grosses_m) if comp_grosses_m else None
    comp_sims = [c.similarity for c in comps if c.similarity is not None]
    max_comp_sim = max(comp_sims) if comp_sims else None
    som_m = row.som_y1_usd / 1e6 if row.som_y1_usd is not None else None

    rating_cell: str = ""
    note_cell: str = ""
    if latest_ratings is not None:
        label = latest_ratings.get(row.run_id)
        if label is not None:
            rating_val = label.get("rating")
            if isinstance(rating_val, int):
                rating_cell = f"{rating_val:+d}"
            note_val = label.get("note")
            if isinstance(note_val, str):
                note_cell = note_val

    return [
        row.run_id,
        row.produced_at,
        row.produced_at[:10],
        rating_cell,  # operator_rating -- now lit up by data/labels.jsonl
        note_cell,  # operator_notes -- now lit up by data/labels.jsonl
        row.world or "",
        row.moral_wager or "",
        _fmt_csv_float(som_m, places=2),
        _fmt_csv_float(row.crystallization_score, places=4),
        row.cluster_label or "",
        _fmt_csv_float(row.genius_score, places=4),
        row.protagonist or "",
        row.antagonist or "",
        row.wound or "",
        row.conflict or "",
        row.compression or "",
        row.divisiveness or "",
        row.axes_triple[0] or "",
        row.axes_triple[1] or "",
        row.axes_triple[2] or "",
        _triple_label(row.axes_triple) if all(row.axes_triple) else "",
        _comp_field(comps, 0, "title"),
        _comp_field(comps, 0, "similarity"),
        _comp_field(comps, 0, "ww_gross_m"),
        _comp_field(comps, 1, "title"),
        _comp_field(comps, 1, "similarity"),
        _comp_field(comps, 1, "ww_gross_m"),
        _comp_field(comps, 2, "title"),
        _comp_field(comps, 2, "similarity"),
        _comp_field(comps, 2, "ww_gross_m"),
        _fmt_csv_float(top_comp_ww_m, places=2),
        _fmt_csv_float(mean_comp_ww_m, places=2),
        _fmt_csv_float(max_comp_sim, places=4),
        _fmt_csv_float(row.som_y1_usd, places=2),
        row.winners_path,
    ]


def _comp_field(comps: list[CompRef], index: int, field: str) -> str:
    if index >= len(comps):
        return ""
    c = comps[index]
    if field == "title":
        return c.title
    if field == "similarity":
        return _fmt_csv_float(c.similarity, places=4)
    if field == "ww_gross_m":
        return _fmt_csv_float(
            c.ww_gross_usd / 1e6 if c.ww_gross_usd is not None else None,
            places=2,
        )
    return ""


def _fmt_csv_float(val: float | None, *, places: int) -> str:
    """Format a float for CSV: blank for None, ``f"{val:.<places>f}"`` otherwise.

    Trailing ``.0000`` is kept so Google Sheets recognizes the column as
    numeric. Blank cells stay blank — Sheets treats them as missing, not zero.
    """
    if val is None:
        return ""
    return f"{val:.{places}f}"


def detect_mode_collapse(
    rows: list[LeaderboardRow], window: int = DEFAULT_MODE_COLLAPSE_WINDOW
) -> list[tuple[AxesTriple, int]]:
    """Return triples appearing ``>= 2`` times in the most recent ``window`` rows.

    Rows missing any of the three axis IDs are skipped — a triple containing
    ``None`` is not informative for the alarm. Sorted by (count desc, triple).
    """
    if window <= 0 or not rows:
        return []
    recent = rows[:window]
    counter: Counter[AxesTriple] = Counter()
    for row in recent:
        triple = row.axes_triple
        if any(part is None for part in triple):
            continue
        counter[triple] += 1
    return sorted(
        [(t, c) for t, c in counter.items() if c >= _MIN_REPEAT_FOR_ALARM],
        key=lambda item: (-item[1], item[0]),
    )


def render_html(
    rows: list[LeaderboardRow],
    path: Path | None = None,
    *,
    offline: bool = False,
    mode_collapse_window: int = DEFAULT_MODE_COLLAPSE_WINDOW,
) -> Path:
    """Render the leaderboard as a single self-contained HTML file.

    Layout (top to bottom):

    1. Header with run count + last produced_at.
    2. Mode-collapse banner — visible only when triples repeat.
    3. Two ``<canvas>`` trend charts (SOM, crystallization), Chart.js-driven.
    4. Sortable ``<table>`` of every row (newest first).

    When ``offline`` is True the page assumes a bundled Chart.js at
    ``out/vendor/chart.min.js``. Default loads from CDN (per F0 prompt).
    """
    dest = path if path is not None else DEFAULT_HTML_PATH
    safe_write(dest, _build_html(rows, offline=offline, window=mode_collapse_window))
    return dest


# ── HTML builders ───────────────────────────────────────────────────────────


def _build_html(rows: list[LeaderboardRow], *, offline: bool, window: int) -> str:
    triples = detect_mode_collapse(rows, window=window)
    chart_src = "vendor/chart.min.js" if offline else _CDN_CHART_JS
    trend = _trend_payload(rows)
    last_at = rows[0].produced_at if rows else "—"

    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="UTF-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            "  <title>Anomaly Engine — Cross-Run Leaderboard</title>",
            f"  <style>{_CSS}</style>",
            "</head>",
            "<body>",
            _header_section(rows, last_at),
            _alarm_section(triples, window),
            _charts_section(),
            _table_section(rows),
            f'  <script src="{chart_src}"></script>',
            _scripts(trend),
            "</body>",
            "</html>",
        ]
    )


def _header_section(rows: list[LeaderboardRow], last_at: str) -> str:
    return (
        '  <header class="hero-scan">'
        '<p class="hero-title">Cross-Run Leaderboard</p>'
        f'<p class="hero-tagline">{len(rows)} top-1 winners — newest at {_escape(last_at)}</p>'
        '<p class="hero-hint">Click any column header to sort. Click any row to expand the full '
        "idea card (world, protagonist, conflict, top comps). The raw winners.json link is at "
        "the bottom of each card.</p>"
        "</header>"
    )


def _alarm_section(triples: list[tuple[AxesTriple, int]], window: int) -> str:
    if not triples:
        return ""
    items = "".join(
        f"<li><code>{_escape(_triple_label(t))}</code> &times; {c}</li>" for t, c in triples
    )
    return (
        '  <section class="alarm" role="alert" aria-live="polite">'
        f"<h2>Mode-collapse alarm — last {window} runs</h2>"
        f"<ul>{items}</ul>"
        '<p class="alarm-note">Same (MF, DE, SDT) triple repeated. Check anti-overfit window '
        "(ADR-0012) or operator-theme reuse.</p>"
        "</section>"
    )


def _charts_section() -> str:
    return (
        '  <section class="charts">'
        '<div class="chart-cell"><canvas id="somChart" '
        'aria-label="SOM Y1 trend"></canvas></div>'
        '<div class="chart-cell"><canvas id="crystalChart" '
        'aria-label="Crystallization trend"></canvas></div>'
        "</section>"
    )


_TABLE_COLSPAN = 7


def _table_section(rows: list[LeaderboardRow]) -> str:
    if not rows:
        return (
            '  <section class="table-wrap"><p class="empty">'
            "No runs yet. Run <code>uv run python -m pipeline.leaderboard --rebuild</code> "
            "after a /single-idea or evolve session.</p></section>"
        )
    head = (
        "<thead><tr>"
        '<th data-sort="produced_at">Date</th>'
        '<th data-sort="som">SOM Y1</th>'
        '<th data-sort="crystal">Crystal</th>'
        '<th data-sort="cluster">Cluster</th>'
        '<th data-sort="world">World</th>'
        '<th data-sort="hook">Hook (compression)</th>'
        '<th aria-label="expand"></th>'
        "</tr></thead>"
    )
    body_rows: list[str] = []
    repeats = {t for t, _c in detect_mode_collapse(rows)}
    for row in rows:
        body_rows.append(_main_row_html(row, is_repeat=row.axes_triple in repeats))
        body_rows.append(_card_row_html(row))
    body = "<tbody>" + "".join(body_rows) + "</tbody>"
    return f'  <section class="table-wrap"><table>{head}{body}</table></section>'


def _main_row_html(row: LeaderboardRow, *, is_repeat: bool) -> str:
    som = _fmt_money_m(row.som_y1_usd)
    crystal = _fmt_float(row.crystallization_score)
    world = row.world or "—"
    # F0.3: the Hook column shows compression_key.description (real per-axis prose,
    # 10 distinct values), not the deprecated moral_wager (3-string hardcoded lookup).
    # See runs/v7-postmortem-F0.2/FINDINGS.md §"Finding 2".
    hook = row.compression or "—"
    classes = ["main-row"]
    if is_repeat:
        classes.append("repeat")
    cls_attr = f' class="{" ".join(classes)}"'
    return (
        "<tr"
        f"{cls_attr}"
        f' data-card="{_escape(row.run_id)}"'
        f' data-produced-at="{_escape(row.produced_at)}"'
        f' data-som="{row.som_y1_usd or 0:.6f}"'
        f' data-crystal="{row.crystallization_score or 0:.6f}"'
        f' data-genius="{row.genius_score or 0:.6f}"'
        f' data-cluster="{_escape(row.cluster_label or "")}"'
        f' data-world="{_escape(world)}"'
        f' data-hook="{_escape(hook)}"'
        ">"
        f"<td>{_escape(row.produced_at)}</td>"
        f"<td>{_escape(som)}</td>"
        f"<td>{_escape(crystal)}</td>"
        f"<td>{_escape(row.cluster_label or '—')}</td>"
        f"<td>{_escape(_truncate(world, _WORLD_CELL_MAX_CHARS))}</td>"
        f"<td>{_escape(_truncate(hook, _HOOK_CELL_MAX_CHARS))}</td>"
        '<td class="expand-cell"><span class="caret" aria-hidden="true">▸</span></td>'
        "</tr>"
    )


def _card_row_html(row: LeaderboardRow) -> str:
    triple_text = _triple_label(row.axes_triple)
    rows_html = _card_dl_rows(row)
    comps_html = _card_comps_html(row)
    # F0.3: pull-quote uses compression_key.description (real per-axis prose),
    # not the deprecated moral_wager (3-string hardcoded lookup).
    pull = row.compression or row.divisiveness or "—"
    return (
        f'<tr class="card-row" id="card-{_escape(row.run_id)}" hidden>'
        f'<td colspan="{_TABLE_COLSPAN}">'
        '<div class="card-content">'
        f'  <p class="card-wager">"{_escape(pull)}"</p>'
        f'  <dl class="card-dl">{rows_html}</dl>'
        f"  {comps_html}"
        '  <p class="card-meta">'
        f"Axes: <code>{_escape(triple_text)}</code>"
        f"  ·  Cluster: {_escape(row.cluster_label or '—')}"
        f"  ·  Genius: {_escape(_fmt_float(row.genius_score))}"
        "</p>"
        '  <p class="card-link">'
        f'<a href="../{_escape(row.winners_path)}">View raw winners.json</a>'
        "</p>"
        "</div>"
        "</td></tr>"
    )


def _card_dl_rows(row: LeaderboardRow) -> str:
    entries: list[tuple[str, str | None]] = [
        ("World", row.world),
        ("Protagonist", row.protagonist),
        ("Wound", row.wound),
        ("Antagonist", row.antagonist),
        ("Conflict", row.conflict),
        ("Compression moment", row.compression),
        ("Divisiveness", row.divisiveness),
    ]
    parts: list[str] = []
    for label, value in entries:
        if value is None:
            continue
        parts.append(f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>")
    if not parts:
        parts.append("<dt>—</dt><dd>No axis detail available for this run.</dd>")
    return "".join(parts)


def _card_comps_html(row: LeaderboardRow) -> str:
    if not row.top_comps:
        return ""
    items = "".join(
        f"<li><strong>{_escape(c.title)}</strong> — "
        f"sim {_fmt_float(c.similarity)}, "
        f"WW {_fmt_money_m(c.ww_gross_usd)}</li>"
        for c in row.top_comps
    )
    return f'<div class="card-comps"><h4>Closest commercial comps</h4><ul>{items}</ul></div>'


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _scripts(trend: dict[str, list[Any]]) -> str:
    return (
        "  <script>\n"
        "  // Trend payload prepared server-side; chronological order.\n"
        f"  const trend = {json.dumps(trend)};\n"
        "  document.addEventListener('DOMContentLoaded', () => {\n"
        "    if (window.Chart && trend.labels.length) {\n"
        "      const somCtx = document.getElementById('somChart');\n"
        "      const crystalCtx = document.getElementById('crystalChart');\n"
        "      const baseOpts = (title) => ({\n"
        "        responsive: true, maintainAspectRatio: false,\n"
        "        plugins: { legend: { display: false },\n"
        "          title: { display: true, text: title, color: '#c9a84c' } },\n"
        "        scales: {\n"
        "          x: { ticks: { color: '#888' }, grid: { color: '#222' } },\n"
        "          y: { ticks: { color: '#888' }, grid: { color: '#222' } } } });\n"
        "      new Chart(somCtx, { type: 'line', data: { labels: trend.labels,\n"
        "        datasets: [{ data: trend.som_m, borderColor: '#c9a84c',\n"
        "          backgroundColor: 'rgba(201,168,76,0.12)', tension: 0.25,\n"
        "          pointRadius: 3, fill: true }] },\n"
        "        options: baseOpts('Top-1 SOM Y1 ($M)') });\n"
        "      new Chart(crystalCtx, { type: 'line', data: { labels: trend.labels,\n"
        "        datasets: [{ data: trend.crystal, borderColor: '#7fb069',\n"
        "          backgroundColor: 'rgba(127,176,105,0.12)', tension: 0.25,\n"
        "          pointRadius: 3, fill: true }] },\n"
        "        options: baseOpts('Top-1 Crystallization') });\n"
        "    }\n"
        "    // Click-to-expand: clicking a main row toggles its companion card row.\n"
        "    document.querySelectorAll('tr.main-row').forEach((row) => {\n"
        "      row.addEventListener('click', (event) => {\n"
        "        if (event.target.closest('a')) { return; }\n"
        "        const id = row.getAttribute('data-card');\n"
        "        const card = document.getElementById('card-' + id);\n"
        "        if (!card) return;\n"
        "        const isHidden = card.hasAttribute('hidden');\n"
        "        if (isHidden) { card.removeAttribute('hidden'); }\n"
        "        else { card.setAttribute('hidden', ''); }\n"
        "        row.classList.toggle('expanded', isHidden);\n"
        "      });\n"
        "    });\n"
        "    // Sort: keep each card-row glued to its main-row after re-ordering.\n"
        "    document.querySelectorAll('th[data-sort]').forEach((th) => {\n"
        "      let asc = true;\n"
        "      th.addEventListener('click', () => {\n"
        "        const key = th.getAttribute('data-sort');\n"
        "        const tbody = th.closest('table').querySelector('tbody');\n"
        "        const mainRows = Array.from(tbody.querySelectorAll('tr.main-row'));\n"
        "        const numericKeys = new Set(['som', 'crystal', 'genius']);\n"
        "        mainRows.sort((a, b) => {\n"
        "          const av = a.getAttribute('data-' + key) || '';\n"
        "          const bv = b.getAttribute('data-' + key) || '';\n"
        "          if (numericKeys.has(key)) {\n"
        "            return asc ? parseFloat(av) - parseFloat(bv)\n"
        "                       : parseFloat(bv) - parseFloat(av);\n"
        "          }\n"
        "          return asc ? av.localeCompare(bv) : bv.localeCompare(av);\n"
        "        });\n"
        "        mainRows.forEach((mainRow) => {\n"
        "          tbody.appendChild(mainRow);\n"
        "          const cardId = mainRow.getAttribute('data-card');\n"
        "          const card = document.getElementById('card-' + cardId);\n"
        "          if (card) { tbody.appendChild(card); }\n"
        "        });\n"
        "        asc = !asc;\n"
        "      });\n"
        "    });\n"
        "  });\n"
        "  </script>"
    )


def _trend_payload(rows: list[LeaderboardRow]) -> dict[str, list[Any]]:
    """Build chronological arrays for the line charts (oldest → newest)."""
    chrono = sorted(rows, key=lambda r: r.produced_at)
    labels: list[str] = []
    som_m: list[float | None] = []
    crystal: list[float | None] = []
    for r in chrono:
        labels.append(r.produced_at[:10] if r.produced_at else r.run_id)
        som_m.append(round(r.som_y1_usd / 1e6, 2) if r.som_y1_usd is not None else None)
        crystal.append(
            round(r.crystallization_score, 4) if r.crystallization_score is not None else None
        )
    return {"labels": labels, "som_m": som_m, "crystal": crystal}


# ── Formatting + escaping helpers ───────────────────────────────────────────


def _triple_label(triple: AxesTriple) -> str:
    parts = [str(p) if p else "—" for p in triple]
    return " + ".join(parts)


def _fmt_money_m(usd: float | None) -> str:
    if usd is None:
        return "—"
    return f"${usd / 1e6:,.0f}M"


def _fmt_float(val: float | None) -> str:
    if val is None:
        return "—"
    return f"{val:.3f}"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ── CSS (dark cinematic; mirrors pipeline.export_html._hero_section) ────────

_CSS = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
    "background:#0a0a0a;color:#ddd;margin:0;padding:0;font-size:15px;line-height:1.55}"
    "header.hero-scan{background:#0a0a0a;color:#f0f0f0;padding:36px 48px 32px;"
    "border-bottom:3px solid #c9a84c}"
    ".hero-title{font-size:1.9em;font-weight:900;color:#fff;margin:0 0 6px;"
    "letter-spacing:-0.02em}"
    ".hero-tagline{font-size:1.05em;color:#c9a84c;font-style:italic;margin:0}"
    "section.alarm{margin:24px 48px;border:2px solid #c9332f;border-radius:6px;"
    "background:#1a0606;padding:18px 22px;animation:pulse 2.4s ease-in-out infinite}"
    "section.alarm h2{margin:0 0 8px;color:#ff7065;font-size:1.05em;text-transform:uppercase;"
    "letter-spacing:.08em}"
    "section.alarm ul{margin:0 0 6px;padding-left:20px}"
    "section.alarm li{margin:.2em 0;color:#f0d0cc}"
    "section.alarm .alarm-note{margin:8px 0 0;font-size:.85em;color:#aa8580}"
    "section.charts{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;"
    "padding:24px 48px}"
    ".chart-cell{background:#111;border:1px solid #222;border-radius:6px;padding:14px;"
    "height:260px;position:relative}"
    "section.table-wrap{padding:8px 48px 48px;overflow-x:auto}"
    "table{border-collapse:collapse;width:100%;font-size:.92em}"
    "th,td{border:1px solid #222;padding:8px 12px;text-align:left;vertical-align:top}"
    "th{background:#161616;color:#c9a84c;font-weight:700;cursor:pointer;"
    "text-transform:uppercase;letter-spacing:.04em;font-size:.82em;user-select:none}"
    "th:hover{background:#1f1f1f}"
    "tr.main-row{cursor:pointer;transition:background .12s ease}"
    "tr.main-row:hover td{background:#181818}"
    "tr.main-row td{background:#0c0c0c}"
    "tr.main-row.expanded td{background:#1a1a1a;border-bottom:1px solid #c9a84c}"
    "tr.main-row.expanded .caret{transform:rotate(90deg);color:#c9a84c}"
    ".caret{display:inline-block;transition:transform .15s ease;color:#666;font-size:.8em}"
    "td.expand-cell{text-align:center;width:36px;color:#666}"
    "tr.repeat td{background:#241010 !important}"
    "tr.repeat td:first-child{border-left:3px solid #c9332f}"
    "tr.card-row td{padding:0;background:#0e0e0e;border:none}"
    "tr.card-row[hidden]{display:none}"
    ".card-content{padding:22px 28px 26px;border-left:3px solid #c9a84c;background:#0e0e0e}"
    ".card-wager{font-size:1.08em;color:#f0e6c8;font-style:italic;line-height:1.55;"
    "margin:0 0 18px;border-left:2px solid #c9a84c;padding-left:14px}"
    ".card-dl{display:grid;grid-template-columns:140px 1fr;gap:6px 18px;margin:0 0 18px;"
    "font-size:.94em}"
    ".card-dl dt{color:#c9a84c;text-transform:uppercase;letter-spacing:.05em;font-size:.78em;"
    "font-weight:700;padding-top:2px}"
    ".card-dl dd{margin:0;color:#ddd;line-height:1.5}"
    ".card-comps{margin:0 0 14px}"
    ".card-comps h4{color:#c9a84c;text-transform:uppercase;letter-spacing:.05em;"
    "font-size:.78em;font-weight:700;margin:0 0 6px}"
    ".card-comps ul{margin:0;padding-left:20px;color:#ddd;font-size:.92em}"
    ".card-comps li{margin:.25em 0}"
    ".card-comps strong{color:#fff}"
    ".card-meta{margin:8px 0 6px;font-size:.84em;color:#888}"
    ".card-link{margin:6px 0 0;font-size:.88em}"
    "td code{font-family:ui-monospace,'Menlo','Consolas',monospace;color:#9bd5ff;"
    "background:#101820;padding:1px 6px;border-radius:3px;font-size:.92em}"
    "a{color:#9bd5ff;text-decoration:none;border-bottom:1px dashed #466}"
    "a:hover{color:#fff;border-bottom-color:#fff}"
    ".empty{color:#888;padding:24px;text-align:center}"
    ".hero-hint{font-size:.88em;color:#888;margin:14px 0 0;max-width:780px;line-height:1.45}"
    "@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(201,51,47,0.5)}"
    "50%{box-shadow:0 0 0 6px rgba(201,51,47,0)}}"
)


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.leaderboard")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild leaderboard.jsonl from scratch by walking runs/.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Truncate to top-K rows (default {DEFAULT_TOP_K}).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Render HTML with offline vendor Chart.js path (out/vendor/chart.min.js).",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=RUNS_ROOT,
        help="Override the runs/ root (default: repo runs/).",
    )
    parser.add_argument(
        "--jsonl-path",
        type=Path,
        default=DEFAULT_JSONL_PATH,
        help="Override the JSONL output path (default: data/leaderboard.jsonl).",
    )
    parser.add_argument(
        "--html-path",
        type=Path,
        default=DEFAULT_HTML_PATH,
        help="Override the HTML output path (default: out/leaderboard.html).",
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Override the CSV output path (default: data/leaderboard.csv).",
    )
    args = parser.parse_args(argv)

    rows = build_leaderboard(args.runs_root, top_k=args.top_k)
    write_jsonl(rows, args.jsonl_path)
    write_csv(rows, args.csv_path)
    render_html(rows, args.html_path, offline=args.offline)

    print(
        f"leaderboard: {len(rows)} rows → {args.jsonl_path} "
        f"+ {args.csv_path} + {args.html_path}" + (" (--rebuild)" if args.rebuild else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "CSV_HEADERS",
    "DEFAULT_CSV_PATH",
    "DEFAULT_HTML_PATH",
    "DEFAULT_JSONL_PATH",
    "DEFAULT_MODE_COLLAPSE_WINDOW",
    "DEFAULT_TOP_K",
    "CompRef",
    "LeaderboardRow",
    "build_leaderboard",
    "detect_mode_collapse",
    "render_html",
    "write_csv",
    "write_jsonl",
]
