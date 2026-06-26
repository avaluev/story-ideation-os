"""EVAL — SOM/SAM/TAM credibility bounds (R15).

Every published revenue triple must satisfy ``0 < SOM_y1 < SAM <= TAM`` and,
where a calculation_method is recorded, it must be ``python_executed``
(ADR-0011). This kills the SOM > SAM credibility bomb before any slate ships.

Scans the multi-format slate JSON (runs/format-slate/*-slate.json) and the
cross-run leaderboard (data/leaderboard.jsonl). SKIPS on a fresh checkout
where neither carries a revenue triple (mirrors the evals/test_revenue_projection
skip-on-empty pattern) so the gate never red-bars a clean clone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_SLATE_DIR = Path("runs/format-slate")
_LEADERBOARD = Path("data/leaderboard.jsonl")


def _triples_from_slate() -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    if not _SLATE_DIR.exists():
        return rows
    for p in sorted(_SLATE_DIR.glob("*-slate.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for c in data.get("concepts", []):
            if isinstance(c, dict) and c.get("som_y1_usd") is not None:
                rows.append((f"{p.name}:{c.get('format')}", c))
    return rows


def _triples_from_leaderboard() -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    if not _LEADERBOARD.exists() or _LEADERBOARD.stat().st_size == 0:
        return rows
    with _LEADERBOARD.open(encoding="utf-8") as f:
        for i, raw in enumerate(f):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rev = obj.get("revenue") if isinstance(obj, dict) else None
            if isinstance(rev, dict) and rev.get("som_y1_usd") is not None:
                rows.append((f"leaderboard:{i}", rev))
    return rows


def _all_triples() -> list[tuple[str, dict[str, Any]]]:
    return _triples_from_slate() + _triples_from_leaderboard()


def test_som_lt_sam_lt_tam() -> None:
    rows = _all_triples()
    if not rows:
        pytest.skip("no slate/leaderboard rows with a revenue triple yet (cold start)")
    violations: list[str] = []
    for label, r in rows:
        som = r.get("som_y1_usd")
        sam = r.get("sam_usd")
        tam = r.get("tam_usd")
        if som is None or sam is None or tam is None:
            continue  # partial row — the python_executed test covers method
        if not (0 < float(som) < float(sam) <= float(tam)):
            violations.append(
                f"{label}: SOM {float(som):,.0f} < SAM {float(sam):,.0f} "
                f"<= TAM {float(tam):,.0f} violated"
            )
    assert not violations, "SOM<SAM<=TAM credibility breached:\n  " + "\n  ".join(violations)


def test_revenue_is_python_executed() -> None:
    rows = _all_triples()
    if not rows:
        pytest.skip("no slate/leaderboard rows with a revenue triple yet (cold start)")
    bad: list[str] = []
    for label, r in rows:
        method = r.get("calculation_method")
        if method is not None and method != "python_executed":
            bad.append(f"{label}: calculation_method={method!r}")
    assert not bad, "non-python_executed revenue published:\n  " + "\n  ".join(bad)
