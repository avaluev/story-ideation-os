"""EVAL — the diversified portfolio slate is *distinct*, card to card.

Companion to ``evals/test_portfolio_slate.py``. Where that eval proves each card
is investor-grade in isolation (one H1, deep-link evidence, SOM<SAM<TAM), this
one proves the cards do not bleed into each other on the page — the failure a
sophisticated investor catches when a slate reads as one idea wearing six hats:

  * **Title distinctiveness** — no two shipped titles share a salient token
    (singularised, so 'Hour' and 'Hours' collide; stop-words ignored). This is
    the exact failure the P5 adversarial review surfaced (4 collisions:
    quiet x4, hour x3, last x3, room x2) and the rename pass fixed.
  * **Logline distinctiveness** — no two loglines exceed a content-word Jaccard
    ceiling (the real distinct slate peaks at 0.275; the gate sits at 0.50).
  * **Comp depth + provenance** — every shipped concept carries >=3 comps, each
    with a deep IMDB or Box-Office-Mojo link (the corpus always supplies both).

Validates the SHIPPED artifact (``INVESTOR_PORTFOLIO_EN.md``) for titles and
loglines, and the portfolio JSON it was built from for comps. Skips cleanly on a
fresh checkout where neither has been generated (mirrors the slate eval).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_pf = pytest.importorskip("pipeline.crystallize.portfolio", reason="defensive import guard")

_SLATE = Path("outputs/portfolio/INVESTOR_PORTFOLIO_EN.md")
_PORTFOLIO_DIR = Path("runs/portfolio")

#: ``### 12. The Last Quiet Hour — Returning Series`` -> title = "The Last Quiet Hour".
_CARD_RE = re.compile(r"^###\s+\d+\.\s+(.+?)\s+—\s+.+$")
_LOGLINE_RE = re.compile(r"^\*\*Logline\.\*\*\s+(.+)$")
#: Content-word Jaccard above this reads as a near-duplicate logline.
_LOGLINE_JACCARD_CEILING = 0.50
_MIN_COMPS = 3

_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "into",
        "over",
        "under",
        "this",
        "that",
        "is",
        "are",
        "be",
        "as",
        "it",
        "its",
        "his",
        "her",
        "their",
        "our",
        "they",
        "them",
        "he",
        "she",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "what",
        "which",
        "but",
        "not",
        "no",
        "out",
        "up",
        "down",
        "off",
        "than",
        "then",
        "so",
        "very",
        "can",
        "will",
        "would",
        "could",
        "should",
        "must",
        "may",
        "might",
        "about",
        "after",
        "before",
        "while",
        "during",
        "against",
        "between",
        "his",
        "her",
        "their",
        "your",
        "you",
        "i",
        "we",
        "us",
    ]
)


pytestmark = pytest.mark.skipif(
    not _SLATE.exists(),
    reason="outputs/portfolio/INVESTOR_PORTFOLIO_EN.md not generated yet",
)


def _slate_text() -> str:
    return _SLATE.read_text(encoding="utf-8")


def _card_titles() -> list[str]:
    return [m.group(1).strip() for ln in _slate_text().splitlines() if (m := _CARD_RE.match(ln))]


def _loglines() -> list[str]:
    return [m.group(1).strip() for ln in _slate_text().splitlines() if (m := _LOGLINE_RE.match(ln))]


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def test_titles_are_token_distinct() -> None:
    """No salient token may appear in more than one shipped title."""
    titles = _card_titles()
    assert len(titles) >= 6, f"only parsed {len(titles)} card titles"
    pseudo = [{"id": t, "enrichment": {"title": t}} for t in titles]
    clusters = _pf.title_overlap_clusters(pseudo)
    assert not clusters, f"titles share salient tokens (read as duplicates): {clusters}"


def test_loglines_are_distinct() -> None:
    """No two loglines may exceed the content-word Jaccard ceiling."""
    loglines = _loglines()
    assert len(loglines) >= 6, f"only parsed {len(loglines)} loglines"
    toks = [_content_tokens(ll) for ll in loglines]
    worst = 0.0
    worst_pair = ()
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            if not toks[i] or not toks[j]:
                continue
            jac = len(toks[i] & toks[j]) / len(toks[i] | toks[j])
            if jac > worst:
                worst, worst_pair = jac, (loglines[i][:50], loglines[j][:50])
    assert worst <= _LOGLINE_JACCARD_CEILING, (
        f"two loglines too similar (Jaccard {worst:.3f} > {_LOGLINE_JACCARD_CEILING}): {worst_pair}"
    )


def _latest_portfolio_json() -> Path | None:
    pointer = _PORTFOLIO_DIR / "latest.json"
    if pointer.exists():
        p = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        if p and Path(p).exists():
            return Path(p)
    candidates = sorted(_PORTFOLIO_DIR.glob("*-portfolio.json"))
    return candidates[-1] if candidates else None


def test_every_concept_has_deep_linked_comps() -> None:
    """Every shipped concept carries >=3 comps, each with a deep IMDB / BOM link."""
    from scripts.build_format_slate import apply_filters  # noqa: PLC0415

    src = _latest_portfolio_json()
    if src is None:
        pytest.skip("no portfolio JSON to cross-check comps")
    data = json.loads(src.read_text(encoding="utf-8"))
    kept, _ = apply_filters(list(data.get("concepts", [])))
    assert kept, "no concepts survived the de-franchise + credibility filter"
    for c in kept:
        comps = c.get("comps") or []
        assert len(comps) >= _MIN_COMPS, f"{c.get('id')}: only {len(comps)} comps (< {_MIN_COMPS})"
        for cm in comps[:_MIN_COMPS]:
            url = str(cm.get("boxofficemojo_url") or cm.get("imdb_url") or "").strip()
            assert _pf.is_deep_path(url), (
                f"{c.get('id')} comp {cm.get('title')!r}: shallow url {url!r}"
            )
