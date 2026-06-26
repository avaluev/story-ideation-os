"""Tests for pipeline/empirical_genius.py — 5th axis kill switch + EGI."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import empirical_genius as eg
from pipeline.empirical_genius import (
    ALPHA_NOVELTY,
    BETA_SHAPE,
    EGI_AXIS_MAX,
    GAMMA_SURVIVAL,
    KILL_SWITCHES,
    score_concept,
)


def _passing_concept() -> dict:
    """A concept that satisfies C006 (Want/Block/Transformation) and 25-35 word logline."""
    return {
        "concept_id": "test-001",
        "title": "Stub",
        # 28 words; has 'must' (want), 'against' (obstacle), 'becomes' (transformation)
        "logline": (
            "A burnt-out radiologist in Bengaluru must protect her replaced colleague "
            "against an automated diagnostic system as she becomes the AI's last "
            "human teacher before the merger."
        ),
        "key_roles": {
            "protagonist": "Dr. Layla, the radiologist",
            "antagonist": "Mehta, the lab CEO",
            "ally": "the union organizer",
            "mentor": None,
        },
    }


def _passing_critique() -> dict:
    return {
        "concept_id": "test-001",
        "novelty_score": 25,
        "jtbd_score": 20,
        "contradiction_score": 22,
        "specificity_score": 18,
        "cap_at_70_triggered": False,
        "ten_school_self_check": [True] * 8 + [False] * 2,  # 8/10 pass
        "cross_checks": {
            "no_anti_slop_violation": True,
            "seven_school_floor_met": True,
            "polti_tobias_coherent": True,
            "logline_word_count_ok": True,
            "triz_both_poles_held": True,
        },
    }


def _passing_audience() -> dict:
    return {
        "asset_id": "asset-001",
        "cited_audience": 600_000_000,
        "target_countries": ["US", "IN", "DE", "BR"],
        "trend_direction": "rising",
    }


def test_egi_constants() -> None:
    """5th axis contributes up to 25 points; ALPHA + BETA + GAMMA == 1.0."""
    assert EGI_AXIS_MAX == 25
    assert ALPHA_NOVELTY + BETA_SHAPE + GAMMA_SURVIVAL == 1.0
    assert KILL_SWITCHES == ("C006", "C007", "C008")


def test_C006_kill_switch_fires_on_unstructured_logline() -> None:
    """A trivially-formed logline (no Want/Block/Transformation) hits C006 reject."""
    bad = {
        "concept_id": "bad-001",
        "title": "Stub",
        "logline": "A short sentence.",  # no want, no obstacle, no transformation
    }
    result = score_concept(
        bad,
        {
            "concept_id": "bad-001",
            "novelty_score": 0,
            "jtbd_score": 0,
            "contradiction_score": 0,
            "specificity_score": 0,
            "ten_school_self_check": [False] * 10,
        },
        audience_row={},
        jtbd_row={},
        asset_row={},
    )
    assert result["final"] == 0.0
    assert "C006" in result["kill_switches_triggered"]
    assert "REJECTED" in result["message"]


def test_C006_passes_with_well_formed_logline() -> None:
    """Properly-formed logline (Want + Block + Transformation) clears C006."""
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        _passing_audience(),
        jtbd_row={},
        asset_row={},
    )
    assert "C006" not in result["kill_switches_triggered"]
    assert "C007" not in result["kill_switches_triggered"]
    assert result["final"] >= 0.0


def test_C007_passes_well_formed_and_opposition_or_clock_agency() -> None:
    """C007 passes when the protagonist drives, changes, faces opposition, or
    races a clock -- including agency expressed only through opposition+clock
    (the Ostankino golden-anchor shape), not just goal verbs."""
    assert eg._check_C007_active_protagonist(_passing_concept()) is True
    # Opposition + clock agency, no explicit goal verb (Ostankino-style).
    obstacle_clock = {
        "logline": (
            "Two married journalists are trapped in a burning television tower for "
            "exactly ninety minutes while the coup collapses outside and the fire "
            "closes in above them."
        )
    }
    assert eg._check_C007_active_protagonist(obstacle_clock) is True
    # A terse logline backed by a richer synopsis still passes.
    terse = {"logline": "A quiet inventory of one small town at dawn light today.", "synopsis": ""}
    # (no marker in the terse line -> fails; this documents the floor)
    assert eg._check_C007_active_protagonist(terse) is False


def test_C007_fires_on_empty_fragment_and_stative() -> None:
    """C007 is a LIVE gate (not the old `return True` no-op): it rejects an
    empty logline, a sub-12-word fragment, and a motion-less stative premise."""
    assert eg._check_C007_active_protagonist({"logline": ""}) is False
    assert eg._check_C007_active_protagonist({"logline": "   "}) is False
    # 5-word fragment that *passes* C006 (want+obstacle) but is too thin for C007.
    assert eg._check_C007_active_protagonist({"logline": "She must fight against time."}) is False
    stative = "A quiet, foggy morning settles over the small coastal village near the grey water."
    assert eg._check_C007_active_protagonist({"logline": stative}) is False


def test_C007_fires_in_score_concept_on_thin_but_c006_passing_logline() -> None:
    """Integration: a logline thin enough to fail C007 but well-formed enough to
    clear C006 is REJECTED with C007 in the trigger list -- proving the kill
    switch reaches the score_concept reject path (final == 0.0)."""
    thin = {"concept_id": "thin-001", "title": "Thin", "logline": "She must fight against time."}
    result = score_concept(
        thin,
        {
            "concept_id": "thin-001",
            "novelty_score": 0,
            "jtbd_score": 0,
            "contradiction_score": 0,
            "specificity_score": 0,
            "ten_school_self_check": [False] * 10,
        },
        audience_row={},
        jtbd_row={},
        asset_row={},
    )
    assert result["final"] == 0.0
    assert "C007" in result["kill_switches_triggered"]


def test_kill_switches_are_live_not_noop() -> None:
    """Harness gate-liveness enforcer: every kill switch MUST be able to return
    False on some input. A kill switch that is an unconditional `return True`
    silently games every downstream score (the C007 regression this fixes), so
    pin that each of C006/C007/C008 actually fires on a degenerate input."""
    assert eg._check_C006_want_need_flaw_transformation({"logline": "A short sentence."}) is False
    assert eg._check_C007_active_protagonist({"logline": ""}) is False
    # C008 degrades-to-pass on ABSENT data (intentional), so it fires only on a
    # present-but-below-floor SOM ($100M < the $1B hard floor).
    assert eg._check_C008_commercial_scale({"projected_som_usd_m": 100}) is False


def test_egi_in_range_when_kill_switches_pass(tmp_path: Path) -> None:
    """EGI is in [0, EGI_AXIS_MAX] when both kill switches pass."""
    checklist = tmp_path / "GREATNESS_CHECKLIST.json"
    checklist.write_text(
        json.dumps({"version": "1.0", "criteria": [], "premortem_kill_conditions": []}),
        encoding="utf-8",
    )
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        _passing_audience(),
        jtbd_row={},
        asset_row={},
        checklist_path=checklist,
    )
    assert 0.0 <= result["final"] <= EGI_AXIS_MAX
    assert 0.0 <= result["novelty"] <= 1.0
    assert 0.0 <= result["shape"] <= 1.0
    assert 0.0 <= result["survival"] <= 1.0


def test_premortem_survival_high_when_full_data(tmp_path: Path) -> None:
    """A concept with named roles + ≥50M audience + ≥3 countries + valid logline + 8/10 schools
    + cross_checks all true should hit a high survival rate.
    """
    checklist = tmp_path / "GREATNESS_CHECKLIST.json"
    checklist.write_text(json.dumps({"version": "1.0", "criteria": []}), encoding="utf-8")
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        _passing_audience(),
        jtbd_row={},
        asset_row={},
        checklist_path=checklist,
    )
    # 8 checks, all should pass: protag, antag, audience, countries, logline-words,
    # 7-school floor (8/10), cap_at_70 not triggered, all cross_checks true → 8/8 = 1.0
    assert result["survival"] == 1.0


def test_premortem_survival_drops_when_audience_below_floor(tmp_path: Path) -> None:
    """Audience <50M drops survival rate by 1/8."""
    audience = _passing_audience()
    audience["cited_audience"] = 1_000_000  # 1M, below floor

    checklist = tmp_path / "GREATNESS_CHECKLIST.json"
    checklist.write_text(json.dumps({"version": "1.0", "criteria": []}), encoding="utf-8")
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
        checklist_path=checklist,
    )
    assert result["survival"] < 1.0
    assert result["survival"] >= 0.875  # 7/8


def test_degraded_flag_when_checklist_missing(tmp_path: Path) -> None:
    """No GREATNESS_CHECKLIST.json → degraded=True (still computes if kill switches pass)."""
    missing = tmp_path / "no_such_checklist.json"
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        _passing_audience(),
        jtbd_row={},
        asset_row={},
        checklist_path=missing,
    )
    assert result["degraded"] is True


def test_message_format_includes_egi_breakdown(tmp_path: Path) -> None:
    """The message string includes the per-component breakdown for transparency."""
    checklist = tmp_path / "GREATNESS_CHECKLIST.json"
    checklist.write_text(json.dumps({"version": "1.0", "criteria": []}), encoding="utf-8")
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        _passing_audience(),
        jtbd_row={},
        asset_row={},
        checklist_path=checklist,
    )
    msg = result["message"]
    assert "EGI=" in msg
    assert "novelty" in msg
    assert "shape" in msg
    assert "survival" in msg


def test_C008_kill_switch_fires_on_sub_1b_som() -> None:
    """C008 fires when projected_som_usd_m < $1 000M (hard floor)."""
    audience = _passing_audience()
    audience["projected_som_usd_m"] = 500.0  # $500M — below the $1B floor
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
    )
    assert result["final"] == 0.0
    assert "C008" in result["kill_switches_triggered"]
    assert "REJECTED" in result["message"]
    assert result["som_band"] == "below_1b"


def test_C008_passes_when_som_above_1b() -> None:
    """C008 passes when projected_som_usd_m >= $1 000M."""
    audience = _passing_audience()
    audience["projected_som_usd_m"] = 1500.0  # $1.5B — in the 1b_to_2b band
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
    )
    assert "C008" not in result["kill_switches_triggered"]
    assert result["criteria_pass"]["C008"] is True
    assert result["som_band"] == "1b_to_2b"


def test_C008_degrades_gracefully_when_som_absent() -> None:
    """C008 passes (no kill) when projected_som_usd_m is not set — degrade mode."""
    audience = _passing_audience()
    # No projected_som_usd_m key at all
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
    )
    assert "C008" not in result["kill_switches_triggered"]
    assert result["som_band"] == "unknown"


def test_C008_criteria_marked_unchecked_when_som_absent() -> None:
    """When projected_som_usd_m is absent, C008 must be None in criteria_pass and
    False in criteria_checked — the criterion was not evaluated against real data."""
    audience = _passing_audience()
    # Explicitly ensure the key is absent
    audience.pop("projected_som_usd_m", None)
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
    )
    # No kill — concept is not rejected due to missing SOM data
    assert "C008" not in result["kill_switches_triggered"]
    assert result["som_band"] == "unknown"
    # Tri-state: criteria_pass["C008"] is None (not True, not False)
    assert result["criteria_pass"]["C008"] is None
    # criteria_checked["C008"] must be False — data was absent so we did not check
    assert result["criteria_checked"]["C008"] is False


def test_C008_criteria_true_only_when_som_present_and_passes() -> None:
    """criteria_pass["C008"] is True only when projected_som_usd_m is present AND >= $1B,
    and criteria_checked["C008"] is True in that case."""
    # Case 1: SOM present and above floor
    audience_pass = _passing_audience()
    audience_pass["projected_som_usd_m"] = 1500.0  # $1.5B — passes
    result_pass = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience_pass,
        jtbd_row={},
        asset_row={},
    )
    assert result_pass["criteria_pass"]["C008"] is True
    assert result_pass["criteria_checked"]["C008"] is True
    assert "C008" not in result_pass["kill_switches_triggered"]

    # Case 2: SOM present but below floor
    audience_fail = _passing_audience()
    audience_fail["projected_som_usd_m"] = 500.0  # $500M — below $1B floor
    result_fail = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience_fail,
        jtbd_row={},
        asset_row={},
    )
    assert result_fail["criteria_pass"]["C008"] is False
    assert result_fail["criteria_checked"]["C008"] is True
    assert "C008" in result_fail["kill_switches_triggered"]

    # Case 3: SOM absent — not True (the old wrong behavior)
    audience_absent = _passing_audience()
    audience_absent.pop("projected_som_usd_m", None)
    result_absent = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience_absent,
        jtbd_row={},
        asset_row={},
    )
    assert result_absent["criteria_pass"]["C008"] is None  # not True — not confirmed pass
    assert result_absent["criteria_checked"]["C008"] is False
    assert "C008" not in result_absent["kill_switches_triggered"]


def test_som_band_above_2b() -> None:
    """som_band is 'above_2b' when projected_som_usd_m >= $2 000M."""
    audience = _passing_audience()
    audience["projected_som_usd_m"] = 2500.0  # $2.5B — above target
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
    )
    assert result["som_band"] == "above_2b"
    assert result["criteria_pass"]["C008"] is True


def test_success_path_includes_som_band_and_c008_criteria() -> None:
    """On a full pass, the result dict carries som_band and C008 in criteria_pass."""
    audience = _passing_audience()
    audience["projected_som_usd_m"] = 3000.0
    result = score_concept(
        _passing_concept(),
        _passing_critique(),
        audience,
        jtbd_row={},
        asset_row={},
    )
    assert "som_band" in result
    assert "C008" in result["criteria_pass"]
    assert result["criteria_pass"]["C008"] is True


# ── C002 embedding novelty (commit ___ wired the CorpusIndex) ────────────────


class _StubCorpusIndex:
    """Stand-in for CorpusIndex with a fixed max_cosine return value."""

    def __init__(self, sim: float) -> None:
        self._sim = sim

    def max_cosine(self, _text: str) -> float:
        return self._sim


def _make_idx_getter(sim: float):  # type: ignore[no-untyped-def]
    """Return a no-arg callable that yields a fresh _StubCorpusIndex with the
    given similarity. Used in monkeypatch.setattr to dodge PLW0108 (no
    bare ``lambda: ...()`` form)."""
    idx = _StubCorpusIndex(sim)

    def get() -> _StubCorpusIndex:
        return idx

    return get


class TestC002EmbeddingNovelty:
    """The novelty value is computed live from
    pipeline.crystallize.embeddings.CorpusIndex when both
    sentence-transformers AND the .npz index file are available.
    Tests inject a stub via monkeypatching the lazy loader."""

    def test_degraded_when_no_index(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]

        # Force the cache to a known "no index" state.
        eg._NOVELTY_INDEX_CACHE.clear()
        monkeypatch.setattr(eg, "_get_corpus_index", lambda: None)
        novelty, degraded = eg._embedding_novelty({"logline": "anything", "synopsis": "anything"})
        assert degraded is True
        assert novelty == eg._NOVELTY_NEUTRAL

    def test_degraded_when_empty_input(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        eg._NOVELTY_INDEX_CACHE.clear()
        monkeypatch.setattr(eg, "_get_corpus_index", _make_idx_getter(1.0))
        novelty, degraded = eg._embedding_novelty({})
        assert degraded is True  # empty text -> can't embed -> degrade
        assert novelty == eg._NOVELTY_NEUTRAL

    def test_high_similarity_low_novelty(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        eg._NOVELTY_INDEX_CACHE.clear()
        monkeypatch.setattr(eg, "_get_corpus_index", _make_idx_getter(0.95))
        novelty, degraded = eg._embedding_novelty({"logline": "x", "synopsis": "y"})
        assert degraded is False
        # novelty = 1 - 0.95 = 0.05
        assert abs(novelty - 0.05) < 1e-6

    def test_low_similarity_high_novelty(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        eg._NOVELTY_INDEX_CACHE.clear()
        monkeypatch.setattr(eg, "_get_corpus_index", _make_idx_getter(0.10))
        novelty, degraded = eg._embedding_novelty({"logline": "x", "synopsis": "y"})
        assert degraded is False
        # novelty = 1 - 0.10 = 0.90
        assert abs(novelty - 0.90) < 1e-6

    def test_clamps_to_unit_interval(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        eg._NOVELTY_INDEX_CACHE.clear()
        monkeypatch.setattr(eg, "_get_corpus_index", _make_idx_getter(1.5))
        novelty, _ = eg._embedding_novelty({"logline": "x", "synopsis": "y"})
        # 1 - 1.5 = -0.5 -> clamped to 0.0
        assert novelty == 0.0
