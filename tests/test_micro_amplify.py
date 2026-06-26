"""Tests for pipeline/micro_amplify.py (Change 5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import pipeline.micro_amplify as ma

# ---------------------------------------------------------------------------
# _clamp_multiplier
# ---------------------------------------------------------------------------


class TestClampMultiplier:
    def test_within_range_passes_through(self) -> None:
        assert ma._clamp_multiplier(2.5) == 2.5

    def test_below_floor_clamped(self) -> None:
        assert ma._clamp_multiplier(0.5) == ma._MULTIPLIER_FLOOR

    def test_above_cap_clamped(self) -> None:
        assert ma._clamp_multiplier(99.0) == ma._MULTIPLIER_CAP

    def test_non_numeric_returns_floor(self) -> None:
        assert ma._clamp_multiplier("oops") == ma._MULTIPLIER_FLOOR

    def test_none_returns_floor(self) -> None:
        assert ma._clamp_multiplier(None) == ma._MULTIPLIER_FLOOR

    def test_exact_floor(self) -> None:
        assert ma._clamp_multiplier(1.0) == 1.0

    def test_exact_cap(self) -> None:
        assert ma._clamp_multiplier(5.0) == 5.0


# ---------------------------------------------------------------------------
# apply — disabled mode
# ---------------------------------------------------------------------------


class TestApplyDisabled:
    def test_disabled_returns_sidecar_with_block(self) -> None:
        sidecar: dict[str, Any] = {"title": "Test"}
        result = ma.apply(sidecar, phase_name="phase2", enabled=False)
        block = result["micro_amplification"]
        assert block["applied"] is False
        assert block["reason"] == "disabled"
        assert block["multiplier"] == 1.0
        assert block["phase"] == "phase2"

    def test_disabled_does_not_mutate_other_keys(self) -> None:
        sidecar: dict[str, Any] = {"title": "My Film"}
        ma.apply(sidecar, phase_name="p", enabled=False)
        assert sidecar["title"] == "My Film"


# ---------------------------------------------------------------------------
# apply — API error path
# ---------------------------------------------------------------------------


class TestApplyApiError:
    def test_api_error_sets_applied_false(self) -> None:
        sidecar: dict[str, Any] = {"title": "T"}
        with patch("pipeline.llm_client.build_chat_client", side_effect=RuntimeError("boom")):
            result = ma.apply(sidecar, phase_name="phase3", enabled=True)
        block = result["micro_amplification"]
        assert block["applied"] is False
        assert "api_error" in block["reason"]

    def test_api_error_preserves_sidecar_keys(self) -> None:
        sidecar: dict[str, Any] = {"logline": "A hero rises"}
        with patch("pipeline.llm_client.build_chat_client", side_effect=Exception("net")):
            result = ma.apply(sidecar, phase_name="p", enabled=True)
        assert result["logline"] == "A hero rises"


# ---------------------------------------------------------------------------
# apply — NONE response path
# ---------------------------------------------------------------------------


class TestApplyNoneResponse:
    def _mock_client(self, json_payload: dict[str, Any]) -> MagicMock:
        client = MagicMock()
        client.chat.return_value = json_payload
        return client

    def test_none_change_sets_applied_false(self) -> None:
        payload = {"change": None, "comp": None, "multiplier": 1.0, "reason": "NONE"}
        sidecar: dict[str, Any] = {"title": "X"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p5", enabled=True)
        assert result["micro_amplification"]["applied"] is False

    def test_multiplier_at_floor_sets_applied_false(self) -> None:
        payload = {"change": "add drama", "comp": "Comp (2020)", "multiplier": 1.0, "reason": "x"}
        sidecar: dict[str, Any] = {"title": "Y"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p6", enabled=True)
        assert result["micro_amplification"]["applied"] is False

    def test_string_none_change(self) -> None:
        payload = {"change": "NONE", "comp": None, "multiplier": 1.0, "reason": "x"}
        sidecar: dict[str, Any] = {"title": "Z"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p", enabled=True)
        assert result["micro_amplification"]["applied"] is False


# ---------------------------------------------------------------------------
# apply — successful amplification path
# ---------------------------------------------------------------------------


class TestApplySuccess:
    def _mock_client(self, json_payload: dict[str, Any]) -> MagicMock:
        client = MagicMock()
        client.chat.return_value = json_payload
        return client

    def test_successful_apply_sets_applied_true(self) -> None:
        payload = {
            "change": "add sci-fi elements",
            "comp": "Arrival (2016, $100M)",
            "multiplier": 1.8,
            "reason": "expands to sci-fi fans",
        }
        sidecar: dict[str, Any] = {"title": "Drama Film"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="phase2", enabled=True)
        block = result["micro_amplification"]
        assert block["applied"] is True
        assert block["multiplier"] == pytest.approx(1.8)
        assert block["phase"] == "phase2"
        assert "Arrival" in block["comp"]

    def test_micro_amplify_notes_appended(self) -> None:
        payload = {
            "change": "set in space",
            "comp": "Gravity (2013, $700M)",
            "multiplier": 2.0,
            "reason": "global reach",
        }
        sidecar: dict[str, Any] = {"title": "Earth Drama"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p", enabled=True)
        notes = result["micro_amplify_notes"]
        assert isinstance(notes, list)
        assert len(notes) == 1
        assert "[micro_amplify]" in notes[0]
        assert "Gravity" in notes[0]

    def test_existing_notes_preserved(self) -> None:
        payload = {
            "change": "add romance subplot",
            "comp": "Titanic (1997)",
            "multiplier": 1.5,
            "reason": "broader",
        }
        sidecar: dict[str, Any] = {"title": "Action Film", "micro_amplify_notes": ["prior note"]}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p", enabled=True)
        notes = result["micro_amplify_notes"]
        assert notes[0] == "prior note"
        assert len(notes) == 2

    def test_non_list_existing_notes_replaced(self) -> None:
        """If micro_amplify_notes was not a list, it gets overwritten cleanly."""
        payload = {
            "change": "add comedy",
            "comp": "Some Film (2020)",
            "multiplier": 1.3,
            "reason": "r",
        }
        sidecar: dict[str, Any] = {"title": "X", "micro_amplify_notes": "bad-type"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p", enabled=True)
        notes = result["micro_amplify_notes"]
        assert isinstance(notes, list)
        assert len(notes) == 1

    def test_multiplier_clamped_to_cap(self) -> None:
        payload = {
            "change": "make universal",
            "comp": "Avatar (2009)",
            "multiplier": 999.0,
            "reason": "everyone wants it",
        }
        sidecar: dict[str, Any] = {"title": "Niche Film"}
        with patch(
            "pipeline.llm_client.build_chat_client", return_value=self._mock_client(payload)
        ):
            result = ma.apply(sidecar, phase_name="p", enabled=True)
        assert result["micro_amplification"]["multiplier"] == ma._MULTIPLIER_CAP


# ---------------------------------------------------------------------------
# __all__ export
# ---------------------------------------------------------------------------


def test_all_exports_apply() -> None:
    assert "apply" in ma.__all__
