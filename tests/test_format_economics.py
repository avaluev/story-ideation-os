"""Per-format economics (v5.1.0) — pipeline.crystallize.format_economics.

Every per-format SOM/TAM/SAM number is a python-executed function of NAMED,
SOURCED constants (ADR-0011). This test locks the six arithmetic identities
the constants were chosen to produce, the feature-default fallback, the
ADR-0002 no-LLM-import boundary, and the deep-link URL hygiene policy
(every constant source_url is a deep path OR exactly "" — never a bare
domain, never a search-engine URL, never fabricated).

Hermetic: pure arithmetic, no network, no corpus.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pipeline.crystallize import format_economics as fe

_BANNED_SEARCH_HOSTS = (
    "google.",
    "bing.",
    "duckduckgo.",
    "search.brave.",
    "yandex.",
    "yahoo.",
)


def test_six_profiles_present() -> None:
    expected = {
        "feature",
        "limited_series",
        "returning_series",
        "animation_feature",
        "animation_series",
        "microdrama",
    }
    assert set(fe.FORMAT_PROFILES) == expected
    assert set(fe.VALID_FORMATS) == expected


def test_all_numeric_fields_finite() -> None:
    for prof in fe.FORMAT_PROFILES.values():
        for name, val in vars(prof).items():
            if isinstance(val, float):
                assert math.isfinite(val), f"{prof.format_id}.{name} not finite"


def test_arithmetic_identities() -> None:
    """The six identities the sourced constants were calibrated to produce."""
    limited = fe.FORMAT_PROFILES["limited_series"]
    returning = fe.FORMAT_PROFILES["returning_series"]
    anim_series = fe.FORMAT_PROFILES["animation_series"]
    microdrama = fe.FORMAT_PROFILES["microdrama"]
    feature = fe.FORMAT_PROFILES["feature"]
    anim_feature = fe.FORMAT_PROFILES["animation_feature"]

    # Limited series: 8 eps x $10M x 1.30 markup = $104.0M Year-1 license.
    assert fe.license_fee_usd(limited) == pytest.approx(104_000_000.0)
    # Returning series lifetime: license(9x10Mx1.30) x 2.5 seasons x 0.6 haircut.
    assert fe.lifetime_license_usd(returning) == pytest.approx(175_500_000.0)
    # Animation series license: $6M recoup/ep x 9 eps (markup 0).
    assert fe.license_fee_usd(anim_series) == pytest.approx(54_000_000.0)
    # Microdrama Year-1 SOM: 1% share of the $1.4B ex-China serviceable market.
    assert fe.microdrama_som_usd(microdrama) == pytest.approx(14_000_000.0)
    # Animation feature documented anchor: $90M budget x 4.3x base multiple.
    assert fe.anim_feature_anchor_usd(anim_feature) == pytest.approx(387_000_000.0)
    # Feature lifetime from a $150M Year-1 SOM x 2.95 multi-window multiple.
    assert fe.lifetime_from_y1(150_000_000.0, feature) == pytest.approx(442_500_000.0)


def test_get_profile_unknown_falls_back_to_feature() -> None:
    assert fe.get_profile("not-a-format").format_id == "feature"
    assert fe.get_profile(None).format_id == "feature"
    # Case / spacing / display-name tolerant.
    assert fe.get_profile("Limited Series").format_id == "limited_series"
    assert fe.get_profile("MICRODRAMA").format_id == "microdrama"


def test_som_lt_sam_lt_tam_for_every_format() -> None:
    """The credibility invariant holds at the profile level for every format."""
    for fmt, prof in fe.FORMAT_PROFILES.items():
        som = fe.reference_som_usd(prof)
        sam = fe.serviceable_sam_usd(prof)
        tam = prof.tam_segment_usd
        assert 0 < som < sam < tam, f"{fmt}: SOM {som} < SAM {sam} < TAM {tam} violated"


def test_som_log_bounds_per_model() -> None:
    feat_lo, feat_hi = fe.som_log_bounds("feature")
    _lic_lo, lic_hi = fe.som_log_bounds("limited_series")
    _micro_lo, micro_hi = fe.som_log_bounds("microdrama")
    # Theatrical scale unchanged; license + microdrama recalibrated downward so
    # their structurally-smaller Year-1 SOMs discriminate instead of flooring.
    assert (feat_lo, feat_hi) == (50_000_000.0, 1_500_000_000.0)
    assert lic_hi < feat_hi
    assert micro_hi < lic_hi


def test_no_llm_imports_adr_0002() -> None:
    src = Path(fe.__file__).read_text(encoding="utf-8")
    for banned in ("import anthropic", "import httpx", "openrouter_client", "import openai"):
        assert banned not in src, f"ADR-0002 violation: {banned!r} in format_economics.py"


def test_module_registered_in_anomaly_001_lint() -> None:
    """The no-LLM-import boundary must be CI-enforced, not just test-local."""
    lint_src = Path("scripts/lint_imports.py").read_text(encoding="utf-8")
    assert "pipeline/crystallize/format_economics.py" in lint_src


def test_source_url_hygiene_deep_link_policy() -> None:
    """Every constant source_url is a deep path OR exactly '' (data_gap) —
    never a bare domain, never a search-engine URL, never fabricated."""
    for name, url in fe.CONSTANT_SOURCES.items():
        if url == "":
            continue  # documented data_gap — compliant
        assert url.startswith("https://"), f"{name}: {url!r} not https"
        host_and_path = url.removeprefix("https://")
        host = host_and_path.split("/", 1)[0]
        path = host_and_path[len(host) :]
        assert path not in ("", "/"), f"{name}: bare domain {url!r} (needs a deep path)"
        assert not any(b in host for b in _BANNED_SEARCH_HOSTS), f"{name}: search URL {url!r}"
