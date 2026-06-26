# ruff: noqa: E501 - the SAMPLE_CARD fixture mirrors real card prose (long sentences are intentional)
"""Tests for the section-aware claim ENUMERATOR (pipeline.veracity.enumerate).

The enumerator is the fix for RC1/RC2 (the tautology + no-prose-scan defects):
it finds EVERY externally-checkable claim in a rendered concept card — not just
the ones that already carry a markdown link — so deep-link *density* gets an
honest denominator. It is a NEW function; ``extract_from_markdown`` is untouched
(its contract is pinned in ``test_veracity.py``).

All offline — pure parsing, no network, no LLM (ADR-0002).
"""

from __future__ import annotations

from pipeline.veracity.enumerate import enumerate_claims

# A hermetic card that exercises every structure the real flagship cards use:
#   - logline/tagline + narrative sections with numbers that MUST be excluded
#   - Audience Sizing prose with TAM, SAM/SOM echoes, a superlative conclusion,
#     and modeled floor/upside/lifetime (computed-context → excluded)
#   - a Comparables table with NO inline links (the RC2 case)
#   - a Revenue Thesis comp restatement (dedup against the comp table)
#   - a Why Now salience statistic
#   - a Verified Proof of Demand bullet that ALREADY carries url + quote
#   - an Economics table (TAM external + SAM/SOM computed)
SAMPLE_CARD = """# Mockfilm

#### Logline
A child has nine days to stop a flood that will displace two thousand people across nine generations of farmland.

#### Tagline
She feels the break.

---

# 1. Market & Audience

## Audience Sizing

The total addressable market is the global theatrical box office, valued at $328.2 billion (industry THEME report). Animated family features are the most durable revenue category in that market. The serviceable addressable market is $39.4 billion. The realistic obtainable market for a first-year theatrical window is **$540M**, with a modeled floor near $300M and an upside near $1.2B. Lifetime value is modeled at approximately $1.6 billion.

## Revenue Thesis

The closest comp earned $411.0 million worldwide against a $25 million budget.

## Why Now

Forced relocation is a present headline; 11 million people were displaced by disaster in 2024.

# 2. The Concept

## Tonal Contract

Hand-painted warmth across roughly 100 minutes, rated PG.

# 3. Story

## Synopsis

Nima, eight, has nine days before the reservoir floods two thousand people out of nine generations of terraces.

## Comparables

| Title | Year | WW Revenue | Budget | ROI | Notes |
|---|---|---|---|---|---|
| The Bodyguard | 1992 | $411.0M | $25.0M | 15.4x | Contained two-hander. |
| Hercules | 1997 | $252.7M | $85.0M | 2.0x | Folk-myth animation. |

## Why Not Generic

It looks adjacent to a fable but inverts the trope.

# 4. Characters

## Protagonist

Nima, eight, can feel the mountain break across nine generations.

## Verified Proof of Demand

- **A comp crossed $1.009B worldwide on a ~$150M budget** — "grand total to $1.009 billion globally" ([source](https://variety.com/2025/film/box-office/x-1236272527/), 2025-01-19)

## Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $328.20B | Total addressable content market — sourced to the THEME Report ([THEME.pdf](https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf)). |
| **SAM** | $39.38B | Serviceable share — a derivation (~12% of TAM). |
| **SOM (Year 1)** | $540M | Obtainable Year-1 revenue — `python_executed`. |
"""


def _claims():
    return enumerate_claims(SAMPLE_CARD, concept_id="mock", concept_title="Mockfilm")


def _external(cs):
    return [c for c in cs if not c.is_computed]


def _computed(cs):
    return [c for c in cs if c.is_computed]


def test_returns_claim_objects_with_concept_identity() -> None:
    cs = _claims()
    assert cs, "enumerator returned no claims"
    assert all(c.concept_id == "mock" for c in cs)
    assert all(c.concept_title == "Mockfilm" for c in cs)


def test_enumerates_comp_table_without_links() -> None:
    """RC2: the Comparables table carries NO inline url, yet each comp must
    become a checkable claim (today it is invisible)."""
    cs = _claims()
    comp_titles = {c.text for c in cs if c.claim_type == "comp_roi"}
    assert any("Bodyguard" in t for t in comp_titles)
    assert any("Hercules" in t for t in comp_titles)
    # comps in the table have no inline link → cited_url empty (needs sourcing)
    bodyguard = next(c for c in cs if c.claim_type == "comp_roi" and "Bodyguard" in c.text)
    assert bodyguard.cited_url == ""
    assert not bodyguard.is_computed


def test_includes_tam_once_dedups_prose_echo() -> None:
    """TAM appears in both Audience Sizing prose and the Economics table; it must
    yield exactly ONE external TAM claim, carrying the table's source URL."""
    cs = _claims()
    tam = [c for c in cs if c.claim_type == "market_tam"]
    assert len(tam) == 1
    assert tam[0].cited_url.startswith("https://www.motionpictures.org")
    assert not tam[0].is_computed


def test_sam_som_are_computed_not_external() -> None:
    cs = _claims()
    by_type = {c.claim_type for c in cs}
    assert "market_sam" in by_type
    assert "market_som" in by_type
    sam = next(c for c in cs if c.claim_type == "market_sam")
    som = next(c for c in cs if c.claim_type == "market_som")
    assert sam.is_computed and som.is_computed


def test_excludes_modeled_floor_upside_lifetime_from_external() -> None:
    """Modeled floor/upside/lifetime are computed projections, not external
    facts — they must never inflate the external denominator."""
    cs = _claims()
    ext_text = " ".join(c.text for c in _external(cs))
    assert "$300M" not in ext_text  # modeled floor
    assert "$1.2B" not in ext_text  # upside
    assert "1.6 billion" not in ext_text  # lifetime


def test_captures_superlative_conclusion() -> None:
    """The operator requires CONCLUSIONS backed too: a market superlative is an
    external claim that needs a source."""
    cs = _claims()
    claims_text = " ".join(c.text.lower() for c in _external(cs))
    assert "most durable revenue category" in claims_text


def test_captures_why_now_salience_stat() -> None:
    cs = _claims()
    ext = " ".join(c.text for c in _external(cs))
    assert "11 million" in ext


def test_proof_bullet_carries_existing_url_and_quote_anchor() -> None:
    cs = _claims()
    bullet = next((c for c in cs if "1.009B" in c.text or "1.009 billion" in c.text), None)
    assert bullet is not None
    assert bullet.cited_url.startswith("https://variety.com")
    assert not bullet.is_computed


def test_excludes_all_narrative_numbers() -> None:
    """RC scope guard: numbers inside logline/synopsis/tonal/characters/why-not
    sections are narrative, not checkable — they must never appear as claims."""
    cs = _claims()
    blob = " ".join(c.text for c in cs)
    for forbidden in ("two thousand", "nine generations", "100 minutes", "nine days"):
        assert forbidden not in blob, f"narrative number leaked: {forbidden!r}"


def test_revenue_thesis_comp_restatement_dedups_against_table() -> None:
    """The $411.0 million restatement in Revenue Thesis is the same fact as the
    Bodyguard comp row — it must not double-count."""
    cs = _claims()
    four_eleven = [c for c in cs if "411" in c.value or "411" in c.text]
    # exactly one logical claim about the $411M figure (the comp row)
    assert len([c for c in four_eleven if c.claim_type == "comp_roi"]) == 1
    # and no separate demand/box_office claim re-stating the same $411M
    assert not any(c.claim_type in {"demand", "box_office"} and "411" in c.text for c in cs)


def test_claim_ids_stable_and_unique_and_targetable() -> None:
    cs = _claims()
    ids = [c.claim_id for c in cs]
    assert len(ids) == len(set(ids)), "claim ids not unique"
    assert ids == [c.claim_id for c in _claims()], "claim ids not stable across calls"
    # an agent can be handed claim_id + text and echo the id back; it is a hash,
    # not the link anchor text (the RC3 fix)
    assert all(len(i) == 12 for i in ids)


def test_external_denominator_matches_hand_count() -> None:
    """The hermetic card has exactly 6 external + 2 computed claims. This is the
    honest density denominator (6), not the ~2 the current link-harvester sees."""
    cs = _claims()
    assert len(_external(cs)) == 6, [(c.claim_type, c.text[:40]) for c in _external(cs)]
    assert len(_computed(cs)) == 2


def test_claims_carry_anchor_and_section_for_renderer() -> None:
    cs = _claims()
    # every external claim knows which section it came from + an anchor span the
    # renderer can locate (so a citation lands at the right place)
    for c in _external(cs):
        assert c.section, f"missing section for {c.text[:40]!r}"
        assert c.anchor, f"missing anchor for {c.text[:40]!r}"
