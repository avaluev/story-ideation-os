"""scripts/build_enrich_args.py — build the enrichment workflow's input args.

Reads a portfolio JSON (from :mod:`scripts.build_portfolio`) and emits
``runs/portfolio/enrich_args.json`` — the minimal per-concept grounding the
enrichment agents read: engine DNA (world / wound / inversion / fault), the
fixed python-executed economics, the matched comps, and two distinctness
guarantees learned from the P5 adversarial review:

  * ``assigned_name`` — a DISTINCT protagonist given-name per concept, drawn
    from a curated, globally varied pool. The prior slate's enrichment collapsed
    onto one name family (Mara / Maren / Maya appeared in 14 of 18 stories); a
    pre-assigned distinct name makes that collapse impossible by construction.
  * ``avoid_title_words`` — overused title tokens the prior slate shared
    (quiet / hour / last / room …), so fresh titles steer clear of them.

Pure I/O — no LLM, no network.

    uv run python -m scripts.build_enrich_args [PORTFOLIO.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: One DISTINCT protagonist given-name per slot, globally varied (gender +
#: geography), deliberately avoiding the Mar-/May-/Mae- family the prior slate
#: collapsed onto. Index = concept position in the portfolio.
_NAME_POOL: tuple[str, ...] = (
    "Idris",
    "Soledad",
    "Cora",
    "Anders",
    "Reza",
    "Priya",
    "Dimitri",
    "Naomi",
    "Kenji",
    "Dahlia",
    "Yusuf",
    "Imani",
    "Lior",
    "Cassia",
    "Amaru",
    "Birgit",
    "Tariq",
    "Esi",
)

#: Title tokens the prior slate over-used (quiet x4, hour x3, last x3, room x2).
_AVOID_TITLE_WORDS: tuple[str, ...] = (
    "quiet",
    "hour",
    "hours",
    "last",
    "room",
    "light",
    "lucid",
    "cold",
    "clean",
    "forgetting",
    "half",
)

_SEED_AXES = {
    "world": ("world_texture", "name"),
    "wound": ("sdt_wound", "description"),
    "inversion": ("structural_inversion", "description"),
    "fault": ("moral_fault_line", "description"),
}


def _axis_text(concept: dict[str, Any], axis: str, field: str) -> str:
    node = (concept.get("seed_axes") or {}).get(axis)
    return str(node.get(field, "")).strip() if isinstance(node, dict) else ""


def _trim_comps(comps: list[dict[str, Any]], k: int = 6) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cm in comps[:k]:
        out.append(
            {
                "title": cm.get("title"),
                "worldwide_gross_usd": cm.get("worldwide_gross_usd"),
                "roi": cm.get("roi"),
                "genres": cm.get("genres"),
                "release_year": cm.get("release_year"),
            }
        )
    return out


def build_args(portfolio_json: Path) -> dict[str, Any]:
    data = json.loads(Path(portfolio_json).read_text(encoding="utf-8"))
    concepts_out: list[dict[str, Any]] = []
    for i, c in enumerate(data.get("concepts", [])):
        concepts_out.append(
            {
                "id": c.get("id"),
                "format": c.get("format"),
                "monetization_model": c.get("monetization_model"),
                "working_title": c.get("working_title"),
                "engine_logline": c.get("engine_logline"),
                "world": _axis_text(c, *_SEED_AXES["world"]),
                "wound": _axis_text(c, *_SEED_AXES["wound"]),
                "inversion": _axis_text(c, *_SEED_AXES["inversion"]),
                "fault": _axis_text(c, *_SEED_AXES["fault"]),
                "genres": c.get("genres", []),
                "som_y1_usd": c.get("som_y1_usd"),
                "sam_usd": c.get("sam_usd"),
                "tam_usd": c.get("tam_usd"),
                "comps": _trim_comps(c.get("comps") or []),
                "assigned_name": _NAME_POOL[i % len(_NAME_POOL)],
                "avoid_title_words": list(_AVOID_TITLE_WORDS),
            }
        )
    return {"concepts": concepts_out}


def main() -> None:
    if len(sys.argv) > 1:
        portfolio_json = Path(sys.argv[1])
    else:
        pointer = Path("runs/portfolio/latest.json")
        portfolio_json = Path(json.loads(pointer.read_text(encoding="utf-8"))["path"])
    out = build_args(portfolio_json)
    out_path = Path("runs/portfolio/enrich_args.json")
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path} with {len(out['concepts'])} concepts from {portfolio_json}")


if __name__ == "__main__":
    main()
