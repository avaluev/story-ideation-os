"""Per-run quality + timing report CLI (S4.2 NB-Q-REPORT).

The :func:`render_report` function and the ``__main__`` CLI entry produce a
human-facing dashboard that combines:

- 5-vector quality pass (read from ``runs/{id}/quality.json``, NB.5 sidecar)
- per-phase wall-clock timings (read from ``runs/{id}/phase_timings.jsonl``
  via :func:`pipeline.phase_timing.summarize`)

The report is informational only. It never blocks the pipeline and degrades
gracefully when any sidecar is absent or malformed.

Hot-path detection: the phase with the highest ``duration_seconds`` in the
timing summary is annotated as the bottleneck, supporting Goldratt step 5
("identify the next named constraint") after every measured run.

ADR-0001: read-only; no atomic writes here.
ADR-0002: no arithmetic of its own — surfaces axis scores composed elsewhere.
ADR-0005: no imports from ``frameworks/``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from pipeline import phase_timing

_ = cast  # keep the import (typed reference; formatter would otherwise strip it)

_log = logging.getLogger(__name__)

_BOX_WIDTH = 64  # internal width between the ║ borders
_VECTORS: tuple[str, ...] = ("Q1", "Q2", "Q3", "Q4", "Q5")


# ── JSON sidecar helpers ────────────────────────────────────────────────────


def _load_sidecar_json(path: Path) -> dict[str, Any] | None:
    """Return parsed JSON object, or None when missing / malformed."""
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("sidecar %s unreadable: %s", path, exc)
        return None
    if not isinstance(loaded, dict):
        return None
    return cast("dict[str, Any]", loaded)


def _coerce_float(raw: object) -> float | None:
    """Return raw as float, or None on any failure."""
    if raw is None:
        return None
    try:
        return float(cast("Any", raw))
    except (TypeError, ValueError):
        return None


# ── Vector + hot-path helpers ───────────────────────────────────────────────


def _vector_pass_map(quality: dict[str, Any] | None) -> dict[str, bool | None]:
    """Extract ``vector_pass`` from quality.json with defensive typing."""
    if quality is None:
        return {}
    raw = quality.get("vector_pass")
    if not isinstance(raw, dict):
        return {}
    raw_dict = cast("dict[str, Any]", raw)
    out: dict[str, bool | None] = {}
    for k, v in raw_dict.items():
        key = str(k)
        if v is None:
            out[key] = None
        else:
            out[key] = bool(v)
    return out


def _format_vector_line(q: str, vp: dict[str, bool | None], have_quality: bool) -> str:
    if not have_quality:
        return f"  {q}: not measured"
    if q not in vp or vp[q] is None:
        return f"  {q}: unmeasured"
    return f"  {q}: {'PASS' if vp[q] else 'FAIL'}"


def _hot_path(by_phase: dict[str, Any]) -> str | None:
    """Return phase name with max duration_seconds, or None when empty."""
    best_name: str | None = None
    best_dur = -1.0
    for name, info in by_phase.items():
        if not isinstance(info, dict):
            continue
        info_dict = cast("dict[str, Any]", info)
        dur = _coerce_float(info_dict.get("duration_seconds"))
        if dur is None:
            continue
        if dur > best_dur:
            best_dur = dur
            best_name = str(name)
    return best_name


def _overall_pass(quality: dict[str, Any] | None) -> bool | None:
    if quality is None:
        return None
    raw = quality.get("overall_pass")
    return raw if isinstance(raw, bool) else None


# ── Rendering helpers (one section each) ────────────────────────────────────


def _pad(content: str, width: int = _BOX_WIDTH) -> str:
    """Left-aligned padding to fit between the ║ borders."""
    if len(content) >= width:
        return content[:width]
    return content + " " * (width - len(content))


def _wrap(content: str) -> str:
    return "║" + _pad(content) + "║"


def _borders() -> tuple[str, str, str]:
    top = "╔" + ("═" * _BOX_WIDTH) + "╗"
    mid = "╠" + ("═" * _BOX_WIDTH) + "╣"
    bot = "╚" + ("═" * _BOX_WIDTH) + "╝"
    return top, mid, bot


def _render_quality_section(
    quality: dict[str, Any] | None,
) -> list[str]:
    have_quality = quality is not None
    vp = _vector_pass_map(quality)
    lines = [_wrap("  5-VECTOR PASS")]
    for q in _VECTORS:
        lines.append(_wrap(_format_vector_line(q, vp, have_quality)))
    overall = _overall_pass(quality)
    if overall is True:
        lines.append(_wrap("  OVERALL: PASS"))
    elif overall is False:
        lines.append(_wrap("  OVERALL: FAIL"))
    else:
        lines.append(_wrap("  OVERALL: not measured"))
    return lines


def _render_timings_section(
    by_phase: dict[str, Any], total_seconds: float, hot: str | None
) -> list[str]:
    lines = [_wrap("  PHASE TIMINGS")]
    if not by_phase:
        lines.append(_wrap("  no phase timings recorded"))
        return lines
    for name, info in by_phase.items():
        dur = 0.0
        if isinstance(info, dict):
            info_dict = cast("dict[str, Any]", info)
            dur = _coerce_float(info_dict.get("duration_seconds")) or 0.0
        marker = "  ← hot path" if name == hot else ""
        lines.append(_wrap(f"  {name!s:<22}{dur:>8.1f}s{marker}"))
    total_min = total_seconds / 60.0
    lines.append(_wrap(f"  {'total':<22}{total_seconds:>8.1f}s  ({total_min:.2f} min)"))
    return lines


def _publish_line(overall: bool | None) -> str:
    if overall is True:
        publish = "yes"
    elif overall is False:
        publish = "no"
    else:
        publish = "n/a"
    return _wrap(f"  ELIGIBLE FOR PUBLISH: {publish}")


# ── Public surface ──────────────────────────────────────────────────────────


def render_report(run_dir: Path | str) -> str:
    """Render the boxed quality + timing dashboard for a single run."""
    run_dir_p = Path(run_dir)

    timings_summary = phase_timing.summarize(run_dir_p)
    by_phase_raw = timings_summary.get("by_phase", {})
    by_phase: dict[str, Any] = (
        cast("dict[str, Any]", by_phase_raw) if isinstance(by_phase_raw, dict) else {}
    )
    total_seconds = _coerce_float(timings_summary.get("total_seconds")) or 0.0

    quality = _load_sidecar_json(run_dir_p / "quality.json")
    hot = _hot_path(by_phase)
    top, mid, bot = _borders()

    title = f"Quality + Timing Report — {run_dir_p.name}"
    lines: list[str] = [top, _wrap(f"  {title}"), mid]
    lines.extend(_render_quality_section(quality))
    lines.append(mid)
    lines.extend(_render_timings_section(by_phase, total_seconds, hot))
    lines.append(mid)
    lines.append(_publish_line(_overall_pass(quality)))
    lines.append(bot)
    return "\n".join(lines)


def _main() -> int:
    """CLI entry: ``uv run python -m pipeline.quality_report --run-dir <run_dir>``.

    Soft-fail design: any exception during rendering logs a warning and
    returns 1, but never raises into the operator's terminal.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="pipeline.quality_report")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    try:
        print(render_report(args.run_dir))
    except Exception as exc:  # pragma: no cover — soft-fail backstop
        _log.warning("quality_report degraded: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "render_report",
]
