"""Character-depth axis (Cycle 1 NB.4, heuristic baseline).

Quantifies axes #19/#20/#21/#22/#25/#27 — does the concept ship a *characterized*
protagonist and antagonist (named, with want/need/contradiction and belief/method),
or just an action verb attached to a placeholder?

Cycle 1 contract: equal-weight signal count, normalized to [0, 1]. No learned
weights, no parquet dependency. Replaced by Tier-1-parquet-driven weights once
S4 lands.

Returns:
    ``(score, evidence)`` where:
      - ``score`` ∈ [0, 1]
      - ``evidence`` = ``{"signals": list[str], "n_fired": int, "n_total": int}``
"""

from __future__ import annotations

from typing import Any, cast

from pipeline.axes._prose import resolve_characters

_ = cast  # keep the import (typed reference; formatter would otherwise strip it)

# Each signal contributes 1/len(SIGNALS) to the score when present.
SIGNALS: tuple[str, ...] = (
    "protagonist_named",
    "protagonist_want_present",
    "protagonist_need_present",
    "protagonist_contradiction_present",
    "antagonist_named",
    "antagonist_belief_present",
    "antagonist_method_distinct_from_protagonist_want",
    "antagonist_entity_type_non_human",
    "key_characters_with_function",
    "logline_specific",
)


_NON_HUMAN_ENTITY_TYPES = frozenset({"institution", "environment", "abstract", "technology"})

# A "specific" logline is one with a named protagonist token (capitalized,
# non-stop-word) and ≥10 words. Tunable; replaced by S4 calibration.
_LOGLINE_MIN_WORDS = 10


def _str(val: object) -> str:
    if isinstance(val, str):
        return val.strip()
    return ""


def _any_key_character_has_function(key_chars: object) -> bool:
    if not isinstance(key_chars, list):
        return False
    items = cast("list[object]", key_chars)
    return any(
        _str(cast("dict[str, object]", kc).get("function")) for kc in items if isinstance(kc, dict)
    )


def _is_specific_logline(logline: str, protagonist_name: str) -> bool:
    if not logline:
        return False
    words = logline.split()
    if len(words) < _LOGLINE_MIN_WORDS:
        return False
    # The protagonist's name (or any proper noun) must appear in the logline.
    if protagonist_name and protagonist_name.lower() in logline.lower():
        return True
    # Otherwise: at least one capitalized non-leading word as proxy for a proper noun.
    return any(w[:1].isupper() for w in words[1:])


def score(concept: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Return ``(score, evidence)`` for the character-depth axis."""
    fired: list[str] = []

    # NB.5-AXIS-PROSE: fall back to prose extraction from concept["sections"]
    # when the structured top-level "characters" field is absent (drafter's
    # real-world output writes character data as prose under sections.*).
    characters: dict[str, Any] = resolve_characters(concept)
    protag: dict[str, Any] = characters.get("protagonist") or {}
    antag: dict[str, Any] = characters.get("antagonist") or {}
    key_chars: list[Any] = characters.get("key_characters") or []
    logline = _str(concept.get("logline"))

    p_name = _str(protag.get("name"))
    p_want = _str(protag.get("want"))
    p_need = _str(protag.get("need"))
    p_contradiction = _str(protag.get("contradiction"))

    a_name = _str(antag.get("name"))
    a_belief = _str(antag.get("belief"))
    a_method = _str(antag.get("method"))
    a_entity = _str(antag.get("entity_type")).lower()

    # Protagonist signals: name must be more than a pronoun for "named" to count.
    if p_name and p_name.lower() not in {"he", "she", "they", "it"}:
        fired.append("protagonist_named")
    if p_want:
        fired.append("protagonist_want_present")
    if p_need and p_need != p_want:
        fired.append("protagonist_need_present")
    if p_contradiction:
        fired.append("protagonist_contradiction_present")

    # Antagonist signals.
    if a_name:
        fired.append("antagonist_named")
    if a_belief:
        fired.append("antagonist_belief_present")
    if a_method and a_method.lower() != p_want.lower():
        fired.append("antagonist_method_distinct_from_protagonist_want")
    if a_entity in _NON_HUMAN_ENTITY_TYPES:
        fired.append("antagonist_entity_type_non_human")

    # Supporting cast signals.
    if _any_key_character_has_function(key_chars):
        fired.append("key_characters_with_function")

    # Logline signal.
    if _is_specific_logline(logline, p_name):
        fired.append("logline_specific")

    n_fired = len(fired)
    n_total = len(SIGNALS)
    s = round(n_fired / n_total, 6) if n_total else 0.0
    return s, {"signals": fired, "n_fired": n_fired, "n_total": n_total}


__all__ = ["SIGNALS", "score"]
