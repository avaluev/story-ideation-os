"""Expand the films knowledge base from ~294 to up to N rows via TMDB.

Operator CLI:

    uv run python -m scripts.corpus.expand_from_tmdb --target 3000

Discovers candidate TMDB movie IDs from three list endpoints
(``movie/top_rated``, ``movie/popular``, ``discover/movie``),
dedupes by id, fetches each via ``GET /movie/{id}?append_to_response=
credits,external_ids,release_dates`` (one HTTP call per film), and writes
each result to::

    Inputs/10May/knowledge/corpus/deep_data/films/tmdb-{tmdb_id}-{slug}.json

The on-disk shape is byte-compatible with the existing 294 rows so
``pipeline.crystallize.corpus.FilmsCorpus`` picks them up with **zero**
loader changes. Source provenance is recorded in ``"source": "tmdb"``.

Safe by construction
--------------------
- **Idempotent**: existing target files are never overwritten. Re-runs
  resume from the last unfetched id.
- **Atomic writes** via ``pipeline.state.safe_write`` — no partial JSON
  files visible to the loader at any moment.
- **No secret leakage**: every key is masked in logs (8-char prefix).
- **Dry-run** mode prints the plan + first 5 fetched titles without
  writing anything to disk.

This script is **offline tooling** — it is not imported anywhere in the
runtime pipeline and adds no runtime dependency.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Final

from pipeline.state import safe_write
from pipeline.tmdb_client import TMDBClient, TMDBError

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS_ROOT: Final[Path] = (
    _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"
)
_DEFAULT_TARGET: Final[int] = 3000
_DEFAULT_SOURCES: Final[tuple[str, ...]] = ("top_rated", "popular", "discover")
_DRY_RUN_PREVIEW_N: Final[int] = 5
_SLUG_MAX_LEN: Final[int] = 60
_SLUG_INVALID_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_PROGRESS_LOG_NAME: Final[str] = "_tmdb_expansion_progress.jsonl"

# Soft per-endpoint share of the discovery budget. The script over-pulls and
# dedupes across endpoints, so these are loose targets — not strict caps.
_ENDPOINT_TARGET_MULTIPLIER: Final[float] = 1.2
_DISCOVERY_POOL_MULTIPLIER: Final[int] = 2  # candidate pool ceiling vs target
_YEAR_PREFIX_LEN: Final[int] = 4
_TMDB_SLUG_MIN_PARTS: Final[int] = 2
_PROGRESS_LOG_EVERY: Final[int] = 50


# ── slug / formatting helpers ───────────────────────────────────────────────


def make_slug(title: str) -> str:
    """Lowercase-kebab a film title, truncated to ``_SLUG_MAX_LEN`` characters."""
    lowered = title.strip().lower()
    kebab = _SLUG_INVALID_RE.sub("-", lowered).strip("-")
    return kebab[:_SLUG_MAX_LEN].rstrip("-") or "untitled"


def slug_for_tmdb_film(tmdb_id: int, title: str) -> str:
    """Namespaced slug for TMDB-sourced rows: ``tmdb-<id>-<title-kebab>``.

    Namespacing prevents any collision with the existing BOM-sourced rows
    and makes provenance visible at a glance in the corpus directory.
    """
    return f"tmdb-{tmdb_id}-{make_slug(title)}"


def _format_dollars(value: object) -> str:
    """Format a TMDB integer revenue/budget to the corpus ``"$1,234,567"`` shape.

    Returns ``"N/A"`` for falsy or non-numeric values (matches the
    existing rows where data is missing). The loader handles both
    cleanly via ``_parse_dollars``.
    """
    if not isinstance(value, int | float):
        return "N/A"
    if value <= 0:
        return "N/A"
    return f"${int(value):,}"


def _format_runtime(minutes: object) -> str:
    """Format TMDB ``runtime`` minutes as ``"1 hr 44 min"`` or ``"N/A"``."""
    if not isinstance(minutes, int) or minutes <= 0:
        return "N/A"
    hours, mins = divmod(minutes, 60)
    if hours == 0:
        return f"{mins} min"
    return f"{hours} hr {mins} min"


def _mpaa_from_release_dates(payload: object, country: str = "US") -> str:
    """Extract the US theatrical certification from ``release_dates`` if present.

    Returns ``"N/A"`` when missing — the loader is tolerant of that value.
    """
    if not isinstance(payload, dict):
        return "N/A"
    results = payload.get("results")
    if not isinstance(results, list):
        return "N/A"
    for entry in results:
        if not isinstance(entry, dict):
            continue
        if entry.get("iso_3166_1") != country:
            continue
        certs = entry.get("release_dates")
        if not isinstance(certs, list):
            continue
        for cert in certs:
            if not isinstance(cert, dict):
                continue
            value = cert.get("certification")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "N/A"


def _genre_names(genres_field: object) -> list[str]:
    """Return the TMDB ``genres: [{id, name}]`` list as plain name strings."""
    if not isinstance(genres_field, list):
        return []
    names: list[str] = []
    for g in genres_field:
        if not isinstance(g, dict):
            continue
        name = g.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _first_distributor(production_companies: object) -> str | None:
    """First non-empty production company name (proxy for distributor)."""
    if not isinstance(production_companies, list):
        return None
    for c in production_companies:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _pro_imdb_link(person_id: object) -> str | None:
    if not isinstance(person_id, int):
        return None
    return f"https://pro.imdb.com/name/nm{person_id:07d}/"


def _format_cast(credits: object, top_n: int = 10) -> list[dict[str, Any]]:
    if not isinstance(credits, dict):
        return []
    raw = credits.get("cast")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for c in raw[:top_n]:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        role = c.get("character") or ""
        out.append(
            {
                "name": name if isinstance(name, str) else "",
                "role": role if isinstance(role, str) else "",
                "link": _pro_imdb_link(c.get("id")),
            }
        )
    return out


_WANTED_CREW_JOBS: Final[frozenset[str]] = frozenset(
    {
        "Director",
        "Writer",
        "Screenplay",
        "Producer",
        "Executive Producer",
        "Composer",
        "Original Music Composer",
        "Director of Photography",
        "Cinematography",
        "Editor",
        "Production Design",
        "Production Designer",
    }
)


def _format_crew(credits: object) -> list[dict[str, Any]]:
    if not isinstance(credits, dict):
        return []
    raw = credits.get("crew")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for c in raw:
        if not isinstance(c, dict):
            continue
        job = c.get("job")
        if not isinstance(job, str) or job not in _WANTED_CREW_JOBS:
            continue
        name = c.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        key = (name, job)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "role": job,
                "link": _pro_imdb_link(c.get("id")),
            }
        )
    return out


def _imdb_url(imdb_id: object) -> str | None:
    if not isinstance(imdb_id, str) or not imdb_id.startswith("tt"):
        return None
    return f"https://www.imdb.com/title/{imdb_id}/"


def _bom_url(imdb_id: object) -> str | None:
    if not isinstance(imdb_id, str) or not imdb_id.startswith("tt"):
        return None
    return f"https://www.boxofficemojo.com/title/{imdb_id}/"


# ── Row transformation ─────────────────────────────────────────────────────


def to_corpus_row(detail: dict[str, Any]) -> dict[str, Any]:
    """Transform a TMDB ``GET /movie/{id}`` payload to the on-disk corpus shape.

    The output is **byte-compatible** with the existing 294 rows under
    ``Inputs/10May/knowledge/corpus/deep_data/films/`` — the loader's
    ``_film_from_dict`` reads every field directly.
    """
    raw_title = detail.get("title") or detail.get("original_title") or ""
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    release_date = detail.get("release_date") if isinstance(detail.get("release_date"), str) else ""

    if title and release_date and len(release_date) >= _YEAR_PREFIX_LEN:
        year = release_date[:_YEAR_PREFIX_LEN]
        title_with_year = f"{title} ({year})" if title and year.isdigit() else title
    else:
        title_with_year = title

    external_ids = (
        detail.get("external_ids") if isinstance(detail.get("external_ids"), dict) else {}
    )
    imdb_id = external_ids.get("imdb_id") if isinstance(external_ids, dict) else None

    return {
        "title": title_with_year,
        "imdb_id": imdb_id if isinstance(imdb_id, str) else None,
        "financials": {
            # TMDB ``revenue`` is total worldwide box office. Domestic /
            # international are not split in the TMDB public API.
            "worldwide": _format_dollars(detail.get("revenue")),
            "domestic": "N/A",
            "international": "N/A",
            "budget": _format_dollars(detail.get("budget")),
        },
        "details": {
            "distributor": _first_distributor(detail.get("production_companies")),
            "release_date": release_date or "",
            "mpaa": _mpaa_from_release_dates(detail.get("release_dates")),
            "running_time": _format_runtime(detail.get("runtime")),
            "genres": _genre_names(detail.get("genres")),
        },
        "personnel": {
            "cast": _format_cast(detail.get("credits")),
            "crew": _format_crew(detail.get("credits")),
        },
        "links": {
            "imdb": _imdb_url(imdb_id),
            "boxofficemojo": _bom_url(imdb_id),
            "tmdb": f"https://www.themoviedb.org/movie/{detail.get('id')}",
        },
        "source": "tmdb",
        "source_tmdb_id": detail.get("id") if isinstance(detail.get("id"), int) else None,
    }


# ── Discovery ───────────────────────────────────────────────────────────────


_SOURCE_TO_ENDPOINT: Final[dict[str, tuple[str, dict[str, Any]]]] = {
    "top_rated": ("movie/top_rated", {}),
    "popular": ("movie/popular", {}),
    "discover": (
        "discover/movie",
        {
            "sort_by": "revenue.desc",
            "vote_count.gte": 100,
            "include_adult": "false",
        },
    ),
}


def discover_ids(client: TMDBClient, sources: list[str], target: int) -> list[int]:
    """Gather candidate TMDB movie ids across the requested sources.

    Pulls roughly ``target * _ENDPOINT_TARGET_MULTIPLIER`` ids per source to
    leave headroom for cross-source duplicates, then dedupes preserving
    first-seen order so the user-supplied source order biases the
    final list.
    """
    per_source_target = int(target * _ENDPOINT_TARGET_MULTIPLIER)
    seen: set[int] = set()
    ordered: list[int] = []
    for source in sources:
        if source not in _SOURCE_TO_ENDPOINT:
            _log.warning("expand: unknown source %r — skipping", source)
            continue
        endpoint, extras = _SOURCE_TO_ENDPOINT[source]
        _log.info(
            "expand: discovering from %s (target=%d, soft per-source=%d)",
            endpoint,
            target,
            per_source_target,
        )
        for mid in client.iter_movie_ids(endpoint, target=per_source_target, extra_params=extras):
            if mid in seen:
                continue
            seen.add(mid)
            ordered.append(mid)
            if len(ordered) >= target * _DISCOVERY_POOL_MULTIPLIER:
                # Hard ceiling: pool-multiplier x target ids is plenty.
                break
        _log.info("expand: pool size after %s = %d unique ids", endpoint, len(ordered))
        if len(ordered) >= target * _DISCOVERY_POOL_MULTIPLIER:
            break
    return ordered


# ── Skip-existing logic ────────────────────────────────────────────────────


def _existing_tmdb_ids(out_dir: Path) -> set[int]:
    """Scan ``out_dir`` for files matching ``tmdb-<id>-*.json`` and return ids.

    Used to skip already-fetched films on re-runs. Files written by the
    original BOM-sourced corpus (different naming convention) are
    invisible to this scan, so we never accidentally overwrite them.
    """
    ids: set[int] = set()
    if not out_dir.exists():
        return ids
    for path in out_dir.glob("tmdb-*.json"):
        stem = path.stem  # tmdb-{id}-{slug}
        parts = stem.split("-", 2)
        if len(parts) < _TMDB_SLUG_MIN_PARTS:
            continue
        try:
            ids.add(int(parts[1]))
        except ValueError:
            continue
    return ids


# ── Main expansion loop ────────────────────────────────────────────────────


_FETCH_OK: Final[str] = "fetched"
_FETCH_ERROR: Final[str] = "error"
_FETCH_NO_TITLE: Final[str] = "no_title"


def _fetch_row(
    client: TMDBClient,
    mid: int,
    progress_log: Path | None,
) -> tuple[str, dict[str, Any] | None]:
    """Fetch and transform one film. Returns (status, row_or_None)."""
    try:
        detail = client.movie_full(mid)
    except TMDBError as exc:
        _log.warning("expand: skipping id=%d (%s)", mid, exc)
        _append_progress(progress_log, mid, status=_FETCH_ERROR, extra={"note": str(exc)})
        return _FETCH_ERROR, None

    row = to_corpus_row(detail)
    if not row["title"]:
        _log.warning("expand: id=%d has no title; skipping", mid)
        _append_progress(progress_log, mid, status=_FETCH_NO_TITLE)
        return _FETCH_NO_TITLE, None

    return _FETCH_OK, row


def _process_id(
    client: TMDBClient,
    mid: int,
    out_dir: Path,
    *,
    existing: set[int],
    dry_run: bool,
    progress_log: Path | None,
    preview_titles: list[str],
) -> str:
    """Process one tmdb id. Returns a label that drives the stats counter."""
    if mid in existing:
        return "skipped_existing"

    fetch_status, row = _fetch_row(client, mid, progress_log)
    if row is None:
        return "errors"

    slug = slug_for_tmdb_film(mid, row["title"])
    path = out_dir / f"{slug}.json"
    if path.exists():
        return "skipped_existing"

    if dry_run:
        preview_titles.append(row["title"])
        return "preview"

    safe_write(path, json.dumps(row, ensure_ascii=False, indent=2))
    _append_progress(progress_log, mid, status="written", extra={"slug": slug})
    _ = fetch_status  # consumed; keep for future telemetry hooks.
    return "written"


def expand(
    *,
    out_dir: Path,
    target: int,
    sources: list[str],
    dry_run: bool = False,
    client: TMDBClient | None = None,
    progress_log: Path | None = None,
) -> dict[str, int]:
    """Run the discovery + fetch loop. Returns a stats dict.

    Args:
        out_dir: where to write the new ``tmdb-<id>-<slug>.json`` files.
        target: maximum number of NEW films to write (films already on
            disk are skipped and do **not** count against this target).
        sources: list of source names — any subset of
            ``("top_rated", "popular", "discover")``.
        dry_run: if True, print a plan + the first 5 fetched titles but
            write nothing to disk.
        client: optional pre-built TMDBClient (used by tests). If None,
            built from environment via ``TMDBClient.from_env()``.
        progress_log: optional path to a JSONL log of per-film results.
    """
    owns_client = client is None
    if client is None:
        client = TMDBClient.from_env()

    stats: dict[str, int] = {
        "discovered": 0,
        "skipped_existing": 0,
        "fetched": 0,
        "written": 0,
        "errors": 0,
    }

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = _existing_tmdb_ids(out_dir)
        _log.info(
            "expand: %d existing tmdb-* rows in %s; client auth=%s",
            len(existing),
            out_dir,
            client.auth_summary(),
        )

        ids = discover_ids(client, sources, target)
        stats["discovered"] = len(ids)
        _log.info("expand: discovered %d unique candidate ids", len(ids))

        preview_titles: list[str] = []
        for mid in ids:
            if stats["written"] >= target:
                break

            result = _process_id(
                client,
                mid,
                out_dir,
                existing=existing,
                dry_run=dry_run,
                progress_log=progress_log,
                preview_titles=preview_titles,
            )
            if result == "written":
                stats["fetched"] += 1
                stats["written"] += 1
                if stats["written"] % _PROGRESS_LOG_EVERY == 0:
                    _log.info(
                        "expand: progress %d/%d written (skipped=%d, errors=%d)",
                        stats["written"],
                        target,
                        stats["skipped_existing"],
                        stats["errors"],
                    )
            elif result == "preview":
                stats["fetched"] += 1
                if len(preview_titles) >= _DRY_RUN_PREVIEW_N:
                    break
            elif result in stats:
                stats[result] += 1

        if dry_run:
            _log.info("DRY RUN — would have written rows for: %s", preview_titles)
    finally:
        if owns_client:
            client.close()

    return stats


def _append_progress(
    path: Path | None,
    tmdb_id: int,
    status: str,
    extra: dict[str, str] | None = None,
) -> None:
    """Append one structured progress row to the JSONL log."""
    if path is None:
        return
    record: dict[str, Any] = {
        "ts": time.time(),
        "tmdb_id": tmdb_id,
        "status": status,
    }
    if extra:
        record.update(extra)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


# ── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expand the films knowledge base from ~294 toward N rows via TMDB. "
            "Writes byte-compatible JSON files alongside the existing rows."
        )
    )
    parser.add_argument(
        "--target",
        type=int,
        default=_DEFAULT_TARGET,
        help="Max number of NEW films to write (existing rows are skipped).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_CORPUS_ROOT,
        help="Destination directory (default = the live Crystallize corpus).",
    )
    parser.add_argument(
        "--sources",
        default=",".join(_DEFAULT_SOURCES),
        help="Comma-separated subset of: top_rated, popular, discover.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan + first 5 fetched titles without writing.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show INFO-level logs from the client and expansion loop.",
    )
    parser.add_argument(
        "--no-progress-log",
        action="store_true",
        help="Skip writing the per-film progress JSONL.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    sources = [s.strip() for s in str(args.sources).split(",") if s.strip()]
    if not sources:
        print("ERROR: --sources cannot be empty", file=sys.stderr)
        return 2

    progress_log: Path | None = None
    if not args.no_progress_log and not args.dry_run:
        progress_log = Path(args.out_dir) / _PROGRESS_LOG_NAME

    try:
        stats = expand(
            out_dir=Path(args.out_dir),
            target=int(args.target),
            sources=sources,
            dry_run=bool(args.dry_run),
            progress_log=progress_log,
        )
    except TMDBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("─" * 60)
    print(f"TMDB corpus expansion → {args.out_dir}")
    for key, val in stats.items():
        print(f"  {key:<18s} {val}")
    print("─" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
