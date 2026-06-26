"""scripts/build_portfolio_slate.py — render the diversified investor portfolio.

Reads an (enriched) portfolio JSON produced by :mod:`scripts.build_portfolio`
+ the enrichment/review workflow, applies the de-franchise hard filter + the
SOM<SAM<TAM credibility gate (reusing :mod:`scripts.build_format_slate`), and
renders a self-contained, evidence-backed ``INVESTOR_PORTFOLIO_EN.md``.

Each concept card fuses the slate's breadth with the narrator's depth:
evocative title · tagline · logline · story · why-now (with deep-linked demand
evidence) · audience sizing · python-executed economics table · DISTINCT comps ·
honest risk. Slate-level Investment Summary + methodology + de-franchise thesis
bracket the cards.

Offline + LLM-free at render time: every number is python_executed upstream
(ADR-0011); every URL is a deep path (deep-link evidence policy); all internal
IDs / framework labels are stripped (ADR-0010).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pipeline.crystallize import portfolio as pf
from pipeline.template_filter import strip_internal_ids
from scripts.build_format_slate import _STANDALONE_PROOF, apply_filters, credibility_gate

_USD_M = 1_000_000.0
_USD_B = 1_000_000_000.0
#: Human-facing format ordering (theatrical scale first).
_FORMAT_ORDER = (
    "feature",
    "animation_feature",
    "returning_series",
    "limited_series",
    "animation_series",
    "microdrama",
)


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= _USD_B:
        return f"${value / _USD_B:.2f}B"
    return f"${value / _USD_M:.0f}M"


def _enr(c: dict[str, Any], key: str, default: str = "") -> str:
    enrichment = c.get("enrichment")
    if isinstance(enrichment, dict):
        v = enrichment.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def _comp_line(comp: dict[str, Any], *, revenue_comp: bool) -> str:
    title = str(comp.get("title", "")).strip()
    url = str(comp.get("boxofficemojo_url") or comp.get("imdb_url") or "").strip()
    bits = [title]
    if revenue_comp:
        ww = comp.get("worldwide_gross_usd")
        roi = comp.get("roi")
        if isinstance(ww, (int, float)):
            bits.append(_fmt_usd(float(ww)) + " WW")
        if isinstance(roi, (int, float)):
            bits.append(f"{roi:.1f}x ROI")
    label = " · ".join(bits)
    return f"[{label}]({url})" if pf.is_deep_path(url) else label


def _demand_lines(c: dict[str, Any]) -> list[str]:
    """Render the deep-linked demand-evidence bullets ('direct links of demand')."""
    rows = c.get("demand_evidence")
    if not isinstance(rows, list) or not rows:
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ok, _ = pf.validate_demand_evidence(row)
        if not ok:
            continue
        stat = str(row.get("stat", "")).strip()
        claim = str(row.get("claim", "")).strip()
        url = str(row.get("source_url", "")).strip()
        date = str(row.get("date", "")).strip()
        tail = f" ({date})" if date else ""
        out.append(f"- [{stat} — {claim}]({url}){tail}")
    return out


def _economics_table(c: dict[str, Any]) -> list[str]:
    som = c.get("som_y1_usd")
    lifetime = c.get("lifetime_usd")
    sam = c.get("sam_usd")
    tam = c.get("tam_usd")
    tam_src = str(c.get("tam_source_url") or "").strip()
    tam_cell = f"[{_fmt_usd(tam)}]({tam_src})" if pf.is_deep_path(tam_src) else _fmt_usd(tam)
    return [
        "| Market line | Value |",
        "| --- | --- |",
        f"| **SOM — Year 1 (realistic single-title capture)** | {_fmt_usd(som)} |",
        f"| **Lifetime (multi-window, directional)** | {_fmt_usd(lifetime)} |",
        f"| **SAM (serviceable category slice)** | {_fmt_usd(sam)} |",
        f"| **TAM (global format market)** | {tam_cell} |",
    ]


def _concept_card(c: dict[str, Any], *, n: int) -> str:
    title = _enr(c, "title", str(c.get("title") or c.get("working_title") or "Untitled"))
    tagline = _enr(c, "tagline")
    logline = _enr(c, "logline", str(c.get("engine_logline", "")))
    story = _enr(c, "story")
    why_now = _enr(c, "why_now")
    audience = _enr(c, "audience")
    what_diff = _enr(c, "what_different")
    revenue_thesis = _enr(c, "revenue_thesis")
    risk = _enr(c, "risk")

    is_theatrical = str(c.get("monetization_model")) == "theatrical"
    comps = c.get("comps") or []
    comp_lines = (
        "\n".join(f"- {_comp_line(cm, revenue_comp=is_theatrical)}" for cm in comps[:4])
        or "- (no comps matched)"
    )
    comp_header = (
        "**Closest comps (box office — revenue anchors):**"
        if is_theatrical
        else (
            "**Tonal anchors** (positioning — NOT revenue comps; this format earns "
            "via license / in-app, not box office):"
        )
    )
    demand = _demand_lines(c)

    lines: list[str] = [
        f"### {n}. {title} — {c.get('format', 'Feature Film')}",
        "",
    ]
    if tagline:
        lines += [f"> *{tagline}*", ""]
    lines += [f"**Logline.** {logline}", ""]
    if story:
        lines += [story, ""]
    if what_diff:
        lines += [f"**What makes it different.** {what_diff}", ""]
    if why_now:
        lines += [f"**Why now.** {why_now}", ""]
    if demand:
        lines += ["**Proof of demand (direct sources):**", *demand, ""]
    if audience:
        lines += [f"**Audience.** {audience}", ""]
    lines += ["**Economics (Year 1, python-executed):**", "", *_economics_table(c), ""]
    lines += [
        f"- **Monetization:** {c.get('format')} · {c.get('monetization_model')}",
        "- **Standalone original IP** — no franchise dependency.",
        "",
    ]
    if revenue_thesis:
        lines += [f"**Revenue thesis.** {revenue_thesis}", ""]
    lines += [comp_header, comp_lines, ""]
    if risk:
        lines += [f"**Key risk & mitigation.** {risk}", ""]
    lines += ["---", ""]
    return "\n".join(lines)


def _ordered(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by format (theatrical first), SOM-descending within each format."""

    def _key(c: dict[str, Any]) -> tuple[int, float]:
        eco = str(c.get("economics_key", ""))
        fi = _FORMAT_ORDER.index(eco) if eco in _FORMAT_ORDER else len(_FORMAT_ORDER)
        return (fi, -float(c.get("som_y1_usd") or 0))

    return sorted(concepts, key=_key)


def render_portfolio_md(concepts: list[dict[str, Any]]) -> str:
    ordered = _ordered(concepts)
    total_som = sum(float(c.get("som_y1_usd") or 0) for c in ordered)
    total_lifetime = sum(float(c.get("lifetime_usd") or 0) for c in ordered)
    formats = sorted({str(c.get("format", "")) for c in ordered})
    demand_total = sum(
        1
        for c in ordered
        for row in (c.get("demand_evidence") or [])
        if isinstance(row, dict) and pf.validate_demand_evidence(row)[0]
    )

    head = [
        "# The Standalone Slate — A Diversified Portfolio of Original Properties",
        "",
        (
            f"{len(ordered)} original, standalone properties across {len(formats)} content "
            "formats — feature film, premium series, animation, and vertical short-form. Every "
            "property carries a python-executed Year-1 revenue floor, credible market sizing, "
            "deep-linked box-office comparables, and direct sources for present-tense audience "
            "demand. Zero franchise dependency."
        ),
        "",
        "## Investment Summary",
        "",
        f"- **Properties:** {len(ordered)} original concepts across {len(formats)} formats",
        f"- **Formats:** {', '.join(formats)}",
        (
            f"- **Combined Year-1 SOM (sum of independent per-title floors):** "
            f"{_fmt_usd(total_som)} (python-executed)"
        ),
        f"- **Combined multi-window lifetime (directional):** {_fmt_usd(total_lifetime)}",
        f"- **Proof-of-demand sources:** {demand_total} deep-linked, independently verifiable",
        "- **IP posture:** 100% original / standalone — zero franchise reliance.",
        "",
        (
            "> Methodology note: each Year-1 SOM is a per-title *floor*, computed in Python "
            "from named, sourced market constants and corpus-anchored comparables — never a "
            "model-written number. SOM < SAM < TAM holds for every property. The combined "
            "figure is the sum of independent floors (a fully-greenlit slate), not a single "
            "project."
        ),
        "",
    ]
    cards = [_concept_card(c, n=i + 1) for i, c in enumerate(ordered)]

    proof_map, proof_note = _STANDALONE_PROOF
    proof_lines = "\n".join(f"- [{name}]({url})" for name, url in proof_map.items())
    thesis = [
        "## Why standalone, not franchise",
        "",
        "The strongest recent cash flow came from ORIGINAL premises, not pre-existing IP. Proof:",
        "",
        proof_lines,
        "",
        proof_note,
        "",
        "## How these numbers were produced",
        "",
        "- **Economics:** every SOM/SAM/TAM is computed by executed Python from named, sourced "
        "market constants and a 894-film corpus of comparables — not written by a language model.",
        "- **Comparables:** matched to each concept by genre + audience similarity against the "
        "corpus, then de-duplicated across the slate so no two cards lean on the same titles.",
        "- **Demand evidence:** each 'proof of demand' source is an independently reachable "
        "deep link to a primary report, trade outlet, or government dataset.",
        "- **Originality:** a franchise detector hard-filters any IP-dependent concept out of "
        "this slate; every property here is standalone by construction.",
        "",
    ]
    md = "\n".join(head) + "\n" + "\n".join(cards) + "\n".join(thesis)
    return strip_internal_ids(md)


def build(portfolio_json: Path, out_md: Path, errors_path: Path) -> dict[str, Any]:
    data = json.loads(Path(portfolio_json).read_text(encoding="utf-8"))
    concepts: list[dict[str, Any]] = list(data.get("concepts", []))
    kept, quarantined = apply_filters(concepts)

    md = render_portfolio_md(kept)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")

    if quarantined:
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        with errors_path.open("w", encoding="utf-8") as f:
            for row in quarantined:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    # Defensive: assert the credibility invariant holds for everything we shipped.
    for c in kept:
        ok, reason = credibility_gate(c)
        assert ok, f"shipped a concept that fails the credibility gate: {reason}"

    return {
        "concepts_in": len(concepts),
        "kept": len(kept),
        "quarantined": len(quarantined),
        "out_md": str(out_md),
    }


def _latest_portfolio_json() -> Path:
    pointer = Path("runs/portfolio/latest.json")
    if pointer.exists():
        path = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        if path and Path(path).exists():
            return Path(path)
    candidates = sorted(Path("runs/portfolio").glob("*-portfolio.json"))
    if not candidates:
        raise SystemExit("no portfolio JSON in runs/portfolio/ — run build_portfolio.py first")
    return candidates[-1]


def main() -> None:
    portfolio_json = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_portfolio_json()
    out_md = Path("outputs/portfolio/INVESTOR_PORTFOLIO_EN.md")
    errors_path = Path("outputs/portfolio/portfolio.errors.jsonl")
    summary = build(portfolio_json, out_md, errors_path)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
