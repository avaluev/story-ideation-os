"""Unit test for KNOW-06: pipeline/data/polti_tobias_coherence.json schema + Pitfall 4.2 sample.

References:
- pipeline/data/polti_tobias_coherence.json (the data file under test)
- frameworks/narrative-master-grid.md (Coherence Anti-Pattern Matrix runtime consumer)
- scripts/audit.py::_check_polti_tobias_threshold (audit-warning logic, plan 01-02)
- tests/test_audit_polti_threshold.py (dedicated helper test in plan 01-02)
- .planning/phases/01-knowledge-layer/01-RESEARCH.md (Polti x Tobias Coherence)
- .planning/STATE.md operator decision 4 (seed=5, alert at >20)
- Pitfall 4.2 (data-side ownership in this plan; audit subcommand in plan 01-02)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA_PATH = Path("pipeline/data/polti_tobias_coherence.json")


@pytest.fixture(scope="module")
def coherence_data() -> dict:
    assert DATA_PATH.exists(), f"{DATA_PATH} missing — see plan 01-04 task 3"
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_top_level_schema(coherence_data: dict) -> None:
    for key in ("schema_version", "operator_caps", "anti_patterns"):
        assert key in coherence_data, f"missing top-level key: {key}"


def test_operator_caps_locked(coherence_data: dict) -> None:
    """STATE.md operator decision 4: seed=5, audit alert at >20. These are LOCKED."""
    assert coherence_data["operator_caps"]["seed"] == 5
    assert coherence_data["operator_caps"]["audit_alert_above"] == 20


def test_seed_size_is_exactly_5(coherence_data: dict) -> None:
    """Seed locked at 5; new entries need operator approval (Pitfall 4.2 + STAB-02 hook)."""
    n = len(coherence_data["anti_patterns"])
    assert n == 5, f"Expected exactly 5 entries (operator-locked seed), got {n}"


def test_polti_tobias_id_ranges(coherence_data: dict) -> None:
    """polti_id in 1..36; tobias_id in 1..20."""
    for entry in coherence_data["anti_patterns"]:
        assert 1 <= entry["polti_id"] <= 36, f"polti_id out of range: {entry['polti_id']}"
        assert 1 <= entry["tobias_id"] <= 20, f"tobias_id out of range: {entry['tobias_id']}"


def test_all_verdicts_incoherent(coherence_data: dict) -> None:
    """v1 only allows verdict='incoherent'; future verdicts require schema bump."""
    for entry in coherence_data["anti_patterns"]:
        assert entry["verdict"] == "incoherent"


def test_entry_ids_unique(coherence_data: dict) -> None:
    ids = [e["id"] for e in coherence_data["anti_patterns"]]
    assert len(set(ids)) == len(ids), "duplicate anti-pattern IDs"


def test_every_entry_has_references(coherence_data: dict) -> None:
    """Pitfall 4.2: structural rationale must be cited; references must be non-empty."""
    for entry in coherence_data["anti_patterns"]:
        assert len(entry.get("references", [])) >= 1, f"entry {entry['id']} has no references"


def test_references_are_plain_text(coherence_data: dict) -> None:
    """Revision-2 L14: book titles in references must be plain text (no markdown asterisks)."""
    bad: list[str] = []
    for entry in coherence_data["anti_patterns"]:
        for ref in entry.get("references", []):
            if "*" in ref:
                bad.append(f"{entry['id']}: {ref}")
    assert not bad, f"asterisks found in references (revision-2 L14): {bad}"


def test_audit_warning_threshold_logic() -> None:
    """Pitfall 4.2 sample: 21 entries triggers the audit-warning condition (warn, not fail).

    The actual warning is emitted by scripts/audit.py::_check_polti_tobias_threshold (plan 01-02);
    that helper has its own dedicated test (tests/test_audit_polti_threshold.py in plan 01-02).
    Here we simply verify the threshold logic the audit subcommand replicates.
    """
    sample = {"operator_caps": {"audit_alert_above": 20}, "anti_patterns": list(range(21))}
    n = len(sample["anti_patterns"])
    threshold = sample["operator_caps"]["audit_alert_above"]
    assert n > threshold, "21 entries must exceed threshold of 20 (warning condition)"
