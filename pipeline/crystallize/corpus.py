"""pipeline.crystallize.corpus — loader + indexer for the films knowledge base.

Reads the 294 .json files at ``Inputs/10May/knowledge/corpus/deep_data/films/``
and exposes a queryable in-memory ``FilmsCorpus`` for comp matching.

Each on-disk file looks like::

    {
      "title": "Blade Runner 2049",
      "imdb_id": "tt1856101",
      "financials": {
        "worldwide": "$277,882,781",
        "domestic":  "$92,071,675",
        "international": "$185,805,079",
        "budget": "$150,000,000"
      },
      "details": {
        "distributor": "Warner Bros.",
        "release_date": "October 6, 2017",
        "mpaa": "R", "running_time": "2 hr 44 min",
        "genres": ["Action", "Drama", "Mystery", "Sci-Fi", "Thriller"]
      },
      "personnel": {...},
      "links": {"imdb": "...", "boxofficemojo": "..."}
    }

The loader normalises genres to lowercase strings and parses the dollar
strings to floats. Missing or malformed financials are surfaced as ``None``
(NOT silently zeroed) so callers can render ``—`` rather than fake ROI = -1.0.

MUST NOT import LLM clients. MUST NOT import from frameworks/.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, cast

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS_ROOT: Final[Path] = (
    _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"
)

# v7.0 F0.4 — genre alias map.
# TMDB emits "Science Fiction"; the legacy corpus + the comp-query genre hints
# in pipeline/crystallize/comps.py use "sci-fi". Without this normalization the
# Jaccard match drops tentpoles ($1B+ films tagged "science fiction") because
# the query genre "sci-fi" has zero overlap. See runs/v7-postmortem-F0.2/FINDINGS.md
# Finding #3 + the F0.4 follow-up.
_GENRE_ALIASES: Final[dict[str, str]] = {
    "science fiction": "sci-fi",
}
_DEFAULT_ENRICHED_PATH: Final[Path] = (
    _REPO_ROOT / "pipeline" / "data" / "films_corpus_enriched.jsonl"
)

_DOLLAR_RE: Final[re.Pattern[str]] = re.compile(r"[^\d.]")


def _parse_dollars(s: str | None) -> float | None:
    """Parse a financial string like ``"$277,882,781"`` to a float, or ``None``.

    Returns ``None`` when the input is None, empty, the literal string
    ``"N/A"``, or contains no digits after symbol stripping. Negative numbers
    are not expected in this corpus and are not handled.
    """
    if s is None:
        return None
    stripped = s.strip()
    if not stripped or stripped.upper() in {"N/A", "NA", "-", "—"}:
        return None
    digits_only = _DOLLAR_RE.sub("", stripped)
    if not digits_only:
        return None
    try:
        return float(digits_only)
    except ValueError:
        return None


def _parse_year(release_date: str | None) -> int | None:
    """Extract year from a release_date string like ``"October 6, 2017"``."""
    if not release_date:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(release_date))
    if match:
        return int(match.group())
    try:
        # Try ISO format fallback.
        return datetime.fromisoformat(str(release_date)).year
    except ValueError:
        return None


@dataclass(frozen=True)
class Film:
    """One film in the corpus — financials parsed, genres normalised."""

    slug: str
    title: str
    imdb_id: str | None
    worldwide_gross_usd: float | None
    domestic_gross_usd: float | None
    international_gross_usd: float | None
    budget_usd: float | None
    genres: tuple[str, ...]  # lowercase
    genres_display: tuple[str, ...]  # original casing for HTML
    distributor: str | None
    release_year: int | None
    mpaa: str | None
    imdb_url: str | None
    boxofficemojo_url: str | None
    # v6.0 E3a — corpus enrichment (TMDB-sourced prose for downstream embedding).
    # All default empty so v5 code paths and pre-enrichment rows stay valid.
    log_line: str = ""
    tagline: str = ""
    synopsis: str = ""
    domain_tags: tuple[str, ...] = ()
    mood_palette: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "imdb_id": self.imdb_id,
            "worldwide_gross_usd": self.worldwide_gross_usd,
            "budget_usd": self.budget_usd,
            "roi": roi(self),
            "genres": list(self.genres_display),
            "release_year": self.release_year,
            "boxofficemojo_url": self.boxofficemojo_url,
            "imdb_url": self.imdb_url,
            "log_line": self.log_line,
            "tagline": self.tagline,
            "synopsis": self.synopsis,
            "domain_tags": list(self.domain_tags),
            "mood_palette": list(self.mood_palette),
        }


def roi(film: Film) -> float | None:
    """Return (worldwide - budget) / budget, or ``None`` when not computable."""
    if film.worldwide_gross_usd is None or film.budget_usd is None:
        return None
    if film.budget_usd <= 0:
        return None
    return (film.worldwide_gross_usd - film.budget_usd) / film.budget_usd


def _typed_str(d: dict[str, Any], key: str) -> str | None:
    v = d.get(key)
    return v if isinstance(v, str) else None


def _typed_dict(d: dict[str, Any], key: str) -> dict[str, Any]:
    v = d.get(key)
    if isinstance(v, dict):
        return cast("dict[str, Any]", v)
    return {}


def _typed_list(d: dict[str, Any], key: str) -> list[Any]:
    v = d.get(key)
    if isinstance(v, list):
        return cast("list[Any]", v)
    return []


def _film_from_dict(
    slug: str,
    raw: dict[str, Any],
    enrichment: dict[str, Any] | None = None,
) -> Film | None:
    """Construct a Film from the on-disk dict; return None if title missing.

    ``enrichment`` is the optional row from ``films_corpus_enriched.jsonl``
    keyed by ``slug``. When provided, its prose fields override the empty
    defaults; when ``None``, the Film carries the v5 empty defaults.
    """
    title = _typed_str(raw, "title")
    if not title:
        return None

    financials: dict[str, Any] = _typed_dict(raw, "financials")
    details: dict[str, Any] = _typed_dict(raw, "details")
    links: dict[str, Any] = _typed_dict(raw, "links")

    raw_genres: list[Any] = _typed_list(details, "genres")
    genres_display: tuple[str, ...] = tuple(
        str(g).strip() for g in raw_genres if isinstance(g, str) and g.strip()
    )
    # Lowercase + apply F0.4 alias map so TMDB "Science Fiction" Jaccard-matches
    # the legacy "sci-fi" query genre. genres_display keeps the original casing
    # for HTML rendering.
    genres: tuple[str, ...] = tuple(
        _GENRE_ALIASES.get(g.lower(), g.lower()) for g in genres_display
    )

    e = enrichment or {}
    log_line = _typed_str(e, "log_line") or ""
    tagline = _typed_str(e, "tagline") or ""
    synopsis = _typed_str(e, "synopsis") or ""
    domain_tags = tuple(
        str(t).strip() for t in _typed_list(e, "domain_tags") if isinstance(t, str) and t.strip()
    )
    mood_palette = tuple(
        str(m).strip() for m in _typed_list(e, "mood_palette") if isinstance(m, str) and m.strip()
    )

    return Film(
        slug=slug,
        title=title.strip(),
        imdb_id=_typed_str(raw, "imdb_id"),
        worldwide_gross_usd=_parse_dollars(_typed_str(financials, "worldwide")),
        domestic_gross_usd=_parse_dollars(_typed_str(financials, "domestic")),
        international_gross_usd=_parse_dollars(_typed_str(financials, "international")),
        budget_usd=_parse_dollars(_typed_str(financials, "budget")),
        genres=genres,
        genres_display=genres_display,
        distributor=_typed_str(details, "distributor"),
        release_year=_parse_year(_typed_str(details, "release_date")),
        mpaa=_typed_str(details, "mpaa"),
        imdb_url=_typed_str(links, "imdb"),
        boxofficemojo_url=_typed_str(links, "boxofficemojo"),
        log_line=log_line,
        tagline=tagline,
        synopsis=synopsis,
        domain_tags=domain_tags,
        mood_palette=mood_palette,
    )


def _load_enrichment_map(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Read ``films_corpus_enriched.jsonl`` into ``{slug: row}``.

    Returns an empty dict when the cache is absent or unreadable. Rows
    without a ``slug`` key are skipped (defensive — we never crash the
    loader because of a corrupt enrichment line).
    """
    target = (path or _DEFAULT_ENRICHED_PATH).resolve()
    if not target.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        with target.open("r", encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    parsed: Any = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    _log.warning("enrichment: skipping malformed line in %s (%s)", target, exc)
                    continue
                if not isinstance(parsed, dict):
                    continue
                row = cast("dict[str, Any]", parsed)
                slug_field = row.get("slug")
                if isinstance(slug_field, str) and slug_field:
                    out[slug_field] = row
    except OSError as exc:
        _log.warning("enrichment: unable to read %s (%s)", target, exc)
        return {}
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets. Returns 0.0 if either is empty."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


_COMP_DECORRELATION_LAMBDA: Final[float] = 0.85

# R6b hybrid comp similarity: final_sim = jaccard_weight*jaccard + cosine_weight*
# cosine(anchor, film), where the anchor is the top-Jaccard comp's pre-baked
# embedding (offline slug-to-slug cosine; no model). Off by default so the
# revenue calibration eval + leaderboard stay byte-identical; the investor
# slate builder opts in via FilmsCorpus.enable_semantic_comps().
_COMP_JACCARD_WEIGHT: Final[float] = 0.5
_COMP_COSINE_WEIGHT: Final[float] = 0.5
_MIN_BLEND_CANDIDATES: Final[int] = 2
"""WEDGE Step 2: multiplicative diversity penalty on Carbonell-Goldstein MMR.

The final score for slot N>=2 is::

    adjusted = sim_to_query * (1 - lambda * max_jaccard_with_any_selected)

``max_jaccard_with_any_selected`` is per-individual-selected-film, not
against the union — so that the second clone of an already-picked film
collapses to ``(1 - lambda) * sim ≈ 0.15 * sim`` and is easily beaten by
a marginally-less-similar but genuinely diverse comp.

Calibrated against the audit fixture (5 A.I.-clones + 6 diverse films):
with ``lambda=0.85`` the algorithm yields ``1 clone + 4 diverse`` in
the top-5. With ``lambda<=0.5`` the subtractive variant lets clones win
all five slots because ``sim=1.0`` dominates any subtractive penalty.
"""


def _max_jaccard_with_selected(
    candidate_genres: set[str],
    selected: list[Film],
) -> float:
    """Highest Jaccard between ``candidate_genres`` and any single selected
    film's genre set. Returns 0.0 when ``selected`` is empty."""
    if not selected:
        return 0.0
    return max(_jaccard(candidate_genres, set(s.genres)) for s in selected)


def _mmr_select(
    candidates: list[tuple[float, float, Film]],
    query: set[str],
    k: int,
) -> list[Film]:
    """Carbonell-Goldstein MMR over ``(similarity, gross, film)`` tuples.

    Picks the highest scorer first; for each subsequent slot recomputes
    ``adjusted = sim * (1 - lambda * max_jaccard_with_any_selected)``
    and picks the highest adjusted (tie-broken on gross descending).

    ``candidates`` must be pre-filtered to ``sim > 0``; it is consumed
    in-place via sort + pop. ``query`` accepted for API symmetry with
    :func:`_mmr_select_with_similarity` but the multiplicative MMR
    variant doesn't need the query denominator.
    """
    if not candidates:
        return []
    candidates.sort(key=lambda t: (-t[0], -t[1]))
    selected: list[Film] = [candidates[0][2]]
    remaining: list[tuple[float, float, Film]] = candidates[1:]

    while remaining and len(selected) < k:
        best_adjusted: float = -1.0
        best_idx: int = -1
        best_gross: float = -1.0
        for idx, (sim, gross, film) in enumerate(remaining):
            max_overlap = _max_jaccard_with_selected(set(film.genres), selected)
            adjusted = sim * (1.0 - _COMP_DECORRELATION_LAMBDA * max_overlap)
            if adjusted > best_adjusted or (adjusted == best_adjusted and gross > best_gross):
                best_adjusted = adjusted
                best_idx = idx
                best_gross = gross
        if best_idx < 0:
            break
        _, _, chosen = remaining.pop(best_idx)
        selected.append(chosen)

    return selected


def _mmr_select_with_similarity(
    candidates: list[tuple[float, float, Film]],
    query: set[str],
    k: int,
) -> list[tuple[Film, float]]:
    """Same as :func:`_mmr_select` but returns ``(film, original_jaccard)`` tuples
    so callers like :mod:`pipeline.crystallize.revenue` can weight comp
    contributions by the un-penalised similarity (the lambda penalty is a
    SELECTION criterion only — it does not modify the returned score)."""
    if not candidates:
        return []
    candidates.sort(key=lambda t: (-t[0], -t[1]))
    selected: list[tuple[Film, float]] = [(candidates[0][2], candidates[0][0])]
    selected_films: list[Film] = [candidates[0][2]]
    remaining: list[tuple[float, float, Film]] = candidates[1:]

    while remaining and len(selected) < k:
        best_adjusted: float = -1.0
        best_idx: int = -1
        best_gross: float = -1.0
        for idx, (sim, gross, film) in enumerate(remaining):
            max_overlap = _max_jaccard_with_selected(set(film.genres), selected_films)
            adjusted = sim * (1.0 - _COMP_DECORRELATION_LAMBDA * max_overlap)
            if adjusted > best_adjusted or (adjusted == best_adjusted and gross > best_gross):
                best_adjusted = adjusted
                best_idx = idx
                best_gross = gross
        if best_idx < 0:
            break
        sim_orig, _, chosen = remaining.pop(best_idx)
        selected.append((chosen, sim_orig))
        selected_films.append(chosen)

    return selected


@dataclass
class FilmsCorpus:
    """In-memory corpus of films loaded from a directory of .json files."""

    films: tuple[Film, ...]
    root: Path
    _genre_index: dict[str, list[Film]] = field(
        default_factory=lambda: cast("dict[str, list[Film]]", {}),
        repr=False,
    )
    _total_ww_gross_usd: float = field(default=0.0, repr=False)
    _genre_slice_cache: dict[frozenset[str], float] = field(
        default_factory=lambda: cast("dict[frozenset[str], float]", {}),
        repr=False,
    )
    #: R6b semantic comps (off by default -> pure Jaccard, byte-identical).
    _semantic_enabled: bool = field(default=False, repr=False)
    _semantic_index: object | None = field(default=None, repr=False)

    @classmethod
    def load(
        cls,
        root: Path | None = None,
        *,
        enriched_path: Path | None = None,
    ) -> FilmsCorpus:
        """Load every ``<slug>.json`` under ``root``.

        Missing or unreadable files are logged and skipped — the corpus is
        best-effort. If the root directory does not exist at all, returns an
        empty corpus (callers degrade gracefully — comp-matching just returns
        empty lists and ``derivative_distance`` defaults to 1.0).

        When ``pipeline/data/films_corpus_enriched.jsonl`` exists (or a custom
        ``enriched_path`` is supplied), every matching slug receives its
        ``log_line / tagline / synopsis / domain_tags / mood_palette`` prose
        from the cache. Films absent from the cache carry empty defaults
        (v5 backwards-compatible).
        """
        root_path = (root or _DEFAULT_CORPUS_ROOT).resolve()
        films: list[Film] = []
        if not root_path.exists():
            _log.warning("FilmsCorpus.load: root %s does not exist", root_path)
            return cls(films=tuple(), root=root_path)

        enrichment_map = _load_enrichment_map(enriched_path)

        for json_path in sorted(root_path.glob("*.json")):
            slug = json_path.stem
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                _log.warning("FilmsCorpus.load: skipping %s (%s)", json_path.name, exc)
                continue
            film = _film_from_dict(slug, raw, enrichment_map.get(slug))
            if film is not None:
                films.append(film)

        corpus = cls(films=tuple(films), root=root_path)
        corpus._build_indices()
        _log.info(
            "FilmsCorpus.load: loaded %d films from %s (enriched=%d)",
            len(films),
            root_path,
            len(enrichment_map),
        )
        return corpus

    def _build_indices(self) -> None:
        """Pre-bucket films by lowercase genre and pre-sum total ww gross."""
        index: dict[str, list[Film]] = {}
        total: float = 0.0
        for f in self.films:
            for g in f.genres:
                index.setdefault(g, []).append(f)
            if f.worldwide_gross_usd is not None and f.worldwide_gross_usd > 0:
                total += f.worldwide_gross_usd
        self._genre_index = index
        self._total_ww_gross_usd = total

    def __len__(self) -> int:
        return len(self.films)

    def find_comps(self, genres: list[str], k: int = 5) -> list[Film]:
        """Return top-k films most similar to ``genres``, with MMR decorrelation.

        WEDGE Step 2 (2026-05-27): replaces greedy top-K-by-Jaccard with
        Maximal-Marginal-Relevance style iterative selection so the top-k
        spans multiple genre clusters instead of returning k copies of the
        same multi-genre film (the audited failure mode where A.I.
        Artificial Intelligence — tagged drama + sci-fi + thriller — won
        22 of 49 leaderboard slots regardless of query intent).

        Algorithm:
          1. Score every film by Jaccard against ``genres``.
          2. Pick the top scorer (ties → highest worldwide gross).
          3. For each subsequent slot, compute an adjusted score
             ``adjusted = jaccard - lambda * overlap_fraction`` where
             ``overlap_fraction = |candidate.genres ∩ selected_union| /
             max(1, |query|)``. ``lambda = _COMP_DECORRELATION_LAMBDA``.
          4. Tie-break adjusted scores on worldwide gross (existing).

        Ties broken by worldwide_gross_usd descending (None treated as 0.0).
        Returns at most ``k`` films. Empty-query / no-overlap fallback
        unchanged: returns top-k by worldwide gross.
        """
        if not self.films:
            return []
        query: set[str] = {g.strip().lower() for g in genres if g and g.strip()}
        if not query:
            # No usable query — fall back to top-k by worldwide gross.
            sorted_by_gross = sorted(
                self.films,
                key=lambda f: f.worldwide_gross_usd or 0.0,
                reverse=True,
            )
            return list(sorted_by_gross[:k])

        candidates: list[tuple[float, float, Film]] = []
        for f in self.films:
            sim = _jaccard(query, set(f.genres))
            if sim <= 0.0:
                continue
            candidates.append((sim, f.worldwide_gross_usd or 0.0, f))

        if not candidates:
            # No genre overlap — fall back to top-k by gross.
            sorted_by_gross = sorted(
                self.films,
                key=lambda f: f.worldwide_gross_usd or 0.0,
                reverse=True,
            )
            return list(sorted_by_gross[:k])

        return _mmr_select(candidates, query, k)

    def all_genres(self) -> set[str]:
        """Return the universe of lowercase genres present in the corpus."""
        return set(self._genre_index.keys())

    def find_comps_with_similarity(self, genres: list[str], k: int = 5) -> list[tuple[Film, float]]:
        """Return ``[(film, jaccard_similarity), ...]`` for the top-k comps.

        WEDGE Step 2 (2026-05-27): mirrors ``find_comps`` with MMR
        decorrelation so revenue projection (``pipeline.crystallize.revenue``)
        sees a diverse comp set instead of k clones. The returned
        ``similarity`` value is the ORIGINAL Jaccard, not the adjusted MMR
        score — downstream weighting math is unaffected by the
        decorrelation lambda.

        Fallback rows (no genre overlap) carry ``similarity = 0.0``.
        """
        if not self.films:
            return []
        query: set[str] = {g.strip().lower() for g in genres if g and g.strip()}
        if not query:
            sorted_by_gross = sorted(
                self.films,
                key=lambda f: f.worldwide_gross_usd or 0.0,
                reverse=True,
            )
            return [(f, 0.0) for f in sorted_by_gross[:k]]

        candidates: list[tuple[float, float, Film]] = []
        for f in self.films:
            sim = _jaccard(query, set(f.genres))
            if sim <= 0.0:
                continue
            candidates.append((sim, f.worldwide_gross_usd or 0.0, f))

        if not candidates:
            sorted_by_gross = sorted(
                self.films,
                key=lambda f: f.worldwide_gross_usd or 0.0,
                reverse=True,
            )
            return [(f, 0.0) for f in sorted_by_gross[:k]]

        if self._semantic_enabled:
            candidates = self._blend_semantic_similarity(candidates)
        return _mmr_select_with_similarity(candidates, query, k)

    def enable_semantic_comps(self, index_path: Path | str | None = None) -> bool:
        """R6b: turn on hybrid Jaccard+slug-cosine comp matching for this corpus
        instance. Loads the pre-baked embedding index (offline; no model). Returns
        True when the index loaded (else stays pure-Jaccard). Idempotent. The
        revenue calibration eval + leaderboard never call this, so they keep the
        byte-identical pure-Jaccard behaviour."""
        from pipeline.crystallize.embeddings import CorpusIndex  # noqa: PLC0415

        idx = CorpusIndex.load(index_path) if index_path else CorpusIndex.load()
        if idx is not None:
            self._semantic_index = idx
            self._semantic_enabled = True
        return self._semantic_enabled

    def _blend_semantic_similarity(
        self, candidates: list[tuple[float, float, Film]]
    ) -> list[tuple[float, float, Film]]:
        """Blend each candidate's Jaccard with its cosine to the top-Jaccard
        anchor's pre-baked embedding (offline). Degrades to pure Jaccard when
        the index is missing or a slug is absent."""
        idx = cast("Any", self._semantic_index)
        if idx is None or len(candidates) < _MIN_BLEND_CANDIDATES:
            return candidates
        anchor_film = max(candidates, key=lambda t: (t[0], t[1]))[2]
        anchor_vec = idx.slug_to_embedding(anchor_film.slug)
        if anchor_vec is None:
            return candidates
        blended: list[tuple[float, float, Film]] = []
        for jac, gross, film in candidates:
            cos = idx.cosine_with_film(anchor_vec, film.slug)
            final = (
                _COMP_JACCARD_WEIGHT * jac + _COMP_COSINE_WEIGHT * float(cos)
                if cos is not None
                else jac
            )
            blended.append((final, gross, film))
        return blended

    def total_ww_gross_usd(self) -> float:
        """Return pre-summed total worldwide gross across the corpus (USD)."""
        return self._total_ww_gross_usd

    def genre_slice_fraction(self, genres: list[str]) -> float:
        """Self-consistent SAM fraction: corpus ww in candidate genres / total.

        Computes ``sum(ww | f.genres ∩ query ≠ ∅) / total_ww``. Cached by
        frozenset(query). Returns 0.0 when query is empty or corpus is
        empty; caps at 1.0 (the union of all genres equals the whole corpus).
        """
        if not self.films or self._total_ww_gross_usd <= 0.0:
            return 0.0
        query: frozenset[str] = frozenset(g.strip().lower() for g in genres if g and g.strip())
        if not query:
            return 0.0
        cached = self._genre_slice_cache.get(query)
        if cached is not None:
            return cached
        in_slice: float = 0.0
        for f in self.films:
            if f.worldwide_gross_usd is None or f.worldwide_gross_usd <= 0:
                continue
            if set(f.genres) & query:
                in_slice += f.worldwide_gross_usd
        fraction = min(in_slice / self._total_ww_gross_usd, 1.0)
        self._genre_slice_cache[query] = fraction
        return fraction

    def median_domestic_ratio(self) -> float:
        """Median ``domestic / worldwide`` ratio across the corpus.

        Used by ``pipeline.crystallize.revenue.apply_geo_penalty`` to anchor
        the US-only base ratio. Skips films where either field is missing or
        worldwide ≤ 0. Returns ``0.45`` as a safe default if no rows qualify.
        """
        ratios: list[float] = []
        for f in self.films:
            if (
                f.domestic_gross_usd is not None
                and f.worldwide_gross_usd is not None
                and f.worldwide_gross_usd > 0
                and 0 < f.domestic_gross_usd <= f.worldwide_gross_usd
            ):
                ratios.append(f.domestic_gross_usd / f.worldwide_gross_usd)
        if not ratios:
            return 0.45
        ratios.sort()
        mid = len(ratios) // 2
        if len(ratios) % 2 == 1:
            return ratios[mid]
        return (ratios[mid - 1] + ratios[mid]) / 2.0


__all__ = ["Film", "FilmsCorpus", "_parse_dollars", "_parse_year", "roi"]
