"""Tests for pipeline.research.value_on_page — anti-hallucination core.

Covers:
- number_variants: TRUE positives (dollar + B/M/K, percent)
- value_on_page: TRUE positives ($1.2B matches '1,200,000,000' and '1.2 billion';
  $758.5M matches '758,500,000'; $758.5M does NOT match '758,539,785' — exact
  integer variants only, not real-page near-miss)
- NEAR-MISS negatives: $1.2B must NOT match '$2.1B', '$1.2M', '12 billion'
- Empty value -> no match
- Quote always contains the matched variant
- source_tier: spot checks for each tier
- build_provenance: populates Provenance correctly from a ValueMatch
"""

from __future__ import annotations

import pytest

from pipeline.research.value_on_page import (
    _NO_MATCH,
    _digits,
    _digits_only,
    _fragment_on_page,
    build_provenance,
    is_credible,
    is_deep_link,
    number_variants,
    source_tier,
    value_on_page,
)

# ── number_variants ───────────────────────────────────────────────────────────


class TestNumberVariants:
    def test_billion_dollar(self) -> None:
        v = number_variants("$1.2B")
        assert "$1.2B" in v
        assert "1.2 billion" in v
        assert "1,200,000,000" in v
        assert "1200000000" in v
        assert "$1,200,000,000" in v

    def test_million_dollar(self) -> None:
        v = number_variants("$758.5M")
        assert "$758.5M" in v
        assert "758.5 million" in v
        assert "758,500,000" in v
        assert "758500000" in v
        assert "$758,500,000" in v

    def test_thousand_dollar(self) -> None:
        v = number_variants("$50K")
        assert "$50K" in v
        assert "50 thousand" in v
        assert "50,000" in v
        assert "50000" in v
        assert "$50,000" in v

    def test_bare_billion_no_dollar(self) -> None:
        v = number_variants("1.2B")
        assert "1.2B" in v
        assert "1.2 billion" in v
        assert "1,200,000,000" in v
        # No dollar prefix variant when no $ in input
        assert "$1,200,000,000" not in v

    def test_percent(self) -> None:
        v = number_variants("40%")
        assert "40%" in v
        assert "40 percent" in v
        # Should not produce billion/million variants
        assert any("billion" in x for x in v) is False

    def test_percent_decimal(self) -> None:
        v = number_variants("12.5%")
        assert "12.5%" in v
        assert "12.5 percent" in v

    def test_empty_returns_empty(self) -> None:
        assert number_variants("") == []
        assert number_variants("   ") == []

    def test_no_duplicates(self) -> None:
        v = number_variants("$1.0B")
        assert len(v) == len(set(v))

    def test_first_element_is_raw(self) -> None:
        raw = "$2.5M"
        v = number_variants(raw)
        assert v[0] == raw

    def test_unrecognised_suffix_returns_original_only(self) -> None:
        v = number_variants("$100T")  # T not in scale map
        assert v == ["$100T"]


# ── value_on_page — TRUE positives ────────────────────────────────────────────


class TestValueOnPagePositives:
    def test_billion_comma_form(self) -> None:
        page = "The film earned 1,200,000,000 dollars worldwide in its opening year."
        m = value_on_page("$1.2B", page)
        assert m.matched is True
        assert "1,200,000,000" in m.quote
        assert m.matched_variant == "1,200,000,000"
        assert m.char_offset >= 0

    def test_billion_word_form(self) -> None:
        page = "Analysts confirmed the 1.2 billion box office milestone was reached."
        m = value_on_page("$1.2B", page)
        assert m.matched is True
        assert "1.2 billion" in m.quote
        assert m.matched_variant == "1.2 billion"

    def test_million_comma_form(self) -> None:
        # $758.5M -> integer variant 758,500,000
        page = "Global revenue reached 758,500,000 according to Box Office Mojo data."
        m = value_on_page("$758.5M", page)
        assert m.matched is True
        assert "758,500,000" in m.quote

    def test_million_word_form(self) -> None:
        page = "The picture grossed 758.5 million in its theatrical window."
        m = value_on_page("$758.5M", page)
        assert m.matched is True
        assert "758.5 million" in m.quote

    def test_percent_match(self) -> None:
        page = "40% of streaming subscribers actively watched the genre last quarter."
        m = value_on_page("40%", page)
        assert m.matched is True
        assert "40%" in m.quote or "40 percent" in m.quote

    def test_original_raw_form_matches(self) -> None:
        page = "The project had a $1.2B valuation confirmed by Bloomberg."
        m = value_on_page("$1.2B", page)
        assert m.matched is True
        assert "$1.2B" in m.quote or "1.2 billion" in m.quote or "1,200,000,000" in m.quote

    def test_quote_length_capped(self) -> None:
        # Sentence with 30+ words containing the value
        long_sent = (
            "According to the latest industry report published in December 2025, "
            "the film earned 1,200,000,000 dollars in combined domestic and "
            "international theatrical and streaming revenue over its first twelve months."
        )
        m = value_on_page("$1.2B", long_sent, max_quote_words=25)
        assert m.matched is True
        words = m.quote.split()
        assert len(words) <= 25

    def test_quote_always_contains_variant(self) -> None:
        page = "Revenue of 1.2 billion was reported in the annual earnings statement."
        m = value_on_page("$1.2B", page)
        assert m.matched is True
        # The quote must contain the matched variant (case-insensitive)
        assert m.matched_variant.lower() in m.quote.lower()


# ── value_on_page — NEAR-MISS negatives ──────────────────────────────────────


class TestValueOnPageNegatives:
    def test_different_magnitude_not_matched(self) -> None:
        # $1.2B must NOT match a page that only mentions $2.1B
        page = "The sequel grossed $2.1B, far exceeding analyst predictions."
        m = value_on_page("$1.2B", page)
        assert m.matched is False

    def test_different_scale_not_matched(self) -> None:
        # $1.2B must NOT match a page that only mentions $1.2M
        page = "The indie film earned $1.2M in its limited theatrical run."
        m = value_on_page("$1.2B", page)
        assert m.matched is False

    def test_wrong_magnitude_word_form(self) -> None:
        # $1.2B must NOT match '12 billion' (different number)
        page = "The studio's total library is worth 12 billion dollars."
        m = value_on_page("$1.2B", page)
        assert m.matched is False

    def test_empty_value_no_match(self) -> None:
        page = "Some page with numbers like 1,200,000,000 dollars."
        m = value_on_page("", page)
        assert m.matched is False

    def test_empty_page_no_match(self) -> None:
        m = value_on_page("$1.2B", "")
        assert m.matched is False

    def test_value_absent_from_page(self) -> None:
        page = "This page contains no financial figures at all."
        m = value_on_page("$1.2B", page)
        assert m.matched is False

    def test_partial_digit_not_matched(self) -> None:
        # '1200000000' must NOT match inside '12000000000' (10x larger)
        page = "The market cap is 12000000000 dollars, not a billion."
        m = value_on_page("$1.2B", page)
        # 1,200,000,000 is a substring of 12,000,000,000 BUT the boundary check
        # should reject it because it is preceded/followed by a digit.
        assert m.matched is False


# ── source_tier ───────────────────────────────────────────────────────────────


class TestSourceTier:
    def test_gov_url_is_tier1(self) -> None:
        assert source_tier("https://www.census.gov/data/tables/2025/demo/popest.html") == 1

    def test_fred_is_tier1(self) -> None:
        assert source_tier("https://fred.stlouisfed.org/series/GDPC1") == 1

    def test_who_is_tier1(self) -> None:
        assert source_tier("https://www.who.int/news/item/2025-report") == 1

    def test_boxofficemojo_is_tier2(self) -> None:
        assert source_tier("https://www.boxofficemojo.com/title/tt1234567/") == 2

    def test_variety_is_tier2(self) -> None:
        assert source_tier("https://variety.com/2025/film/news/article-slug.html") == 2

    def test_statista_is_tier3(self) -> None:
        assert source_tier("https://www.statista.com/statistics/123456/") == 3

    def test_unknown_host_is_tier5(self) -> None:
        assert source_tier("https://random-blog.example.org/post/123") == 5

    def test_empty_url_is_tier5(self) -> None:
        assert source_tier("") == 5

    def test_bare_domain_is_tier5(self) -> None:
        # bare domain without path — still tier-classified by host
        assert source_tier("https://www.google.com/") == 5


# ── build_provenance ──────────────────────────────────────────────────────────


class TestBuildProvenance:
    def test_matched_provenance(self) -> None:
        page = "The film grossed 1.2 billion dollars globally."
        m = value_on_page("$1.2B", page)
        assert m.matched is True
        prov = build_provenance(
            "$1.2B",
            page,
            m,
            url="https://variety.com/2025/film/article.html",
            http_status=200,
            fetched_at="2026-06-01T10:00:00Z",
            content_sha256="abc123",
        )
        assert prov.supports_claim is True
        assert prov.quote == m.quote
        assert prov.url == "https://variety.com/2025/film/article.html"
        assert prov.http_status == 200
        assert prov.fetched_at == "2026-06-01T10:00:00Z"
        assert prov.content_sha256 == "abc123"

    def test_unmatched_provenance(self) -> None:

        prov = build_provenance("$1.2B", "no numbers here", _NO_MATCH)
        assert prov.supports_claim is False
        assert prov.quote == ""

    def test_provenance_is_frozen(self) -> None:

        prov = build_provenance("$1.2B", "", _NO_MATCH)
        with pytest.raises((AttributeError, TypeError)):
            prov.supports_claim = True  # type: ignore[misc]


# ── Promoted helpers (smoke checks) ──────────────────────────────────────────


class TestPromotedHelpers:
    def test_digits(self) -> None:
        assert _digits("$505.0M") == "505"
        assert _digits("40%") == "40"
        assert _digits("") == ""

    def test_digits_only(self) -> None:
        assert _digits_only("$1,200,000,000") == "1200000000"
        assert _digits_only("abc") == ""

    def test_fragment_on_page_exact(self) -> None:
        assert _fragment_on_page("the quick brown fox", "the quick brown fox jumped") is True

    def test_fragment_on_page_five_word_window(self) -> None:
        quote = "earned one point two billion dollars"
        page = "The film earned one point two billion dollars in 2025."
        assert _fragment_on_page(quote, page) is True

    def test_fragment_on_page_no_match(self) -> None:
        assert _fragment_on_page("totally different text here now", "nothing matches") is False

    def test_is_deep_link_true(self) -> None:
        assert is_deep_link("https://variety.com/2025/film/article.html") is True

    def test_is_deep_link_bare_domain(self) -> None:
        assert is_deep_link("https://variety.com") is False
        assert is_deep_link("https://variety.com/") is False

    def test_is_deep_link_search_engine(self) -> None:
        assert is_deep_link("https://www.google.com/search?q=box+office") is False

    def test_is_credible_box_office(self) -> None:
        assert is_credible("https://www.boxofficemojo.com/title/tt123/", "comp_roi") is True

    def test_is_credible_blog_rejected(self) -> None:
        assert is_credible("https://myblog.wordpress.com/post/123", "comp_roi") is False
