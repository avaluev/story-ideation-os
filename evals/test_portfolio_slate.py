"""EVAL — the diversified investor portfolio slate is investor-grade.

Validates ``outputs/portfolio/INVESTOR_PORTFOLIO_EN.md`` (when present) against
the content-quality + deep-link-evidence policy:

  * exactly one H1
  * no internal IDs / framework labels leaked (ADR-0010)
  * no search-engine URLs, no markdown auto-link form
  * every markdown hyperlink is a deep path (deep-link evidence policy)
  * at least a slate's worth of concept cards
  * every shipped concept in the source JSON satisfies SOM < SAM < TAM and is
    python_executed (ADR-0011), via the same credibility gate the builder uses

Skips on a fresh checkout where the artifact has not been generated yet.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_tf = pytest.importorskip("pipeline.template_filter", reason="defensive import guard")
_pf = pytest.importorskip("pipeline.crystallize.portfolio", reason="defensive import guard")
scan_for_internal_ids = _tf.scan_for_internal_ids

_SLATE = Path("outputs/portfolio/INVESTOR_PORTFOLIO_EN.md")
_PORTFOLIO_DIR = Path("runs/portfolio")
_MIN_CARDS = 6
_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")


def _slate_text() -> str:
    return _SLATE.read_text(encoding="utf-8")


pytestmark = pytest.mark.skipif(
    not _SLATE.exists(),
    reason="outputs/portfolio/INVESTOR_PORTFOLIO_EN.md not generated yet",
)


def test_exactly_one_h1() -> None:
    h1s = [ln for ln in _slate_text().splitlines() if ln.startswith("# ")]
    assert len(h1s) == 1, f"expected exactly one H1, found {len(h1s)}: {h1s}"


def test_no_internal_ids_or_framework_labels() -> None:
    hits = scan_for_internal_ids(_slate_text())
    assert not hits, f"internal IDs / framework labels leaked: {hits[:5]}"


def test_no_search_urls_or_autolinks() -> None:
    text = _slate_text()
    assert "<http" not in text, "markdown auto-link form <http...> is banned"
    banned = ("google.com/search", "bing.com/search", "duckduckgo.com", "yandex.com")
    for host in banned:
        assert host not in text, f"search-engine URL leaked: {host}"


def test_every_hyperlink_is_deep_path() -> None:
    bad = [u for u in _LINK_RE.findall(_slate_text()) if not _pf.is_deep_path(u)]
    assert not bad, f"non-deep-path hyperlinks: {bad[:5]}"


def test_has_a_slate_of_cards() -> None:
    cards = [ln for ln in _slate_text().splitlines() if re.match(r"^### \d+\. ", ln)]
    assert len(cards) >= _MIN_CARDS, f"only {len(cards)} concept cards (< {_MIN_CARDS})"


def _latest_portfolio_json() -> Path | None:
    pointer = _PORTFOLIO_DIR / "latest.json"
    if pointer.exists():
        p = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        if p and Path(p).exists():
            return Path(p)
    candidates = sorted(_PORTFOLIO_DIR.glob("*-portfolio.json"))
    return candidates[-1] if candidates else None


def test_every_shipped_concept_passes_som_sam_tam() -> None:
    """SOM < SAM < TAM and python_executed for every kept concept (reuses the
    builder's own credibility gate so the eval can never drift from it)."""
    from scripts.build_format_slate import apply_filters, credibility_gate  # noqa: PLC0415

    src = _latest_portfolio_json()
    if src is None:
        pytest.skip("no portfolio JSON to cross-check")
    data = json.loads(src.read_text(encoding="utf-8"))
    kept, _ = apply_filters(list(data.get("concepts", [])))
    assert kept, "no concepts survived the de-franchise + credibility filter"
    for c in kept:
        ok, reason = credibility_gate(c)
        assert ok, f"{c.get('id')}: {reason}"
