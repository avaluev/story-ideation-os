"""scripts/build_corpus_embeddings.py — materialise the corpus FAISS-equivalent.

One-shot offline build. Reads the FilmsCorpus, concatenates each film's
log_line + synopsis, embeds with all-MiniLM-L6-v2 (cached locally — no
network required when the HF cache has it), and persists the result to
``pipeline/data/films_corpus_embeddings.npz``.

The persisted file is consumed at runtime by:
  - pipeline.empirical_genius._embedding_novelty (C002 kill-switch)
  - pipeline.loop_wedge (mean_novelty_last_20 KPI population)

Both consumers degrade gracefully when the file is absent, so this
script is safe to skip on bare checkouts and safe to re-run any time
the corpus or model changes.

Run:
  PYTHONPATH=. uv run python scripts/build_corpus_embeddings.py
"""

from __future__ import annotations

import logging
import sys

from pipeline.crystallize.corpus import FilmsCorpus
from pipeline.crystallize.embeddings import DEFAULT_INDEX_PATH, build_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_log = logging.getLogger("build_corpus_embeddings")

_MIN_FILMS_FOR_BUILD = 50


def _film_text(log_line: str, synopsis: str, title: str) -> str:
    """Build the embedding input. Prefer log_line + synopsis when available;
    fall back to title to keep degenerate films in the index (avoids
    crash-on-empty during encode)."""
    parts = [p.strip() for p in (log_line, synopsis) if p and p.strip()]
    if parts:
        return " ".join(parts)
    return title


def main() -> int:
    corpus = FilmsCorpus.load()
    if len(corpus.films) < _MIN_FILMS_FOR_BUILD:
        _log.error(
            "Refusing to build: only %d films loaded (need >= %d). Did the corpus path change?",
            len(corpus.films),
            _MIN_FILMS_FOR_BUILD,
        )
        return 1

    texts_by_slug: dict[str, str] = {}
    skipped = 0
    for f in corpus.films:
        text = _film_text(f.log_line, f.synopsis, f.title)
        if not text:
            skipped += 1
            continue
        texts_by_slug[f.slug] = text

    _log.info(
        "build_corpus_embeddings: %d films -> embedding (%d skipped for empty text)",
        len(texts_by_slug),
        skipped,
    )

    index = build_index(texts_by_slug)
    _log.info(
        "build_corpus_embeddings: wrote %s with %d embeddings",
        DEFAULT_INDEX_PATH,
        len(index.slugs),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
