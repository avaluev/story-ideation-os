"""Scorer-calibration regression gate (G5).

The cheapest ground-truth anchor for the engine's taste: under the LIVE goal,
every golden concept must outrank every rejected concept. A weight refit, a
magic-multiplier edit, or a facet bug that breaks that ordering fails CI here.

Anchor profiles
===============

The seven anchors exist on disk as markdown (``examples/golden/*.md`` x3,
``examples/rejected/*.md`` x4) with a *rubric* frontmatter schema (score /
novelty_score / failure_mode) that is NOT the ``CompoundScore`` shape
``crystallization_score`` consumes. The "96/90/85" figures in those files are
human rubric scores, not ``[0,1]`` crystallization outputs (the G5 pre-write
caveat). So each anchor is given a faithful ``CompoundScore``-shaped profile
below, derived from its documented strength/failure:

* golden anchors are strong across every facet (they are greenlight-grade);
* each rejected anchor is weak on a DIFFERENT facet, matching its file's
  documented failure mode -- so the separation is not driven by one facet and a
  plausible weight change to any facet can move the ranking.

That diversity is what makes this a real regression gate rather than a tautology:
``test_calibration_is_weight_sensitive`` proves a som-only weight vector PROMOTES
the unsourced-inflated-market reject above a golden concept (the exact Goodhart
failure the operator's balanced weights guard against). The values were confirmed
to separate under the live goal BEFORE this assertion was locked (the G5
pre-write check).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from pipeline.crystallize.score import crystallization_score
from pipeline.goal import DEFAULT_GOAL_PATH, Goal

ROOT = Path(__file__).resolve().parent.parent

# Each entry: (CompoundScore-shaped dict, derivative_distance). derivative_distance
# is a separate arg to crystallization_score (novelty vs corpus), not a score key.
GOLDEN: dict[str, tuple[dict[str, Any], float]] = {
    # examples/golden/HC-bukhari.md   -- score 96, novelty 28/30, audience 2B.
    "HC-bukhari": (
        dict(
            genius_score=0.95,
            goldilocks_score=0.85,
            cluster_coherence=0.90,
            emotional_universality_score=4.7,
            som_y1_usd=700e6,
            standalone_ip_flag=True,
            passes_500m_gate=True,
            passes_genius_gate=True,
        ),
        0.92,
    ),
    # examples/golden/HC-ostankino.md -- score 90.
    "HC-ostankino": (
        dict(
            genius_score=0.88,
            goldilocks_score=0.82,
            cluster_coherence=0.85,
            emotional_universality_score=4.5,
            som_y1_usd=500e6,
            standalone_ip_flag=True,
            passes_500m_gate=True,
            passes_genius_gate=True,
        ),
        0.85,
    ),
    # examples/golden/HC-mamontenok.md -- score 85.
    "HC-mamontenok": (
        dict(
            genius_score=0.82,
            goldilocks_score=0.78,
            cluster_coherence=0.80,
            emotional_universality_score=4.3,
            som_y1_usd=420e6,
            standalone_ip_flag=True,
            passes_500m_gate=True,
            passes_genius_gate=True,
        ),
        0.80,
    ),
}

REJECTED: dict[str, tuple[dict[str, Any], float]] = {
    # generic-logline slop, novelty 8/30, anti-slop violation -> fails the genius
    # gate; corpus-near -> low derivative_distance.
    "REJ-slop-logline": (
        dict(
            genius_score=0.20,
            goldilocks_score=0.45,
            cluster_coherence=0.50,
            emotional_universality_score=3.0,
            som_y1_usd=200e6,
            standalone_ip_flag=True,
            passes_500m_gate=True,
            passes_genius_gate=False,
        ),
        0.25,
    ),
    # no TRIZ contradiction -> low goldilocks tension + fails the genius gate.
    "REJ-no-triz": (
        dict(
            genius_score=0.35,
            goldilocks_score=0.20,
            cluster_coherence=0.55,
            emotional_universality_score=3.0,
            som_y1_usd=200e6,
            standalone_ip_flag=True,
            passes_500m_gate=True,
            passes_genius_gate=False,
        ),
        0.45,
    ),
    # well-crafted but tiny market -> sub-floor SOM + fails the 500m gate.
    "REJ-niche-audience": (
        dict(
            genius_score=0.70,
            goldilocks_score=0.70,
            cluster_coherence=0.70,
            emotional_universality_score=3.5,
            som_y1_usd=8e6,
            standalone_ip_flag=True,
            passes_500m_gate=False,
            passes_genius_gate=True,
        ),
        0.70,
    ),
    # unsourced / inflated market claim -> a deceptively HIGH SOM with weak craft.
    # Scores low under balanced weights but is PROMOTED by a som-obsessed vector
    # (see test_calibration_is_weight_sensitive).
    "REJ-bad-sourcing": (
        dict(
            genius_score=0.30,
            goldilocks_score=0.40,
            cluster_coherence=0.45,
            emotional_universality_score=3.0,
            som_y1_usd=1200e6,
            standalone_ip_flag=True,
            passes_500m_gate=True,
            passes_genius_gate=True,
        ),
        0.40,
    ),
}


def _score(profile: tuple[dict[str, Any], float], goal: Goal) -> float:
    scores, deriv = profile
    return crystallization_score(scores, derivative_distance=deriv, goal=goal)


def _live_goal() -> Goal:
    return Goal.load(DEFAULT_GOAL_PATH)


def test_anchor_files_exist() -> None:
    """Tie the profiles to the real anchor files; a deleted/renamed anchor fails."""
    for name in GOLDEN:
        assert (ROOT / "examples" / "golden" / f"{name}.md").exists(), name
    for name in REJECTED:
        assert (ROOT / "examples" / "rejected" / f"{name}.md").exists(), name


def test_golden_outrank_rejected_under_live_goal() -> None:
    """Every golden concept outranks every rejected one under the LIVE goal.

    This is the regression gate: edit a weight (or a magic multiplier in
    compound_seed) so the ordering breaks, and this goes RED.
    """
    goal = _live_goal()
    golden = {k: _score(v, goal) for k, v in GOLDEN.items()}
    rejected = {k: _score(v, goal) for k, v in REJECTED.items()}
    separation = min(golden.values()) - max(rejected.values())
    assert separation > 0, (
        f"golden cohort must outrank rejected under {goal.goal_id}. "
        f"min(golden)={min(golden.values()):.4f} max(rejected)={max(rejected.values()):.4f} "
        f"(golden={golden}, rejected={rejected})"
    )


def test_calibration_is_weight_sensitive() -> None:
    """Prove the gate is NOT a tautology: a som-only weight vector PROMOTES the
    unsourced-inflated-market reject above a golden concept. The eval responds to
    weights, so a real weight regression can move it (and this demonstrates the
    Goodhart failure the operator's balanced weights prevent)."""
    som_only = replace(
        _live_goal(),
        facet_weights={
            "genius": 0.0,
            "goldilocks": 0.0,
            "cluster_coherence": 0.0,
            "emotional_universality": 0.0,
            "som_y1": 1.0,
            "derivative_distance": 0.0,
            "standalone_ip": 0.0,
        },
    )
    bad_sourcing = _score(REJECTED["REJ-bad-sourcing"], som_only)
    worst_golden = min(_score(v, som_only) for v in GOLDEN.values())
    assert bad_sourcing > worst_golden, (
        "a som-only goal should rank the inflated-unsourced-market reject above a "
        f"golden concept (sensitivity proof): bad_sourcing={bad_sourcing:.4f} "
        f"worst_golden={worst_golden:.4f}"
    )
