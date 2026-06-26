"""Tests for pipeline.quota — subscription weekly quota tracker (ADR-0008)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import pipeline.quota as q


@pytest.fixture(autouse=True)
def _isolate_quota_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect QUOTA_LOG to a per-test tmp file."""
    monkeypatch.setattr(q, "QUOTA_LOG", tmp_path / "quota.jsonl")


def test_record_appends_one_row(tmp_path: Path) -> None:
    q.record(model="sonnet", tokens_in=100, tokens_out=50, run_id="abc", phase="miner")
    text = q.QUOTA_LOG.read_text(encoding="utf-8")
    assert text.count("\n") == 1
    assert '"model": "sonnet"' in text
    assert '"tokens_in": 100' in text


def test_record_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        q.record(model="opus", tokens_in=-1, tokens_out=0, run_id="r", phase="forger")


def test_consumed_this_week_sums_in_plus_out() -> None:
    q.record(model="opus", tokens_in=1000, tokens_out=500, run_id="r1", phase="forger")
    q.record(model="opus", tokens_in=2000, tokens_out=200, run_id="r2", phase="judge")
    q.record(model="sonnet", tokens_in=99, tokens_out=99, run_id="r3", phase="critic")
    assert q.consumed_this_week("opus") == 1000 + 500 + 2000 + 200
    assert q.consumed_this_week("sonnet") == 99 + 99
    assert q.consumed_this_week("haiku") == 0


def test_consumed_this_week_filters_by_iso_week(monkeypatch: pytest.MonkeyPatch) -> None:
    q.record(model="opus", tokens_in=10, tokens_out=10, run_id="r", phase="forger")
    # Simulate "next week" by spoofing _current_week_iso
    monkeypatch.setattr(q, "_current_week_iso", lambda now=None: "2099-W01")
    assert q.consumed_this_week("opus") == 0


def test_remaining_fraction_floor_and_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPUS_WEEKLY_TOKEN_CAP", "100")
    q.record(model="opus", tokens_in=30, tokens_out=20, run_id="r", phase="forger")
    assert q.remaining_fraction("opus") == pytest.approx(0.5)
    q.record(model="opus", tokens_in=50, tokens_out=0, run_id="r", phase="forger")
    assert q.remaining_fraction("opus") == 0.0


def test_remaining_fraction_disabled_cap_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPUS_WEEKLY_TOKEN_CAP", "0")
    q.record(model="opus", tokens_in=999_999, tokens_out=0, run_id="r", phase="forger")
    assert q.remaining_fraction("opus") == 1.0


def test_gate_allows_when_above_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPUS_WEEKLY_TOKEN_CAP", "1000")
    q.record(model="opus", tokens_in=100, tokens_out=0, run_id="r", phase="forger")
    # 100 used + 100 expected = 200; 800/1000 = 0.8 > 0.05 → True
    assert q.gate(model="opus", expected_tokens=100, floor=0.05) is True


def test_gate_blocks_when_below_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPUS_WEEKLY_TOKEN_CAP", "1000")
    q.record(model="opus", tokens_in=900, tokens_out=0, run_id="r", phase="forger")
    # 900 + 80 = 980; 20/1000 = 0.02 < 0.05 → False
    assert q.gate(model="opus", expected_tokens=80, floor=0.05) is False


def test_gate_blocks_when_dispatch_overflows_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SONNET_WEEKLY_TOKEN_CAP", "100")
    q.record(model="sonnet", tokens_in=50, tokens_out=0, run_id="r", phase="critic")
    assert q.gate(model="sonnet", expected_tokens=60) is False


def test_gate_disabled_cap_always_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bug-pinning test: previously cap==0 silently failed-open (returned True)
    # with no env flag set, allowing unbounded token spend.  The fix requires
    # the operator to set ANOMALY_QUOTA_DISABLED=1 explicitly to get that
    # behaviour in dev/test environments.
    monkeypatch.setenv("HAIKU_WEEKLY_TOKEN_CAP", "0")
    monkeypatch.setenv("ANOMALY_QUOTA_DISABLED", "1")
    assert q.gate(model="haiku", expected_tokens=10**12) is True


def test_gate_cap_zero_hard_fails_without_disable_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cap==0 without ANOMALY_QUOTA_DISABLED=1 must return False (hard-fail)."""
    monkeypatch.setenv("OPUS_WEEKLY_TOKEN_CAP", "0")
    monkeypatch.setenv("ANOMALY_QUOTA_DISABLED", "")
    assert q.gate(model="opus", expected_tokens=1) is False


def test_gate_cap_zero_fails_open_with_explicit_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cap==0 WITH ANOMALY_QUOTA_DISABLED=1 must return True (dev escape hatch)."""
    monkeypatch.setenv("SONNET_WEEKLY_TOKEN_CAP", "0")
    monkeypatch.setenv("ANOMALY_QUOTA_DISABLED", "1")
    assert q.gate(model="sonnet", expected_tokens=10**9) is True


def test_gate_normal_cap_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero caps follow the standard floor logic regardless of the flag."""
    monkeypatch.setenv("OPUS_WEEKLY_TOKEN_CAP", "1000")
    # Flag set should not interfere with ordinary cap evaluation.
    monkeypatch.setenv("ANOMALY_QUOTA_DISABLED", "1")
    q.record(model="opus", tokens_in=100, tokens_out=0, run_id="r", phase="forger")
    # 100 used + 100 expected = 200; 800/1000 = 0.80 > 0.05 floor → True
    assert q.gate(model="opus", expected_tokens=100, floor=0.05) is True
    # Overflow: 100 used + 950 expected = 1050 >= 1000 → False
    assert q.gate(model="opus", expected_tokens=950, floor=0.05) is False


def test_gate_rejects_negative_tokens() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        q.gate(model="opus", expected_tokens=-1)


def test_print_status_renders_three_tiers() -> None:
    q.record(model="opus", tokens_in=10, tokens_out=10, run_id="r", phase="forger")
    out = q.print_status()
    assert "opus" in out
    assert "sonnet" in out
    assert "haiku" in out
    assert "ISO week" in out


def test_current_week_iso_format() -> None:
    label = q._current_week_iso(datetime(2026, 5, 9, tzinfo=UTC))
    # 2026-05-09 falls in ISO week 19
    assert label == "2026-W19"
    # Edge case: year boundary
    label2 = q._current_week_iso(datetime(2026, 1, 1, tzinfo=UTC))
    assert label2.startswith("2026-W") or label2.startswith("2025-W")


def test_corrupt_quota_log_does_not_raise() -> None:
    """A line that fails json.loads should be silently skipped."""
    q.QUOTA_LOG.parent.mkdir(parents=True, exist_ok=True)
    q.QUOTA_LOG.write_text("not json\n", encoding="utf-8")
    q.record(model="opus", tokens_in=10, tokens_out=0, run_id="r", phase="forger")
    assert q.consumed_this_week("opus") == 10  # corrupt line skipped, valid one counted
