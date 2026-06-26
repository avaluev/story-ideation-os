"""tests/test_axes_prose_fallback.py — NB.5-AXIS-PROSE contract (Cycle 1 Session 6).

The Q2 axes ``character_depth`` and ``agency_ratio`` must produce a meaningful
score when the drafter writes character data as **prose** under
``concept["sections"]["protagonist" | "antagonist" | "key_characters" |
"characters"]`` instead of as a structured top-level ``characters`` dict.

Background — caught by NB.10 first instrumented run on 2026-05-19
(``runs/2026-05-19-133938-the-quota/``): both Q2 axes returned 0.0 because the
real-world concept-drafter agent does not populate ``concept["characters"]``;
it only writes prose. The eval_gate's Cycle-1 contract treats quality.json as
informational, so the pipeline did not halt — but the 5-vector gate was
functionally non-measuring on real drafter output.

Contract enforced here:

1. ``resolve_characters`` returns the structured ``characters`` dict verbatim
   when the drafter provides one (no regression on the hand-built fixtures
   used in ``test_axis_character_depth.py`` / ``test_axis_agency_ratio.py``).
2. When the structured field is absent or has no named protagonist, the
   resolver derives a structured shape from ``concept["sections"]`` using
   sentence-level keyword cues.
3. Missing cues yield empty strings — the resolver does NOT fabricate data.
4. Both Q2 axes, given the real Quota draft as input, produce
   ``axis_pass=True`` (``character_depth ≥ 0.50`` and ``agency_ratio ≥ 0.50``).
5. The resolver and both axes are pure-Python — no I/O, no LLM calls.

Anti-pattern guards:

- No category labels in the resolver — it returns prose text, not classes.
- ``entity_type`` is classified from keyword presence in name + prose; no
  hand-authored canonical list of antagonist titles.
- Tests are shape and threshold assertions; semantic correctness defers to
  Cycle 2 S0 calibration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.axes import agency_ratio, character_depth
from pipeline.axes._prose import resolve_characters

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def structured_draft() -> dict[str, Any]:
    """Concept with the canonical hand-built top-level ``characters`` field."""
    return {
        "slug": "the-quota",
        "logline": (
            "A public defender named Maya forces a corrupt judge to choose "
            "between her son's freedom and the truth she swore to defend."
        ),
        "characters": {
            "protagonist": {
                "name": "Maya",
                "want": "expose the judge",
                "need": "forgive her father's silence",
                "contradiction": "the system that protects her son is the one she must dismantle",
            },
            "antagonist": {
                "name": "Judge Reed",
                "belief": "law without mercy is the only law that survives",
                "method": "weaponize procedure to make injustice legal",
                "entity_type": "human",
            },
            "key_characters": [{"name": "Father", "function": "moral mirror"}],
        },
    }


@pytest.fixture
def prose_only_draft() -> dict[str, Any]:
    """Concept matching the real-world drafter output — prose under sections,
    no structured ``characters`` field. Mirrors the shape observed in
    ``runs/2026-05-19-133938-the-quota/draft_v0.json``."""
    return {
        "slug": "the-quota",
        "logline": (
            "A public defender discovers her own office is rigging her son's "
            "trial and must dismantle it before his verdict."
        ),
        "sections": {
            "protagonist": (
                "## Protagonist\n\n"
                "**Mara Voss** — A public defender whose belief in the system has always "
                "been the engine of her competence, and whose competence is now the only "
                "tool available to dismantle the system she believes in.\n\n"
                "She wants to save her son without burning down the institution she "
                "helped build. She needs to understand that those two things have "
                "always been incompatible — that her eighteen years of professional "
                "accommodation, however justified, helped construct the arrangement "
                "she is now trying to escape. The gap between what she wants and what "
                "she needs is the story."
            ),
            "antagonist": (
                "## Antagonist\n\n"
                "**The Office of the Public Defender** — not any individual administrator, "
                "but the institutional logic that has quietly decided a managed outcome "
                "rate is more sustainable than a fully adversarial defense system.\n\n"
                "The office optimises for survival: budget lines, political relationships, "
                "caseload ratios that keep the DA's office cooperative and the county "
                "board from cutting funding further."
            ),
            "key_characters": (
                "## Key Characters\n\n"
                "**Priya Nair** — Mara's closest colleague and Daniel's assigned defender, "
                "whose quiet competence makes her complicity in the quota not a betrayal "
                "but a tragedy.\n\n"
                "**Daniel Voss** — Mara's son, whose case functions as the moral test the "
                "film administers to every character."
            ),
        },
    }


@pytest.fixture
def quota_run_draft() -> dict[str, Any]:
    """Regression fixture: the literal draft_v0.json from the NB.10 first
    instrumented run. If this run dir is ever cleaned up, the test still
    passes via the in-repo fixture below; the in-repo fixture is the
    contract."""
    p = Path("runs/2026-05-19-133938-the-quota/draft_v0.json")
    if not p.exists():
        pytest.skip("NB.10 reference run not present (runs/ may have been cleaned)")
    return json.loads(p.read_text(encoding="utf-8"))


# ── resolve_characters: structured pass-through ──────────────────────────────


def test_resolve_returns_structured_dict_verbatim(structured_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(structured_draft)
    assert resolved is structured_draft["characters"], (
        "When structured characters has content, the resolver MUST return it verbatim "
        "(same object reference) so no information is silently dropped."
    )


def test_resolve_returns_empty_when_no_data() -> None:
    empty: dict[str, Any] = {}
    assert resolve_characters(empty) == {}


def test_resolve_returns_empty_when_neither_field_populated() -> None:
    no_data: dict[str, Any] = {"sections": {}, "characters": {}}
    assert resolve_characters(no_data) == {}


def test_resolve_respects_partial_structured_data() -> None:
    """If structured.protagonist.name is set, we trust the structured field
    even if other fields are missing — drafter intent is explicit."""
    draft: dict[str, Any] = {
        "characters": {"protagonist": {"name": "Maya"}},
        "sections": {"protagonist": "## Protagonist\n\n**Other Name** — wrong."},
    }
    resolved = resolve_characters(draft)
    assert resolved["protagonist"]["name"] == "Maya"


# ── resolve_characters: prose fallback ───────────────────────────────────────


def test_resolve_extracts_protagonist_name_from_prose(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    assert resolved["protagonist"]["name"] == "Mara Voss"


def test_resolve_extracts_protagonist_want_sentence(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    want = resolved["protagonist"]["want"]
    assert "wants" in want.lower()
    assert "save her son" in want


def test_resolve_extracts_protagonist_need_sentence(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    need = resolved["protagonist"]["need"]
    assert "needs" in need.lower()


def test_resolve_extracts_protagonist_contradiction(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    contradiction = resolved["protagonist"]["contradiction"]
    assert contradiction != ""  # cue fired somewhere


def test_resolve_extracts_antagonist_name_from_prose(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    assert resolved["antagonist"]["name"] == "The Office of the Public Defender"


def test_resolve_classifies_institution_entity_type(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    assert resolved["antagonist"]["entity_type"] == "institution"


def test_resolve_extracts_antagonist_method(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    method = resolved["antagonist"]["method"]
    assert "optimi" in method.lower()  # "optimises" or "optimizes"


def test_resolve_extracts_key_characters_with_functions(prose_only_draft: dict[str, Any]) -> None:
    resolved = resolve_characters(prose_only_draft)
    key_chars = resolved["key_characters"]
    assert len(key_chars) == 2
    names = {kc["name"] for kc in key_chars}
    assert names == {"Priya Nair", "Daniel Voss"}
    for kc in key_chars:
        assert kc["function"], f"key character {kc['name']} has no function text"


def test_resolve_handles_combined_characters_section() -> None:
    """When prose lives under ``sections.characters`` as one block (instead of
    split into protagonist/antagonist/key_characters fields), the resolver
    must still slice it by ``## Heading``."""
    combined: dict[str, Any] = {
        "sections": {
            "characters": (
                "## Protagonist\n\n"
                "**Sara Chen** — a logistics analyst. "
                "She wants to ship the truth. She needs to trust her instincts.\n\n"
                "## Antagonist\n\n"
                "**The Algorithm** — a recommendation system that decides who "
                "the workforce optimises around.\n\n"
                "## Key Characters\n\n"
                "**Sam** — her oldest friend and conscience anchor."
            )
        }
    }
    resolved = resolve_characters(combined)
    assert resolved["protagonist"]["name"] == "Sara Chen"
    assert resolved["antagonist"]["name"] == "The Algorithm"
    assert resolved["antagonist"]["entity_type"] == "technology"
    assert len(resolved["key_characters"]) == 1


def test_resolve_missing_cue_yields_empty_string() -> None:
    """Faithful absence: if the prose has no `wants` cue, ``want`` is empty.
    The axis must score zero for that signal — no fabrication."""
    draft: dict[str, Any] = {
        "sections": {
            "protagonist": (
                "## Protagonist\n\n**Solo** — operates alone, says little, never explains."
            )
        }
    }
    resolved = resolve_characters(draft)
    protag = resolved.get("protagonist") or {}
    assert protag.get("want") == ""
    assert protag.get("need") == ""


# ── character_depth: integration via resolver ────────────────────────────────


def test_character_depth_passes_threshold_on_prose_draft(
    prose_only_draft: dict[str, Any],
) -> None:
    s, ev = character_depth.score(prose_only_draft)
    assert s >= 0.50, (
        f"character_depth must pass the 0.50 threshold on real drafter prose; got {s}. "
        f"Signals fired: {ev['signals']}"
    )


def test_character_depth_no_regression_on_structured(
    structured_draft: dict[str, Any],
) -> None:
    """Hand-built structured fixtures must still score the same as before
    the prose fallback was introduced."""
    s, _ev = character_depth.score(structured_draft)
    assert s >= 0.50


def test_character_depth_score_zero_when_no_data() -> None:
    s, ev = character_depth.score({})
    assert s == 0.0
    assert ev["n_fired"] == 0


# ── agency_ratio: integration via resolver ───────────────────────────────────


def test_agency_ratio_passes_threshold_on_prose_draft(prose_only_draft: dict[str, Any]) -> None:
    s, _ev = agency_ratio.score(prose_only_draft)
    assert s >= 0.50, f"agency_ratio must pass the 0.50 threshold on real drafter prose; got {s}"


def test_agency_ratio_uses_extracted_protagonist_text(prose_only_draft: dict[str, Any]) -> None:
    """The active-verb count should be > 0 because the prose contains
    "dismantle" in the protagonist description."""
    _s, ev = agency_ratio.score(prose_only_draft)
    assert ev["active_count"] >= 1


# ── Regression: the actual Quota run ─────────────────────────────────────────


def test_quota_run_q2_pass(quota_run_draft: dict[str, Any]) -> None:
    """The literal Quota draft must score Q2 = PASS on both axes.

    This is the canonical NB.10 regression test: if a future change to the
    resolver, the axes, or the drafter contract breaks Q2 measurement on
    this run, this test catches it immediately.
    """
    cd_score, _cd_ev = character_depth.score(quota_run_draft)
    ar_score, _ar_ev = agency_ratio.score(quota_run_draft)
    assert cd_score >= 0.50, f"character_depth regression on Quota run: {cd_score}"
    assert ar_score >= 0.50, f"agency_ratio regression on Quota run: {ar_score}"
