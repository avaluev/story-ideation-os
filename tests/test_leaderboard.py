"""Unit tests for pipeline.leaderboard (v7.0 Stage F0).

Covers:
- ``LeaderboardRow.from_winners_json`` parsing of a synthetic fixture run.
- ``LeaderboardRow.from_dict`` / ``to_dict`` round trip + missing-field defence.
- ``detect_mode_collapse`` window logic + repeat detection + edge cases.
- ``write_jsonl`` idempotency under repeated invocation.
- ``render_html`` smoke — produces well-formed HTML with the expected sections.
- ``build_leaderboard`` ordering by ``produced_at`` descending.

ADR-0001: every write goes through ``pipeline.state.safe_write`` (proved by
the file-existence + atomicity assertions). ADR-0007: no LLM imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.leaderboard import (
    CSV_HEADERS,
    DEFAULT_MODE_COLLAPSE_WINDOW,
    CompRef,
    LeaderboardRow,
    build_leaderboard,
    detect_mode_collapse,
    render_html,
    write_csv,
    write_jsonl,
)

# ── Fixture builders ────────────────────────────────────────────────────────


def _make_winner(
    *,
    mf: str = "MF_01",
    de: str = "DE_04",
    sdt: str = "SW_02",
    crystal: float = 0.73,
    som_y1: float = 250_000_000.0,
    cluster: str = "civilizational",
    genius: float = 0.95,
    themes: list[str] | None = None,
    problems: list[str] | None = None,
    world: str | None = "pharmaceutical research lab during a drug trial",
    moral_wager: str
    | None = "Precision without accountability is harm the precision cannot measure.",
    protagonist_label: str | None = "The Rebel",
    antagonist_label: str | None = "Hollow Caregiver",
    wound: str | None = "to help they must keep distance",
    conflict: str | None = "individual conscience vs collective loyalty",
    compression: str | None = "the moment of maximum competence is the moment of maximum failure",
    divisiveness: str | None = "good faith is the mechanism",
    comps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "themes": themes if themes is not None else ["legibility", "agency"],
        "problems": problems
        if problems is not None
        else ["the cost of being legible to algorithms"],
        "moral_fault_line": {"id": mf, "description": conflict or "x"},
        "divisiveness_engine": {"id": de, "description": divisiveness or "x"},
        "sdt_wound": {"id": sdt, "description": wound or "x"},
        "compression_key": {"id": "CK_06", "description": compression or "x"},
        "scores": {"primary_cluster": cluster, "genius_score": genius},
    }
    if world is not None:
        candidate["world_texture"] = {"id": "WT_10", "name": world}
    if moral_wager is not None:
        candidate["hidden_attrs"] = {"moral_wager": moral_wager}
    if protagonist_label is not None:
        candidate["protagonist_archetype"] = {"id": "PA_006", "label": protagonist_label}
    if antagonist_label is not None:
        candidate["antagonist_archetype"] = {"id": "DA_011", "label": antagonist_label}
    rev: dict[str, Any] = {"som_y1_usd": som_y1}
    if comps is None:
        rev["comp_provenance"] = [
            {
                "title": "A.I. Artificial Intelligence (2001)",
                "similarity": 0.6,
                "ww_gross_usd": 235_926_635.0,
            },
            {
                "title": "A Quiet Place: Day One (2024)",
                "similarity": 0.5,
                "ww_gross_usd": 261_907_653.0,
            },
            {
                "title": "Far and Away (1992)",
                "similarity": 0.5,
                "ww_gross_usd": 137_783_840.0,
            },
        ]
    else:
        rev["comp_provenance"] = comps
    return {
        "candidate": candidate,
        "revenue": rev,
        "crystallization_score": crystal,
        "lineage": ["base"],
    }


def _seed_run(
    runs_root: Path,
    run_id: str,
    winners: list[dict[str, Any]] | None = None,
) -> Path:
    run_dir = runs_root / run_id
    gen0 = run_dir / "evolve" / "gen0"
    gen0.mkdir(parents=True)
    payload = winners if winners is not None else [_make_winner()]
    (gen0 / "winners.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_dir


# ── from_winners_json ───────────────────────────────────────────────────────


def test_from_winners_json_parses_top1(tmp_path: Path) -> None:
    run_dir = _seed_run(
        tmp_path,
        "evolve-20260524T172830Z",
        [
            _make_winner(mf="MF_04", crystal=0.50, som_y1=200e6),
            _make_winner(mf="MF_09", crystal=0.80, som_y1=400e6),
            _make_winner(mf="MF_07", crystal=0.65, som_y1=300e6),
        ],
    )
    row = LeaderboardRow.from_winners_json(run_dir)
    assert row is not None
    # Highest-crystal entry wins.
    assert row.run_id == "evolve-20260524T172830Z"
    assert row.crystallization_score == pytest.approx(0.80)
    assert row.som_y1_usd == pytest.approx(400e6)
    assert row.axes_triple[0] == "MF_09"
    # produced_at is ISO-8601 derived from the run-id.
    assert row.produced_at == "2026-05-24T17:28:30Z"
    # Logline is "world: compression" — F0.3 uses compression_key.description
    # (real per-axis prose) instead of the deprecated moral_wager 3-string lookup.
    assert row.world == "pharmaceutical research lab during a drug trial"
    assert row.compression is not None
    assert "competence" in row.compression
    assert "pharmaceutical" in row.top1_logline
    assert "competence" in row.top1_logline
    # Idea-essence fields populated from the candidate.
    assert row.protagonist == "The Rebel"
    assert row.antagonist == "Hollow Caregiver"
    assert row.wound is not None and "distance" in row.wound
    assert row.conflict is not None
    assert row.compression is not None
    # Top comps sorted by similarity descending, capped at 3.
    assert len(row.top_comps) == 3
    assert row.top_comps[0].title == "A.I. Artificial Intelligence (2001)"
    assert row.top_comps[0].similarity == pytest.approx(0.6)


def test_from_winners_json_returns_none_when_missing(tmp_path: Path) -> None:
    assert LeaderboardRow.from_winners_json(tmp_path / "evolve-20260101T000000Z") is None


def test_from_winners_json_malformed_returns_none(tmp_path: Path) -> None:
    run_dir = tmp_path / "evolve-20260101T000000Z" / "evolve" / "gen0"
    run_dir.mkdir(parents=True)
    (run_dir / "winners.json").write_text("not json", encoding="utf-8")
    assert LeaderboardRow.from_winners_json(run_dir.parent.parent) is None


def test_from_winners_json_handles_missing_axes(tmp_path: Path) -> None:
    payload = [
        {
            "candidate": {
                "themes": ["x"],
                "problems": ["y"],
                "scores": {"primary_cluster": "identity"},
            },
            "revenue": {"som_y1_usd": 100e6},
            "crystallization_score": 0.4,
        }
    ]
    run_dir = _seed_run(tmp_path, "evolve-20260101T000000Z", payload)
    row = LeaderboardRow.from_winners_json(run_dir)
    assert row is not None
    assert row.axes_triple == (None, None, None)


def test_from_winners_json_truncates_long_logline(tmp_path: Path) -> None:
    long_compression = "x " * 120
    run_dir = _seed_run(
        tmp_path,
        "evolve-20260101T000000Z",
        [_make_winner(compression=long_compression)],
    )
    row = LeaderboardRow.from_winners_json(run_dir)
    assert row is not None
    # Logline cap is the documented _LOGLINE_MAX_CHARS (160 in F0.1).
    assert len(row.top1_logline) <= 160
    assert row.top1_logline.endswith("…")


def test_from_winners_json_falls_back_to_themes_when_axes_missing(tmp_path: Path) -> None:
    """When world + compression are absent, fall back to theme+problem (legacy behavior)."""
    payload = [
        {
            "candidate": {
                "themes": ["legibility", "agency"],
                "problems": ["the cost of being legible to algorithms"],
                "scores": {"primary_cluster": "identity"},
            },
            "revenue": {"som_y1_usd": 100e6},
            "crystallization_score": 0.4,
        }
    ]
    run_dir = _seed_run(tmp_path, "evolve-20260101T000000Z", payload)
    row = LeaderboardRow.from_winners_json(run_dir)
    assert row is not None
    assert row.world is None
    assert row.compression is None
    assert "legibility" in row.top1_logline
    assert "algorithms" in row.top1_logline


def test_from_winners_json_picks_dark_archetype_when_antagonist_missing(tmp_path: Path) -> None:
    """Fallback: dark_archetype.label is used when antagonist_archetype is absent."""
    payload = [
        {
            "candidate": {
                "themes": ["x"],
                "world_texture": {"name": "an island"},
                "hidden_attrs": {"moral_wager": "hook"},
                "dark_archetype": {"label": "Corrupted Mentor"},
                "scores": {"primary_cluster": "identity"},
            },
            "revenue": {"som_y1_usd": 100e6},
            "crystallization_score": 0.4,
        }
    ]
    run_dir = _seed_run(tmp_path, "evolve-20260101T000000Z", payload)
    row = LeaderboardRow.from_winners_json(run_dir)
    assert row is not None
    assert row.antagonist == "Corrupted Mentor"


def test_from_winners_json_handles_non_timestamp_run_id(tmp_path: Path) -> None:
    run_dir = _seed_run(tmp_path, "evolve-handnamed", [_make_winner()])
    row = LeaderboardRow.from_winners_json(run_dir)
    assert row is not None
    assert row.produced_at == ""  # falls back gracefully


# ── to_dict / from_dict round-trip ──────────────────────────────────────────


def test_row_round_trip_preserves_data() -> None:
    row = LeaderboardRow(
        run_id="evolve-20260524T172830Z",
        produced_at="2026-05-24T17:28:30Z",
        top1_logline="pharma lab: precision without accountability",
        som_y1_usd=270e6,
        crystallization_score=0.73,
        genius_score=0.97,
        cluster_label="nature",
        axes_triple=("MF_04", "DE_09", "SW_11"),
        winners_path="runs/evolve-20260524T172830Z/evolve/gen0/winners.json",
        world="pharmaceutical research lab during a drug trial",
        moral_wager="Precision without accountability leads to harm.",
        protagonist="The Rebel",
        antagonist="Hollow Caregiver",
        wound="to help they must keep distance",
        conflict="individual conscience vs collective loyalty",
        compression="the moment of maximum competence is the moment of maximum failure",
        divisiveness="good faith is the mechanism",
        top_comps=(CompRef(title="Whiplash (2014)", similarity=0.62, ww_gross_usd=49_000_000.0),),
    )
    encoded = row.to_dict()
    assert encoded["axes_triple"] == ["MF_04", "DE_09", "SW_11"]
    assert encoded["top_comps"] == [
        {"title": "Whiplash (2014)", "similarity": 0.62, "ww_gross_usd": 49_000_000.0}
    ]
    decoded = LeaderboardRow.from_dict(encoded)
    assert decoded == row
    assert decoded.top_comps == row.top_comps


def test_row_from_dict_handles_legacy_v1_jsonl_rows() -> None:
    """Older rows without the v7 F0.1 essence fields still decode cleanly."""
    legacy = {
        "run_id": "evolve-20260524T172830Z",
        "produced_at": "2026-05-24T17:28:30Z",
        "top1_logline": "legibility — algorithms",
        "som_y1_usd": 270e6,
        "crystallization_score": 0.73,
        "genius_score": 0.97,
        "cluster_label": "nature",
        "axes_triple": ["MF_04", "DE_09", "SW_11"],
        "winners_path": "runs/evolve-20260524T172830Z/evolve/gen0/winners.json",
    }
    row = LeaderboardRow.from_dict(legacy)
    assert row.world is None
    assert row.top_comps == ()
    assert row.moral_wager is None


def test_row_from_dict_handles_missing_optional_fields() -> None:
    minimal = {
        "run_id": "evolve-20260524T172830Z",
        "produced_at": "2026-05-24T17:28:30Z",
    }
    row = LeaderboardRow.from_dict(minimal)
    assert row.run_id == "evolve-20260524T172830Z"
    assert row.som_y1_usd is None
    assert row.crystallization_score is None
    assert row.axes_triple == (None, None, None)


# ── detect_mode_collapse ────────────────────────────────────────────────────


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


def _full_row(
    run_id: str,
    triple: tuple[str | None, str | None, str | None],
    *,
    world: str = "pharmaceutical research lab during a drug trial",
    moral_wager: str = "Precision without accountability leads to harm.",
) -> LeaderboardRow:
    """Row with all idea-essence fields populated (for HTML rendering tests)."""
    return LeaderboardRow(
        run_id=run_id,
        produced_at="2026-05-24T17:28:30Z",
        top1_logline=f"{world}: {moral_wager}",
        som_y1_usd=270e6,
        crystallization_score=0.73,
        genius_score=0.95,
        cluster_label="nature",
        axes_triple=triple,
        winners_path=f"runs/{run_id}/evolve/gen0/winners.json",
        world=world,
        moral_wager=moral_wager,
        protagonist="The Rebel",
        antagonist="Hollow Caregiver",
        wound="to help they must keep distance",
        conflict="individual conscience vs collective loyalty",
        compression="the moment of maximum competence is the moment of maximum failure",
        divisiveness="good faith is the mechanism",
        top_comps=(
            CompRef(
                title="A.I. Artificial Intelligence (2001)",
                similarity=0.6,
                ww_gross_usd=235_926_635.0,
            ),
            CompRef(
                title="A Quiet Place: Day One (2024)",
                similarity=0.5,
                ww_gross_usd=261_907_653.0,
            ),
            CompRef(
                title="Far and Away (1992)",
                similarity=0.5,
                ww_gross_usd=137_783_840.0,
            ),
        ),
    )


def test_detect_mode_collapse_empty() -> None:
    assert detect_mode_collapse([], window=10) == []


def test_detect_mode_collapse_no_repeat() -> None:
    rows = [
        _row("evolve-A", ("MF_01", "DE_01", "SW_01")),
        _row("evolve-B", ("MF_02", "DE_02", "SW_02")),
    ]
    assert detect_mode_collapse(rows, window=10) == []


def test_detect_mode_collapse_finds_repeat() -> None:
    triple = ("MF_01", "DE_04", "SW_02")
    rows = [
        _row("evolve-A", triple),
        _row("evolve-B", triple),
        _row("evolve-C", ("MF_03", "DE_05", "SW_06")),
    ]
    result = detect_mode_collapse(rows, window=10)
    assert result == [(triple, 2)]


def test_detect_mode_collapse_window_excludes_old() -> None:
    repeat = ("MF_01", "DE_04", "SW_02")
    rows = [_row(f"evolve-{i:02d}", ("MF_NEW", "DE_NEW", f"SW_{i:02d}")) for i in range(10)]
    rows += [_row("evolve-OLD-A", repeat), _row("evolve-OLD-B", repeat)]
    # Window of 10 keeps only the unique recent rows; the OLD repeats fall off.
    assert detect_mode_collapse(rows, window=10) == []
    # A larger window picks them back up.
    found = detect_mode_collapse(rows, window=15)
    assert (repeat, 2) in found


def test_detect_mode_collapse_skips_partial_triples() -> None:
    rows = [
        _row("evolve-A", ("MF_01", None, "SW_02")),
        _row("evolve-B", ("MF_01", None, "SW_02")),
    ]
    assert detect_mode_collapse(rows, window=10) == []


def test_detect_mode_collapse_default_window_constant() -> None:
    """Default window is the documented 10."""
    assert DEFAULT_MODE_COLLAPSE_WINDOW == 10


def test_detect_mode_collapse_sorts_by_count_desc() -> None:
    triple_a = ("MF_A", "DE_A", "SW_A")
    triple_b = ("MF_B", "DE_B", "SW_B")
    rows = [
        _row("evolve-1", triple_a),
        _row("evolve-2", triple_a),
        _row("evolve-3", triple_b),
        _row("evolve-4", triple_b),
        _row("evolve-5", triple_b),
    ]
    result = detect_mode_collapse(rows, window=10)
    assert result[0] == (triple_b, 3)
    assert result[1] == (triple_a, 2)


# ── write_jsonl idempotency ─────────────────────────────────────────────────


def test_write_jsonl_round_trip(tmp_path: Path) -> None:
    rows = [
        _row("evolve-A", ("MF_01", "DE_01", "SW_01")),
        _row("evolve-B", ("MF_02", "DE_02", "SW_02")),
    ]
    path = tmp_path / "leaderboard.jsonl"
    write_jsonl(rows, path)
    content = path.read_text(encoding="utf-8").splitlines()
    assert len(content) == 2
    assert json.loads(content[0])["run_id"] == "evolve-A"


def test_write_jsonl_idempotent(tmp_path: Path) -> None:
    rows = [_row("evolve-A", ("MF_01", "DE_01", "SW_01"))]
    path = tmp_path / "leaderboard.jsonl"
    write_jsonl(rows, path)
    first = path.read_bytes()
    write_jsonl(rows, path)
    second = path.read_bytes()
    assert first == second


def test_write_jsonl_empty(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.jsonl"
    write_jsonl([], path)
    assert path.read_text(encoding="utf-8") == ""


# ── write_csv (Google-Sheets-friendly export) ───────────────────────────────


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    import csv as _csv  # noqa: PLC0415

    with path.open(encoding="utf-8") as f:
        reader = _csv.reader(f)
        header = next(reader)
        rows = list(reader)
    return header, rows


def test_csv_headers_are_stable() -> None:
    """CSV_HEADERS is the public schema — operator's Sheets formulas pin to these."""
    expected_first_six = (
        "run_id",
        "produced_at",
        "date_only",
        "operator_rating",
        "operator_notes",
        "world",
    )
    assert CSV_HEADERS[: len(expected_first_six)] == expected_first_six
    # Empty operator columns sit near the front so the spreadsheet shows them
    # without scrolling.
    assert "operator_rating" in CSV_HEADERS
    assert "operator_notes" in CSV_HEADERS
    # Derived analytical columns are present.
    assert "top_comp_ww_m" in CSV_HEADERS
    assert "mean_comp_ww_m" in CSV_HEADERS
    assert "max_comp_similarity" in CSV_HEADERS
    # Every comp slot has three companion columns.
    for n in (1, 2, 3):
        assert f"comp{n}_title" in CSV_HEADERS
        assert f"comp{n}_similarity" in CSV_HEADERS
        assert f"comp{n}_ww_gross_m" in CSV_HEADERS


def test_write_csv_round_trip(tmp_path: Path) -> None:
    rows = [
        _full_row("evolve-20260524T172830Z", ("MF_04", "DE_09", "SW_11")),
        _full_row("evolve-20260524T161607Z", ("MF_07", "DE_08", "SW_09")),
    ]
    path = tmp_path / "leaderboard.csv"
    write_csv(rows, path)
    header, data_rows = _read_csv(path)
    assert tuple(header) == CSV_HEADERS
    assert len(data_rows) == 2
    by_run = {r[header.index("run_id")]: r for r in data_rows}
    sample = by_run["evolve-20260524T172830Z"]
    # Spot-check headline columns.
    assert sample[header.index("world")] == "pharmaceutical research lab during a drug trial"
    assert sample[header.index("moral_wager")].startswith("Precision without accountability")
    assert sample[header.index("som_y1_m")] == "270.00"
    assert sample[header.index("crystallization_score")] == "0.7300"
    assert sample[header.index("date_only")] == "2026-05-24"
    assert sample[header.index("operator_rating")] == ""  # ready for the operator
    assert sample[header.index("operator_notes")] == ""
    assert sample[header.index("axes_triple")] == "MF_04 + DE_09 + SW_11"


def test_write_csv_empty_emits_header_only(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.csv"
    write_csv([], path)
    header, data_rows = _read_csv(path)
    assert tuple(header) == CSV_HEADERS
    assert data_rows == []


def test_write_csv_is_idempotent(tmp_path: Path) -> None:
    rows = [_full_row("evolve-A", ("MF_01", "DE_01", "SW_01"))]
    path = tmp_path / "leaderboard.csv"
    write_csv(rows, path)
    first = path.read_bytes()
    write_csv(rows, path)
    assert path.read_bytes() == first


def test_write_csv_escapes_commas_and_quotes(tmp_path: Path) -> None:
    """Prose fields containing commas + quotes round-trip via csv.QUOTE_MINIMAL."""
    nasty = 'Setting, with a comma, "embedded quote", and a newline\nhere'
    row = _full_row("evolve-A", ("MF_01", "DE_01", "SW_01"), world=nasty)
    path = tmp_path / "leaderboard.csv"
    write_csv([row], path)
    _, data_rows = _read_csv(path)
    assert data_rows[0][5] == nasty  # world column survives the quoting round-trip


def test_write_csv_computes_derived_comp_columns(tmp_path: Path) -> None:
    row = LeaderboardRow(
        run_id="evolve-A",
        produced_at="2026-05-24T17:28:30Z",
        top1_logline="x",
        som_y1_usd=None,
        crystallization_score=None,
        genius_score=None,
        cluster_label=None,
        axes_triple=("MF_01", "DE_01", "SW_01"),
        winners_path="",
        top_comps=(
            CompRef(title="A", similarity=0.7, ww_gross_usd=300_000_000.0),
            CompRef(title="B", similarity=0.5, ww_gross_usd=100_000_000.0),
            CompRef(title="C", similarity=0.4, ww_gross_usd=200_000_000.0),
        ),
    )
    path = tmp_path / "leaderboard.csv"
    write_csv([row], path)
    header, data_rows = _read_csv(path)
    sample = data_rows[0]
    # max WW gross of the three comps is the "commercial ceiling" benchmark.
    assert sample[header.index("top_comp_ww_m")] == "300.00"
    # Mean = (300 + 100 + 200) / 3 = 200.00.
    assert sample[header.index("mean_comp_ww_m")] == "200.00"
    # Max similarity of the three.
    assert sample[header.index("max_comp_similarity")] == "0.7000"


def test_write_csv_handles_row_with_no_comps(tmp_path: Path) -> None:
    row = LeaderboardRow(
        run_id="evolve-A",
        produced_at="2026-05-24T17:28:30Z",
        top1_logline="x",
        som_y1_usd=None,
        crystallization_score=None,
        genius_score=None,
        cluster_label=None,
        axes_triple=(None, None, None),
        winners_path="",
    )
    path = tmp_path / "leaderboard.csv"
    write_csv([row], path)
    header, data_rows = _read_csv(path)
    sample = data_rows[0]
    # Comp slots blank; derived columns blank; axes_triple blank (partial triple).
    assert sample[header.index("comp1_title")] == ""
    assert sample[header.index("top_comp_ww_m")] == ""
    assert sample[header.index("mean_comp_ww_m")] == ""
    assert sample[header.index("max_comp_similarity")] == ""
    assert sample[header.index("axes_triple")] == ""


# ── render_html smoke ───────────────────────────────────────────────────────


def test_render_html_contains_required_sections(tmp_path: Path) -> None:
    rows = [
        _full_row("evolve-20260524T172830Z", ("MF_04", "DE_09", "SW_11")),
        _row("evolve-20260524T161607Z", ("MF_07", "DE_08", "SW_09")),
    ]
    out = tmp_path / "leaderboard.html"
    render_html(rows, out)
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "<table" in html
    assert "<canvas" in html
    assert "Cross-Run Leaderboard" in html
    # New column headers.
    assert "World" in html
    assert "Hook" in html
    # Main row + companion card row.
    assert 'class="main-row"' in html
    assert 'class="card-row"' in html
    # The actual essence fields rendered in the card. F0.3: the pull-quote shows
    # compression_key.description, not the deprecated moral_wager 3-string lookup.
    assert "pharmaceutical research lab" in html
    assert "moment of maximum competence" in html  # compression in pull-quote
    assert "The Rebel" in html
    assert "Hollow Caregiver" in html
    # Top comp surfaced in card.
    assert "A.I. Artificial Intelligence" in html
    # Axes still surface in the card meta line (not in main row).
    assert "MF_04" in html


def test_render_html_card_can_be_targeted_by_id(tmp_path: Path) -> None:
    """Each card-row has a stable id so the JS expand toggle can find it."""
    rows = [_full_row("evolve-20260524T172830Z", ("MF_04", "DE_09", "SW_11"))]
    out = tmp_path / "leaderboard.html"
    render_html(rows, out)
    html = out.read_text(encoding="utf-8")
    assert 'id="card-evolve-20260524T172830Z"' in html
    assert 'data-card="evolve-20260524T172830Z"' in html


def test_render_html_truncates_long_world_in_main_row(tmp_path: Path) -> None:
    long_world = "x " * 80
    rows = [_full_row("evolve-A", ("MF_01", "DE_01", "SW_01"), world=long_world)]
    out = tmp_path / "leaderboard.html"
    render_html(rows, out)
    html = out.read_text(encoding="utf-8")
    # The main row cell is truncated with an ellipsis, but the full string is
    # in the data-world attribute (used for sorting).
    assert "…" in html
    assert long_world.strip() in html  # full string still present via data-world


def test_render_html_handles_empty_rows(tmp_path: Path) -> None:
    out = tmp_path / "leaderboard.html"
    render_html([], out)
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "No runs yet" in html


def test_render_html_fires_alarm_banner(tmp_path: Path) -> None:
    triple = ("MF_01", "DE_04", "SW_02")
    rows = [_row("evolve-A", triple), _row("evolve-B", triple)]
    out = tmp_path / "leaderboard.html"
    render_html(rows, out)
    html = out.read_text(encoding="utf-8")
    assert "Mode-collapse alarm" in html
    assert "MF_01" in html


def test_render_html_offline_uses_local_chart_js(tmp_path: Path) -> None:
    rows = [_row("evolve-A", ("MF_01", "DE_01", "SW_01"))]
    out = tmp_path / "leaderboard.html"
    render_html(rows, out, offline=True)
    html = out.read_text(encoding="utf-8")
    assert "vendor/chart.min.js" in html
    assert "cdn.jsdelivr.net" not in html


# ── build_leaderboard ───────────────────────────────────────────────────────


def test_build_leaderboard_orders_newest_first(tmp_path: Path) -> None:
    _seed_run(tmp_path, "evolve-20260101T000000Z")
    _seed_run(tmp_path, "evolve-20260524T172830Z")
    _seed_run(tmp_path, "evolve-20260301T120000Z")
    rows = build_leaderboard(tmp_path)
    assert [r.run_id for r in rows] == [
        "evolve-20260524T172830Z",
        "evolve-20260301T120000Z",
        "evolve-20260101T000000Z",
    ]


def test_build_leaderboard_skips_non_evolve_dirs(tmp_path: Path) -> None:
    _seed_run(tmp_path, "evolve-20260524T172830Z")
    # A folder that isn't an evolve run should be ignored.
    (tmp_path / "2026-05-19-the-quota").mkdir()
    rows = build_leaderboard(tmp_path)
    assert len(rows) == 1


def test_build_leaderboard_truncates_to_top_k(tmp_path: Path) -> None:
    for i in range(5):
        _seed_run(tmp_path, f"evolve-2026010{i + 1}T000000Z")
    rows = build_leaderboard(tmp_path, top_k=2)
    assert len(rows) == 2


def test_build_leaderboard_returns_empty_when_root_missing(tmp_path: Path) -> None:
    assert build_leaderboard(tmp_path / "nonexistent") == []
