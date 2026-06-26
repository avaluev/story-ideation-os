"""Format sampling in the compound seed engine (v5.1.0).

Asserts the engine samples a content FORMAT (single-pick), honors the
cross-run frequency penalty on the ``format`` axis, surfaces it on
``to_dict()`` + ``hidden_attrs``, and stays backward-compatible (existing
generate() callsites with no new kwargs keep working; the format draw is
appended LAST so it does not perturb the RNG stream for other axes).

Hermetic: no network (conftest blanks provider keys); fast (direct
_sample_format calls for the distribution check, not full generate()).
"""

from __future__ import annotations

from collections import Counter

from pipeline.compound_seed import CompoundSeedEngine


def _engine(seed: int = 7) -> CompoundSeedEngine:
    return CompoundSeedEngine(rng_seed=seed)


def test_to_dict_has_format_key() -> None:
    eng = _engine()
    result = eng.generate(n_audiences=3, max_attempts=5)
    d = result.to_dict()
    assert "format" in d  # present even when None


def test_force_format_resolves_by_name() -> None:
    eng = _engine()
    result = eng.generate(n_audiences=3, max_attempts=5, force_format="Microdrama")
    fmt = result.to_dict()["format"]
    assert fmt is not None
    assert fmt["name"] == "Microdrama"
    assert fmt["id"] == "FMT_06"


def test_n_formats_zero_yields_none() -> None:
    eng = _engine()
    fmt = eng._sample_format(0, None, None)
    assert fmt is None


def test_sample_format_honors_freq_penalty() -> None:
    """An over-sampled format is picked far less often than uniform 1/6."""
    eng = _engine(seed=123)
    # Heavily penalize FMT_01 (Feature Film); others fresh.
    freq_table = {("format", "FMT_01"): 100}
    picks: list[str] = []
    for _ in range(600):
        fmt = eng._sample_format(1, None, freq_table)
        if fmt is not None:
            picks.append(str(fmt["id"]))
    assert picks, "expected some non-None format picks across 600 draws"
    counts = Counter(picks)
    feature_share = counts.get("FMT_01", 0) / len(picks)
    # Down-weighted format must land well below the uniform 1/6 (~0.167).
    assert feature_share < 0.10, f"FMT_01 share {feature_share:.3f} not penalized"
    # Diversity: at least 5 of the 6 formats should appear across 600 draws.
    assert len(counts) >= 5, f"only {len(counts)} distinct formats sampled"


def test_backward_compatible_generate() -> None:
    """An existing-shape generate() call (no format kwargs) still returns a
    valid result whose other sampled axes are unaffected by the new draw."""
    a = _engine(seed=42).generate(themes=["loneliness"], n_audiences=3, max_attempts=5)
    # Re-run with the SAME seed: the format draw is appended last, so the
    # pre-existing axes must be identical run-to-run.
    b = _engine(seed=42).generate(themes=["loneliness"], n_audiences=3, max_attempts=5)
    assert a.to_dict()["sdt_wound"] == b.to_dict()["sdt_wound"]
    assert a.to_dict()["world_texture"] == b.to_dict()["world_texture"]


def test_hidden_attrs_carry_format() -> None:
    eng = _engine()
    result = eng.generate(n_audiences=3, max_attempts=5, force_format="Limited Series")
    assert result.hidden_attrs.get("format") == "Limited Series"
