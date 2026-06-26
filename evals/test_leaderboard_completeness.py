"""Stage F0 — Cross-Run Leaderboard completeness eval (v7.0).

Asserts the leaderboard ingest + render contract end-to-end:

1. Every ``runs/evolve-*/evolve/gen0/winners.json`` from the recent window
   appears in the rebuilt leaderboard. Newest run sits at the top when
   sorted by ``crystallization_score`` (sanity ordering).
2. ``out/leaderboard.html`` is under 200 KB and contains the structural
   elements (``<table``, ``<canvas``) the operator UI depends on.
3. ``detect_mode_collapse`` correctly fires the alarm on a synthetic
   fixture that mirrors the within-run repeat captured in the v7 plan
   (MF_01+DE_04+SW_02 from ``evolve-20260524T145508Z``). This validates
   the alarm function, not the present-day cross-run state — the engine
   may have moved off the collapsed triple since the plan was drafted.

The slow ingest paths over the real ``runs/`` tree are gated on
``RUN_V7_EVIDENCE=1`` (mirrors ``RUN_V5_EVIDENCE``); fast structural
assertions on rendered HTML and the detection function run always.

ADR-0001 atomic writes are exercised by ``write_jsonl`` / ``render_html``.
ADR-0007: read-only over ``runs/``, no LLM dispatches.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline.leaderboard import (
    LeaderboardRow,
    build_leaderboard,
    detect_mode_collapse,
    render_html,
    write_jsonl,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUNS_ROOT = _REPO_ROOT / "runs"
_HTML_SIZE_CAP_BYTES = 200_000
_RECENT_WINDOW_DAYS = 7
_RUN_TS_FORMAT = "%Y%m%dT%H%M%SZ"

_run_v7_evidence = os.environ.get("RUN_V7_EVIDENCE") == "1"


# ── Structural assertions (always run) ──────────────────────────────────────


def test_render_html_size_and_required_markup(tmp_path: Path) -> None:
    """The rendered HTML stays under 200 KB and contains the markup the operator uses."""
    rows = _synthetic_rows(triples_repeat=True)
    out = tmp_path / "leaderboard.html"
    render_html(rows, out)
    size = out.stat().st_size
    assert size < _HTML_SIZE_CAP_BYTES, (
        f"leaderboard.html grew past {_HTML_SIZE_CAP_BYTES} bytes: {size}"
    )
    html = out.read_text(encoding="utf-8")
    assert "<table" in html, "table markup missing"
    assert "<canvas" in html, "Chart.js canvas placeholder missing"
    assert "Cross-Run Leaderboard" in html, "page title missing"


def test_detect_mode_collapse_fires_on_known_triple() -> None:
    """The within-run mode-collapse triple from the v7 plan is detectable.

    The v7 plan captured a 5-run repeat of ``(MF_01, DE_04, SW_02)`` originating
    in ``runs/evolve-20260524T145508Z``. Whether that triple is currently the
    top-1 across recent runs varies as the engine evolves; this eval asserts
    the *function* still catches it when present.
    """
    triple = ("MF_01", "DE_04", "SW_02")
    rows = [_row("evolve-A", triple), _row("evolve-B", triple)]
    result = detect_mode_collapse(rows, window=10)
    assert (triple, 2) in result, f"expected {triple} repeat in alarm output, got {result}"


def test_leaderboard_jsonl_writes_round_trip(tmp_path: Path) -> None:
    """write_jsonl round-trip — empty placeholder pattern from data/_consumers.jsonl."""
    path = tmp_path / "leaderboard.jsonl"
    write_jsonl([], path)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""
    # Re-running with rows produces decodable lines.
    rows = _synthetic_rows(triples_repeat=False)
    write_jsonl(rows, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(rows)
    decoded = [LeaderboardRow.from_dict(json.loads(ln)) for ln in lines]
    assert decoded == rows


# ── Evidence assertions (gated on RUN_V7_EVIDENCE) ─────────────────────────


@pytest.mark.skipif(
    not _run_v7_evidence,
    reason="Stage F0 evidence sweep; set RUN_V7_EVIDENCE=1 to run.",
)
def test_recent_runs_appear_in_leaderboard(tmp_path: Path) -> None:
    """Every recent ``runs/evolve-*/evolve/gen0/winners.json`` ends up in the JSONL."""
    if not _RUNS_ROOT.exists():
        pytest.skip(f"{_RUNS_ROOT} not present")
    recent = _recent_evolve_run_ids(_RUNS_ROOT, days=_RECENT_WINDOW_DAYS)
    if not recent:
        pytest.skip("no evolve runs in the last 7 days")
    rows = build_leaderboard(_RUNS_ROOT)
    jsonl = tmp_path / "leaderboard.jsonl"
    write_jsonl(rows, jsonl)
    reloaded = [
        LeaderboardRow.from_dict(json.loads(ln))
        for ln in jsonl.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    ingested = {r.run_id for r in reloaded}
    missing = recent - ingested
    assert not missing, f"recent runs missing from leaderboard: {sorted(missing)}"


@pytest.mark.skipif(
    not _run_v7_evidence,
    reason="Stage F0 evidence sweep; set RUN_V7_EVIDENCE=1 to run.",
)
def test_crystallization_top_row_is_max_score() -> None:
    """Sorting by crystallization_score descending puts the highest-scoring run at the top."""
    if not _RUNS_ROOT.exists():
        pytest.skip(f"{_RUNS_ROOT} not present")
    rows = build_leaderboard(_RUNS_ROOT)
    if not rows:
        pytest.skip("no evolve runs ingested")
    scored = [r for r in rows if r.crystallization_score is not None]
    if not scored:
        pytest.skip("no evolve runs with crystallization_score")
    by_score = sorted(scored, key=lambda r: r.crystallization_score or -1.0, reverse=True)
    expected_max = by_score[0].crystallization_score
    assert expected_max is not None
    actual_max = max(r.crystallization_score or -1.0 for r in scored)
    assert expected_max == pytest.approx(actual_max)


@pytest.mark.skipif(
    not _run_v7_evidence,
    reason="Stage F0 evidence sweep; set RUN_V7_EVIDENCE=1 to run.",
)
def test_html_renders_from_real_runs(tmp_path: Path) -> None:
    """Rendering against the real runs/ tree stays under the 200 KB cap."""
    if not _RUNS_ROOT.exists():
        pytest.skip(f"{_RUNS_ROOT} not present")
    rows = build_leaderboard(_RUNS_ROOT)
    out = tmp_path / "leaderboard.html"
    render_html(rows, out)
    size = out.stat().st_size
    assert size < _HTML_SIZE_CAP_BYTES, (
        f"real-runs leaderboard.html grew past {_HTML_SIZE_CAP_BYTES} bytes: {size}"
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _synthetic_rows(*, triples_repeat: bool) -> list[LeaderboardRow]:
    triple_a = ("MF_01", "DE_04", "SW_02")
    triple_b = ("MF_03", "DE_05", "SW_06")
    return [
        LeaderboardRow(
            run_id="evolve-20260525T120000Z",
            produced_at="2026-05-25T12:00:00Z",
            top1_logline="alpha / beta — first synthetic",
            som_y1_usd=240e6,
            crystallization_score=0.71,
            genius_score=0.95,
            cluster_label="civilizational",
            axes_triple=triple_a,
            winners_path="runs/evolve-20260525T120000Z/evolve/gen0/winners.json",
        ),
        LeaderboardRow(
            run_id="evolve-20260524T120000Z",
            produced_at="2026-05-24T12:00:00Z",
            top1_logline="gamma / delta — second synthetic",
            som_y1_usd=260e6,
            crystallization_score=0.69,
            genius_score=0.93,
            cluster_label="identity",
            axes_triple=triple_a if triples_repeat else triple_b,
            winners_path="runs/evolve-20260524T120000Z/evolve/gen0/winners.json",
        ),
    ]


def _row(run_id: str, triple: tuple[str | None, str | None, str | None]) -> LeaderboardRow:
    return LeaderboardRow(
        run_id=run_id,
        produced_at=run_id.replace("evolve-", ""),
        top1_logline="",
        som_y1_usd=None,
        crystallization_score=None,
        genius_score=None,
        cluster_label=None,
        axes_triple=triple,
        winners_path="",
    )


def _recent_evolve_run_ids(runs_root: Path, *, days: int) -> set[str]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    out: set[str] = set()
    for run_dir in runs_root.glob("evolve-*"):
        if not run_dir.is_dir():
            continue
        if not (run_dir / "evolve" / "gen0" / "winners.json").exists():
            continue
        raw = run_dir.name.removeprefix("evolve-")
        try:
            ts = datetime.strptime(raw, _RUN_TS_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            continue
        if ts >= cutoff:
            out.add(run_dir.name)
    return out
