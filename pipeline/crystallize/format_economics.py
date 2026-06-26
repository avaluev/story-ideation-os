"""pipeline.crystallize.format_economics — per-format SOM/SAM/TAM constants.

Single home for the NAMED, SOURCED economic constants that let
:mod:`pipeline.crystallize.revenue` project a credible, python-executed
Year-1 SOM for each content FORMAT (ADR-0011). Feature & animation feature
keep the existing theatrical comps math (this module only supplies their
TAM-segment + lifetime context); the streaming-license formats
(limited / returning / animation series) and microdrama use their own
monetization models because box-office comps do not price them.

Credibility invariant (enforced by tests + evals/test_som_credibility_bounds):
for every format ``0 < SOM_y1 < SAM < TAM``. SOM is the realistic single-
title Year-1 capture; SAM the serviceable category slice; TAM the global
format market.

Deep-link evidence policy: every market/revenue constant carries a
deep-path source_url in :data:`CONSTANT_SOURCES`. Low-confidence /
operator-judgment knobs (cancellation haircut, ancillary multiple, SAM
slice fractions, score-facet log bounds) carry ``""`` (a documented data
gap) — NEVER a fabricated or bare-domain URL.

Pure Python — no LLM, no network, no numpy. ADR-0002 + ADR-0011.
Subject to the ANOMALY-001 LLM-client import ban (see scripts/lint_imports.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# Sourced market + cost constants (deep-link URLs in CONSTANT_SOURCES)
# ---------------------------------------------------------------------------

# -- Theatrical (feature + animation feature) --
#: Multi-window lifetime multiple on Year-1 theatrical SOM (UNC/McCourt 2017:
#: US home-ent $20.49B / theatrical $10.51B = 1.95x, + 1.0 theatrical = 2.95x).
LIFETIME_MULTIPLE_FEATURE: Final[float] = 2.95
#: Global theatrical box office (2024) — narrative CONTEXT stat, not the TAM line.
FEATURE_THEATRICAL_BOXOFFICE_USD: Final[float] = 30_000_000_000.0
#: Total global content market (theatrical + home/mobile entertainment + pay TV),
#: per the MPA THEME Report — "$328.2 billion ... a six percent increase, matching
#: 2019's record high." Re-sourced 2026-05-30 after the veracity layer caught the
#: prior $152B citing a now-404 MPA-2023 URL; the MPA-2021 report is live + states
#: this figure verbatim, so it is the larger, directly-sourced TAM (excl. pay TV
#: the same report states $99.7B). Matches revenue.DEFAULT_TAM_USD.
FEATURE_TAM_USD: Final[float] = 328_200_000_000.0
#: Animated-feature budget->WW-gross multiple band (base/mid/opt).
ANIM_FEATURE_MULTIPLE_BASE: Final[float] = 4.3  # The Wild Robot $334.5M / $78M
ANIM_FEATURE_MULTIPLE_MID: Final[float] = 6.9  # Across the Spider-Verse $690.5M / $100M
ANIM_FEATURE_MULTIPLE_OPT: Final[float] = 8.5  # Inside Out 2 $1.699B / $200M
#: Representative animated-feature negative cost for the documented anchor.
ANIM_FEATURE_DEFAULT_BUDGET_USD: Final[float] = 90_000_000.0
#: Representative top-quartile original feature Year-1 theatrical SOM (invariant ref).
FEATURE_REFERENCE_SOM_USD: Final[float] = 250_000_000.0

# -- Streaming license (limited / returning / animation series) --
COST_PER_EP_BASE_USD: Final[float] = 10_000_000.0  # The Last of Us ~$10M/ep
COST_PLUS_MARKUP_BASE: Final[float] = 0.30  # Netflix cost-plus license markup
LIMITED_SERIES_EP_COUNT: Final[int] = 8  # Wednesday / typical limited
RETURNING_SERIES_EP_COUNT: Final[int] = 9
SEASON_COUNT_FACTOR: Final[float] = 2.5  # premium dramas average ~2-3 seasons
CANCELLATION_HAIRCUT: Final[float] = 0.6  # data_gap: operator-judgment renewal risk
SVOD_SUBSCRIPTION_TAM_USD: Final[float] = 157_100_000_000.0  # Ampere 2025
SVOD_SUB_AD_TAM_USD: Final[float] = 177_000_000_000.0  # subscription + ad-tier 2025
#: Animation series: per-episode license RECOUP (Arcane ~$6M/ep recoup on $13.9M cost).
ANIM_SERIES_LICENSE_RECOUP_PER_EP_USD: Final[float] = 6_000_000.0
ANIM_SERIES_EP_COUNT: Final[int] = 9
ANIM_SERIES_ANCILLARY_MULTIPLE: Final[float] = 1.5  # data_gap: merch/games/IP uplift [estimated]
ANIM_SERIES_LICENSE_ONLY_RETURN: Final[float] = 0.43  # Arcane recouped <50% on license alone
ANIME_LICENSING_TAM_USD: Final[float] = 17_450_000_000.0  # anime licensing 2025

# -- Microdrama / vertical short-form --
MICRODRAMA_TAM_GLOBAL_USD: Final[float] = 8_400_000_000.0  # whole-format global 2024
MICRODRAMA_TAM_EX_CHINA_USD: Final[float] = 1_400_000_000.0  # serviceable ex-China 2024
MICRODRAMA_SOM_SHARE: Final[float] = 0.01  # single-title/slate share of ex-China serviceable
MICRODRAMA_NET_MARGIN: Final[float] = 0.03  # DramaBox ~3% net (heavy paid UA)

# -- SAM slice fractions (serviceable category share; operator-judgment) --
_SAM_SLICE_THEATRICAL: Final[float] = 0.12  # genre/language serviceable slice (data_gap)
_SAM_SLICE_LICENSE: Final[float] = 0.02  # English premium-scripted slice of SVOD (data_gap)
_SAM_SLICE_ANIM_SERIES: Final[float] = 0.05  # serviceable anime-licensing slice (data_gap)

# -- Per-format SOM log bounds for the score facet (calibration, not market) --
SOM_LOG_FLOOR_THEATRICAL_USD: Final[float] = 50_000_000.0
SOM_LOG_CEILING_THEATRICAL_USD: Final[float] = 1_500_000_000.0
SOM_LOG_FLOOR_LICENSE_USD: Final[float] = 20_000_000.0
SOM_LOG_CEILING_LICENSE_USD: Final[float] = 500_000_000.0
SOM_LOG_FLOOR_MICRODRAMA_USD: Final[float] = 5_000_000.0
SOM_LOG_CEILING_MICRODRAMA_USD: Final[float] = 200_000_000.0


# ---------------------------------------------------------------------------
# Source registry (deep-link evidence policy — "" == documented data gap)
# ---------------------------------------------------------------------------

CONSTANT_SOURCES: Final[dict[str, str]] = {
    "LIFETIME_MULTIPLE_FEATURE": "https://cdr.lib.unc.edu/downloads/cf95jg84k",
    "FEATURE_THEATRICAL_BOXOFFICE_USD": "https://www.gower.st/articles/sparkling-december-finishes-2024-high-3bn-global-box-office-2024-total-30bn/",
    "FEATURE_TAM_USD": "https://www.motionpictures.org/wp-content/uploads/2022/03/MPA-2021-THEME-Report-FINAL.pdf",
    "ANIM_FEATURE_MULTIPLE_BASE": "https://www.boxofficemojo.com/title/tt29623480/",
    "ANIM_FEATURE_MULTIPLE_MID": "https://www.boxofficemojo.com/release/rl2812183041/",
    "ANIM_FEATURE_MULTIPLE_OPT": "https://www.boxofficemojo.com/title/tt22022452/",
    "ANIM_FEATURE_DEFAULT_BUDGET_USD": "https://www.boxofficemojo.com/title/tt29623480/",
    "COST_PER_EP_BASE_USD": "https://collider.com/the-last-of-us-hbo-series-budget-revealed/",
    "COST_PLUS_MARKUP_BASE": "https://www.fool.com/investing/2018/05/20/look-how-much-netflix-saves-by-producing-its-own-o.aspx",
    "LIMITED_SERIES_EP_COUNT": "https://en.wikipedia.org/wiki/Wednesday_(TV_series)",
    "RETURNING_SERIES_EP_COUNT": "https://en.wikipedia.org/wiki/List_of_most_expensive_television_series",
    "SEASON_COUNT_FACTOR": "https://en.wikipedia.org/wiki/List_of_most_expensive_television_series",
    "CANCELLATION_HAIRCUT": "",  # data_gap: operator-judgment renewal risk
    "SVOD_SUBSCRIPTION_TAM_USD": "https://www.mediaplaynews.com/ampere-global-streaming-subscription-revenue-topped-150-billion-in-2025/",
    # data_gap: combined sub+ad $177B not in the cited source; unused as a headline.
    "SVOD_SUB_AD_TAM_USD": "",
    "ANIM_SERIES_LICENSE_RECOUP_PER_EP_USD": "https://variety.com/2024/biz/news/riot-games-arcane-hollywood-netflix-most-expensive-animated-series-ever-1236196655/",
    "ANIM_SERIES_LICENSE_ONLY_RETURN": "https://variety.com/2024/biz/news/riot-games-arcane-hollywood-netflix-most-expensive-animated-series-ever-1236196655/",
    "ANIM_SERIES_ANCILLARY_MULTIPLE": "",  # data_gap: [estimated] merch/games/IP uplift
    # data_gap: Grand View landing page is a paywall, not a deep-path primary;
    # $17.45B anime-licensing figure is operator-judgment pending a free primary.
    "ANIME_LICENSING_TAM_USD": "",
    "MICRODRAMA_TAM_GLOBAL_USD": "https://variety.com/2025/digital/news/microdrama-apps-revenue-reelshort-dramabox-1236521194/",
    "MICRODRAMA_TAM_EX_CHINA_USD": "https://variety.com/2025/digital/news/microdrama-apps-revenue-reelshort-dramabox-1236521194/",
    "MICRODRAMA_SOM_SHARE": "",  # data_gap: single-title serviceable-share assumption
    "MICRODRAMA_NET_MARGIN": "https://variety.com/2025/digital/news/microdrama-apps-revenue-reelshort-dramabox-1236521194/",
    "_SAM_SLICE_THEATRICAL": "",  # data_gap: serviceable genre/language slice
    "_SAM_SLICE_LICENSE": "",  # data_gap
    "_SAM_SLICE_ANIM_SERIES": "",  # data_gap
}


# ---------------------------------------------------------------------------
# FormatProfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormatProfile:
    """Per-format economic profile. Fields not relevant to a model carry 0.0."""

    format_id: str
    display_name: str
    monetization_model: str  # "theatrical" | "license" | "microdrama"
    default_window: str
    tam_segment_usd: float
    tam_source_url: str
    sam_usd: float
    som_log_floor_usd: float
    som_log_ceiling_usd: float
    lifetime_multiple: float = 1.0
    # license-model fields
    ep_count: int = 0
    cost_per_ep_usd: float = 0.0
    cost_plus_markup: float = 0.0
    season_count_factor: float = 1.0
    cancellation_haircut: float = 1.0
    ancillary_multiple: float = 1.0
    # theatrical / microdrama reference
    default_budget_usd: float = 0.0
    budget_multiple_base: float = 0.0
    reference_som_usd: float = 0.0
    som_share: float = 0.0


FORMAT_PROFILES: Final[dict[str, FormatProfile]] = {
    "feature": FormatProfile(
        format_id="feature",
        display_name="Feature Film",
        monetization_model="theatrical",
        default_window="theatrical_wide",
        tam_segment_usd=FEATURE_TAM_USD,
        tam_source_url=CONSTANT_SOURCES["FEATURE_TAM_USD"],
        sam_usd=FEATURE_TAM_USD * _SAM_SLICE_THEATRICAL,
        som_log_floor_usd=SOM_LOG_FLOOR_THEATRICAL_USD,
        som_log_ceiling_usd=SOM_LOG_CEILING_THEATRICAL_USD,
        lifetime_multiple=LIFETIME_MULTIPLE_FEATURE,
        reference_som_usd=FEATURE_REFERENCE_SOM_USD,
    ),
    "animation_feature": FormatProfile(
        format_id="animation_feature",
        display_name="Animation Feature",
        monetization_model="theatrical",
        default_window="theatrical_wide",
        tam_segment_usd=FEATURE_TAM_USD,
        tam_source_url=CONSTANT_SOURCES["FEATURE_TAM_USD"],
        sam_usd=FEATURE_TAM_USD * _SAM_SLICE_THEATRICAL,
        som_log_floor_usd=SOM_LOG_FLOOR_THEATRICAL_USD,
        som_log_ceiling_usd=SOM_LOG_CEILING_THEATRICAL_USD,
        lifetime_multiple=LIFETIME_MULTIPLE_FEATURE,
        default_budget_usd=ANIM_FEATURE_DEFAULT_BUDGET_USD,
        budget_multiple_base=ANIM_FEATURE_MULTIPLE_BASE,
        reference_som_usd=ANIM_FEATURE_DEFAULT_BUDGET_USD * ANIM_FEATURE_MULTIPLE_BASE,
    ),
    "limited_series": FormatProfile(
        format_id="limited_series",
        display_name="Limited Series",
        monetization_model="license",
        default_window="streaming_first",
        tam_segment_usd=SVOD_SUBSCRIPTION_TAM_USD,
        tam_source_url=CONSTANT_SOURCES["SVOD_SUBSCRIPTION_TAM_USD"],
        sam_usd=SVOD_SUBSCRIPTION_TAM_USD * _SAM_SLICE_LICENSE,
        som_log_floor_usd=SOM_LOG_FLOOR_LICENSE_USD,
        som_log_ceiling_usd=SOM_LOG_CEILING_LICENSE_USD,
        ep_count=LIMITED_SERIES_EP_COUNT,
        cost_per_ep_usd=COST_PER_EP_BASE_USD,
        cost_plus_markup=COST_PLUS_MARKUP_BASE,
        season_count_factor=1.0,
        cancellation_haircut=1.0,
    ),
    "returning_series": FormatProfile(
        format_id="returning_series",
        display_name="Returning Series",
        monetization_model="license",
        default_window="streaming_first",
        # Same well-sourced SVOD subscription TAM as limited series (the
        # combined sub+ad $177B figure was not supported by the cited source).
        tam_segment_usd=SVOD_SUBSCRIPTION_TAM_USD,
        tam_source_url=CONSTANT_SOURCES["SVOD_SUBSCRIPTION_TAM_USD"],
        sam_usd=SVOD_SUBSCRIPTION_TAM_USD * _SAM_SLICE_LICENSE,
        som_log_floor_usd=SOM_LOG_FLOOR_LICENSE_USD,
        som_log_ceiling_usd=SOM_LOG_CEILING_LICENSE_USD,
        ep_count=RETURNING_SERIES_EP_COUNT,
        cost_per_ep_usd=COST_PER_EP_BASE_USD,
        cost_plus_markup=COST_PLUS_MARKUP_BASE,
        season_count_factor=SEASON_COUNT_FACTOR,
        cancellation_haircut=CANCELLATION_HAIRCUT,
    ),
    "animation_series": FormatProfile(
        format_id="animation_series",
        display_name="Animation Series",
        monetization_model="license",
        default_window="streaming_first",
        tam_segment_usd=ANIME_LICENSING_TAM_USD,
        tam_source_url=CONSTANT_SOURCES["ANIME_LICENSING_TAM_USD"],
        sam_usd=ANIME_LICENSING_TAM_USD * _SAM_SLICE_ANIM_SERIES,
        som_log_floor_usd=SOM_LOG_FLOOR_LICENSE_USD,
        som_log_ceiling_usd=SOM_LOG_CEILING_LICENSE_USD,
        ep_count=ANIM_SERIES_EP_COUNT,
        cost_per_ep_usd=ANIM_SERIES_LICENSE_RECOUP_PER_EP_USD,
        cost_plus_markup=0.0,
        season_count_factor=1.0,
        cancellation_haircut=1.0,
        ancillary_multiple=ANIM_SERIES_ANCILLARY_MULTIPLE,
    ),
    "microdrama": FormatProfile(
        format_id="microdrama",
        display_name="Microdrama",
        monetization_model="microdrama",
        default_window="streaming_first",
        tam_segment_usd=MICRODRAMA_TAM_GLOBAL_USD,
        tam_source_url=CONSTANT_SOURCES["MICRODRAMA_TAM_GLOBAL_USD"],
        sam_usd=MICRODRAMA_TAM_EX_CHINA_USD,
        som_log_floor_usd=SOM_LOG_FLOOR_MICRODRAMA_USD,
        som_log_ceiling_usd=SOM_LOG_CEILING_MICRODRAMA_USD,
        lifetime_multiple=1.0,
        som_share=MICRODRAMA_SOM_SHARE,
    ),
}

VALID_FORMATS: Final[tuple[str, ...]] = tuple(FORMAT_PROFILES.keys())

#: Display-name / alias -> canonical format_id (case-insensitive lookups).
_ALIASES: Final[dict[str, str]] = {
    "feature film": "feature",
    "feature": "feature",
    "cinema": "feature",
    "film": "feature",
    "limited series": "limited_series",
    "limited_series": "limited_series",
    "miniseries": "limited_series",
    "returning series": "returning_series",
    "returning_series": "returning_series",
    "tv series": "returning_series",
    "tv show": "returning_series",
    "series": "returning_series",
    "animation feature": "animation_feature",
    "animation_feature": "animation_feature",
    "animated feature": "animation_feature",
    "animation series": "animation_series",
    "animation_series": "animation_series",
    "animated series": "animation_series",
    "microdrama": "microdrama",
    "micro drama": "microdrama",
    "vertical": "microdrama",
    "short_form": "microdrama",
}


# ---------------------------------------------------------------------------
# Pure helpers (all python_executed — ADR-0011)
# ---------------------------------------------------------------------------


def normalize_format(fmt: str | None) -> str:
    """Resolve a display name / id / alias to a canonical format_id.

    Unknown / None falls back to ``"feature"`` (the safest, theatrical-comps
    default that preserves legacy behaviour)."""
    if not fmt:
        return "feature"
    key = str(fmt).strip().lower()
    if key in FORMAT_PROFILES:
        return key
    return _ALIASES.get(key, "feature")


def get_profile(fmt: str | None) -> FormatProfile:
    """Return the :class:`FormatProfile` for ``fmt`` (feature-default)."""
    return FORMAT_PROFILES[normalize_format(fmt)]


def license_fee_usd(profile: FormatProfile) -> float:
    """Year-1 cost-plus license fee = ep_count x cost_per_ep x (1 + markup)."""
    return profile.ep_count * profile.cost_per_ep_usd * (1.0 + profile.cost_plus_markup)


def lifetime_license_usd(profile: FormatProfile) -> float:
    """Multi-season lifetime license = license_fee x seasons x cancellation haircut
    x ancillary multiple (1.0 for non-animation license formats)."""
    return (
        license_fee_usd(profile)
        * profile.season_count_factor
        * profile.cancellation_haircut
        * profile.ancillary_multiple
    )


def anim_feature_anchor_usd(profile: FormatProfile) -> float:
    """Documented animated-feature anchor = default budget x base WW multiple."""
    return profile.default_budget_usd * profile.budget_multiple_base


def microdrama_som_usd(profile: FormatProfile) -> float:
    """Year-1 microdrama SOM = serviceable-share x ex-China serviceable SAM."""
    return profile.som_share * profile.sam_usd


def reference_som_usd(profile: FormatProfile) -> float:
    """A representative single-title Year-1 SOM for the SOM<SAM<TAM invariant.

    Theatrical uses the stored reference; license uses the computed fee;
    microdrama uses the share-of-SAM figure."""
    if profile.monetization_model == "license":
        return license_fee_usd(profile)
    if profile.monetization_model == "microdrama":
        return microdrama_som_usd(profile)
    return profile.reference_som_usd


def serviceable_sam_usd(profile: FormatProfile) -> float:
    """Serviceable addressable market (category slice) for the format."""
    return profile.sam_usd


def lifetime_from_y1(som_y1_usd: float, profile: FormatProfile) -> float:
    """Project a credible multi-window LIFETIME figure from the actual Year-1 SOM.

    Theatrical/microdrama scale by ``lifetime_multiple``; streaming-license
    formats scale by seasons x cancellation-haircut x ancillary. Every
    multiplier is >= 1.0 in aggregate, so lifetime >= Year-1 always."""
    if profile.monetization_model == "license":
        return (
            som_y1_usd
            * profile.season_count_factor
            * profile.cancellation_haircut
            * profile.ancillary_multiple
        )
    return som_y1_usd * profile.lifetime_multiple


def som_log_bounds(fmt: str | None) -> tuple[float, float]:
    """Per-format (floor, ceiling) USD bounds for the log-scaled SOM score facet."""
    p = get_profile(fmt)
    return (p.som_log_floor_usd, p.som_log_ceiling_usd)


__all__ = [
    "CONSTANT_SOURCES",
    "FORMAT_PROFILES",
    "VALID_FORMATS",
    "FormatProfile",
    "anim_feature_anchor_usd",
    "get_profile",
    "license_fee_usd",
    "lifetime_from_y1",
    "lifetime_license_usd",
    "microdrama_som_usd",
    "normalize_format",
    "reference_som_usd",
    "serviceable_sam_usd",
    "som_log_bounds",
]
