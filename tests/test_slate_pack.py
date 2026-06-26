"""Multi-format investor slate builder — scripts.build_format_slate.

Fixture-driven (no network, no LLM): the slate spans >=5 formats, the
de-franchise hard filter drops franchise-dependent concepts, the SOM<SAM<TAM
credibility gate quarantines bad rows (never silently), and the rendered EN
markdown is investor-clean (one H1, a Format mention, no internal framework
IDs, no markdown auto-link form, deep-path URLs only).
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.template_filter import scan_for_internal_ids
from scripts.build_format_slate import (
    apply_filters,
    credibility_gate,
    render_slate_md,
    select_top1_per_format,
)

_FORMATS = [
    ("feature", "Feature Film", 420_000_000, 18_240_000_000, 152_000_000_000),
    ("limited_series", "Limited Series", 104_000_000, 3_142_000_000, 157_100_000_000),
    ("returning_series", "Returning Series", 117_000_000, 3_540_000_000, 177_000_000_000),
    ("animation_feature", "Animation Feature", 387_000_000, 18_240_000_000, 152_000_000_000),
    ("animation_series", "Animation Series", 54_000_000, 872_500_000, 17_450_000_000),
    ("microdrama", "Microdrama", 14_000_000, 1_400_000_000, 8_400_000_000),
]


def _concept(eco: str, name: str, som: float, sam: float, tam: float, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "economics_key": eco,
        "format": name,
        "monetization_model": "theatrical" if "feature" in eco else "license",
        "title": f"The {name} One",
        "logline": f"An original {name.lower()} about a fierce moral reckoning.",
        "som_y1_usd": som,
        "lifetime_usd": som * 1.5,
        "sam_usd": sam,
        "tam_usd": tam,
        "tam_source_url": "https://www.boxofficemojo.com/title/tt29623480/",
        "crystallization_score": 0.5,
        "standalone_ip_flag": True,
        "calculation_method": "python_executed",
        "comps": [
            {
                "title": "Some Comp",
                "worldwide_gross_usd": 500_000_000,
                "roi": 4.2,
                "boxofficemojo_url": "https://www.boxofficemojo.com/title/tt1234567/",
            }
        ],
    }
    base.update(kw)
    return base


def _full_slate() -> list[dict[str, Any]]:
    return [_concept(*row) for row in _FORMATS]


def test_slate_spans_at_least_five_formats() -> None:
    selected = select_top1_per_format(_full_slate())
    formats = {c["economics_key"] for c in selected}
    assert len(formats) >= 5


def test_de_franchise_filter_excludes_franchise() -> None:
    concepts = _full_slate()
    concepts.append(
        _concept(
            "feature",
            "Feature Film",
            900_000_000,
            18e9,
            152e9,
            title="Sequel Two",
            standalone_ip_flag=False,
            crystallization_score=0.99,
        )
    )
    kept, quarantined = apply_filters(concepts)
    titles = {c["title"] for c in kept}
    assert "Sequel Two" not in titles
    assert any(q["title"] == "Sequel Two" for q in quarantined)


def test_credibility_gate_quarantines_bad_ordering() -> None:
    bad = _concept("feature", "Feature Film", 200e9, 18e9, 152e9)  # SOM > SAM
    ok, reason = credibility_gate(bad)
    assert ok is False
    assert "ordering" in reason
    _, quarantined = apply_filters([bad])
    assert len(quarantined) == 1


def test_credibility_gate_requires_python_executed() -> None:
    c = _concept("feature", "Feature Film", 400e6, 18e9, 152e9, calculation_method="llm")
    ok, _ = credibility_gate(c)
    assert ok is False


def test_credibility_gate_rejects_sam_near_tam() -> None:
    # SAM at 92% of TAM is the canonical investor red flag — must be quarantined.
    c = _concept("feature", "Feature Film", 400e6, 140e9, 152e9)
    ok, reason = credibility_gate(c)
    assert ok is False
    assert "TAM" in reason


def test_non_theatrical_cards_use_tonal_anchor_disclaimer() -> None:
    """Box-office comps beside a license/microdrama SOM are a scale mismatch:
    non-theatrical cards must label comps as tonal anchors and drop WW/ROI."""
    md = render_slate_md(_full_slate())
    assert "Closest comps (box office)" in md  # theatrical cards keep revenue comps
    assert "Tonal anchors" in md  # license/microdrama cards relabel
    # The microdrama card's comp must NOT carry theatrical WW/ROI.
    micro_section = md.split("— Microdrama")[1].split("## ")[0]
    assert "WW" not in micro_section
    assert "ROI" not in micro_section


def test_rendered_md_is_investor_clean() -> None:
    md = render_slate_md(_full_slate())
    # exactly one H1
    assert md.count("\n# ") + (1 if md.startswith("# ") else 0) == 1
    assert "Format" in md
    # no internal framework IDs / run-ids leaked
    assert scan_for_internal_ids(md) == []
    # no markdown auto-link form
    assert "<https://" not in md
    # every markdown link target is a deep path (has a path beyond the host)

    for url in re.findall(r"\]\((https?://[^)]+)\)", md):
        host_path = url.split("://", 1)[1]
        assert "/" in host_path.rstrip("/"), f"bare-domain URL leaked: {url}"
