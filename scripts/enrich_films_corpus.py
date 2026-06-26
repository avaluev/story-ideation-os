"""Enrich every film in the corpus with TMDB prose (v6.0 Stage E3a).

Reads ``Inputs/10May/knowledge/corpus/deep_data/films/*.json`` (the existing
~588-film corpus), resolves each IMDb id to a TMDB movie id via
``TMDBClient.find_by_imdb_id``, fetches ``/movie/{id}`` with
``append_to_response=keywords``, and writes one row per film to::

    pipeline/data/films_corpus_enriched.jsonl

Each row carries::

    {
      "slug":        "<filename stem>",
      "imdb_id":     "ttNNNNNNN" | null,
      "tmdb_id":     int | null,
      "log_line":    "<first sentence of overview>" | "",
      "tagline":     "<TMDB tagline>" | "",
      "synopsis":    "<TMDB overview, verbatim>" | "",
      "domain_tags": ["keyword1", "keyword2", ...],
      "mood_palette":["mood_label1", ...],
      "produced_at": "<ISO-8601 UTC>",
      "source":      "tmdb"
    }

Safe by construction
--------------------
- **Idempotent**: skips slugs already present in the enrichment cache.
- **Atomic writes** via ``pipeline.state.append_jsonl`` (O_APPEND).
- **No LLM call**: ``log_line`` is the first sentence of the TMDB overview
  by a deterministic regex split — no model in the loop.
- **No literal numeric fabrication**: this is text prose only; no SOM /
  TAM / revenue numbers (ADR-0011 unaffected).

Network handoff
---------------
Per the v6.0 master plan + the sandbox protections in CLAUDE.md
(``MUST NOT read .env* post-P0``), this script is **operator-side
tooling**. The agent ships the script + dataclass migration + test +
consumer-map rows. The operator runs::

    uv run python scripts/enrich_films_corpus.py

after putting a TMDB key in ``.env`` (``TMDB_API_KEY`` or
``TMDB_READ_TOKEN``). The corpus loader (``FilmsCorpus.load``) silently
falls back to empty prose when the cache is absent, so v5 code paths
keep working until the operator runs the fetch.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pipeline.state import append_jsonl
from pipeline.tmdb_client import TMDBClient, TMDBError

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_DEFAULT_CORPUS_ROOT: Final[Path] = (
    _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"
)
_DEFAULT_ENRICHED_PATH: Final[Path] = (
    _REPO_ROOT / "pipeline" / "data" / "films_corpus_enriched.jsonl"
)
_DEFAULT_MOOD_MAP_PATH: Final[Path] = _REPO_ROOT / "scripts" / "data" / "film_mood_keywords.json"
_PROGRESS_LOG_PATH: Final[Path] = _REPO_ROOT / "data" / "run_log.jsonl"

_RATE_LIMIT_SLEEP_S: Final[float] = 0.025  # 40 req/sec ceiling per TMDB ToS
_PROGRESS_EVERY: Final[int] = 50

# First-sentence splitter. Conservative: split on `.!?` followed by space + capital,
# or at end of string. Honours abbreviations crudely — TMDB overviews rarely use them.
_SENTENCE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\'])")


# ── Helpers ────────────────────────────────────────────────────────────────


def _first_sentence(text: str) -> str:
    """Return the first sentence of ``text`` (deterministic — no LLM call)."""
    if not text:
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""
    parts = _SENTENCE_SPLIT_RE.split(cleaned, maxsplit=1)
    return parts[0].strip() if parts else cleaned


def _normalise_keyword(kw: str) -> str:
    """Lowercase + collapse whitespace for keyword lookup."""
    return " ".join(kw.lower().split())


def _extract_keywords(payload: dict[str, Any]) -> list[str]:
    """Pull plain-text keyword names from a TMDB movie payload.

    The ``keywords`` sub-resource lives at ``payload["keywords"]["keywords"]``
    on the movie endpoint (the ``tv`` endpoint uses ``"results"`` instead —
    movies use ``"keywords"``). Defensive: returns ``[]`` for any malformed
    nesting.
    """
    kw_block_any: Any = payload.get("keywords")
    if not isinstance(kw_block_any, dict):
        return []
    kw_block: dict[str, Any] = kw_block_any
    raw_any: Any = kw_block.get("keywords") or kw_block.get("results")
    if not isinstance(raw_any, list):
        return []
    out: list[str] = []
    for entry_any in raw_any:
        if not isinstance(entry_any, dict):
            continue
        entry: dict[str, Any] = entry_any
        name_any: Any = entry.get("name")
        if isinstance(name_any, str) and name_any.strip():
            out.append(name_any.strip())
    return out


def _load_mood_map(path: Path) -> dict[str, str]:
    """Read the keyword → mood JSON, dropping schema/metadata keys."""
    raw_any: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_any, dict):
        raise ValueError(f"mood map at {path} is not a JSON object")
    out: dict[str, str] = {}
    for key, value in raw_any.items():
        if not isinstance(key, str) or key.startswith("_"):
            continue
        if isinstance(value, str) and value.strip():
            out[_normalise_keyword(key)] = value.strip()
    return out


def _derive_mood_palette(keywords: list[str], mood_map: dict[str, str]) -> list[str]:
    """Map each TMDB keyword to a mood label; drop unknowns; dedupe preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for kw in keywords:
        mood = mood_map.get(_normalise_keyword(kw))
        if mood and mood not in seen:
            seen.add(mood)
            out.append(mood)
    return out


# ── Cache (idempotency) ────────────────────────────────────────────────────


def _load_existing_slugs(path: Path) -> set[str]:
    """Read the enrichment JSONL and return the set of slugs already written.

    Malformed lines are skipped (defensive — never crash on a partial file).
    Returns an empty set when the file does not exist yet.
    """
    if not path.exists():
        return set()
    out: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed: Any = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                slug_any: Any = parsed.get("slug")
                if isinstance(slug_any, str) and slug_any:
                    out.add(slug_any)
    return out


# ── Corpus iteration ───────────────────────────────────────────────────────


def _iter_corpus_rows(corpus_root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(slug, raw_dict), ...]`` for every readable corpus JSON."""
    out: list[tuple[str, dict[str, Any]]] = []
    for json_path in sorted(corpus_root.glob("*.json")):
        slug = json_path.stem
        try:
            parsed: Any = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("enrich: skipping %s (%s)", json_path.name, exc)
            continue
        if isinstance(parsed, dict):
            out.append((slug, parsed))
    return out


def _resolve_tmdb_id(client: TMDBClient, row: dict[str, Any]) -> int | None:
    """Find a TMDB movie id for a corpus row.

    Strategy:
    1. ``source_tmdb_id`` (present on TMDB-sourced rows from
       ``expand_from_tmdb.py``) → use directly.
    2. ``imdb_id`` → call ``/find`` to resolve.
    3. No usable id → return ``None``.
    """
    tmdb_id_any: Any = row.get("source_tmdb_id")
    if isinstance(tmdb_id_any, int) and tmdb_id_any > 0:
        return tmdb_id_any
    imdb_id_any: Any = row.get("imdb_id")
    if isinstance(imdb_id_any, str) and imdb_id_any.startswith("tt"):
        return client.find_by_imdb_id(imdb_id_any)
    return None


# ── Main loop ──────────────────────────────────────────────────────────────


def _make_row(
    slug: str,
    raw: dict[str, Any],
    tmdb_id: int,
    detail: dict[str, Any],
    mood_map: dict[str, str],
) -> dict[str, Any]:
    """Build the enrichment JSONL row for one film."""
    overview_any: Any = detail.get("overview")
    tagline_any: Any = detail.get("tagline")
    overview = overview_any.strip() if isinstance(overview_any, str) else ""
    tagline = tagline_any.strip() if isinstance(tagline_any, str) else ""
    keywords = _extract_keywords(detail)
    mood_palette = _derive_mood_palette(keywords, mood_map)
    imdb_id_any: Any = raw.get("imdb_id")
    imdb_id = imdb_id_any if isinstance(imdb_id_any, str) else None
    return {
        "slug": slug,
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
        "log_line": _first_sentence(overview),
        "tagline": tagline,
        "synopsis": overview,
        "domain_tags": keywords,
        "mood_palette": mood_palette,
        "produced_at": datetime.now(UTC).isoformat(),
        "source": "tmdb",
    }


def _process_one(
    *,
    client: TMDBClient,
    slug: str,
    raw: dict[str, Any],
    mood_map: dict[str, str],
    enriched_path: Path,
    dry_run: bool,
) -> str:
    """Process a single corpus row. Returns one of:
    ``"fetch_errors" | "no_id" | "written"``.
    """
    try:
        tmdb_id = _resolve_tmdb_id(client, raw)
    except TMDBError as exc:
        _log.warning("enrich: id-resolve failed for %s (%s)", slug, exc)
        return "fetch_errors"

    if tmdb_id is None:
        return "no_id"

    try:
        detail = client.movie_full(tmdb_id, extra_append=("keywords",))
    except TMDBError as exc:
        _log.warning(
            "enrich: detail-fetch failed for %s tmdb=%d (%s)",
            slug,
            tmdb_id,
            exc,
        )
        return "fetch_errors"

    row_out = _make_row(slug, raw, tmdb_id, detail, mood_map)
    if not dry_run:
        append_jsonl(enriched_path, row_out)
    return "written"


def _log_progress(stats: dict[str, int]) -> None:
    _log.info(
        "enrich: progress %d written / %d (skipped=%d, errors=%d, no_id=%d)",
        stats["written"],
        stats["corpus_rows"],
        stats["skipped_existing"],
        stats["fetch_errors"],
        stats["no_id"],
    )


def enrich(
    *,
    corpus_root: Path,
    enriched_path: Path,
    mood_map_path: Path,
    sleep_s: float = _RATE_LIMIT_SLEEP_S,
    client: TMDBClient | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Run the enrichment loop. Returns counter stats."""
    mood_map = _load_mood_map(mood_map_path)
    rows = _iter_corpus_rows(corpus_root)
    existing = _load_existing_slugs(enriched_path)
    stats: dict[str, int] = {
        "corpus_rows": len(rows),
        "skipped_existing": 0,
        "no_id": 0,
        "fetch_errors": 0,
        "written": 0,
    }

    owns_client = client is None
    if client is None:
        client = TMDBClient.from_env()

    try:
        for slug, raw in rows:
            if slug in existing:
                stats["skipped_existing"] += 1
                continue
            status = _process_one(
                client=client,
                slug=slug,
                raw=raw,
                mood_map=mood_map,
                enriched_path=enriched_path,
                dry_run=dry_run,
            )
            stats[status] += 1
            if status == "written" and stats["written"] % _PROGRESS_EVERY == 0:
                _log_progress(stats)
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        if owns_client:
            with contextlib.suppress(Exception):
                client.close()

    # ADR-0001 — append a single summary row to data/run_log.jsonl on completion.
    with contextlib.suppress(OSError):
        append_jsonl(
            _PROGRESS_LOG_PATH,
            {
                "ts": datetime.now(UTC).isoformat(),
                "event": "enrich_films_corpus_summary",
                **stats,
            },
        )

    return stats


# ── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich the existing films corpus with TMDB prose (tagline + overview + keywords). "
            "Writes pipeline/data/films_corpus_enriched.jsonl idempotently."
        )
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=_DEFAULT_CORPUS_ROOT,
        help="Source corpus directory (default = live Crystallize corpus).",
    )
    parser.add_argument(
        "--enriched-path",
        type=Path,
        default=_DEFAULT_ENRICHED_PATH,
        help="Destination JSONL (default = pipeline/data/films_corpus_enriched.jsonl).",
    )
    parser.add_argument(
        "--mood-map",
        type=Path,
        default=_DEFAULT_MOOD_MAP_PATH,
        help="Keyword → mood-label JSON (default = scripts/data/film_mood_keywords.json).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=_RATE_LIMIT_SLEEP_S,
        help="Sleep between requests in seconds (40 req/sec ceiling).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve + fetch but do not write the enriched JSONL.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show INFO-level logs (progress every 50 fetches).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    try:
        stats = enrich(
            corpus_root=Path(args.corpus_root),
            enriched_path=Path(args.enriched_path),
            mood_map_path=Path(args.mood_map),
            sleep_s=float(args.sleep),
            dry_run=bool(args.dry_run),
        )
    except TMDBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print()
    print("─" * 60)
    print(f"TMDB corpus enrichment → {args.enriched_path}")
    for key, val in stats.items():
        print(f"  {key:<18s} {val}")
    print("─" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
