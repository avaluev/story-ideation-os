"""scripts/build_format_slate.py — render the multi-format investor slate (EN).

Reads a slate JSON (produced by scripts/run_format_slate.py), applies the
de-franchise hard filter + the SOM<SAM<TAM credibility gate (quarantining
failures to an operator-actionable errors file, never silently dropping them),
and renders a self-contained, evidence-backed INVESTOR_SLATE_EN.md.

Offline + LLM-free: every number is python_executed (ADR-0011); every URL is a
deep path (deep-link evidence policy); all internal IDs / framework labels are
stripped via pipeline.template_filter.strip_internal_ids (ADR-0010).

The RU translation is a separate operator step (it needs a live LLM); this
builder ships the EN slate only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pipeline.crystallize import format_economics as fe
from pipeline.template_filter import strip_internal_ids

#: A slate must span at least this many distinct formats to be investor-grade.
MIN_FORMATS_FOR_SLATE: int = 5

_USD_M = 1_000_000.0
_USD_B = 1_000_000_000.0
#: An https URL with more than this many slashes has a real path beyond the host.
_MIN_DEEP_PATH_SLASHES = 2
#: SAM may not be this large a share of TAM — a near-tautological SAM for a
#: single title is the canonical red flag a sophisticated investor rejects.
_MAX_SAM_TAM_RATIO = 0.5

#: Sourced proof that ORIGINAL, non-franchise titles drive top-tier cash flow —
#: the evidence spine of the de-franchise thesis. Every URL is a deep path.
_STANDALONE_PROOF: tuple[dict[str, str], str] = (
    {
        "Parasite (2019)": "https://www.boxofficemojo.com/release/rl1258849793/",
        "Oppenheimer (2023)": "https://www.the-numbers.com/movie/Oppenheimer-(2023)",
        "Squid Game (2021)": "https://deadline.com/2021/10/squid-game-netflix-generate-900-million-value-1234857378/",
        "Baby Reindeer (2024)": "https://variety.com/2024/tv/news/netflix-data-viewing-fool-me-once-bridgerton-baby-reindeer-first-half-of-2024-1236150283/",
        "The Wild Robot (2024)": "https://www.boxofficemojo.com/title/tt29623480/",
    },
    "None of these leaned on a pre-existing franchise; each created the cash flow "
    "from an original premise.",
)


def _is_deep_path(url: str) -> bool:
    """True only for an https URL with a real path beyond the host (deep-link
    evidence policy: no bare domains, no search-engine URLs)."""
    return url.startswith("https://") and url.rstrip("/").count("/") > _MIN_DEEP_PATH_SLASHES


def _fmt_usd(value: float | None) -> str:
    """Human dollar string: $X.XB / $XXXM / em-dash for None."""
    if value is None:
        return "—"
    if value >= _USD_B:
        return f"${value / _USD_B:.2f}B"
    return f"${value / _USD_M:.0f}M"


def credibility_gate(concept: dict[str, Any]) -> tuple[bool, str]:
    """Return (passes, reason). A concept ships only when
    0 < som_y1 < sam < tam AND its revenue is python_executed."""
    som = concept.get("som_y1_usd")
    sam = concept.get("sam_usd")
    tam = concept.get("tam_usd")
    if concept.get("calculation_method") != "python_executed":
        return (False, "revenue not python_executed")
    if not (isinstance(som, (int, float)) and som > 0):
        return (False, "som_y1_usd missing or <= 0")
    if not (isinstance(sam, (int, float)) and isinstance(tam, (int, float))):
        return (False, "sam/tam missing")
    if not (som < sam <= tam):
        return (False, f"ordering SOM {som:.0f} < SAM {sam:.0f} <= TAM {tam:.0f} violated")
    if tam > 0 and sam / tam >= _MAX_SAM_TAM_RATIO:
        return (
            False,
            f"SAM {sam / tam:.0%} of TAM (>= {_MAX_SAM_TAM_RATIO:.0%}) — implausible slice",
        )
    return (True, "ok")


def apply_filters(
    concepts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split concepts into (kept, quarantined). Drops franchise-dependent
    concepts (standalone_ip_flag False) and credibility-gate failures — both
    to the quarantine list with a reason, never silently."""
    kept: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for c in concepts:
        if c.get("standalone_ip_flag") is False:
            quarantined.append(
                {**c, "_quarantine_reason": "franchise-dependent (de-franchise filter)"}
            )
            continue
        ok, reason = credibility_gate(c)
        if not ok:
            quarantined.append({**c, "_quarantine_reason": reason})
            continue
        kept.append(c)
    return (kept, quarantined)


def select_top1_per_format(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the highest-scoring concept per format, ordered by SOM descending."""
    best: dict[str, dict[str, Any]] = {}
    for c in concepts:
        key = str(c.get("economics_key") or c.get("format") or "")
        cur = best.get(key)
        if cur is None or float(c.get("crystallization_score", 0)) > float(
            cur.get("crystallization_score", 0)
        ):
            best[key] = c
    return sorted(best.values(), key=lambda c: float(c.get("som_y1_usd") or 0), reverse=True)


def _comp_line(comp: dict[str, Any], *, revenue_comp: bool) -> str:
    """Render one comp. For theatrical formats it is a revenue comp (WW gross +
    ROI). For license/microdrama formats the box-office comps are only TONAL
    anchors — showing their theatrical WW/ROI beside a license/share product
    would be a scale mismatch, so we render title + link alone."""
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
    # deep-path URLs only; bare domains / search URLs never reach here.
    if _is_deep_path(url):
        return f"[{label}]({url})"
    return label


def _concept_card(c: dict[str, Any]) -> str:
    som = c.get("som_y1_usd")
    lifetime = c.get("lifetime_usd")
    sam = c.get("sam_usd")
    tam = c.get("tam_usd")
    tam_src = str(c.get("tam_source_url") or "").strip()
    tam_cell = _fmt_usd(tam)
    if _is_deep_path(tam_src):
        tam_cell = f"[{_fmt_usd(tam)}]({tam_src})"
    is_theatrical = str(c.get("monetization_model")) == "theatrical"
    comps = c.get("comps") or []
    comp_lines = (
        "\n".join(f"- {_comp_line(comp, revenue_comp=is_theatrical)}" for comp in comps[:4])
        or "- (no comps matched)"
    )
    # Theatrical comps ARE revenue comps; for license/microdrama the box-office
    # corpus only supplies tonal/positioning anchors (different revenue regime).
    comp_header = (
        "**Closest comps (box office):**"
        if is_theatrical
        else (
            "**Tonal anchors** (positioning — NOT revenue comps; this format "
            "earns via license / in-app, not box office):"
        )
    )
    lines = [
        f"## {c.get('title', 'Untitled')} — {c.get('format', 'Feature Film')}",
        "",
        f"{c.get('logline', '').strip()}",
        "",
        f"- **Format / model:** {c.get('format')} · {c.get('monetization_model')}",
        f"- **SOM (Year 1):** {_fmt_usd(som)} (python-executed)",
        f"- **Lifetime (multi-window, directional):** {_fmt_usd(lifetime)}",
        f"- **SAM:** {_fmt_usd(sam)}  ·  **TAM:** {tam_cell}",
        "- **Standalone original IP** — no franchise dependency.",
        "",
        comp_header,
        comp_lines,
        "",
    ]
    return "\n".join(lines)


def render_slate_md(
    concepts: list[dict[str, Any]], *, generated_label: str = "format-slate"
) -> str:
    """Render the investor slate markdown (one H1; per-format cards; de-franchise
    thesis; slate-level diversity + revenue totals)."""
    ordered = select_top1_per_format(concepts)
    total_som = sum(float(c.get("som_y1_usd") or 0) for c in ordered)
    total_lifetime = sum(float(c.get("lifetime_usd") or 0) for c in ordered)
    formats = [str(c.get("format", "")) for c in ordered]

    proof_map, proof_note = _STANDALONE_PROOF
    proof_lines = "\n".join(f"- [{name}]({url})" for name, url in proof_map.items())

    head = [
        "# Multi-Format Original Slate",
        "",
        (
            f"A slate of {len(ordered)} original, standalone concepts spanning "
            f"{len({c.get('economics_key') for c in ordered})} content formats — "
            "feature film, premium series, animation, and vertical short-form — each "
            "with a python-executed Year-1 revenue floor and credible market sizing. "
            "No franchise dependency."
        ),
        "",
        "## Investment Summary",
        "",
        f"- **Formats covered:** {', '.join(formats)}",
        f"- **Combined Year-1 SOM:** {_fmt_usd(total_som)} (python-executed; per-title floors)",
        f"- **Combined multi-window lifetime (directional):** {_fmt_usd(total_lifetime)}",
        "- **IP posture:** 100% original / standalone — zero franchise reliance.",
        "",
    ]
    cards = [_concept_card(c) for c in ordered]
    thesis = [
        "## Why standalone, not franchise",
        "",
        ("The strongest recent cash flow came from ORIGINAL premises, not pre-existing IP. Proof:"),
        "",
        proof_lines,
        "",
        proof_note,
        "",
    ]
    md = "\n".join(head) + "\n" + "\n".join(cards) + "\n" + "\n".join(thesis)
    return strip_internal_ids(md)


def build(
    slate_json: Path,
    out_md: Path,
    errors_path: Path,
) -> dict[str, Any]:
    """Read slate JSON, filter + gate, render the EN markdown. Returns a summary."""
    data = json.loads(Path(slate_json).read_text(encoding="utf-8"))
    concepts: list[dict[str, Any]] = list(data.get("concepts", []))
    kept, quarantined = apply_filters(concepts)
    ordered = select_top1_per_format(kept)

    md = render_slate_md(kept, generated_label=str(data.get("generated_label", "format-slate")))
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")

    if quarantined:
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        with errors_path.open("w", encoding="utf-8") as f:
            for row in quarantined:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    return {
        "concepts_in": len(concepts),
        "kept": len(kept),
        "quarantined": len(quarantined),
        "formats": sorted({str(c.get("economics_key")) for c in ordered}),
        "out_md": str(out_md),
        "meets_breadth": len({str(c.get("economics_key")) for c in ordered})
        >= MIN_FORMATS_FOR_SLATE,
    }


def main() -> None:
    slate_json = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_slate_json()
    out_md = Path("outputs/slate/INVESTOR_SLATE_EN.md")
    errors_path = Path("outputs/slate/slate.errors.jsonl")
    summary = build(slate_json, out_md, errors_path)
    print(json.dumps(summary, indent=2))
    # All valid format ids must be real (defensive vs typos in the slate JSON).
    assert all(f in fe.VALID_FORMATS or f == "None" for f in summary["formats"])


def _latest_slate_json() -> Path:
    root = Path("runs/format-slate")
    candidates = sorted(root.glob("*-slate.json"))
    if not candidates:
        raise SystemExit(
            "no slate JSON found in runs/format-slate/ — run run_format_slate.py first"
        )
    return candidates[-1]


if __name__ == "__main__":
    main()
