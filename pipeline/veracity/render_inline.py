"""Inline-citation renderer — inject live-sourced URLs into a rendered card.

Given a card and a ``{claim_id: {"url", "quote", "date"}}`` binding produced by
the source-claims workflow, insert each source AT the claim's location so the
card visibly carries its evidence and the enumerator then counts the claim
deep-linked.

**INSERT-ONLY** — it wraps an existing Comparables title cell in
``[title](url)`` or appends ``([source](url))`` after a prose claim sentence. It
never deletes, reorders, or alters a ``$`` token (ADR-0011: a ``python_executed``
figure is byte-identical before and after; a ``$`` multiset change raises). The
transform is idempotent (``render_inline(render_inline(x)) == render_inline(x)``)
and ``strip_internal_ids``-clean (ADR-0010). No ``<url>`` auto-link form.
"""

from __future__ import annotations

import re

from pipeline.veracity.claims import Claim
from pipeline.veracity.enumerate import enumerate_claims, tag_lines

try:  # the output filter is always present in v4+, but keep render_inline importable
    from pipeline.template_filter import strip_internal_ids
except Exception:  # pragma: no cover

    def strip_internal_ids(md_text: str) -> str:
        return md_text


_MONEY_RE = re.compile(
    r"\$\s?[\d,]+(?:\.\d+)?\s*(?:trillion|billion|million|thousand|[bmkt])?",
    re.IGNORECASE,
)
_LINK_IN = re.compile(r"\[[^\]]+\]\(https?://[^)\s]+\)")
#: Prose claim types whose sentence gets an appended citation (comps use the
#: table rule; TAM/proof bullets are already linked in the card).
_PROSE_TYPES = frozenset({"box_office", "demand", "cultural_signal", "market_claim"})
#: ``"| a | b |".split("|")`` → ``['', ' a ', ' b ', '']``; a real row needs ≥3.
_MIN_ROW_PARTS = 3


def _money_multiset(text: str) -> list[str]:
    """Whitespace-normalised, sorted multiset of every ``$`` token (ADR-0011 guard)."""
    return sorted(re.sub(r"\s+", "", m.group(0)) for m in _MONEY_RE.finditer(text))


def _cite(url: str, date: str = "") -> str:
    tail = f", {date}" if date else ""
    return f"([source]({url}){tail})"


def _linkify_comp_cell(line: str, title: str, url: str) -> str | None:
    """Wrap the first-column title of a Comparables row in ``[title](url)``.

    Returns the rewritten line, or ``None`` if this is not the row for ``title``
    (or its title cell is already a link → idempotent).
    """
    if not line.lstrip().startswith("|"):
        return None
    parts = line.split("|")
    if len(parts) < _MIN_ROW_PARTS:
        return None
    cell = parts[1]
    if _LINK_IN.search(cell):
        return None  # already linked → idempotent
    stripped = cell.replace("*", "").strip()
    if not stripped or stripped != title:
        return None
    parts[1] = cell.replace(cell.strip(), f"[{cell.strip()}]({url})", 1)
    return "|".join(parts)


def _apply_comp(claim: Claim, lines: list[str], sections: list[str], url: str) -> None:
    for i, line in enumerate(lines):
        if sections[i] != "comparables":
            continue
        rewritten = _linkify_comp_cell(line, claim.anchor, url)
        if rewritten is not None:
            lines[i] = rewritten
            return


def _apply_prose(claim: Claim, lines: list[str], sections: list[str], url: str, date: str) -> None:
    if any(url in ln for ln in lines):
        return  # already cited somewhere → idempotent
    for i, line in enumerate(lines):
        if sections[i] and claim.anchor in line and not _LINK_IN.search(line):
            lines[i] = line.replace(claim.anchor, f"{claim.anchor} {_cite(url, date)}", 1)
            return


def render_inline(md: str, bound: dict[str, dict[str, str]], *, concept_id: str = "doc") -> str:
    """Return ``md`` with a citation inserted at every bound, not-yet-linked claim.

    ``bound`` maps the enumerator's ``claim_id`` → ``{"url", "quote", "date"}``
    (the source-claims workflow output). Claims already carrying a ``cited_url``
    in the card are skipped. Raises ``ValueError`` if any ``$`` token changes.
    """
    if not bound:
        return strip_internal_ids(md)

    claims = enumerate_claims(md, concept_id=concept_id)
    tagged = tag_lines(md)
    lines = [t[0] for t in tagged]
    sections = [t[2] for t in tagged]

    for claim in claims:
        judgment = bound.get(claim.claim_id)
        if not judgment or not judgment.get("url") or claim.cited_url:
            continue
        url = judgment["url"]
        date = str(judgment.get("date", "") or "")
        if claim.claim_type == "comp_roi":
            _apply_comp(claim, lines, sections, url)
        elif claim.claim_type in _PROSE_TYPES and claim.anchor:
            _apply_prose(claim, lines, sections, url, date)

    out = "\n".join(lines)
    if md.endswith("\n"):
        out += "\n"
    if _money_multiset(out) != _money_multiset(md):
        raise ValueError(
            f"render_inline changed a $ token for {concept_id!r} — refusing (ADR-0011)"
        )
    return strip_internal_ids(out)
