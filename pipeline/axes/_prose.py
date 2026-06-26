"""Prose-fallback resolver for character data (NB.5-AXIS-PROSE, Cycle 1 Session 6).

The Q2 axes (``character_depth`` and ``agency_ratio``) read structured fields
under ``concept["characters"]`` — top-level keys ``protagonist``, ``antagonist``,
``key_characters`` with ``name``, ``want``, ``need``, ``contradiction``,
``belief``, ``method``, ``entity_type``, ``function``.

The ``concept-drafter`` agent's real-world output does **not** populate this
structured field. Instead it writes character data as **prose under**
``concept["sections"]["protagonist" | "antagonist" | "key_characters" |
"characters"]`` (the V2 template's `## Protagonist`, `## Antagonist`,
`## Key Characters` markdown headings). This was caught on the first
instrumented NB.10 run (``runs/2026-05-19-133938-the-quota/``) where both
Q2 axes returned 0.0 because the structured field was empty.

This module's :func:`resolve_characters` returns the structured dict the
axes expect. It prefers the literal structured field when it has content,
and only falls back to prose extraction when the structured field is
missing or empty. Prose extraction is heuristic — sentence-level keyword
cues — and faithfully returns empty strings for fields whose cue does not
fire (so the character-depth signal count stays meaningful: an absent
``need`` sentence still scores zero).

ADR-0001: read-only; no atomic writes here.
ADR-0002: no arithmetic — scoring stays in the axis modules.
ADR-0005: no imports from ``frameworks/``.

The two axes call :func:`resolve_characters` instead of
``concept.get("characters")``; that is the entire integration surface.
"""

from __future__ import annotations

import re
from typing import Any, cast

_ = cast  # keep the import (typed reference; formatter would otherwise strip it)


# ── Sentence-level cues per field ────────────────────────────────────────────
#
# Each cue is a list of regexes. The first regex that matches a sentence claims
# that sentence for that field. Order within the list is precedence — more
# specific cues come first.

_WANT_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwants?\s+to\b", re.IGNORECASE),
    re.compile(r"\bwants?\b", re.IGNORECASE),
    re.compile(r"\bwanted\b", re.IGNORECASE),
    re.compile(r"\bdesires?\s+to\b", re.IGNORECASE),
)

_NEED_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bneeds?\s+to\b", re.IGNORECASE),
    re.compile(r"\bneeds?\b", re.IGNORECASE),
    re.compile(r"\bneeded\b", re.IGNORECASE),
    re.compile(r"\bmust\s+(?:learn|come\s+to|accept|forgive|surrender|admit)\b", re.IGNORECASE),
)

_CONTRADICTION_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcontradiction\b", re.IGNORECASE),
    re.compile(r"\bincompatible\b", re.IGNORECASE),
    re.compile(r"\bgap\s+between\b", re.IGNORECASE),
    re.compile(r"\btorn\s+between\b", re.IGNORECASE),
    re.compile(r"\bcaught\s+between\b", re.IGNORECASE),
    re.compile(r"\b(?:but|yet)\s+must\b", re.IGNORECASE),
    re.compile(r"\bcannot\s+(?:both|simultaneously)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:same|very)\s+\w+\s+(?:that|she|he|they)", re.IGNORECASE),
)

_BELIEF_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbelieves?\b", re.IGNORECASE),
    re.compile(r"\bconvinced\b", re.IGNORECASE),
    re.compile(r"\bthinks?\b", re.IGNORECASE),
    re.compile(r"\bdecided\b", re.IGNORECASE),
    re.compile(r"\bdoctrine\b", re.IGNORECASE),
    re.compile(r"\blogic\s+(?:that|of)\b", re.IGNORECASE),
    re.compile(r"\bideology\b", re.IGNORECASE),
)

_METHOD_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\boptimi[sz]es?\b", re.IGNORECASE),
    re.compile(r"\bweaponi[sz]es?\b", re.IGNORECASE),
    re.compile(r"\bwields?\b", re.IGNORECASE),
    re.compile(r"\boperates?\s+by\b", re.IGNORECASE),
    re.compile(r"\bmanages?\s+(?:by|through|via)\b", re.IGNORECASE),
    re.compile(r"\benforces?\b", re.IGNORECASE),
    re.compile(r"\bexerts?\b", re.IGNORECASE),
    re.compile(r"\b(?:its|his|her|their)\s+method\b", re.IGNORECASE),
)


# Entity-type classification by keyword in name or description.
# Order: more specific → more general. First match wins.
_ENTITY_TYPE_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "institution",
        re.compile(
            r"\b(?:office|institution|agency|department|bureau|ministry|"
            r"corporation|company|firm|board|committee|authority|tribunal|"
            r"system|the\s+state|the\s+government|the\s+church|the\s+party)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "technology",
        re.compile(
            r"\b(?:algorithm|machine|network|AI|artificial\s+intelligence|"
            r"protocol|platform|software|model|kernel|engine|database|"
            r"surveillance\s+grid)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "environment",
        re.compile(
            r"\b(?:wilderness|forest|ocean|sea|desert|storm|hurricane|"
            r"volcano|mountain|ice|tundra|jungle|swamp|environment|"
            r"the\s+wild|the\s+climate|the\s+weather|the\s+land)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "abstract",
        re.compile(
            r"\b(?:fate|time|memory|grief|silence|the\s+past|"
            r"the\s+future|history|truth|loss|justice)\b",
            re.IGNORECASE,
        ),
    ),
)


# Sentence splitter — naive but adequate. Splits on . ! ? followed by space/EOF.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Strong-bold name extractor — captures the `**Name**` prefix common in V2 prose.
# Accepts em-dash (U+2014), en-dash (U+2013), or ASCII hyphen as the separator.
_BOLD_NAME_RE = re.compile(
    "\\*\\*([^*]+)\\*\\*\\s*[—–\\-]\\s*"  # noqa: RUF001 — V2 template uses em-dash literally
)

# Plain heading extractor — captures the first capitalised proper-noun phrase
# (≤ 5 words) inside a section, for when bold markers are missing.
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z']*(?:\s+(?:of\s+the\s+)?[A-Z][a-zA-Z']*){0,4})\b")


# ── Section text helpers ─────────────────────────────────────────────────────


def _section_text(sections: dict[str, Any], key: str) -> str:
    """Return the section's prose text, stripped. Empty string when absent."""
    raw = sections.get(key)
    return raw.strip() if isinstance(raw, str) else ""


def _slice_subsection(text: str, heading: str) -> str:
    """Within a combined `## Protagonist` / `## Antagonist` / `## Key Characters`
    block, extract just the named subsection. Returns "" when not found.
    """
    if not text:
        return ""
    # Match the heading line `## Heading` and capture until the next `## ` or EOF.
    pattern = re.compile(r"(?ms)^\s*##\s+" + re.escape(heading) + r"\s*$\s*(.*?)(?=^\s*##\s+|\Z)")
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _first_sentence_matching(sentences: list[str], cues: tuple[re.Pattern[str], ...]) -> str:
    """Return the first sentence that matches any cue, in cue-precedence order."""
    for cue in cues:
        for sent in sentences:
            if cue.search(sent):
                return sent
    return ""


def _extract_name(prose: str) -> str:
    """Pull the protagonist/antagonist name from a `**Name** —` prefix or the
    first capitalised proper-noun phrase."""
    if not prose:
        return ""
    bold = _BOLD_NAME_RE.search(prose)
    if bold:
        return bold.group(1).strip()
    proper = _PROPER_NOUN_RE.search(prose)
    return proper.group(1).strip() if proper else ""


def _classify_entity_type(name: str, prose: str) -> str:
    """Return one of {'human', 'institution', 'technology', 'environment',
    'abstract'}. Defaults to 'human'.

    The classifier checks the antagonist's **name** first — the name is more
    authoritative than incidental keywords in the surrounding prose. Only
    when the name has no matching keyword does the classifier fall back to
    scanning the description. Without this two-pass design, an antagonist
    named "The Algorithm" whose description happens to mention a
    "recommendation system" would be misclassified as ``institution`` because
    of the word "system" — which is the exact failure mode caught by
    ``tests/test_axes_prose_fallback.py``.
    """
    for label, pattern in _ENTITY_TYPE_TABLE:
        if name and pattern.search(name):
            return label
    for label, pattern in _ENTITY_TYPE_TABLE:
        if prose and pattern.search(prose):
            return label
    return "human"


# ── Public surface ───────────────────────────────────────────────────────────


def _resolve_subsection(sections: dict[str, Any], heading_key: str) -> str:
    """Resolve a subsection's prose by trying (a) the dedicated section field,
    (b) the combined `characters` field sliced by `## Heading`."""
    direct = _section_text(sections, heading_key)
    if direct:
        return direct
    combined = _section_text(sections, "characters")
    return _slice_subsection(combined, heading_key.replace("_", " ").title())


def _extract_protagonist(sections: dict[str, Any]) -> dict[str, Any]:
    prose = _resolve_subsection(sections, "protagonist")
    if not prose:
        return {}
    sentences = _split_sentences(prose)
    return {
        "name": _extract_name(prose),
        "want": _first_sentence_matching(sentences, _WANT_CUES),
        "need": _first_sentence_matching(sentences, _NEED_CUES),
        "contradiction": _first_sentence_matching(sentences, _CONTRADICTION_CUES),
    }


def _extract_antagonist(sections: dict[str, Any]) -> dict[str, Any]:
    prose = _resolve_subsection(sections, "antagonist")
    if not prose:
        return {}
    sentences = _split_sentences(prose)
    name = _extract_name(prose)
    return {
        "name": name,
        "belief": _first_sentence_matching(sentences, _BELIEF_CUES),
        "method": _first_sentence_matching(sentences, _METHOD_CUES),
        "entity_type": _classify_entity_type(name, prose),
    }


def _extract_key_characters(sections: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the `## Key Characters` section into a list of {name, function}."""
    prose = _resolve_subsection(sections, "key_characters")
    if not prose:
        return []
    entries: list[dict[str, Any]] = []
    # Each `**Name** — function description` is one entry. Split on the bold-name
    # marker; the surrounding text becomes the function.
    parts = _BOLD_NAME_RE.split(prose)
    # `_BOLD_NAME_RE.split` yields: [pre, name1, body1, name2, body2, ...]
    if len(parts) < 3:  # noqa: PLR2004 — pattern is "pre, name, body" minimum
        return []
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip()
        body = parts[i + 1].strip()
        if not name:
            continue
        # Function = first sentence of the body (skip leading dashes/punct).
        first = _split_sentences(body)[0] if body else ""
        entries.append({"name": name, "function": first})
    return entries


def _has_structured_data(chars: object) -> bool:
    """A truthy structured ``characters`` dict has a protagonist with a name."""
    if not isinstance(chars, dict):
        return False
    chars_dict = cast("dict[str, Any]", chars)
    protag = chars_dict.get("protagonist")
    if not isinstance(protag, dict):
        return False
    protag_dict = cast("dict[str, Any]", protag)
    name = protag_dict.get("name")
    return isinstance(name, str) and bool(name.strip())


def resolve_characters(concept: dict[str, Any]) -> dict[str, Any]:
    """Return a structured ``characters`` dict for the Q2 axes.

    Precedence:
        1. If ``concept["characters"]`` has a named protagonist (i.e. the
           drafter populated the structured field), return it verbatim.
        2. Otherwise, derive structured data from ``concept["sections"]``
           prose using sentence-level keyword cues. Missing cue → empty
           string (faithful: the axis signals must still measure absence).
        3. If neither structured nor sections data is usable, return ``{}``.

    Output schema matches what the axes expect — keys ``protagonist``,
    ``antagonist``, ``key_characters``; each character has at minimum a
    ``name`` field plus the cue-extracted prose for ``want``, ``need``,
    ``contradiction``, ``belief``, ``method`` (as applicable), and an
    ``entity_type`` classification for the antagonist.
    """
    chars = concept.get("characters")
    if _has_structured_data(chars):
        return cast("dict[str, Any]", chars)

    sections = concept.get("sections")
    if not isinstance(sections, dict):
        return cast("dict[str, Any]", chars) if isinstance(chars, dict) else {}
    sections_dict = cast("dict[str, Any]", sections)

    derived: dict[str, Any] = {}
    protag = _extract_protagonist(sections_dict)
    antag = _extract_antagonist(sections_dict)
    key_chars = _extract_key_characters(sections_dict)
    if protag:
        derived["protagonist"] = protag
    if antag:
        derived["antagonist"] = antag
    if key_chars:
        derived["key_characters"] = key_chars
    if derived:
        return derived
    return cast("dict[str, Any]", chars) if isinstance(chars, dict) else {}


__all__ = ["resolve_characters"]
