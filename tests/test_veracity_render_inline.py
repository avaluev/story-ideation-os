"""Tests for the inline-citation renderer (pipeline.veracity.render_inline).

Locks the ADR-0011 byte-identical-$ guarantee, idempotency, and the two
insertion rules (comp-table title linkify + prose-sentence citation append).
"""

from __future__ import annotations

from pipeline.veracity.enumerate import enumerate_claims
from pipeline.veracity.render_inline import _money_multiset, render_inline

CARD = """# Test Card

# 1. Market & Audience

## Why Now

Streaming demand for the category grew 12% year over year.

## Comparables

| Title | Year | WW Revenue | Budget | ROI | Notes |
|---|---|---|---|---|---|
| Ghost | 1990 | $505.0M | $22.0M | 22.0x | note one |
| [Maleficent](https://ex.com/mal) | 2014 | $758.5M | $180.0M | 3.2x | note two |

## Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| TAM | $328.20B | [MPA](https://www.motionpictures.org/x.pdf) |
| SAM | $39.38B | derivation |
| SOM (Year 1) | $675M | python_executed |
"""

_GHOST_URL = "https://www.boxofficemojo.com/title/tt0099653/"


def _comp(card: str, title: str):
    return next(
        c
        for c in enumerate_claims(card, concept_id="t")
        if c.claim_type == "comp_roi" and c.anchor == title
    )


def test_linkifies_unlinked_comp_title() -> None:
    ghost = _comp(CARD, "Ghost")
    assert ghost.cited_url == ""  # unlinked in the card
    bound = {ghost.claim_id: {"url": _GHOST_URL, "quote": "q", "date": ""}}
    out = render_inline(CARD, bound, concept_id="t")
    assert f"[Ghost]({_GHOST_URL})" in out
    assert _money_multiset(out) == _money_multiset(CARD)  # $ untouched (ADR-0011)


def test_already_linked_comp_untouched() -> None:
    mal = _comp(CARD, "Maleficent")
    assert mal.cited_url  # already linked
    bound = {mal.claim_id: {"url": "https://other.example/x", "quote": "q"}}
    out = render_inline(CARD, bound, concept_id="t")
    assert "other.example" not in out  # skipped because cited_url already set
    assert out.count("[Maleficent](") == 1  # not double-wrapped


def test_idempotent() -> None:
    ghost = _comp(CARD, "Ghost")
    bound = {ghost.claim_id: {"url": _GHOST_URL, "quote": "q"}}
    once = render_inline(CARD, bound, concept_id="t")
    twice = render_inline(once, bound, concept_id="t")
    assert once == twice
    assert f"[Ghost]({_GHOST_URL})" in once


def test_prose_claim_gets_citation() -> None:
    cs = next(
        c for c in enumerate_claims(CARD, concept_id="t") if c.claim_type == "cultural_signal"
    )
    url = "https://www.example-research.org/report"
    bound = {cs.claim_id: {"url": url, "quote": "q", "date": "2024"}}
    out = render_inline(CARD, bound, concept_id="t")
    assert f"([source]({url}), 2024)" in out
    assert _money_multiset(out) == _money_multiset(CARD)


def test_empty_bound_adds_no_links() -> None:
    out = render_inline(CARD, {}, concept_id="t")
    assert "[Ghost]" not in out
    assert _money_multiset(out) == _money_multiset(CARD)


def test_every_dollar_token_preserved_under_full_binding() -> None:
    claims = enumerate_claims(CARD, concept_id="t")
    bound = {c.claim_id: {"url": _GHOST_URL, "quote": "q"} for c in claims}
    out = render_inline(CARD, bound, concept_id="t")
    assert _money_multiset(out) == _money_multiset(CARD)
