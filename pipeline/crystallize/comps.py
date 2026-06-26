"""pipeline.crystallize.comps — match each candidate to the films corpus.

For each compound seed the engine generates, we infer the candidate's
likely genre set, find the top-k most similar films in the 294-film
corpus (Jaccard on genres), and compute two side outputs:

  * ``derivative_distance`` — ``1 - max(Jaccard(query, comp.genres))``
    over the returned comps. High = novel; low = derivative. Surrogate
    for the GREATNESS C001 "Expert Surprise Delta" criterion.

  * ``corpus_grounded_audience_overlap_M`` — median worldwide gross of
    the returned comps in $M; ``None`` if every comp has no gross.

Genre inference uses three engine fields:
  * ``scores.primary_cluster`` (one of the 8 ``_CLUSTER_NAMES``)
  * ``scores.arc_shape_6`` (one of 6 Reagan/Kim/Dodds shapes)
  * ``world_texture.name`` (free-text — keyword-matched)

These are deliberately heuristic. The films corpus has no engine-style
dimensions to align with directly; the only structured overlap is genres.

MUST NOT import LLM clients. MUST NOT import from frameworks/.
"""

from __future__ import annotations

import logging
from typing import Any, Final, cast

from pipeline.crystallize.corpus import Film, FilmsCorpus, roi

_log = logging.getLogger(__name__)

_DEFAULT_K: Final[int] = 5

# Map engine cluster id (string from _CLUSTER_NAMES) to film genre hints.
_CLUSTER_GENRE_HINTS: Final[dict[str, tuple[str, ...]]] = {
    "institutional": ("drama", "thriller", "mystery", "crime"),
    "emotional": ("drama", "romance", "family"),
    "technology": ("sci-fi", "thriller", "action"),
    "identity": ("drama", "mystery", "fantasy"),
    "nature": ("adventure", "drama", "fantasy", "family"),
    "economic": ("drama", "crime", "thriller"),
    "temporal": ("drama", "sci-fi", "mystery", "fantasy"),
    "civilizational": ("drama", "sci-fi", "adventure", "fantasy", "action"),
}

# Map arc_shape_6 (Reagan/Kim/Dodds 2016) to film genre hints.
_ARC_GENRE_HINTS: Final[dict[str, tuple[str, ...]]] = {
    "Cinderella": ("drama", "romance"),
    "Man in a Hole": ("drama", "thriller"),
    "Rags to Riches": ("drama", "crime"),
    "Icarus": ("drama", "thriller"),
    "Oedipus": ("drama", "mystery"),
    "Tragedy": ("drama",),
}

# Map keywords in world_texture.name to film genre hints.
_WORLD_KEYWORD_HINTS: Final[dict[str, tuple[str, ...]]] = {
    "ai": ("sci-fi", "thriller"),
    "artificial": ("sci-fi", "thriller"),
    "algorithmic": ("sci-fi", "thriller"),
    "lab": ("sci-fi", "drama"),
    "alien": ("sci-fi", "adventure"),
    "prison": ("crime", "drama"),
    "court": ("drama", "thriller"),
    "tribunal": ("drama", "thriller"),
    "war": ("action", "drama", "war"),
    "battle": ("action", "war"),
    "hospital": ("drama",),
    "clinic": ("drama", "thriller"),
    "village": ("drama",),
    "elder": ("drama",),
    "child": ("drama", "family"),
    "school": ("drama",),
    "university": ("drama",),
    "factory": ("drama", "thriller"),
    "ship": ("adventure", "drama"),
    "submarine": ("adventure", "thriller"),
    "space": ("sci-fi", "adventure"),
    "newsroom": ("drama", "thriller"),
    "embassy": ("drama", "thriller"),
    "border": ("drama", "thriller"),
    "monastery": ("drama",),
    "cult": ("drama", "thriller", "horror"),
    "haunted": ("horror", "mystery"),
    "ghost": ("horror", "mystery"),
    "forest": ("adventure", "drama"),
    "desert": ("drama", "adventure"),
    "city": ("drama", "thriller"),
    # R6a: reach the high-gross animation/fantasy/family/comedy/sport/western
    # corpus genres that the 11-genre vocabulary left structurally unreachable —
    # the $1B+ tentpoles (Ne Zha, Zootopia, Inside Out, Avatar) can now be comps,
    # which both breaks the A.I.-(2001) monoculture and lifts the SOM ceiling.
    "enchant": ("fantasy", "adventure", "family"),
    "magic": ("fantasy", "adventure", "family"),
    "realm": ("fantasy", "adventure"),
    "kingdom": ("fantasy", "adventure", "action"),
    "myth": ("fantasy", "adventure", "drama"),
    "legend": ("fantasy", "adventure", "action"),
    "fairy": ("fantasy", "family", "animation"),
    "dragon": ("fantasy", "adventure", "animation"),
    "wizard": ("fantasy", "adventure", "family"),
    "superhero": ("action", "adventure", "sci-fi"),
    "heist": ("crime", "thriller", "comedy"),
    "wedding": ("romance", "comedy"),
    "animated": ("animation", "family", "adventure"),
    "creature": ("fantasy", "horror", "adventure"),
    "monster": ("fantasy", "horror", "adventure"),
    "quest": ("adventure", "fantasy"),
    "jungle": ("adventure", "action", "family"),
    "ocean": ("adventure", "family"),
    "sport": ("sport", "drama"),
    "stadium": ("sport", "drama"),
    "western": ("western", "action"),
    "frontier": ("western", "adventure", "drama"),
}

# Fallback genres when the seed produces no recognised hints.
_FALLBACK_GENRES: Final[tuple[str, ...]] = ("drama",)

# Worldwide-gross scaling.
_USD_TO_MILLIONS: Final[float] = 1_000_000.0


_MAX_QUERY_TERMS: Final[int] = 8


def _hints_from_axis_cluster(axis_entry: dict[str, Any] | None) -> tuple[str, ...]:
    """Map an axis entry's ``thematic_cluster`` field to genre hints.

    Every axis in ``pipeline/data/compound_seed_variables.json`` (sdt_wounds,
    moral_fault_lines, divisiveness_engines, world_textures, etc.) carries
    a ``thematic_cluster`` from the same 8-cluster space as
    ``scores.primary_cluster``. Re-using ``_CLUSTER_GENRE_HINTS`` keeps the
    mapping in one place and adapts automatically when pool entries are
    added (Step 7 pool expansion). Returns an empty tuple when the entry is
    None or carries an unknown cluster.
    """
    if not axis_entry:
        return ()
    cluster = str(axis_entry.get("thematic_cluster", "")).strip().lower()
    return _CLUSTER_GENRE_HINTS.get(cluster, ())


def _infer_query_genres(seed_dict: dict[str, Any]) -> list[str]:
    """Heuristically infer film-genre candidates from one engine seed.

    Combines six signals (was three before Step 2 of the WEDGE plan):
      * scores.primary_cluster
      * scores.arc_shape_6
      * world_texture.name (keyword scan)
      * sdt_wound.thematic_cluster        (NEW Step 2)
      * moral_fault_line.thematic_cluster (NEW Step 2)
      * divisiveness_engine.thematic_cluster (NEW Step 2)

    The three NEW signals address the audited failure mode: previously
    the engine sampled 19 axes per candidate but only 3 voted on comp
    retrieval, so multi-genre films (e.g. A.I. Artificial Intelligence
    tagged drama+sci-fi+thriller) Jaccard-matched almost any query and
    won 22 of 49 leaderboard slots. With six signals voting, identical
    primary_cluster + arc + world but different wound/fault_line/
    divisiveness now produce divergent query sets — the search space the
    operator's taste model can then steer through.

    Caps the deduplicated list at ``_MAX_QUERY_TERMS`` (8) to keep
    Jaccard denominators bounded. Falls back to ``_FALLBACK_GENRES``
    when no hint resolves.
    """
    genres: list[str] = []

    scores: dict[str, Any] = cast("dict[str, Any]", seed_dict.get("scores") or {})
    primary_cluster = str(scores.get("primary_cluster", "")).strip().lower()
    if primary_cluster in _CLUSTER_GENRE_HINTS:
        genres.extend(_CLUSTER_GENRE_HINTS[primary_cluster])

    arc_shape = str(scores.get("arc_shape_6", "")).strip()
    if arc_shape in _ARC_GENRE_HINTS:
        genres.extend(_ARC_GENRE_HINTS[arc_shape])

    world_texture: dict[str, Any] = cast("dict[str, Any]", seed_dict.get("world_texture") or {})
    world_name = str(world_texture.get("name", "")).lower()
    for keyword, hints in _WORLD_KEYWORD_HINTS.items():
        if keyword in world_name:
            genres.extend(hints)

    # Step 2: three more axis signals vote via their thematic_cluster.
    for axis_key in ("sdt_wound", "moral_fault_line", "divisiveness_engine"):
        axis_entry = cast("dict[str, Any] | None", seed_dict.get(axis_key))
        genres.extend(_hints_from_axis_cluster(axis_entry))

    if not genres:
        return list(_FALLBACK_GENRES)

    # Dedupe while preserving order, cap at _MAX_QUERY_TERMS.
    seen: set[str] = set()
    deduped: list[str] = []
    for g in genres:
        gl = g.lower()
        if gl not in seen:
            seen.add(gl)
            deduped.append(gl)
            if len(deduped) >= _MAX_QUERY_TERMS:
                break
    return deduped


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        return sorted_v[mid]
    return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0


def _film_to_comp_dict(f: Film) -> dict[str, Any]:
    return {
        "title": f.title,
        "imdb_id": f.imdb_id,
        "worldwide_gross_usd": f.worldwide_gross_usd,
        "budget_usd": f.budget_usd,
        "roi": roi(f),
        "genres": list(f.genres_display),
        "release_year": f.release_year,
        "imdb_url": f.imdb_url,
        "boxofficemojo_url": f.boxofficemojo_url,
    }


def match_comps(
    seed_dict: dict[str, Any],
    corpus: FilmsCorpus,
    k: int = _DEFAULT_K,
) -> dict[str, Any]:
    """Match a compound-seed candidate to the films corpus.

    Args:
        seed_dict: A ``CompoundSeedResult.to_dict()`` output.
        corpus: Loaded FilmsCorpus (may be empty when corpus is unavailable).
        k: Number of comps to return (default 5).

    Returns:
        Dict with keys:
          * ``comps``: list of dicts (one per matched film, max k entries)
          * ``derivative_distance``: 0.0-1.0, novelty vs best comp
          * ``corpus_grounded_audience_overlap_M``: median ww gross in $M,
            or None when no comp has a gross figure
          * ``query_genres``: the genres we inferred (for debugging / HTML)
    """
    query_genres = _infer_query_genres(seed_dict)

    if len(corpus) == 0:
        return {
            "comps": [],
            "derivative_distance": 1.0,
            "corpus_grounded_audience_overlap_M": None,
            "query_genres": query_genres,
        }

    comp_films = corpus.find_comps(query_genres, k=k)
    if not comp_films:
        return {
            "comps": [],
            "derivative_distance": 1.0,
            "corpus_grounded_audience_overlap_M": None,
            "query_genres": query_genres,
        }

    query_set = set(query_genres)
    max_jaccard = max(_jaccard(query_set, set(f.genres)) for f in comp_films)
    derivative_distance = max(0.0, min(1.0, 1.0 - max_jaccard))

    ww_values = [
        f.worldwide_gross_usd / _USD_TO_MILLIONS
        for f in comp_films
        if f.worldwide_gross_usd is not None
    ]
    median_M = _median(ww_values)

    return {
        "comps": [_film_to_comp_dict(f) for f in comp_films],
        "derivative_distance": derivative_distance,
        "corpus_grounded_audience_overlap_M": median_M,
        "query_genres": query_genres,
    }


def infer_query_genres(seed_dict: dict[str, Any]) -> list[str]:
    """Public alias for ``_infer_query_genres``.

    Exposed for use by sibling modules (e.g.,
    ``pipeline.crystallize.revenue``) that need the same genre-inference
    heuristic without reaching across the private namespace.
    """
    return _infer_query_genres(seed_dict)


__all__ = ["infer_query_genres", "match_comps"]
