"""Pydantic v2 schemas for all 5 Anomaly Engine pipeline phase outputs.

This module is the dependency graph root — openrouter_client.py, scoring.py,
and run.py all import from here.  It MUST NOT import from any other pipeline
module (ANOMALY-001, ANOMALY-002).

Phase output models:
    Phase1Assets      — asset-miner output (one row per untapped asset)
    Phase2JTBD        — jtbd-mapper output (one row per JTBD mapping)
    Phase3Audience    — audience-validator output (one row per audience profile)
    Phase4Concept     — concept-forger output (one row per generated concept)
    Phase5Critique    — critic output (one row per critique)

total_score protection (ADR-0002, PIPE-01):
    Every model carries ``total_score: Optional[float] = None``.
    The @model_validator(mode='before') on EACH model raises ValueError if the
    incoming data dict has a non-None total_score.  This prevents LLMs from
    populating the field.  scoring.py sets it afterward via:
        model.model_copy(update={'total_score': val})
    Pydantic v2 model_copy does NOT re-run validators — that bypass is
    intentional and documented in ADR-0002.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

# ── Named constants (avoids PLR2004 magic-number lint) ───────────────────────

SOURCE_QUOTE_MAX_WORDS: int = 14
NOVELTY_SCORE_MAX: int = 30
JTBD_SCORE_MAX: int = 25
CONTRADICTION_SCORE_MAX: int = 25
SPECIFICITY_SCORE_MAX: int = 20
COLLISION_MAX_WORDS: int = 30
ANTI_SLOP_SELF_CHECK_MAX_WORDS: int = 50
CLOSING_IMAGE_MAX_WORDS: int = 30  # V4A-003e — Section 13 of v4 14-section A4

# 10 cinema schools used by the Cinema-School Floor (KNOW-08).
# Order is canonical; the formatter zips this with ten_school_self_check.
TEN_SCHOOLS: list[str] = [
    "USC",
    "UCLA",
    "AFI",
    "NYU Tisch",
    "Columbia",
    "NFTS",
    "FAMU",
    "Lodz",
    "VGIK",
    "Beijing",
]

# 5 cross-checks emitted by the Adversarial Critic (PROMPT-05).
# Order is canonical; the formatter renders Section 11 (Critic Verdict).
CROSS_CHECK_KEYS: list[str] = [
    "no_anti_slop_violation",
    "seven_school_floor_met",
    "polti_tobias_coherent",
    "logline_word_count_ok",
    "triz_both_poles_held",
]

# ── Word-count helper ─────────────────────────────────────────────────────────


def _count_words(text: str) -> int:
    """Return number of whitespace-separated words in *text*."""
    return len(text.split())


# ── Shared total_score guard ──────────────────────────────────────────────────

# Pydantic v2 does not support mixin validators cleanly across BaseModel
# subclasses when using model_validator.  The guard is a standalone function
# referenced explicitly in each model's @model_validator(mode='before').


def _reject_llm_total_score(data: object) -> object:
    """Raise ValueError if incoming data has a non-None total_score.

    Called from each model's @model_validator(mode='before') to enforce
    ADR-0002: scoring.py is the only setter of total_score.
    """
    if not isinstance(data, dict):
        return data
    # pyright strict: dict[Unknown,Unknown] after isinstance — use type:ignore
    # only on the subscript lines; str() avoids the repr(Unknown) complaint.
    if "total_score" in data and data["total_score"] is not None:  # type: ignore[index]
        val_str: str = str(data["total_score"])  # type: ignore[index]
        raise ValueError(
            "total_score MUST be None in LLM output — "
            "pipeline/scoring.py is the only setter (ADR-0002). "
            "Got: " + val_str
        )
    return data  # type: ignore[return-value]


# ── Phase 1: Asset Miner ──────────────────────────────────────────────────────


class Phase1Assets(BaseModel):
    """Output of the asset-miner agent (Phase 1).

    One row per discovered untapped cultural/historical asset.
    """

    asset_id: str
    asset_name: str
    domain: str
    theme: str
    source_url: str
    source_quote: str  # <= SOURCE_QUOTE_MAX_WORDS words — validated below
    untapped_check_passed: bool
    produced_at: str
    session_id: str
    total_score: float | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_llm_total_score(cls, data: object) -> object:
        return _reject_llm_total_score(data)

    @field_validator("source_quote")
    @classmethod
    def validate_quote_length(cls, v: str) -> str:
        wc = _count_words(v)
        if wc > SOURCE_QUOTE_MAX_WORDS:
            raise ValueError(f"source_quote must be <=14 words; got {wc}: {v!r}")
        return v


# ── Phase 2: JTBD Mapper ──────────────────────────────────────────────────────


class Phase2JTBD(BaseModel):
    """Output of the jtbd-mapper agent (Phase 2).

    One row per JTBD (Jobs-to-be-Done) mapping for an asset.
    """

    asset_id: str
    job_statement: str
    primary_need: Literal["autonomy", "competence", "relatedness"]
    primary_strength: float  # [0.0, 1.0] — validated below
    secondary_need: str | None = None
    secondary_strength: float = 0.0  # [0.0, 1.0] — validated below
    deprivation_amplifier_active: bool
    jtbd_notes: str = ""
    total_score: float | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_llm_total_score(cls, data: object) -> object:
        return _reject_llm_total_score(data)

    @field_validator("primary_strength")
    @classmethod
    def validate_primary_strength(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"primary_strength must be in [0.0, 1.0]; got {v}")
        return v

    @field_validator("secondary_strength")
    @classmethod
    def validate_secondary_strength(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"secondary_strength must be in [0.0, 1.0]; got {v}")
        return v


# ── Phase 3: Audience Validator ───────────────────────────────────────────────

_ISO2_RE = re.compile(r"^[A-Z]{2}$")


class Phase3Audience(BaseModel):
    """Output of the audience-validator agent (Phase 3).

    One row per validated audience profile.
    """

    asset_id: str
    target_countries: list[str]  # ISO 3166-1 alpha-2 — validated below
    cited_audience: int
    sources_per_claim: int
    trend_direction: Literal["rising", "stable", "declining"]
    primary_jtbd_strength: float
    source_quote: str  # <= SOURCE_QUOTE_MAX_WORDS words — validated below
    produced_at: str
    session_id: str
    total_score: float | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_llm_total_score(cls, data: object) -> object:
        return _reject_llm_total_score(data)

    @field_validator("target_countries", mode="before")
    @classmethod
    def validate_iso2_countries(cls, v: list[str]) -> list[str]:
        for code in v:
            if not _ISO2_RE.match(str(code)):
                raise ValueError(
                    f"target_countries must be ISO2 codes (2 uppercase letters); got {code!r}"
                )
        return v

    @field_validator("source_quote")
    @classmethod
    def validate_quote_length(cls, v: str) -> str:
        wc = _count_words(v)
        if wc > SOURCE_QUOTE_MAX_WORDS:
            raise ValueError(f"source_quote must be <=14 words; got {wc}: {v!r}")
        return v


# ── Phase 4: Concept Forger ───────────────────────────────────────────────────


class Phase4Concept(BaseModel):
    """Output of the concept-forger agent (Phase 4).

    One row per generated high-concept film/TV idea.

    Rich fields (booker_plot_id, stc_genre_id, truby_archetype_id,
    triz_contradiction_id, irreversibility_pattern_id, archetype_id,
    sdt_primary_need, collision_contradiction, key_roles,
    ten_school_self_check, anti_slop_self_check) are Optional for
    backward compatibility with older fixtures. New runs through the
    refactored forger populate them; legacy fixtures degrade to None.
    Section 9 / 10 / 11 of the 12-section A4 use these directly.

    v4 fields (mutation_provenance, closing_image; added 2026-05-10 per
    V4A-003e) drive the 14-section A4 bifurcation in
    `prompts/06-a4-formatter.md`: when both are None the formatter renders
    the v3 12-section schema (Score at position 12); when either is
    populated the formatter renders 14 sections (12 = Mutation Provenance,
    13 = Closing Image, 14 = Score). Backward-compat: 1067 v3.1 outputs
    keep both null and continue producing 12-section docs untouched.
    """

    # Core fields (required since v0)
    concept_id: str
    title: str
    logline: str
    polti_id: int
    tobias_id: int
    seed_used: int
    seed_increments: int = 0
    forge_meta: dict[str, Any]  # model name, K, token counts, etc.
    produced_at: str
    session_id: str
    total_score: float | None = None

    # Rich fields for the 12-section A4 (added 2026-05-08; all Optional).
    booker_plot_id: int | None = None  # 1..7
    stc_genre_id: int | None = None  # 1..10
    truby_archetype_id: int | None = None  # 1..4
    triz_contradiction_id: int | None = None  # 1..12
    irreversibility_pattern_id: int | None = None  # 1..12
    archetype_id: int | None = None  # 0..11 (Pearson)
    sdt_primary_need: Literal["autonomy", "competence", "relatedness"] | None = None
    collision_contradiction: str | None = None  # ≤30 words; both TRIZ poles named
    key_roles: dict[str, str | None] | None = None  # protagonist/antagonist/ally/mentor
    ten_school_self_check: dict[str, bool] | None = None  # forger's own 10-school check
    anti_slop_self_check: str | None = None  # ≤50 words; pattern subverted or "none triggered"

    # v4 fields for the 14-section A4 (added 2026-05-10 per V4A-003e; both Optional).
    # When BOTH are None, the v4 formatter renders 12 sections (v3 backward-compat).
    # When EITHER is populated, the v4 formatter renders 14 sections.
    mutation_provenance: dict[str, Any] | None = (
        None  # {op, parents, intruder_asset_id?, transpose_to?}
    )
    closing_image: str | None = None  # ≤30 words; the final visual beat

    @model_validator(mode="before")
    @classmethod
    def reject_llm_total_score(cls, data: object) -> object:
        return _reject_llm_total_score(data)

    @field_validator("collision_contradiction")
    @classmethod
    def validate_collision_word_count(cls, v: str | None) -> str | None:
        if v is None:
            return v
        wc = _count_words(v)
        if wc > COLLISION_MAX_WORDS:
            raise ValueError(
                f"collision_contradiction must be ≤{COLLISION_MAX_WORDS} words; got {wc}: {v!r}"
            )
        return v

    @field_validator("anti_slop_self_check")
    @classmethod
    def validate_anti_slop_word_count(cls, v: str | None) -> str | None:
        if v is None:
            return v
        wc = _count_words(v)
        if wc > ANTI_SLOP_SELF_CHECK_MAX_WORDS:
            raise ValueError(
                f"anti_slop_self_check must be ≤{ANTI_SLOP_SELF_CHECK_MAX_WORDS} words; got {wc}"
            )
        return v

    @field_validator("closing_image")
    @classmethod
    def validate_closing_image_word_count(cls, v: str | None) -> str | None:
        """v4 14-section: closing_image is the final visual beat, ≤30 words."""
        if v is None:
            return v
        wc = _count_words(v)
        if wc > CLOSING_IMAGE_MAX_WORDS:
            raise ValueError(
                f"closing_image must be ≤{CLOSING_IMAGE_MAX_WORDS} words; got {wc}: {v!r}"
            )
        return v

    @field_validator("mutation_provenance")
    @classmethod
    def validate_mutation_provenance_op(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """v4 14-section: mutation_provenance.op MUST be one of the 6 canonical
        operator labels (mirrors evals/test_mutation_doctrine_preserved.py)."""
        if v is None:
            return v
        canonical = {"SWAP", "CROSSOVER", "INVERT", "INTRUSION", "TRANSPOSE", "DISTILL"}
        op = v.get("op")
        if op not in canonical:
            raise ValueError(f"mutation_provenance.op must be in {sorted(canonical)}; got {op!r}")
        parents = v.get("parents")
        if not isinstance(parents, list | tuple) or not parents:
            raise ValueError(
                f"mutation_provenance.parents must be a non-empty list/tuple; got {parents!r}"
            )
        return v


# ── Phase 5: Critic ───────────────────────────────────────────────────────────


class Phase5Critique(BaseModel):
    """Output of the critic agent (Phase 5).

    One row per critique of a concept.  total_score is ALWAYS None from the
    LLM — scoring.py computes it afterward via model_copy(update={...}).
    """

    concept_id: str
    novelty_score: int  # 0..NOVELTY_SCORE_MAX
    jtbd_score: int  # 0..JTBD_SCORE_MAX
    contradiction_score: int  # 0..CONTRADICTION_SCORE_MAX
    specificity_score: int  # 0..SPECIFICITY_SCORE_MAX
    cap_at_70_triggered: bool = False
    ten_school_self_check: list[bool]
    cross_checks: dict[str, bool] | None = None  # 5-check dict (CROSS_CHECK_KEYS); rendered in §11
    axis_rationales: dict[str, str] | None = None  # per-axis "why" for §11 4-row table
    investment_readiness: Literal["PASS", "REVISE", "FAIL"] | None = None  # for §11 footer
    stabilization_pattern_to_add_to_anti_slop: str | None = None
    total_score: float | None = None  # set by scoring.py only (ADR-0002)

    @model_validator(mode="before")
    @classmethod
    def reject_llm_total_score(cls, data: object) -> object:
        """Enforce ADR-0002: total_score MUST be None in any LLM output."""
        return _reject_llm_total_score(data)

    @field_validator("novelty_score")
    @classmethod
    def validate_novelty_score(cls, v: int) -> int:
        if not (0 <= v <= NOVELTY_SCORE_MAX):
            raise ValueError(f"novelty_score must be in [0, {NOVELTY_SCORE_MAX}]; got {v}")
        return v

    @field_validator("jtbd_score")
    @classmethod
    def validate_jtbd_score(cls, v: int) -> int:
        if not (0 <= v <= JTBD_SCORE_MAX):
            raise ValueError(f"jtbd_score must be in [0, {JTBD_SCORE_MAX}]; got {v}")
        return v

    @field_validator("contradiction_score")
    @classmethod
    def validate_contradiction_score(cls, v: int) -> int:
        if not (0 <= v <= CONTRADICTION_SCORE_MAX):
            raise ValueError(
                f"contradiction_score must be in [0, {CONTRADICTION_SCORE_MAX}]; got {v}"
            )
        return v

    @field_validator("specificity_score")
    @classmethod
    def validate_specificity_score(cls, v: int) -> int:
        if not (0 <= v <= SPECIFICITY_SCORE_MAX):
            raise ValueError(f"specificity_score must be in [0, {SPECIFICITY_SCORE_MAX}]; got {v}")
        return v
