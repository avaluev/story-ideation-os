"""Unit tests for pipeline.kb — V4A-003b knowledge memory substrate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline.kb import (
    DEFAULT_USE_THRESHOLD,
    KbAsset,
    _main,
    load_kb,
    record_asset,
    retire_overused,
    search,
)


def _asset(
    asset_id: str,
    *,
    domain: str = "K",
    title: str | None = None,
    summary: str | None = None,
    audience: int = 75_000_000,
    used: tuple[str, ...] = (),
    retired: str | None = None,
) -> KbAsset:
    return KbAsset(
        asset_id=asset_id,
        domain=domain,
        asset_title=title or f"Asset {asset_id}",
        ferocious_specific_summary=summary
        or f"Specific summary about {asset_id} antarctic ice cores winter rituals",
        audience_size=audience,
        created_at=datetime.now(UTC).isoformat(),
        used_in_concepts=used,
        retired_at=retired,
    )


def test_kb_asset_validates_summary_word_count() -> None:
    long_summary = " ".join(["w"] * 200)
    with pytest.raises(ValueError, match="ferocious_specific_summary"):
        KbAsset(
            asset_id="x",
            domain="K",
            asset_title="t",
            ferocious_specific_summary=long_summary,
            audience_size=60_000_000,
            created_at="2026-05-10T00:00:00+00:00",
        )


def test_load_kb_returns_empty_when_path_missing(tmp_path: Path) -> None:
    assert load_kb(tmp_path / "nope.jsonl") == []


def test_record_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    asset = _asset("a1")
    record_asset(asset, path=p)
    rows = load_kb(p)
    assert len(rows) == 1
    assert rows[0].asset_id == "a1"
    assert rows[0].used_in_concepts == ()


def test_record_appends_used_in_concept_when_passed(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    asset = _asset("a1")
    record_asset(asset, used_in="concept-xyz", path=p)
    row = load_kb(p)[0]
    assert "concept-xyz" in row.used_in_concepts


def test_search_returns_top_k_by_overlap(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    record_asset(
        _asset("a1", title="Antarctic ice cores", summary="ice cores antarctic permafrost"),
        path=p,
    )
    record_asset(
        _asset("a2", title="Mongolian throat singing", summary="throat singing nomadic steppe"),
        path=p,
    )
    record_asset(
        _asset("a3", title="Pacific tide pools", summary="tide pools coastal ecosystem"),
        path=p,
    )
    hits = search("antarctic ice", top_k=2, path=p)
    assert len(hits) >= 1
    assert hits[0].asset_id == "a1"


def test_search_returns_empty_for_empty_query(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    record_asset(_asset("a1"), path=p)
    assert search("", path=p) == []


def test_search_excludes_retired_rows(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    record_asset(
        _asset("active", title="active antarctic", summary="active antarctic ice"),
        path=p,
    )
    record_asset(
        _asset(
            "retired",
            title="retired antarctic",
            summary="retired antarctic ice",
            retired="2026-01-01T00:00:00+00:00",
        ),
        path=p,
    )
    hits = search("antarctic", path=p)
    assert {h.asset_id for h in hits} == {"active"}


def test_retire_overused_marks_when_use_count_exceeds_threshold(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    overused = _asset("hot", used=tuple(f"c{i}" for i in range(DEFAULT_USE_THRESHOLD + 2)))
    cool = _asset("cool", used=("c1",))
    record_asset(overused, path=p)
    record_asset(cool, path=p)
    n = retire_overused(path=p)
    assert n == 1
    rows = {r.asset_id: r for r in load_kb(p)}
    assert rows["hot"].retired_at is not None
    assert rows["cool"].retired_at is None


def test_retire_overused_returns_zero_when_kb_empty(tmp_path: Path) -> None:
    assert retire_overused(path=tmp_path / "missing.jsonl") == 0


def test_retire_is_idempotent_on_already_retired(tmp_path: Path) -> None:
    p = tmp_path / "kb.jsonl"
    overused = _asset("hot", used=tuple(f"c{i}" for i in range(DEFAULT_USE_THRESHOLD + 2)))
    record_asset(overused, path=p)
    assert retire_overused(path=p) == 1
    # Second pass should retire 0 (row already retired)
    assert retire_overused(path=p) == 0


def test_cli_search_prints_hits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "kb.jsonl"
    record_asset(_asset("a1", title="ice"), path=p)
    rc = _main(["--search", "ice", "--kb-path", str(p)])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "a1" in captured


def test_cli_retire_prints_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "kb.jsonl"
    record_asset(
        _asset("hot", used=tuple(f"c{i}" for i in range(DEFAULT_USE_THRESHOLD + 1))),
        path=p,
    )
    rc = _main(["--retire-overused", "--kb-path", str(p)])
    assert rc == 0
    assert "retired 1" in capsys.readouterr().out


def test_cli_no_subcommand_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _main([])
    assert rc == 1


def test_record_uses_append_jsonl_format(tmp_path: Path) -> None:
    """Each row is one JSON line; trailing newline; valid JSON."""
    p = tmp_path / "kb.jsonl"
    record_asset(_asset("a1"), path=p)
    record_asset(_asset("a2"), path=p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # raises if malformed
