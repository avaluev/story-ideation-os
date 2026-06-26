"""Tests for pipeline.commercial_prescreen."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pipeline.commercial_prescreen import PrescreenResult, prescreen


@dataclass
class _FakeSeed:
    bt_id: str
    us_space: str
    resonance_score: float
    novelty_band: str = "neutral"


class TestPrescreenVerdict:
    def test_high_commercial_bt_passes(self) -> None:
        seed = _FakeSeed("BT-003", "a courtroom during a murder trial", 0.75)
        result = prescreen(seed)
        assert result.verdict == "PASS"

    def test_overdone_bt_fails(self) -> None:
        seed = _FakeSeed("BT-029", "a deep-sea mining platform", 0.70)
        result = prescreen(seed)
        assert result.verdict == "FAIL"

    def test_low_resonance_unknown_bt_is_maybe(self) -> None:
        seed = _FakeSeed("BT-099", "a niche local festival", 0.50)
        result = prescreen(seed)
        assert result.verdict in {"MAYBE", "FAIL"}

    def test_universal_space_boosts_score(self) -> None:
        seed_basic = _FakeSeed("BT-099", "an unusual place", 0.60)
        seed_universal = _FakeSeed("BT-099", "a corporation during a trial", 0.60)
        r_basic = prescreen(seed_basic)
        r_universal = prescreen(seed_universal)
        assert r_universal.commercial_score >= r_basic.commercial_score

    def test_underexplored_band_boosts(self) -> None:
        seed_neutral = _FakeSeed("BT-043", "a courtroom", 0.65, "neutral")
        seed_under = _FakeSeed("BT-043", "a courtroom", 0.65, "underexplored")
        r_neutral = prescreen(seed_neutral)
        r_under = prescreen(seed_under)
        assert r_under.commercial_score > r_neutral.commercial_score

    def test_overdone_band_penalises(self) -> None:
        # Use a BT not in _HIGH_COMMERCIAL_BT so the penalty is not cancelled
        seed = _FakeSeed("BT-099", "an unusual place", 0.80, "overdone")
        result = prescreen(seed)
        assert result.commercial_score < 0.80

    def test_result_has_recommendation(self) -> None:
        seed = _FakeSeed("BT-003", "a legal trial", 0.75)
        result = prescreen(seed)
        assert result.recommendation
        assert len(result.recommendation) > 10

    def test_ceiling_estimate_positive(self) -> None:
        seed = _FakeSeed("BT-003", "a courtroom", 0.75)
        result = prescreen(seed)
        assert result.ceiling_estimate_M > 0

    def test_reasons_non_empty(self) -> None:
        seed = _FakeSeed("BT-003", "a courtroom", 0.75)
        result = prescreen(seed)
        assert isinstance(result.reasons, list)
        assert len(result.reasons) >= 1

    def test_result_is_frozen(self) -> None:
        seed = _FakeSeed("BT-003", "a courtroom", 0.75)
        result = prescreen(seed)
        assert isinstance(result, PrescreenResult)
        with pytest.raises((AttributeError, TypeError)):
            result.verdict = "FAIL"  # type: ignore[misc]
