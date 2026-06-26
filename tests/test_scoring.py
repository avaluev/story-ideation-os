"""Unit tests for pipeline/scoring.py — ADR-0002 compliance + Al-Bukhari golden fixture.

All scoring logic lives in pipeline/scoring.py; LLMs MUST NOT compute scores (ADR-0002).
This file pins the contract that scoring.py must satisfy.

References:
- frameworks/sdt-spine.md §The sdt_score Formula
- frameworks/ajtbd-segmentation.md §The ajtbd_score Formula
- pipeline/data/polti_tobias_coherence.json (anti-pattern matrix)
- ADR-0002, ADR-0005
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# Defer import: module does not exist until Task 2 implements it.
# Tests are RED until pipeline/scoring.py is created.
scoring = pytest.importorskip(
    "pipeline.scoring",
    reason="pipeline.scoring lands in plan 03-03 Task 2 (scoring.py body)",
)


# ── sdt_score tests ───────────────────────────────────────────────────────────


def test_sdt_score_al_bukhari() -> None:
    """Al-Bukhari golden fixture: sdt_score must return exactly 70.

    Inputs (from frameworks/sdt-spine.md §The Worked Al-Bukhari Example):
        primary_need="relatedness", primary_strength=0.95,
        secondary_need="competence", secondary_strength=0.7,
        deprivation_amplifier_active=True

    Computation:
        amplified = (50 * 0.95 * 1.5) + (20 * 0.7) = 71.25 + 14.0 = 85.25
        rounded   = round(85.25) = 85
        capped    = min(85, 70) = 70
    """
    result = scoring.sdt_score("relatedness", 0.95, "competence", 0.7, True)
    assert result == 70, (
        f"Al-Bukhari sdt_score drift: got {result}, expected 70. "
        "See frameworks/sdt-spine.md §The Worked Al-Bukhari Example."
    )


def test_sdt_score_below_floor() -> None:
    """primary_strength < 0.7 must return 0 (hard floor from SDT framework)."""
    result = scoring.sdt_score("autonomy", 0.65, None, 0.0, False)
    assert result == 0, (
        f"Floor gate drift: primary_strength=0.65 (<0.7) must return 0, got {result}. "
        "See frameworks/sdt-spine.md §SDT primary-strength ≥0.7 floor."
    )


def test_sdt_score_no_amplifier() -> None:
    """No deprivation amplifier: amp=1.0, no secondary need."""
    result = scoring.sdt_score("competence", 0.8, None, 0.0, False)
    # amplified = (50 * 0.8 * 1.0) + (20 * 0.0) = 40.0 + 0.0 = 40.0
    # rounded = round(40.0) = 40; capped = min(40, 70) = 40
    assert result == 40, (
        f"No-amplifier sdt_score drift: got {result}, expected 40. "
        "Formula: min(round((50*0.8*1.0)+(20*0.0)), 70) = 40."
    )


# ── ajtbd_score tests ─────────────────────────────────────────────────────────


def test_ajtbd_score_al_bukhari() -> None:
    """Al-Bukhari golden fixture: ajtbd_score must return exactly 30.

    Inputs (from frameworks/ajtbd-segmentation.md §Worked Mini-Example):
        cited_audience=250_000_000, country_count=5, sources_per_claim=2,
        trend_direction="rising", primary_jtbd_strength=0.85

    All five thresholds met: 10+5+5+5+5 = 30; min(30,30) = 30.
    """
    result = scoring.ajtbd_score(250_000_000, 5, 2, "rising", 0.85)
    assert result == 30, (
        f"Al-Bukhari ajtbd_score drift: got {result}, expected 30. "
        "See frameworks/ajtbd-segmentation.md §Worked Mini-Example."
    )


def test_ajtbd_score_partial() -> None:
    """No thresholds met: all parameters below thresholds -> score 0."""
    # cited_audience=10M (<50M), country_count=2 (<3), sources_per_claim=1 (<2),
    # trend_direction="declining", primary_jtbd_strength=0.5 (<0.6)
    result = scoring.ajtbd_score(10_000_000, 2, 1, "declining", 0.5)
    assert result == 0, (
        f"Partial ajtbd_score drift: got {result}, expected 0. None of the five thresholds are met."
    )


# ── overall_score tests ───────────────────────────────────────────────────────


def test_overall_score_al_bukhari() -> None:
    """Al-Bukhari golden fixture: overall_score['final'] must be in [94, 98].

    upstream = 70 + 30 = 100
    critic_raw = 28 + 23 + 23 + 17 = 91
    cap_at_70_triggered = False (no cap applied)
    base = min(91, 100) = 91
    agreement_bonus = 5 (abs(91 - 100) = 9 <= 10)
    final = min(91 + 5, 100) = 96 — within [94, 98] tolerance
    """
    result = scoring.overall_score(70, 30, 28, 23, 23, 17, False)
    final = result["final"]
    assert 94 <= final <= 98, (
        f"Al-Bukhari overall_score['final'] drift: got {final}, expected 94..98. "
        "See .planning/phases/03-pipeline-code/03-03-PLAN.md §Al-Bukhari hand-computed values."
    )


def test_overall_score_keys() -> None:
    """Return dict must contain all six required keys.

    Keys: upstream, critic, base, agreement_bonus, final, passes_85_floor.
    """
    result = scoring.overall_score(70, 30, 28, 23, 23, 17, False)
    required_keys = {"upstream", "critic", "base", "agreement_bonus", "final", "passes_85_floor"}
    missing = required_keys - result.keys()
    assert not missing, (
        f"overall_score return dict missing keys: {missing}. "
        "All six keys are required per FEATURES.md REQ-P-006."
    )


def test_overall_score_passes_85_floor() -> None:
    """passes_85_floor semantics: True when final >= 85, False when final < 85."""
    # Score 86 -> passes_85_floor = True
    # upstream=50, ajtbd=30 -> upstream=80
    # critic: 25+20+20+15 = 80; no cap
    # base = min(80, 80) = 80; agreement_bonus = 5 (abs(80-80)=0 <= 10)
    # final = min(80+5, 100) = 85
    result_pass = scoring.overall_score(50, 30, 25, 20, 20, 15, False)
    # final should be 85 -> passes_85_floor = True (85 >= 85)
    assert result_pass["passes_85_floor"] is True, (
        f"passes_85_floor should be True for final=85, got {result_pass}"
    )

    # Score 84 -> passes_85_floor = False
    # upstream=40+20=60; critic=20+18+18+10=66; base=min(66,60)=60
    # agreement_bonus=5 (abs(66-60)=6 <= 10); final=min(65,100)=65 < 85
    result_fail = scoring.overall_score(40, 20, 20, 18, 18, 10, False)
    assert result_fail["passes_85_floor"] is False, (
        f"passes_85_floor should be False for final<85, got {result_fail}"
    )


# ── polti_tobias_coherence tests ──────────────────────────────────────────────


def test_polti_tobias_anti_pattern() -> None:
    """Known anti-pattern POLTI-5 x TOBIAS-15 (Pursuit x Forbidden Love) must return False.

    The first entry in pipeline/data/polti_tobias_coherence.json is:
        {"polti_id": 5, "tobias_id": 15, "verdict": "incoherent", ...}
    polti_tobias_coherence returns False for incoherent combinations.
    """
    result = scoring.polti_tobias_coherence(5, 15)
    assert result is False, (
        f"polti_tobias_coherence(5, 15) should return False (anti-pattern), got {result}. "
        "Entry POLTI-5_x_TOBIAS-15 (Pursuit x Forbidden Love) is in the anti_patterns list."
    )


def test_polti_tobias_coherent() -> None:
    """A combination NOT in the anti_patterns list must return True (coherent).

    polti_id=1 (Supplication), tobias_id=1 (Rescue) — not in the 5-entry seed.
    """
    result = scoring.polti_tobias_coherence(1, 1)
    assert result is True, (
        f"polti_tobias_coherence(1, 1) should return True (not in anti_patterns), got {result}. "
        "Polti 1 x Tobias 1 is not in pipeline/data/polti_tobias_coherence.json."
    )


# ── ANOMALY-001 belt-and-suspenders import check ─────────────────────────────


def test_no_llm_imports() -> None:
    """scoring.py must not import LLM clients — ANOMALY-001 belt-and-suspenders.

    Belt-and-suspenders alongside `make lint` (scripts/lint_imports.py).
    Banned: openrouter_client, pipeline.openrouter_client, anthropic, httpx.
    """
    src_path = pathlib.Path("pipeline/scoring.py")
    if not src_path.exists():
        pytest.skip("pipeline/scoring.py does not exist yet")
    src = src_path.read_text()
    tree = ast.parse(src)
    banned = {
        "openrouter_client",
        "pipeline.openrouter_client",
        "anthropic",
        "httpx",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in banned, (
                    f"ANOMALY-001: scoring.py imports '{alias.name}' which is banned. "
                    "scoring.py must be pure Python — no LLM clients. ADR-0002."
                )
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in banned, (
                f"ANOMALY-001: scoring.py has 'from {module} import ...' which is banned. "
                "scoring.py must be pure Python — no LLM clients. ADR-0002."
            )
