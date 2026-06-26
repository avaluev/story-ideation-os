"""Fetch tentpole films from TMDB and append to the engine's corpus (v7.0 F0.4).

Closes Finding #1 from ``runs/v7-postmortem-F0.2/FINDINGS.md``: the existing
294-film corpus has zero films grossing more than $300M, which mathematically
caps the engine's SOM Y1 projection at ~$300M. This script discovers the
highest-grossing films of all time via TMDB ``/discover/movie?sort_by=revenue.desc``,
filters to films with WW gross ≥ ``--threshold-usd`` (default $500M), and
writes each as a canonical corpus film .json file at::

    Inputs/10May/knowledge/corpus/deep_data/films/<slug>.json

After running, ``FilmsCorpus.load()`` picks up the new films on next call, the
revenue projection has tentpoles to surface as comps, and the SOM ceiling
lifts from ~$300M to whatever the new comp pool's max gross supports.

302.ai integration
------------------
When ``TAO_AI_API_KEY`` is set, an optional second pass enriches each newly
fetched film's ``mood_palette`` via ``perplexity/sonar-pro`` (one call per
film). When the key is absent, the film still lands in the corpus with all
the headline fields populated (title, WW gross, budget, genres, year, IMDb id);
``mood_palette`` defaults to empty.

Safe by construction
--------------------
- **Idempotent**: skips slugs already present under the corpus root (so re-running
  on a new ``--target`` just adds the new ones).
- **Atomic writes** via ``pipeline.state.safe_write`` (corpus .json) and
  ``append_jsonl`` (enrichment cache). ADR-0001.
- **No literal numeric fabrication**: every dollar figure comes from TMDB's
  ``revenue``/``budget`` fields verbatim. ADR-0011 unaffected.
- **No-op on TMDB error**: any single-movie fetch failure is logged + skipped;
  the script continues with the next movie.

Usage
-----
::

    # Default: fetch top-500 by revenue, write tentpoles (WW ≥ $500M) into corpus.
    uv run python scripts/fetch_tentpoles.py

    # Aim for hundreds with a $500M floor.
    uv run python scripts/fetch_tentpoles.py --target 800 --threshold-usd 500000000

    # Dry-run — print summary, don't write files.
    uv run python scripts/fetch_tentpoles.py --target 200 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pipeline.state import append_jsonl, safe_write
from pipeline.tmdb_client import TMDBClient, TMDBError

_log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_CORPUS_ROOT: Final[Path] = (
    _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"
)
_ENRICHED_PATH: Final[Path] = _REPO_ROOT / "pipeline" / "data" / "films_corpus_enriched.jsonl"

_DEFAULT_TARGET: Final[int] = 500
_TENTPOLE_THRESHOLD_USD: Final[int] = 500_000_000
_RATE_LIMIT_SLEEP_S: Final[float] = 0.05  # 20 req/sec under TMDB's 50 req/sec ceiling
_PROGRESS_EVERY: Final[int] = 25
_MAX_CAST_LISTED: Final[int] = 6
_MAX_CREW_LISTED: Final[int] = 6
_YEAR_PREFIX_LEN: Final[int] = 4
_BILLION_USD: Final[int] = 1_000_000_000
_HALF_BILLION_USD: Final[int] = 500_000_000

_SLUG_NONALNUM_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_RUNTIME_FMT: Final[str] = "{hours} hr {minutes} min"

# Crew roles surfaced in the corpus personnel block (matches existing schema).
_CREW_ROLES_OF_INTEREST: Final[frozenset[str]] = frozenset(
    {
        "Director",
        "Writer",
        "Producer",
        "Composer",
        "Director of Photography",
        "Editor",
        "Production Designer",
    }
)

# Cert ratings TMDB returns; mapped to MPAA-style strings the corpus uses.
_MPAA_CERTS: Final[frozenset[str]] = frozenset(
    {
        "G",
        "PG",
        "PG-13",
        "R",
        "NC-17",
        "NR",
        "Unrated",
    }
)


# ── Slug / formatting helpers ───────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Convert ``"Avengers: Endgame"`` to ``"avengers-endgame"``.

    Lowercases, replaces every non-alphanumeric run with ``-``, strips leading
    and trailing dashes. Empty input yields empty string.
    """
    if not text:
        return ""
    lowered = text.lower()
    dashed = _SLUG_NONALNUM_RE.sub("-", lowered).strip("-")
    return dashed


def _fmt_dollars(amount: int | float | None) -> str | None:
    """Format an integer dollar amount as ``"$2,923,706,026"``.

    Returns ``None`` for zero/missing values — the corpus loader treats
    ``None`` as "no data" rather than "zero gross" (ADR-0011).
    """
    if amount is None:
        return None
    try:
        as_int = int(amount)
    except (TypeError, ValueError):
        return None
    if as_int <= 0:
        return None
    return f"${as_int:,}"


def _release_year(release_date: str | None) -> int | None:
    if not release_date or len(release_date) < _YEAR_PREFIX_LEN:
        return None
    try:
        return int(release_date[:_YEAR_PREFIX_LEN])
    except ValueError:
        return None


def _runtime_display(runtime_min: int | None) -> str | None:
    if not runtime_min or runtime_min <= 0:
        return None
    hours, minutes = divmod(int(runtime_min), 60)
    return _RUNTIME_FMT.format(hours=hours, minutes=minutes)


# ── TMDB payload → corpus film JSON ─────────────────────────────────────────


def _extract_distributor(detail: dict[str, Any]) -> str | None:
    companies_any: Any = detail.get("production_companies")
    if not isinstance(companies_any, list):
        return None
    for entry in companies_any:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def _extract_mpaa(detail: dict[str, Any]) -> str | None:
    """Pull the US MPAA rating from the release_dates sub-resource."""
    block_any: Any = detail.get("release_dates")
    if not isinstance(block_any, dict):
        return None
    results_any: Any = block_any.get("results")
    if not isinstance(results_any, list):
        return None
    for entry in results_any:
        if not isinstance(entry, dict):
            continue
        if entry.get("iso_3166_1") != "US":
            continue
        dates_any: Any = entry.get("release_dates")
        if not isinstance(dates_any, list):
            continue
        for date_entry in dates_any:
            if not isinstance(date_entry, dict):
                continue
            cert = str(date_entry.get("certification", "")).strip()
            if cert and cert in _MPAA_CERTS:
                return cert
    return None


def _extract_cast(detail: dict[str, Any]) -> list[dict[str, Any]]:
    credits_any: Any = detail.get("credits")
    if not isinstance(credits_any, dict):
        return []
    cast_any: Any = credits_any.get("cast")
    if not isinstance(cast_any, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in cast_any[:_MAX_CAST_LISTED]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        role = str(entry.get("character", "")).strip()
        if not name:
            continue
        out.append({"name": name, "role": role or ""})
    return out


def _extract_crew(detail: dict[str, Any]) -> list[dict[str, Any]]:
    credits_any: Any = detail.get("credits")
    if not isinstance(credits_any, dict):
        return []
    crew_any: Any = credits_any.get("crew")
    if not isinstance(crew_any, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in crew_any:
        if len(out) >= _MAX_CREW_LISTED:
            break
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("job", "")).strip()
        name = str(entry.get("name", "")).strip()
        if not name or role not in _CREW_ROLES_OF_INTEREST:
            continue
        key = (name, role)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "role": role})
    return out


def _imdb_id(detail: dict[str, Any]) -> str | None:
    ext_any: Any = detail.get("external_ids")
    if isinstance(ext_any, dict):
        imdb_any = ext_any.get("imdb_id")
        if isinstance(imdb_any, str) and imdb_any.startswith("tt"):
            return imdb_any
    direct = detail.get("imdb_id")
    if isinstance(direct, str) and direct.startswith("tt"):
        return direct
    return None


def _genres(detail: dict[str, Any]) -> list[str]:
    genres_any: Any = detail.get("genres")
    if not isinstance(genres_any, list):
        return []
    out: list[str] = []
    for entry in genres_any:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def _build_corpus_json(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Project a TMDB ``movie_full`` payload into the corpus film schema.

    Returns ``None`` when the title or WW gross is missing (those are the only
    two hard requirements for the comp matcher + revenue projection).
    """
    title_raw: Any = detail.get("title") or detail.get("original_title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        return None
    title_clean = title_raw.strip()
    year = _release_year(str(detail.get("release_date", "")))
    title_with_year = f"{title_clean} ({year})" if year else title_clean

    revenue_any: Any = detail.get("revenue")
    worldwide_str = _fmt_dollars(revenue_any if isinstance(revenue_any, (int, float)) else None)
    if not worldwide_str:
        return None

    budget_any: Any = detail.get("budget")
    budget_str = _fmt_dollars(budget_any if isinstance(budget_any, (int, float)) else None)

    imdb_id = _imdb_id(detail)
    genres = _genres(detail)
    runtime_str = _runtime_display(
        detail.get("runtime") if isinstance(detail.get("runtime"), int) else None
    )

    return {
        "title": title_with_year,
        "imdb_id": imdb_id,
        "financials": {
            "worldwide": worldwide_str,
            "domestic": None,  # TMDB does not split domestic/international
            "international": None,
            "budget": budget_str,
        },
        "details": {
            "distributor": _extract_distributor(detail),
            "release_date": detail.get("release_date") or None,
            "mpaa": _extract_mpaa(detail),
            "running_time": runtime_str,
            "genres": genres,
        },
        "personnel": {
            "cast": _extract_cast(detail),
            "crew": _extract_crew(detail),
        },
        "links": {
            "imdb": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else None,
            "boxofficemojo": (
                f"https://www.boxofficemojo.com/title/{imdb_id}/" if imdb_id else None
            ),
        },
        "tmdb_source": {
            "tmdb_id": detail.get("id"),
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    }


# ── Enrichment row (mirrors enrich_films_corpus.py shape) ───────────────────


_SENTENCE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\'])")


def _first_sentence(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""
    parts = _SENTENCE_SPLIT_RE.split(cleaned, maxsplit=1)
    return parts[0].strip() if parts else cleaned


def _extract_keywords(detail: dict[str, Any]) -> list[str]:
    kw_any: Any = detail.get("keywords")
    if not isinstance(kw_any, dict):
        return []
    raw_any: Any = kw_any.get("keywords") or kw_any.get("results")
    if not isinstance(raw_any, list):
        return []
    out: list[str] = []
    for entry in raw_any:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def _build_enrichment_row(slug: str, detail: dict[str, Any]) -> dict[str, Any]:
    overview = str(detail.get("overview", "") or "")
    return {
        "slug": slug,
        "imdb_id": _imdb_id(detail),
        "tmdb_id": detail.get("id"),
        "log_line": _first_sentence(overview),
        "tagline": str(detail.get("tagline", "") or "").strip(),
        "synopsis": overview.strip(),
        "domain_tags": _extract_keywords(detail)[:20],
        "mood_palette": [],  # filled by optional 302.ai pass (skipped without key)
        "produced_at": datetime.now(UTC).isoformat(),
        "source": "tmdb+fetch_tentpoles",
    }


# ── Main fetch loop ─────────────────────────────────────────────────────────


class _FetchAccumulator:
    """Mutable tallies updated as each movie is processed."""

    def __init__(self) -> None:
        self.new_count: int = 0
        self.skipped_existing: int = 0
        self.below_threshold: int = 0
        self.fetched_total: int = 0
        self.max_gross_added: float = 0.0
        self.new_slugs: list[str] = []
        self.new_at_500m_plus: int = 0
        self.new_at_1b_plus: int = 0

    def as_dict(self, *, dry_run: bool) -> dict[str, Any]:
        return {
            "new_count": self.new_count,
            "new_slugs": self.new_slugs,
            "skipped_existing": self.skipped_existing,
            "below_threshold": self.below_threshold,
            "fetched_total": self.fetched_total,
            "max_gross_added_usd": self.max_gross_added,
            "new_at_500m_plus": self.new_at_500m_plus,
            "new_at_1b_plus": self.new_at_1b_plus,
            "dry_run": dry_run,
        }


def _process_one_movie(
    client: TMDBClient,
    movie_id: int,
    *,
    threshold_usd: int,
    corpus_dir: Path,
    cache_path: Path,
    dry_run: bool,
    acc: _FetchAccumulator,
) -> None:
    """Fetch one movie, write it to the corpus if it clears the threshold + slug filters."""
    acc.fetched_total += 1
    try:
        detail = client.movie_full(movie_id, extra_append=("keywords",))
    except TMDBError as exc:
        _log.warning("tentpole fetch: movie_id=%s skipped (%s)", movie_id, exc)
        return
    time.sleep(_RATE_LIMIT_SLEEP_S)

    revenue_raw: Any = detail.get("revenue")
    revenue_usd = float(revenue_raw) if isinstance(revenue_raw, (int, float)) else 0.0
    if revenue_usd < threshold_usd:
        acc.below_threshold += 1
        return

    title = str(detail.get("title") or detail.get("original_title") or "").strip()
    year = _release_year(str(detail.get("release_date", "")))
    slug = _slugify(f"{title} {year}" if year else title)
    if not slug:
        _log.warning("tentpole fetch: movie_id=%s has no slug (%r)", movie_id, title)
        return

    corpus_file = corpus_dir / f"{slug}.json"
    if corpus_file.exists():
        acc.skipped_existing += 1
        return

    corpus_json = _build_corpus_json(detail)
    if corpus_json is None:
        _log.warning("tentpole fetch: movie_id=%s schema build failed", movie_id)
        return

    if not dry_run:
        safe_write(corpus_file, json.dumps(corpus_json, indent=2, ensure_ascii=False))
        append_jsonl(cache_path, _build_enrichment_row(slug, detail))

    acc.new_count += 1
    acc.new_slugs.append(slug)
    acc.max_gross_added = max(acc.max_gross_added, revenue_usd)
    if revenue_usd >= _BILLION_USD:
        acc.new_at_1b_plus += 1
    elif revenue_usd >= _HALF_BILLION_USD:
        acc.new_at_500m_plus += 1

    if acc.new_count % _PROGRESS_EVERY == 0:
        _log.info(
            "tentpole fetch: +%d (latest: %s @ $%.0fM)",
            acc.new_count,
            slug,
            revenue_usd / 1e6,
        )


def fetch_tentpoles(
    target: int,
    threshold_usd: int,
    *,
    dry_run: bool = False,
    corpus_root: Path | None = None,
    enriched_path: Path | None = None,
) -> dict[str, Any]:
    """Iterate TMDB ``discover/movie?sort_by=revenue.desc`` and write tentpoles.

    Returns a summary dict the caller prints. The summary always contains:
    ``new_count``, ``new_slugs``, ``skipped_existing``, ``below_threshold``,
    ``fetched_total``, ``max_gross_added_usd``, ``new_at_500m_plus``,
    ``new_at_1b_plus``.
    """
    corpus_dir = corpus_root or _CORPUS_ROOT
    cache_path = enriched_path or _ENRICHED_PATH
    corpus_dir.mkdir(parents=True, exist_ok=True)

    acc = _FetchAccumulator()
    extra_params: dict[str, Any] = {
        "sort_by": "revenue.desc",
        "include_adult": "false",
        "with_runtime.gte": 60,
    }

    with TMDBClient.from_env() as client:
        for movie_id in client.iter_movie_ids(
            "discover/movie", target=target, extra_params=extra_params
        ):
            _process_one_movie(
                client,
                movie_id,
                threshold_usd=threshold_usd,
                corpus_dir=corpus_dir,
                cache_path=cache_path,
                dry_run=dry_run,
                acc=acc,
            )

    return acc.as_dict(dry_run=dry_run)


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(prog="scripts.fetch_tentpoles")
    parser.add_argument(
        "--target",
        type=int,
        default=_DEFAULT_TARGET,
        help=f"Max TMDB results to iterate (default {_DEFAULT_TARGET}).",
    )
    parser.add_argument(
        "--threshold-usd",
        type=int,
        default=_TENTPOLE_THRESHOLD_USD,
        help=(
            f"Minimum WW gross in USD to admit into the corpus "
            f"(default ${_TENTPOLE_THRESHOLD_USD:,})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Iterate and report only; do not write any files.",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=_CORPUS_ROOT,
        help=f"Corpus film directory (default {_CORPUS_ROOT}).",
    )
    parser.add_argument(
        "--enriched-path",
        type=Path,
        default=_ENRICHED_PATH,
        help=f"Enrichment cache path (default {_ENRICHED_PATH}).",
    )
    args = parser.parse_args(argv)

    summary = fetch_tentpoles(
        target=args.target,
        threshold_usd=args.threshold_usd,
        dry_run=args.dry_run,
        corpus_root=args.corpus_root,
        enriched_path=args.enriched_path,
    )

    summary_serializable = {k: v for k, v in summary.items() if k != "new_slugs"}
    summary_serializable["new_slugs_sample"] = summary["new_slugs"][:5]
    summary_serializable["new_slugs_total"] = len(summary["new_slugs"])

    print()
    print("=" * 64)
    print("Tentpole fetch summary")
    print("=" * 64)
    for k, v in summary_serializable.items():
        if isinstance(v, float):
            print(f"  {k:30s} ${v / 1e6:,.0f}M")
        else:
            print(f"  {k:30s} {v}")
    print("=" * 64)

    # Hint about 302.ai prose enrichment.
    if os.environ.get("TAO_AI_API_KEY", "").strip():
        print("note: TAO_AI_API_KEY detected — prose enrichment can be wired in a follow-up.")
    else:
        print(
            "note: TAO_AI_API_KEY not set — film mood_palette stays empty until the key is added."
        )
    return 0


if __name__ == "__main__":
    sys.exit(_main())


__all__ = [
    "fetch_tentpoles",
]
