"""Tests for pipeline.seed_engine."""

from __future__ import annotations

from pipeline.seed_engine import (
    SeedPackage,
    axis_sizes,
    is_coherent,
    sample,
)


def test_deterministic() -> None:
    """Same seed_int -> equal SeedPackage."""
    pkg_a = sample(42)
    pkg_b = sample(42)
    assert pkg_a == pkg_b


def test_different_seeds_differ() -> None:
    """Distinct seeds usually produce distinct packages on big axes."""
    pkg_a = sample(1)
    pkg_b = sample(2)
    # 25 axes; collision on a few small ones (Truby=4) is allowed,
    # but the full SeedPackage should not be byte-identical.
    assert pkg_a != pkg_b


def test_returns_seed_package() -> None:
    pkg = sample(7)
    assert isinstance(pkg, SeedPackage)
    assert pkg.seed_int == 7


def test_to_dict_round_trip() -> None:
    pkg = sample(99)
    d = pkg.to_dict()
    assert d["seed_int"] == 99
    assert "tension" in d
    assert "mutation_operator" in d
    # Each axis serialized as a dict carrying id + label.
    assert isinstance(d["tension"], dict)
    assert "id" in d["tension"]
    assert "label" in d["tension"]


def test_axis_sizes_loaded() -> None:
    sizes = axis_sizes()
    # Sanity floors — all axes should have at least their canonical
    # minimum row count.
    assert sizes["polti"] == 36
    assert sizes["tobias"] == 20
    assert sizes["booker"] == 7
    assert sizes["stc"] == 10
    assert sizes["truby"] == 4
    assert sizes["archetypes"] == 12
    assert sizes["arc_shapes"] == 6
    assert sizes["tensions"] >= 100
    assert sizes["spaces"] >= 100
    assert sizes["geography"] >= 100
    assert sizes["mutation_operators"] >= 10


def test_distinctness_at_1000() -> None:
    """1000 seeds yield >= 950 distinct (tension, space, polti, archetype, geo) tuples.

    The tail uniqueness comes from the 25-axis combinatorics; collisions on
    this 5-tuple are rare because tensions and spaces each have 100 entries.
    """
    seen: set[tuple[int, int, int, int, int]] = set()
    for s in range(1, 1001):
        p = sample(s)
        seen.add((p.tension.id, p.space.id, p.polti.id, p.archetype.id, p.geography.id))
    assert len(seen) >= 950, f"Only {len(seen)} distinct 5-tuples"


def test_active_mutation_operators_only() -> None:
    """The sampler should pull from active_day1 operators when any are flagged."""
    drawn: set[str] = set()
    for s in range(1, 1001):
        drawn.add(sample(s).mutation_operator.name)
    # 10 of the 30 are flagged active_day1; only those should appear.
    assert len(drawn) <= 10, f"Drew {len(drawn)} distinct operators (expected <=10 active)"
    assert len(drawn) >= 5, f"Sampling looks degenerate: {drawn}"


def test_irreversibility_pattern_axis_loaded() -> None:
    """The 26th axis (irreversibility patterns) loads with all 12 canonical IPs."""
    sizes = axis_sizes()
    assert sizes["irreversibility_patterns"] == 12


def test_seed_package_carries_irreversibility_pattern() -> None:
    """Every SeedPackage now exposes an irreversibility_pattern row."""
    pkg = sample(42)
    assert pkg.irreversibility_pattern is not None
    assert pkg.irreversibility_pattern.label
    assert pkg.irreversibility_pattern.extra.get("act_iii_phrasing")
    assert pkg.irreversibility_pattern.extra.get("plain_language")


def test_is_coherent_passes_for_clean_seed() -> None:
    """A coherent SeedPackage returns ``(True, '')``."""
    # Find one coherent seed (most are coherent).
    for s in range(1, 200):
        ok, reason = is_coherent(sample(s))
        if ok:
            assert reason == ""
            return
    msg = "no coherent seed found in [1, 200) — guard is over-strict"
    raise AssertionError(msg)


def test_is_coherent_blocks_at_least_some_seeds() -> None:
    """Across 1000 seeds, the coherence guard blocks at least one combination.

    The guard's denylist covers pre-modern-school + modern-tech, modern-period +
    pre-modern-tech, and atheist + religious-school. Hits should be rare but
    non-zero across a 1000-seed sweep.
    """
    blocked = 0
    for s in range(1, 1001):
        ok, _ = is_coherent(sample(s))
        if not ok:
            blocked += 1
    # At least one block expected; runaway blocking would suggest the guard is wrong.
    assert blocked >= 1, "is_coherent never fires — denylist may be unreachable"
    assert blocked < 200, f"is_coherent fires on {blocked}/1000 — guard is too aggressive"
