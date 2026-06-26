"""Unit test for scripts.audit._check_polti_tobias_threshold (Pitfall 4.2 warning logic).

Exercises the helper with a synthetic 21-entry fixture so the warning is testable
in Wave 1 without depending on plan 01-04 having shipped pipeline/data/polti_tobias_coherence.json.

References:
- scripts/audit.py::_check_polti_tobias_threshold (under test)
- .planning/phases/01-knowledge-layer revision-2 BLOCKER H9
- pipeline/data/polti_tobias_coherence.json (lands in plan 01-04 task 3)
"""

from __future__ import annotations

from scripts.audit import _check_polti_tobias_threshold


def test_warning_fires_when_entries_exceed_soft_cap() -> None:
    """21 entries with audit_alert_above=20 must return a WARNING string."""
    fixture = {
        "operator_caps": {"audit_alert_above": 20},
        "anti_patterns": [{"id": f"placeholder-{i}"} for i in range(21)],
    }
    msg = _check_polti_tobias_threshold(data=fixture)
    assert msg is not None, "Expected WARNING string for 21 entries; got None"
    assert "exceeds soft cap" in msg, f"WARNING message missing required substring: {msg!r}"


def test_no_warning_when_entries_at_or_below_seed() -> None:
    """5 entries (operator-locked seed) must return None -- no warning."""
    fixture = {
        "operator_caps": {"audit_alert_above": 20},
        "anti_patterns": [{"id": f"placeholder-{i}"} for i in range(5)],
    }
    msg = _check_polti_tobias_threshold(data=fixture)
    assert msg is None, f"Expected None for 5 entries; got {msg!r}"


def test_no_warning_when_entries_exactly_at_threshold() -> None:
    """20 entries (exactly == threshold) must NOT trigger; threshold is strict >."""
    fixture = {
        "operator_caps": {"audit_alert_above": 20},
        "anti_patterns": [{"id": f"placeholder-{i}"} for i in range(20)],
    }
    msg = _check_polti_tobias_threshold(data=fixture)
    assert msg is None, f"Expected None for 20 entries (== threshold); got {msg!r}"
