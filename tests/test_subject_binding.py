"""tests/test_subject_binding.py — off-scope deep-link guard.

``value_on_page.subject_on_page`` binds a claim's NUMBER to its SUBJECT: it
returns True only when the claim's anchor (e.g. a comp film title) actually
appears on the fetched page, closing the cheat where the right number sits on an
in-host page about a different title.
"""

from __future__ import annotations

from pipeline.research.value_on_page import subject_on_page

_PAGE = (
    "Box Office Mojo — Barbie (2023). Domestic $636,238,421. "
    "Worldwide $1,445,638,421. Distributor Warner Bros."
)


def test_subject_present_full_title() -> None:
    assert subject_on_page("Barbie", _PAGE) is True


def test_subject_present_multiword_case_insensitive() -> None:
    assert subject_on_page("box OFFICE mojo", _PAGE) is True


def test_subject_absent_returns_false() -> None:
    assert subject_on_page("Oppenheimer", _PAGE) is False


def test_empty_anchor_returns_false() -> None:
    assert subject_on_page("", _PAGE) is False
    assert subject_on_page("   ", _PAGE) is False


def test_whitespace_normalised_match() -> None:
    page = "the   final\n release   of   Warner Bros. titles"
    assert subject_on_page("Warner Bros.", page) is True


def test_five_word_window_for_long_anchor() -> None:
    anchor = "the fairest organ transplant allocation list ever"  # 7 words, not verbatim
    page = "Critics called it the fairest organ transplant allocation list anyone had seen."
    assert subject_on_page(anchor, page) is True


def test_off_scope_number_right_wrong_title() -> None:
    """The classic cheat: correct gross, wrong film on a shared in-host page."""
    page = "Oppenheimer (2023) worldwide gross $975,000,000 per studio filings."
    # The claim is about Barbie — its subject must NOT bind to an Oppenheimer page.
    assert subject_on_page("Barbie", page) is False


def test_one_word_anchor_substring_match_is_a_known_limitation() -> None:
    """A 1-word anchor binds on any SUBSTRING occurrence (not word-boundary) —
    the documented weakness. The Run-B driver compensates by applying
    subject-binding only on tier-1/2 credible (single-title) pages and flagging
    tier-4/5 survivors for human review (plan §4). Pinned here so the limitation
    is explicit, not silent."""
    # "Up" (the Pixar comp) incidentally matches inside "group".
    assert subject_on_page("Up", "the team grew as a group over the years") is True
