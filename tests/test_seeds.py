"""Structural validation tests for seed YAML matrices.

Covers OPS-05 (seeds/domains.yaml — 12 domain Miner seed matrix) and
OPS-06 (seeds/audience-segments.yaml — 12 macro-segment seed matrix).

All tests use yaml.safe_load and check schema compliance only — no network
calls, no pipeline imports.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
DOMAINS_PATH = REPO_ROOT / "seeds" / "domains.yaml"
SEGMENTS_PATH = REPO_ROOT / "seeds" / "audience-segments.yaml"

VALID_SDT_ROOTS = {"autonomy", "competence", "relatedness"}


@pytest.fixture(scope="module")
def domains_data():
    """Load seeds/domains.yaml once for the entire module."""
    return yaml.safe_load(DOMAINS_PATH.read_text())


@pytest.fixture(scope="module")
def segments_data():
    """Load seeds/audience-segments.yaml once for the entire module."""
    return yaml.safe_load(SEGMENTS_PATH.read_text())


# ─── domains.yaml tests ──────────────────────────────────────────────────────


def test_domains_yaml_exists():
    """seeds/domains.yaml must exist on disk."""
    assert DOMAINS_PATH.exists(), f"File not found: {DOMAINS_PATH}"


def test_domains_has_12_entries(domains_data):
    """domains list must have exactly 12 entries (OPS-05)."""
    assert len(domains_data["domains"]) == 12


def test_domains_cooldown_constant(domains_data):
    """DOMAIN_COOLDOWN_DAYS must equal 7 (named constant, not magic number)."""
    assert domains_data["DOMAIN_COOLDOWN_DAYS"] == 7


def test_domains_required_fields(domains_data):
    """Every domain entry must have id, name, description, query_hints (list), last_used."""
    for domain in domains_data["domains"]:
        assert "id" in domain, f"Missing 'id' in domain: {domain}"
        assert "name" in domain, f"Missing 'name' in domain: {domain}"
        assert "description" in domain, f"Missing 'description' in domain: {domain}"
        assert "query_hints" in domain, f"Missing 'query_hints' in domain: {domain}"
        assert isinstance(domain["query_hints"], list), (
            f"'query_hints' must be a list in domain {domain.get('id')}"
        )
        assert "last_used" in domain, f"Missing 'last_used' in domain: {domain}"


def test_domains_unique_ids(domains_data):
    """All domain IDs must be unique and span D01..D12."""
    ids = [d["id"] for d in domains_data["domains"]]
    assert len(ids) == len(set(ids)), f"Duplicate domain IDs found: {ids}"
    expected = {f"D{i:02d}" for i in range(1, 13)}
    assert set(ids) == expected, f"Domain IDs do not match D01..D12: {set(ids)}"


# ─── audience-segments.yaml tests ────────────────────────────────────────────


def test_segments_yaml_exists():
    """seeds/audience-segments.yaml must exist on disk."""
    assert SEGMENTS_PATH.exists(), f"File not found: {SEGMENTS_PATH}"


def test_segments_has_12_entries(segments_data):
    """segments list must have exactly 12 entries (OPS-06)."""
    assert len(segments_data["segments"]) == 12


def test_segments_required_fields(segments_data):
    """Every segment must have id, name, sdt_root, current_deprivation_claim,
    evidence_sources_to_check (list), addressable_audience_m (int)."""
    for seg in segments_data["segments"]:
        assert "id" in seg, f"Missing 'id' in segment: {seg}"
        assert "name" in seg, f"Missing 'name' in segment: {seg}"
        assert "sdt_root" in seg, f"Missing 'sdt_root' in segment: {seg}"
        assert "current_deprivation_claim" in seg, (
            f"Missing 'current_deprivation_claim' in segment: {seg}"
        )
        assert "evidence_sources_to_check" in seg, (
            f"Missing 'evidence_sources_to_check' in segment: {seg}"
        )
        assert isinstance(seg["evidence_sources_to_check"], list), (
            f"'evidence_sources_to_check' must be a list in segment {seg.get('id')}"
        )
        assert "addressable_audience_m" in seg, (
            f"Missing 'addressable_audience_m' in segment: {seg}"
        )
        assert isinstance(seg["addressable_audience_m"], int), (
            f"'addressable_audience_m' must be int in segment {seg.get('id')}"
        )


def test_segments_audience_floor(segments_data):
    """Every segment must have addressable_audience_m >= 50 (OPS-06)."""
    for seg in segments_data["segments"]:
        assert seg["addressable_audience_m"] >= 50, (
            f"Segment {seg.get('id')} has addressable_audience_m="
            f"{seg.get('addressable_audience_m')} < 50"
        )


def test_segments_sdt_root_valid(segments_data):
    """All sdt_root values must be in {autonomy, competence, relatedness}."""
    for seg in segments_data["segments"]:
        assert seg["sdt_root"] in VALID_SDT_ROOTS, (
            f"Segment {seg.get('id')} has invalid sdt_root='{seg.get('sdt_root')}'; "
            f"must be one of {VALID_SDT_ROOTS}"
        )


def test_segments_unique_ids(segments_data):
    """All segment IDs must be unique and span S01..S12."""
    ids = [s["id"] for s in segments_data["segments"]]
    assert len(ids) == len(set(ids)), f"Duplicate segment IDs found: {ids}"
    expected = {f"S{i:02d}" for i in range(1, 13)}
    assert set(ids) == expected, f"Segment IDs do not match S01..S12: {set(ids)}"
