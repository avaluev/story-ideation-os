"""tests/test_parse_som_widen.py — NB-PARSE-SOM-WIDEN contract (Cycle 1 Session 6).

The eval-gate's :func:`pipeline.template_filter.parse_som` previously required
the literal canonical shape:

    **SOM (Year 1):** $NNN[M|B]

Real-world drafter output writes investor-readable variants the strict
regex rejected — caught live on the NB.10 first instrumented run when the
L4-patched SOM line ``**SOM: $1,540M**`` failed parse_som and tripped
``eval.json.failures == ["SOM_BELOW_100M"]`` (because the parser returned
None, not because the value was small).

This atom widens the regex to accept all investor-readable forms:

    **SOM (Year 1):** $120M           ← canonical (unchanged)
    **SOM (Y1):** $120M               ← short qualifier
    **SOM (Year One):** $120M         ← verbose qualifier
    **SOM:** $120M                    ← no qualifier
    **SOM:** $1,540M                  ← comma-separated thousands
    **SOM: $1,540M**                  ← colon + closing bold after the number
    **SOM** $1540M                    ← no colon at all

While simultaneously preserving:

    parse_som("") is None                      (empty input)
    parse_som("no SOM here") is None           (no marker)

A new :func:`is_som_line_canonical` returns True only for the strict
canonical shape, so the eval gate can emit a soft "consider canonical
form" warning without rejecting the run.

Anti-pattern guards:

- No backward-incompat removal of the strict tests in
  ``evals/test_som_threshold.py`` — those continue to pass.
- No silent value-coercion: commas are stripped explicitly; the rest of
  the float parsing path is unchanged.
- Tests are shape + boundary assertions; semantic SOM thresholds remain
  in :mod:`pipeline.empirical_genius` (C006/C007/C008 kill switches).
"""

from __future__ import annotations

import pytest

from pipeline.template_filter import is_som_line_canonical, parse_som

# ── Backward compatibility (canonical form) ─────────────────────────────────


class TestCanonicalFormStillWorks:
    """Every assertion in ``evals/test_som_threshold.py`` must remain true."""

    def test_canonical_120m(self) -> None:
        result = parse_som("**SOM (Year 1):** $120M")
        assert result is not None
        value, _ = result
        assert abs(value - 120.0) < 0.01

    def test_canonical_50m(self) -> None:
        result = parse_som("**SOM (Year 1):** $50M")
        assert result is not None
        value, _ = result
        assert abs(value - 50.0) < 0.01

    def test_canonical_1_2b_yields_1200m(self) -> None:
        result = parse_som("**SOM (Year 1):** $1.2B")
        assert result is not None
        value, _ = result
        assert abs(value - 1200.0) < 0.01

    def test_canonical_200_5m(self) -> None:
        result = parse_som("**SOM (Year 1):** $200.5M")
        assert result is not None
        value, _ = result
        assert abs(value - 200.5) < 0.01

    def test_no_som_returns_none(self) -> None:
        assert parse_som("Nothing about SOM here.") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_som("") is None


# ── NB-PARSE-SOM-WIDEN — newly-accepted variants ────────────────────────────


class TestWidenedVariants:
    """The drafter's real-world outputs that previously failed."""

    @pytest.mark.parametrize(
        "line,expected_m",
        [
            ("**SOM (Year 1):** $1,540M", 1540.0),
            ("**SOM (Year One):** $120M", 120.0),
            ("**SOM (Y1):** $200M", 200.0),
            ("**SOM:** $1540M", 1540.0),
            ("**SOM:** $1,540M", 1540.0),
            # The live NB.10 failure mode: colon+number+M all inside the bold pair.
            ("**SOM: $1,540M**", 1540.0),
            # Mixed-case qualifier
            ("**SOM (year 1):** $120M", 120.0),
            # Bare "**SOM** $120M" without colon (rare but valid markdown bold)
            ("**SOM** $120M", 120.0),
            # Whitespace tolerance around dollar amount
            ("**SOM (Year 1):**  $ 1,540M", 1540.0),
        ],
    )
    def test_widened_variant_parses(self, line: str, expected_m: float) -> None:
        result = parse_som(line)
        assert result is not None, f"widened variant rejected: {line!r}"
        value, _ = result
        assert abs(value - expected_m) < 0.01, f"line {line!r} expected {expected_m}M, got {value}M"

    def test_comma_separated_billions(self) -> None:
        # No comma needed in B form, but make sure decimals still work.
        result = parse_som("**SOM:** $1.54B")
        assert result is not None
        value, _ = result
        assert abs(value - 1540.0) < 0.01

    def test_full_concept_md_with_widened_line(self) -> None:
        """Embedded in the kind of paragraph the drafter actually writes."""
        md = (
            "## Audience Sizing\n"
            "Some paragraph of audience sizing prose.\n"
            "\n"
            "**SOM: $1,540M** *(franchise platform value across three installments; "
            "standalone theatrical-first feature SOM is $110M, based on documented "
            "comp range $50.9M-$108.9M worldwide)*\n"
            "\n"
            "## Revenue Thesis\n"
        )
        result = parse_som(md)
        assert result is not None
        value, line_no = result
        assert abs(value - 1540.0) < 0.01
        assert line_no >= 3  # must be on the SOM line, not before


# ── is_som_line_canonical ────────────────────────────────────────────────────


class TestIsSomLineCanonical:
    def test_canonical_line_returns_true(self) -> None:
        assert is_som_line_canonical("**SOM (Year 1):** $120M") is True

    def test_widened_without_qualifier_returns_false(self) -> None:
        assert is_som_line_canonical("**SOM:** $1540M") is False

    def test_widened_with_comma_returns_false(self) -> None:
        assert is_som_line_canonical("**SOM (Year 1):** $1,540M") is False

    def test_widened_colon_inside_bold_returns_false(self) -> None:
        assert is_som_line_canonical("**SOM: $1,540M**") is False

    def test_short_qualifier_returns_false(self) -> None:
        assert is_som_line_canonical("**SOM (Y1):** $120M") is False

    def test_absent_returns_false(self) -> None:
        assert is_som_line_canonical("") is False
        assert is_som_line_canonical("no SOM here") is False

    def test_canonical_inside_multiline_returns_true(self) -> None:
        md = "Some preamble.\n**SOM (Year 1):** $120M\nFollowing paragraph.\n"
        assert is_som_line_canonical(md) is True
