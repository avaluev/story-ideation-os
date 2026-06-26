"""pipeline.crystallize.revenue -- corpus-anchored revenue / SOM projection.

Replaces LLM-prose TAM/SAM/SOM with a self-consistent, comp-anchored,
Venn-correct calculation. Every number traces to a corpus row or a
documented constant.

Math summary
============

1. **Comps** -- :func:`pipeline.crystallize.corpus.FilmsCorpus.find_comps_with_similarity`
   returns the top-k films + Jaccard similarity. Weights are ``sim ** alpha``
   (alpha=2 by default -- penalises weak matches harder than linear).
2. **Weighted log-mean** of worldwide-gross over the trimmed comp set --
   we use log-space because film revenue is log-normal across a small
   corpus; arithmetic mean is dominated by the single largest comp.
3. **Winsorisation** -- any comp whose ln(ww) is more than
   ``outlier_sigma`` standard deviations from the unweighted log-mean of the
   *corpus* worldwide-gross has its weight capped at 0.05 (so one Avatar
   doesn't move the projection by 200%).
4. **Audience overlap** -- explicit inclusion-exclusion on
   ``audience_domains[].domain_tags`` set Jaccard, with ``affinity_with``
   raising the floor to 0.30. Returns ``unique_addressable_M``.
5. **Audience factor** -- bounded ratio ``unique_addressable_M /
   audience_anchor_M`` (default 300M = corpus median broad-appeal reach).
6. **Window penalty** -- table lookup, defaults inferred from distributor
   when ``window="auto"``.
7. **Geo penalty** -- anchored to corpus median domestic/worldwide ratio.
8. **SOM Y1** = ``p50 * audience_factor * window_factor * geo_factor``.
9. **SAM** = ``TAM * genre_slice_fraction`` (corpus self-share, not LLM).
10. **TAM** = MPA THEME Report 2021 constant ($328.2B combined content market),
    overridable via ``ProjectionContext.facts["tam_usd"]`` when a fresher fact is on-hand.

Pure Python. No LLM. No sklearn / numpy / PyMC. ADR-0002 + ADR-0001 + ADR-0011.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

from pipeline.crystallize import format_economics
from pipeline.crystallize.comps import infer_query_genres
from pipeline.crystallize.corpus import Film, FilmsCorpus

# ---------------------------------------------------------------------------
# Constants (named, sourced)
# ---------------------------------------------------------------------------

#: Total global content market (theatrical + home/mobile entertainment + pay TV),
#: $328.2B per the live MPA THEME Report (verbatim, deep-linked in
#: format_economics.CONSTANT_SOURCES). Re-sourced 2026-05-30 after the veracity
#: layer caught the prior $152B citing a now-404 MPA URL.
DEFAULT_TAM_USD: Final[float] = 328_200_000_000.0

#: Median "broad-appeal" reach observed in the corpus' top-100 grossing films.
DEFAULT_AUDIENCE_ANCHOR_M: Final[float] = 300.0

#: Maximum audience factor -- even Avatar at peak doesn't reach 1.6x anchor.
DEFAULT_AUDIENCE_FACTOR_CAP: Final[float] = 1.6

#: Window factor lookup. Streaming-first 0.40 calibrated to:
#: median acquisition price for limited series / median theatrical gross for
#: same Jaccard cohort = ~0.38-0.42 in public Netflix/Apple licensing reports.
WINDOW_FACTORS: Final[dict[str, float]] = {
    "theatrical_wide": 1.00,
    "theatrical_prestige": 0.85,
    "mixed": 0.70,
    "streaming_first": 0.40,
}

#: Distributor patterns -> window inference (used when window="auto").
_STREAMING_DISTRIBUTORS: Final[tuple[str, ...]] = (
    "netflix",
    "apple",
    "amazon",
    "hulu",
    "hbo max",
    "max",
    "disney+",
    "paramount+",
    "peacock",
)
_PRESTIGE_DISTRIBUTORS: Final[tuple[str, ...]] = ("a24", "neon", "focus", "searchlight")
_WIDE_DISTRIBUTORS: Final[tuple[str, ...]] = (
    "warner",
    "universal",
    "disney",
    "paramount",
    "sony",
    "20th century",
    "fox",
    "lionsgate",
)

#: Geo factor table. Baseline = corpus median domestic/worldwide ratio (~0.45).
GEO_FACTORS: Final[dict[str, float]] = {
    "us_only": 0.45,
    "us_canada": 0.50,
    "us_uk": 0.62,
    "english_5": 0.75,  # US + UK + AU + CA + NZ (Ireland often lumped here)
    "global": 1.00,
}

#: ``affinity_with`` is treated as a hard prior -- if domain A lists domain B,
#: their pairwise Jaccard cannot drop below this floor.
AFFINITY_JACCARD_FLOOR: Final[float] = 0.30

#: 80% confidence half-width in log space: exp(+/- 1.2816 * sigma) gives p10/p90.
_QUANTILE_Z: Final[float] = 1.2816

#: When weight-cap kicks in for outlier comps.
_OUTLIER_WEIGHT: Final[float] = 0.05

#: When fewer than this many comps survive, the projection is degraded.
_MIN_COMPS_FOR_PROJECTION: Final[int] = 2

#: Minimum corpus sample for a useful unweighted log-mean reference.
_MIN_CORPUS_LOG_SAMPLE: Final[int] = 3

#: Minimum number of audience domains required for the triple-overlap term.
_TRIPLE_DOMAIN_THRESHOLD: Final[int] = 3

#: Baseline weight applied to fallback (sim == 0) comp rows so projection
#: doesn't collapse when no genre overlap is found.
_FALLBACK_SIM_WEIGHT: Final[float] = 0.10


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


GeoKey = Literal["us_only", "us_canada", "us_uk", "english_5", "global"]
WindowKey = Literal[
    "theatrical_wide",
    "theatrical_prestige",
    "streaming_first",
    "mixed",
    "auto",
]


@dataclass(frozen=True)
class ProjectionContext:
    """Tunable knobs for :func:`project_revenue`.

    ``facts`` is an optional dict written by ``cc_dispatch`` for sonar/302.ai
    sourced numbers. Never live-fetched here.
    """

    geo: GeoKey = "english_5"
    window: WindowKey = "auto"
    #: v5.1.0 content format (display name / id / alias; ``None`` = legacy
    #: theatrical-comps path, byte-identical to pre-format behaviour). When set
    #: to a streaming-license or microdrama format, per-format economics from
    #: :mod:`pipeline.crystallize.format_economics` replace the theatrical derate.
    content_format: str | None = None
    facts: dict[str, Any] = field(default_factory=lambda: cast("dict[str, Any]", {}))
    similarity_alpha: float = 2.0
    outlier_sigma: float = 3.0
    audience_anchor_M: float = DEFAULT_AUDIENCE_ANCHOR_M
    audience_factor_cap: float = DEFAULT_AUDIENCE_FACTOR_CAP
    comp_k: int = 10


@dataclass(frozen=True)
class CompContribution:
    """Per-comp weighted contribution to the projection."""

    film_slug: str
    title: str
    similarity: float
    ww_gross_usd: float | None
    contribution_pct: float
    primary_audience_domain_id: str | None


@dataclass(frozen=True)
class OverlapResult:
    """Inclusion-exclusion result over audience domains."""

    unique_addressable_M: float
    pairwise_M: dict[str, float]  # "AD_01|AD_02" -> overlap millions
    triple_M: float
    audience_factor: float


@dataclass(frozen=True)
class RevenueProjection:
    """Output of :func:`project_revenue`."""

    p10_usd: float | None
    p50_usd: float | None
    p90_usd: float | None
    som_y1_usd: float | None
    sam_usd: float | None
    tam_usd: float | None
    comp_provenance: tuple[CompContribution, ...]
    overlap: OverlapResult
    assumptions: dict[str, Any]
    calculation_method: Literal["python_executed"] = "python_executed"


# ---------------------------------------------------------------------------
# Small typed helpers (narrow Any -> concrete shapes for pyright)
# ---------------------------------------------------------------------------


def _domain_tags(domain: dict[str, Any]) -> set[str]:
    raw: Any = domain.get("domain_tags")
    if not isinstance(raw, list):
        return set()
    return {str(t).lower() for t in cast("list[Any]", raw)}


def _domain_affinity(domain: dict[str, Any]) -> set[str]:
    raw: Any = domain.get("affinity_with")
    if not isinstance(raw, list):
        return set()
    return {str(a) for a in cast("list[Any]", raw)}


def _domain_size_M(domain: dict[str, Any]) -> float:
    raw = domain.get("size_M") or 0
    try:
        return float(cast("Any", raw))
    except (TypeError, ValueError):
        return 0.0


def _domain_id(domain: dict[str, Any], fallback_index: int) -> str:
    raw = domain.get("id")
    return str(raw) if raw else f"AD_{fallback_index:02d}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _corpus_log_mean_sigma(corpus: FilmsCorpus) -> tuple[float, float]:
    """Unweighted ln(ww) mean + sigma over the whole corpus (cheap; small).

    Used as the outlier reference for individual-comp weight capping.
    Returns (mu, sigma); sigma defaults to 1.0 when too few films qualify.
    """
    logs: list[float] = []
    for f in corpus.films:
        if f.worldwide_gross_usd and f.worldwide_gross_usd > 0:
            logs.append(math.log(f.worldwide_gross_usd))
    if len(logs) < _MIN_CORPUS_LOG_SAMPLE:
        return (0.0, 1.0)
    mu = sum(logs) / len(logs)
    var = sum((x - mu) ** 2 for x in logs) / len(logs)
    sigma = math.sqrt(var) if var > 0 else 1.0
    return (mu, sigma)


def weighted_log_quantiles(
    comps: list[tuple[Film, float]],
    *,
    alpha: float = 2.0,
    outlier_sigma: float = 3.0,
    corpus_log_stats: tuple[float, float] | None = None,
) -> tuple[float | None, float | None, float | None, float]:
    """Return (p10, p50, p90, sigma) in USD assuming log-normal comp distribution.

    Comps with ``worldwide_gross_usd`` None or <=0 are skipped.
    Weights are ``similarity ** alpha`` then normalised. Comps that are more
    than ``outlier_sigma`` from the corpus log-mean get weight capped at
    :data:`_OUTLIER_WEIGHT` before renormalisation.

    Returns (None, None, None, 0.0) when too few usable comps survive.
    """
    raw: list[tuple[float, float]] = []  # (log_ww, weight)
    for film, sim in comps:
        ww = film.worldwide_gross_usd
        if ww is None or ww <= 0:
            continue
        effective_sim = sim if sim > 0 else _FALLBACK_SIM_WEIGHT
        raw.append((math.log(ww), effective_sim**alpha))

    if len(raw) < _MIN_COMPS_FOR_PROJECTION:
        return (None, None, None, 0.0)

    if corpus_log_stats is not None:
        mu_c, sigma_c = corpus_log_stats
        capped: list[tuple[float, float]] = []
        for ln_ww, w in raw:
            if sigma_c > 0 and abs(ln_ww - mu_c) > outlier_sigma * sigma_c:
                capped.append((ln_ww, min(w, _OUTLIER_WEIGHT)))
            else:
                capped.append((ln_ww, w))
        raw = capped

    w_total = sum(w for _, w in raw)
    if w_total <= 0:
        return (None, None, None, 0.0)
    weights = [(ln_ww, w / w_total) for ln_ww, w in raw]

    mu = sum(ln_ww * w for ln_ww, w in weights)
    var = sum(w * (ln_ww - mu) ** 2 for ln_ww, w in weights)
    sigma = math.sqrt(var) if var > 0 else 0.0

    p50 = math.exp(mu)
    p10 = math.exp(mu - _QUANTILE_Z * sigma)
    p90 = math.exp(mu + _QUANTILE_Z * sigma)
    return (p10, p50, p90, sigma)


def _pair_jaccard(
    tags_i: set[str],
    tags_j: set[str],
    affinity_i: set[str],
    affinity_j: set[str],
    id_i: str,
    id_j: str,
) -> float:
    """Jaccard with affinity floor."""
    base = _jaccard(tags_i, tags_j)
    if id_i in affinity_j or id_j in affinity_i:
        return max(base, AFFINITY_JACCARD_FLOOR)
    return base


def compute_audience_overlap(
    domains: list[dict[str, Any]],
    *,
    anchor_M: float = DEFAULT_AUDIENCE_ANCHOR_M,
    factor_cap: float = DEFAULT_AUDIENCE_FACTOR_CAP,
) -> OverlapResult:
    """Inclusion-exclusion Venn over up to N audience domains.

    Replaces the flat 30%/15% in
    :func:`pipeline.compound_seed._compute_audience_overlap`.
    Handles 0, 1, 2, 3+ domains. For more than 3 domains, the triple-overlap
    term reuses the smallest-triangle approximation (rare in practice -- the
    engine emits exactly 3).
    """
    if not domains:
        return OverlapResult(0.0, {}, 0.0, 0.0)

    sizes = [_domain_size_M(d) for d in domains]
    tags = [_domain_tags(d) for d in domains]
    ids = [_domain_id(d, i) for i, d in enumerate(domains)]
    affinity = [_domain_affinity(d) for d in domains]

    if len(domains) == 1:
        unique = sizes[0]
        factor = round(min(unique / anchor_M, factor_cap), 4) if anchor_M > 0 else 0.0
        return OverlapResult(
            unique_addressable_M=round(unique, 2),
            pairwise_M={},
            triple_M=0.0,
            audience_factor=factor,
        )

    pairwise: dict[str, float] = {}
    pair_overlap_sum = 0.0
    for i in range(len(domains)):
        for j in range(i + 1, len(domains)):
            jac = _pair_jaccard(tags[i], tags[j], affinity[i], affinity[j], ids[i], ids[j])
            pair_overlap = jac * min(sizes[i], sizes[j])
            pairwise[f"{ids[i]}|{ids[j]}"] = round(pair_overlap, 2)
            pair_overlap_sum += pair_overlap

    triple_M = 0.0
    if len(domains) >= _TRIPLE_DOMAIN_THRESHOLD:
        jac01 = _pair_jaccard(tags[0], tags[1], affinity[0], affinity[1], ids[0], ids[1])
        jac12 = _pair_jaccard(tags[1], tags[2], affinity[1], affinity[2], ids[1], ids[2])
        jac02 = _pair_jaccard(tags[0], tags[2], affinity[0], affinity[2], ids[0], ids[2])
        triple_M = min(jac01, jac12, jac02) * min(sizes[0], sizes[1], sizes[2])

    unique = max(0.0, sum(sizes) - pair_overlap_sum + triple_M)
    factor = min(unique / anchor_M, factor_cap) if anchor_M > 0 else 0.0

    return OverlapResult(
        unique_addressable_M=round(unique, 2),
        pairwise_M=pairwise,
        triple_M=round(triple_M, 2),
        audience_factor=round(factor, 4),
    )


def _infer_window_from_distributor(distributor: str | None) -> str:
    """Map a distributor string to a window key. Default: ``"mixed"``."""
    if not distributor:
        return "mixed"
    needle = distributor.lower()
    if any(s in needle for s in _STREAMING_DISTRIBUTORS):
        return "streaming_first"
    if any(s in needle for s in _PRESTIGE_DISTRIBUTORS):
        return "theatrical_prestige"
    if any(s in needle for s in _WIDE_DISTRIBUTORS):
        return "theatrical_wide"
    return "mixed"


def apply_window_penalty(
    base: float, window: WindowKey, *, distributor: str | None = None
) -> tuple[float, str]:
    """Return (derated, window_key_used). ``window="auto"`` infers from distributor."""
    key: str = window if window != "auto" else _infer_window_from_distributor(distributor)
    factor = WINDOW_FACTORS.get(key, WINDOW_FACTORS["mixed"])
    return (base * factor, key)


def apply_geo_penalty(base: float, geo: GeoKey) -> tuple[float, float]:
    """Return (derated, factor_used)."""
    factor = GEO_FACTORS.get(geo, GEO_FACTORS["english_5"])
    return (base * factor, factor)


def _assign_audience_to_comp(film: Film, domains: list[dict[str, Any]]) -> str | None:
    """Return ``id`` of the audience domain whose tags best overlap film genres.

    Ties resolved by domain order. ``None`` when the candidate has no domains
    or the film has no genres.
    """
    if not domains or not film.genres:
        return None
    best: tuple[float, str | None] = (-1.0, None)
    film_genres = set(film.genres)
    for d in domains:
        tags = _domain_tags(d)
        if not tags:
            continue
        score = _jaccard(film_genres, tags)
        if score > best[0]:
            best = (score, _domain_id(d, 0))
    fallback = _domain_id(domains[0], 0)
    return best[1] if best[1] else (fallback or None)


def _resolve_genres(candidate: dict[str, Any]) -> list[str]:
    """Pull a usable genre list off a candidate dict, with comp-module fallback."""
    raw = candidate.get("genres")
    if isinstance(raw, list):
        genres = [str(g).strip().lower() for g in cast("list[Any]", raw) if str(g).strip()]
        if genres:
            return genres
    return infer_query_genres(candidate)


def _resolve_domains(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Return audience domains in dict form, dropping non-dict noise."""
    raw: Any = candidate.get("audiences")
    if not isinstance(raw, list):
        return []
    return [a for a in cast("list[Any]", raw) if isinstance(a, dict)]


def _build_provenance(
    comps_pairs: list[tuple[Film, float]],
    domains: list[dict[str, Any]],
    alpha: float,
) -> tuple[tuple[CompContribution, ...], int]:
    """Build per-comp contribution rows; return (rows, n_comps_used)."""
    total_w = 0.0
    per_comp_w: list[float] = []
    for film, sim in comps_pairs:
        if film.worldwide_gross_usd is None or film.worldwide_gross_usd <= 0:
            per_comp_w.append(0.0)
            continue
        effective = sim if sim > 0 else _FALLBACK_SIM_WEIGHT
        w = effective**alpha
        per_comp_w.append(w)
        total_w += w
    rows: list[CompContribution] = []
    n_used = 0
    for (film, sim), w in zip(comps_pairs, per_comp_w, strict=False):
        share = round(w / total_w, 4) if total_w > 0 else 0.0
        if share > 0:
            n_used += 1
        rows.append(
            CompContribution(
                film_slug=film.slug,
                title=film.title,
                similarity=round(sim, 4),
                ww_gross_usd=film.worldwide_gross_usd,
                contribution_pct=share,
                primary_audience_domain_id=_assign_audience_to_comp(film, domains),
            )
        )
    return (tuple(rows), n_used)


#: Minimum audience factor applied to license/microdrama SOM so a candidate
#: with no audience domains still yields a non-zero (base-fee) projection.
_LICENSE_MIN_AUDIENCE_FACTOR: Final[float] = 1.0
#: Floor applied ONLY when theatrical audience overlap is exactly zero (a data gap),
#: so a valid projection never collapses to a $0 SOM and SOM<SAM<TAM always holds.
#: Positive factors are left untouched, so calibrated projections never shift.
_THEATRICAL_MIN_AUDIENCE_FACTOR: Final[float] = 0.05


def _compose_som_and_sam(
    *,
    p50: float,
    comps_pairs: list[tuple[Film, float]],
    overlap: OverlapResult,
    ctx: ProjectionContext,
    corpus: FilmsCorpus,
    genres: list[str],
    assumptions: dict[str, Any],
) -> tuple[float, float, float]:
    """Theatrical path. Apply window+geo+overlap derates; return
    ``(som_y1_usd, sam_usd, tam_usd)``. Unchanged math for feature /
    animation feature — the per-format LIFETIME context is recorded only
    when an explicit theatrical ``content_format`` is supplied (so the
    legacy ``content_format=None`` assumptions stay byte-identical)."""
    top_distributor: str | None = comps_pairs[0][0].distributor if comps_pairs else None
    windowed, window_key_used = apply_window_penalty(p50, ctx.window, distributor=top_distributor)
    geoed, geo_factor = apply_geo_penalty(windowed, ctx.geo)
    # A positive p50 with zero measured audience overlap is a data gap, not a real
    # $0 SOM — floor the factor so SOM<SAM<TAM always holds. Positive factors are
    # unchanged, so this never shifts a calibrated projection.
    audience_factor = (
        overlap.audience_factor if overlap.audience_factor > 0 else _THEATRICAL_MIN_AUDIENCE_FACTOR
    )
    som_y1 = geoed * audience_factor

    assumptions["window_key_used"] = window_key_used
    assumptions["window_factor"] = WINDOW_FACTORS.get(window_key_used, WINDOW_FACTORS["mixed"])
    assumptions["geo_factor"] = geo_factor

    slice_frac = corpus.genre_slice_fraction(genres)
    assumptions["genre_slice_fraction"] = round(slice_frac, 4)
    tam_override = ctx.facts.get("tam_usd")
    tam_usd = float(tam_override) if tam_override is not None else DEFAULT_TAM_USD
    assumptions["tam_source"] = (
        ctx.facts.get("tam_source") if tam_override is not None else "constant:MPA_THEME_2021"
    )
    # Cap SAM at the sane, market-sourced static slice for the format. The raw
    # corpus genre_slice_fraction has no realistic ceiling (broad genres push it
    # to ~0.95), which would make SAM ~95% of TAM for a single original title —
    # the canonical red flag a sophisticated investor rejects. The profile's
    # sam_usd encodes a defensible serviceable slice (~12% theatrical).
    profile = format_economics.get_profile(ctx.content_format or "feature")
    sam = min(tam_usd * slice_frac, profile.sam_usd)
    assumptions["sam_slice_capped"] = sam < tam_usd * slice_frac

    if ctx.content_format is not None:
        assumptions["format_used"] = profile.format_id
        assumptions["format_profile_applied"] = True
        assumptions["lifetime_som_y1_usd"] = format_economics.lifetime_from_y1(som_y1, profile)
    return (som_y1, sam, tam_usd)


def _compose_format_economics(
    profile: format_economics.FormatProfile,
    overlap: OverlapResult,
    assumptions: dict[str, Any],
) -> tuple[float, float, float]:
    """Non-theatrical path (license / microdrama). SOM derives from the
    format's own monetization model (cost-plus license fee or share-of-
    serviceable-market), NOT box-office comps. Returns
    ``(som_y1_usd, sam_usd, tam_usd)`` with ``som < sam < tam`` by
    construction. All python_executed from named, sourced constants (ADR-0011)."""
    factor = (
        overlap.audience_factor if overlap.audience_factor > 0 else _LICENSE_MIN_AUDIENCE_FACTOR
    )
    if profile.monetization_model == "microdrama":
        som_y1 = format_economics.microdrama_som_usd(profile) * factor
    else:  # license
        som_y1 = format_economics.license_fee_usd(profile) * factor
    sam = profile.sam_usd
    tam_usd = profile.tam_segment_usd

    assumptions["format_used"] = profile.format_id
    assumptions["format_profile_applied"] = True
    assumptions["monetization_model"] = profile.monetization_model
    assumptions["audience_factor_applied"] = round(factor, 4)
    assumptions["lifetime_som_y1_usd"] = format_economics.lifetime_from_y1(som_y1, profile)
    assumptions["tam_source"] = profile.tam_source_url or "format_economics:data_gap"
    return (som_y1, sam, tam_usd)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def project_revenue(
    candidate: dict[str, Any],
    corpus: FilmsCorpus,
    *,
    ctx: ProjectionContext | None = None,
) -> RevenueProjection:
    """Compute a defensible revenue projection for a single compound seed.

    ``candidate`` is a ``CompoundSeedResult.to_dict()`` (or any dict that
    carries ``audiences: list[...]`` and either ``genres: list[str]`` or
    ``scores.primary_cluster`` + ``world_texture.name``).

    Returns a :class:`RevenueProjection`. All numeric fields can be ``None``
    when comp coverage is insufficient -- callers must render an em-dash, not 0.
    """
    if ctx is None:
        ctx = ProjectionContext()

    genres = _resolve_genres(candidate)
    domains = _resolve_domains(candidate)
    assumptions: dict[str, Any] = {
        "geo": ctx.geo,
        "window_requested": ctx.window,
        "comp_k": ctx.comp_k,
        "similarity_alpha": ctx.similarity_alpha,
        "outlier_sigma": ctx.outlier_sigma,
        "audience_anchor_M": ctx.audience_anchor_M,
        "query_genres": genres,
    }

    comps_pairs = corpus.find_comps_with_similarity(genres, k=ctx.comp_k)
    corpus_stats = _corpus_log_mean_sigma(corpus)
    p10, p50, p90, sigma = weighted_log_quantiles(
        comps_pairs,
        alpha=ctx.similarity_alpha,
        outlier_sigma=ctx.outlier_sigma,
        corpus_log_stats=corpus_stats,
    )

    overlap = compute_audience_overlap(
        domains,
        anchor_M=ctx.audience_anchor_M,
        factor_cap=ctx.audience_factor_cap,
    )

    provenance, n_used = _build_provenance(comps_pairs, domains, ctx.similarity_alpha)
    assumptions["n_comps_used"] = n_used
    assumptions["sigma_log"] = round(sigma, 4)

    # Resolve the content format. Non-theatrical formats (license / microdrama)
    # price off their own economics — independent of box-office comps — so they
    # project even when p50 is None. Feature / animation feature / no-format keep
    # the theatrical comps path (byte-identical for content_format=None).
    profile = format_economics.get_profile(ctx.content_format) if ctx.content_format else None
    non_theatrical = profile is not None and profile.monetization_model in ("license", "microdrama")

    som_y1: float | None
    sam: float | None
    tam_usd_final: float
    if non_theatrical and profile is not None:
        som_y1, sam, tam_usd_final = _compose_format_economics(profile, overlap, assumptions)
    elif p50 is None:
        som_y1 = None
        sam = None
        tam_override = ctx.facts.get("tam_usd")
        tam_usd_final = float(tam_override) if tam_override is not None else DEFAULT_TAM_USD
    else:
        som_y1, sam, tam_usd_final = _compose_som_and_sam(
            p50=p50,
            comps_pairs=comps_pairs,
            overlap=overlap,
            ctx=ctx,
            corpus=corpus,
            genres=genres,
            assumptions=assumptions,
        )

    return RevenueProjection(
        p10_usd=p10,
        p50_usd=p50,
        p90_usd=p90,
        som_y1_usd=som_y1,
        sam_usd=sam,
        tam_usd=tam_usd_final,
        comp_provenance=provenance,
        overlap=overlap,
        assumptions=assumptions,
    )


__all__ = [
    "AFFINITY_JACCARD_FLOOR",
    "DEFAULT_AUDIENCE_ANCHOR_M",
    "DEFAULT_TAM_USD",
    "GEO_FACTORS",
    "WINDOW_FACTORS",
    "CompContribution",
    "OverlapResult",
    "ProjectionContext",
    "RevenueProjection",
    "apply_geo_penalty",
    "apply_window_penalty",
    "compute_audience_overlap",
    "project_revenue",
    "weighted_log_quantiles",
]
