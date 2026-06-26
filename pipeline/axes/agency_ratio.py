"""Agency-ratio axis (Cycle 1 S4.3 NB-AXIS-AGENCY).

Implements the CIE Agency Ratio constraint from the master plan
(§"Anti-Overengineering — Simple Amplifiers"): a protagonist should drive
the action more than they receive it. The Cycle-1 heuristic counts curated
**active** verbs and copula-based **passive** constructions across the four
text sources where protagonist agency surfaces:

- ``concept["logline"]``
- ``concept["characters"]["protagonist"]["want" | "need" | "contradiction"]``

Score formula (per Session 4 prompt §STREAM B / S4.3):

    score = min(1.0, active_count / max(1, passive_count) / 2.0)

A ratio of 2.0 maps to 1.0; the Cycle-1 ``BASE_AXIS_THRESHOLDS["agency_ratio"]``
is 0.50 (= ratio ≥ 1.0). A score ≥ 0.5 satisfies the CIE Agency Ratio
threshold and contributes ``True`` to the Q2 vector pass alongside
:mod:`pipeline.axes.character_depth`.

This is intentionally a **heuristic baseline**: the curated verb list is tight
(only the 9 base verbs the spec names — run, decide, confront, expose, force,
choose, betray, defend, dismantle — with inflection variants). The list is
expanded by the S4 discovery notebook, not by hand. Same Cycle-1 anti-pattern
discipline as ``character_depth.py``.

Returns:
    ``(score, evidence)`` where:

    - ``score`` ∈ [0, 1]
    - ``evidence`` keys: ``active_verbs``, ``passive_constructions``,
      ``active_count``, ``passive_count``, ``ratio``
"""

from __future__ import annotations

import re
from typing import Any, cast

from pipeline.axes._prose import resolve_characters

_ = cast  # keep the import (typed reference; formatter would otherwise strip it)

# Curated active-action verbs. Inflections enumerated explicitly so the
# matcher is exact and auditable (no stemmer dependency).
_ACTIVE_VERBS: frozenset[str] = frozenset(
    {
        "run", "runs", "ran", "running",
        "decide", "decides", "decided", "deciding",
        "confront", "confronts", "confronted", "confronting",
        "expose", "exposes", "exposed", "exposing",
        "force", "forces", "forced", "forcing",
        "choose", "chooses", "chose", "chosen", "choosing",
        "betray", "betrays", "betrayed", "betraying",
        "defend", "defends", "defended", "defending",
        "dismantle", "dismantles", "dismantled", "dismantling",
    }
)  # fmt: skip

# Passive constructions: copula + past-participle. Tight enough to avoid
# false hits on "is the one" (copula + noun phrase) — only matches when the
# follower ends in -ed.
_PASSIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bis\s+\w*ed\b", re.IGNORECASE),
    re.compile(r"\bwas\s+\w*ed\b", re.IGNORECASE),
    re.compile(r"\bare\s+\w*ed\b", re.IGNORECASE),
    re.compile(r"\bwere\s+\w*ed\b", re.IGNORECASE),
    re.compile(r"\bbecomes\s+\w+", re.IGNORECASE),
    re.compile(r"\bgets\s+\w*ed\b", re.IGNORECASE),
)

_TOKEN_RE = re.compile(r"[a-z']+")


def _str(val: object) -> str:
    return val.strip() if isinstance(val, str) else ""


def _collect_text(concept: dict[str, Any]) -> str:
    # NB.5-AXIS-PROSE: resolve_characters falls back to prose extraction from
    # concept["sections"] when the structured top-level "characters" field is
    # absent (drafter's real-world output puts character data in sections.*).
    characters: dict[str, Any] = resolve_characters(concept)
    protag_obj = characters.get("protagonist")
    protag: dict[str, Any] = (
        cast("dict[str, Any]", protag_obj) if isinstance(protag_obj, dict) else {}
    )
    parts = [
        _str(concept.get("logline")),
        _str(protag.get("want")),
        _str(protag.get("need")),
        _str(protag.get("contradiction")),
    ]
    return "\n".join(p for p in parts if p)


def _find_passive_spans(text: str) -> tuple[list[tuple[int, int]], list[str]]:
    """Return ``(spans, surface_forms)`` for every passive match."""
    if not text:
        return [], []
    spans: list[tuple[int, int]] = []
    surface: list[str] = []
    for pat in _PASSIVE_PATTERNS:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
            surface.append(m.group(0))
    return spans, surface


def _find_active_verbs(text: str, passive_spans: list[tuple[int, int]]) -> tuple[int, list[str]]:
    """Count active-verb tokens; tokens inside a passive span don't count.

    Excluding tokens inside passive spans prevents double-counting cases like
    "is forced to confront" — "forced" is part of the passive construction
    rather than an independent active verb of the protagonist.
    """
    if not text:
        return 0, []
    hits: list[str] = []
    lowered = text.lower()
    for m in _TOKEN_RE.finditer(lowered):
        tok = m.group(0)
        if tok not in _ACTIVE_VERBS:
            continue
        pos = m.start()
        if any(start <= pos < end for start, end in passive_spans):
            continue
        hits.append(tok)
    return len(hits), hits


def score(concept: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Return ``(score, evidence)`` for the agency-ratio axis."""
    text = _collect_text(concept)
    passive_spans, passive_constructions = _find_passive_spans(text)
    passive_count = len(passive_constructions)
    active_count, active_verbs = _find_active_verbs(text, passive_spans)

    ratio = active_count / max(1, passive_count)
    s = round(min(1.0, ratio / 2.0), 6)

    evidence: dict[str, Any] = {
        "active_verbs": active_verbs,
        "passive_constructions": passive_constructions,
        "active_count": active_count,
        "passive_count": passive_count,
        "ratio": float(ratio),
    }
    return s, evidence


__all__ = ["score"]
