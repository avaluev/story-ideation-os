"""Regression: the enumerator covers all 20 flagship cards, not just the 3 sampled.

Locks the honest denominator slate-wide so a parser regression (a section that
silently stops being scanned, a comp table that stops parsing) is caught. Skips
when the flagship slate is absent (it is an uncommitted output dir).
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from pipeline.veracity.assess import assess_card
from pipeline.veracity.enumerate import enumerate_claims

_FLAGSHIP = Path("outputs/portfolio/flagship")
# The honest slate-wide external-claim denominator measured at build time. A wide
# band catches a gross parser regression without being brittle to a re-render.
_MIN_SLATE_EXTERNAL = 150
_MAX_SLATE_EXTERNAL = 230
_MIN_CARDS = 20


def _cards() -> list[Path]:
    hits = sorted(Path(p) for p in glob.glob(str(_FLAGSHIP / "[0-9]*.md")))
    if len(hits) < _MIN_CARDS:
        pytest.skip(f"flagship slate not present ({len(hits)} cards)")
    return hits


def test_every_card_enumerates_core_structures() -> None:
    """Every card must yield its comps, TAM, and computed SAM/SOM — proof the
    Comparables / Economics / Audience sections are all being scanned on all 20."""
    for card in _cards():
        cs = enumerate_claims(card.read_text(encoding="utf-8"), concept_id=card.stem)
        types = {c.claim_type for c in cs}
        ext = [c for c in cs if not c.is_computed]
        assert "comp_roi" in types, f"{card.name}: Comparables table not parsed"
        assert "market_tam" in types, f"{card.name}: TAM (Economics) not parsed"
        assert "market_som" in types, f"{card.name}: SOM (Economics) not parsed"
        assert len(ext) >= 5, f"{card.name}: only {len(ext)} external claims (denominator too thin)"


def test_slate_external_denominator_in_band() -> None:
    """The slate-wide honest external-claim count stays in a sane band."""
    total = sum(
        sum(
            1
            for c in enumerate_claims(card.read_text(encoding="utf-8"), concept_id=card.stem)
            if not c.is_computed
        )
        for card in _cards()
    )
    assert _MIN_SLATE_EXTERNAL <= total <= _MAX_SLATE_EXTERNAL, (
        f"slate external-claim count {total} outside [{_MIN_SLATE_EXTERNAL}, "
        f"{_MAX_SLATE_EXTERNAL}] — enumerator recall regressed or cards changed shape"
    )


def test_deep_link_density_is_honest_not_tautological() -> None:
    """No card may report the old tautological ~100% deep-link density. With the
    complete denominator at least one card must sit clearly below 100%, proving
    the metric now counts unlinked claims."""
    below_100 = 0
    for card in _cards():
        _a, score = assess_card(
            card.read_text(encoding="utf-8"), offline=True, concept_id=card.stem
        )
        assert score.n_external >= 5
        if score.deep_link_pct < 100.0:
            below_100 += 1
    assert below_100 >= 1, "every card reported 100% deep-link — denominator still tautological"
