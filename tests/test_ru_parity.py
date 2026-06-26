"""tests/test_ru_parity.py — deterministic EN/RU parity multisets (Run A).

Pins the three hard parity extractors (url / dollar / heading) and
``check_parity``'s pass/fail behaviour, plus the advisory readability surface.
"""

from __future__ import annotations

from collections import Counter

from pipeline.veracity.render_inline import _money_multiset
from scripts.ru_parity import (
    ParityResult,
    check_parity,
    heading_vector,
    money_multiset,
    url_multiset,
)

_EN = (
    "# Title\n\n"
    "## Revenue Thesis\n"
    "Worldwide gross was $1.4B per [Box Office Mojo](https://www.boxofficemojo.com/title/tt123/).\n"
    "Budget $145M; opening $162M ([source](https://variety.com/2023/film/box-office-99/)).\n\n"
    "### Comparables\n"
    "See [The Numbers](https://www.the-numbers.com/movie/Barbie).\n"
)


# ── extractors ────────────────────────────────────────────────────────────────


def test_url_multiset_counts_each_link() -> None:
    assert url_multiset(_EN) == Counter(
        {
            "https://www.boxofficemojo.com/title/tt123/": 1,
            "https://variety.com/2023/film/box-office-99/": 1,
            "https://www.the-numbers.com/movie/Barbie": 1,
        }
    )


def test_url_multiset_counts_duplicates() -> None:
    text = "[a](https://x.com/p) and again [b](https://x.com/p)"
    assert url_multiset(text) == Counter({"https://x.com/p": 2})


def test_url_multiset_handles_wikipedia_parens() -> None:
    """Wikipedia film URLs contain balanced parens; capture them intact."""
    text = "[Coco](https://en.wikipedia.org/wiki/Coco_(2017_film)) was a hit."
    assert url_multiset(text) == Counter({"https://en.wikipedia.org/wiki/Coco_(2017_film)": 1})


def test_money_multiset_matches_render_inline() -> None:
    assert money_multiset(_EN) == Counter(_money_multiset(_EN))
    assert money_multiset(_EN).total() == 3  # $1.4B, $145M, $162M


def test_heading_vector_per_level() -> None:
    assert heading_vector(_EN) == Counter({1: 1, 2: 1, 3: 1})


# ── check_parity ──────────────────────────────────────────────────────────────


def test_check_parity_identical_passes() -> None:
    result = check_parity(_EN, _EN)
    assert isinstance(result, ParityResult)
    assert result.passed is True
    assert result.mismatches == []


def test_check_parity_dropped_url_fails() -> None:
    ru = _EN.replace("[The Numbers](https://www.the-numbers.com/movie/Barbie)", "The Numbers")
    result = check_parity(_EN, ru)
    assert result.passed is False
    assert result.url_ok is False
    assert any("the-numbers.com" in m for m in result.mismatches)


def test_check_parity_changed_dollar_fails() -> None:
    ru = _EN.replace("$1.4B", "$1.5B")
    result = check_parity(_EN, ru)
    assert result.passed is False
    assert result.money_ok is False


def test_check_parity_demoted_heading_fails() -> None:
    ru = _EN.replace("## Revenue Thesis", "### Revenue Thesis")
    result = check_parity(_EN, ru)
    assert result.passed is False
    assert result.heading_ok is False


def test_readability_warning_surfaced_not_gated() -> None:
    """An idiom is surfaced as a readability warning but does NOT fail parity."""
    en = "## H\nThe plan is a flagship release.\n"
    result = check_parity(en, en)  # parity identical -> passes
    assert result.passed is True
    assert any("flagship" in w for w in result.readability_warnings)


def test_fk_grade_is_advisory_only() -> None:
    result = check_parity(_EN, _EN)
    assert isinstance(result.fk_grade_advisory, float)
    # The FK warning is never counted as a readability warning (English counter).
    assert all("Flesch-Kincaid" not in w for w in result.readability_warnings)
