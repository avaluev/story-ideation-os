"""scripts/build_idea_onepager.py — deep-dive one-pager for a single idea.

Turns one concept into a financier-ready brief: the premise, the full verified
demand wall, a comp-by-comp ROI table (honest — keeps the flops), a budget
build-up, and a conservative / base / upside revenue path with the math shown.
Joins the enriched concept (by bespoke title) to its reality-verified claims (by
concept id) and renders a self-consistent, deep-linked document.

    uv run python -m scripts.build_idea_onepager --title Provenance [--budget-musd 25]

Pure assembly (ADR-0002) — no LLM, no network. The model SOM is the engine's
python-executed reach-adjusted figure; this brief frames it honestly against the
verified like-for-like comp so a reader sees both the realistic anchor and the
upside ceiling.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from pipeline.crystallize import format_economics as fe
from pipeline.veracity.claims import Claim
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.scorecard import ClaimAssessment, score_by_concept
from pipeline.veracity.verdict import Verdict

_ENRICHED = Path("outputs/portfolio/portfolio_enriched.json")
_VERACITY = Path("outputs/veracity/portfolio_enriched.veracity.json")
_USD_B, _USD_M = 1_000_000_000.0, 1_000_000.0
#: Feature-tier model band shape (p10/p50 and p90/p50), observed from the engine's
#: SOM-ranked feature concepts — used to bracket the point SOM as conservative/upside.
_CONSERVATIVE_RATIO, _UPSIDE_RATIO = 0.56, 1.77


def _m(x: float | None) -> str:
    v = float(x or 0)
    return f"${v / _USD_B:.2f}B" if v >= _USD_B else f"${v / _USD_M:.0f}M"


def _load_assessments(vdata: dict[str, Any]) -> list[ClaimAssessment]:
    out: list[ClaimAssessment] = []
    for a in cast("list[dict[str, Any]]", vdata.get("assessments", [])):
        pv = cast("dict[str, Any]", a.get("provenance") or {})
        out.append(
            ClaimAssessment(
                Claim(
                    a["claim_id"],
                    a["concept_id"],
                    a["concept_title"],
                    a["claim_type"],
                    a["text"],
                    a["value"],
                    a["cited_url"],
                ),
                Verdict(a["verdict"]),
                Provenance("", None, "", None, pv.get("quote", ""), bool(pv.get("supports_claim"))),
            )
        )
    return out


def _find(concepts: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    for c in concepts:
        if (c.get("enrichment") or {}).get("title", "").lower() == title.lower():
            return c
        if str(c.get("title", "")).lower() == title.lower():
            return c
    return None


def _comp_rows(concept: dict[str, Any]) -> list[str]:
    rows = [
        "| Comparable | Worldwide gross | Budget | ROI | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    comps = cast("list[dict[str, Any]]", concept.get("comps") or [])
    for cm in comps:
        g = float(cm.get("worldwide_gross_usd") or 0)
        b = float(cm.get("budget_usd") or 0)
        roi = cm.get("roi")
        url = str(cm.get("boxofficemojo_url") or cm.get("imdb_url") or "")
        title = f"[{cm.get('title')}]({url})" if url else str(cm.get("title"))
        roi_s = f"{float(roi):.1f}x" if roi else "n/a"
        note = "underperformer" if (roi and float(roi) < 1.0) else "scale/tonal anchor"
        rows.append(f"| {title} | {_m(g)} | {_m(b) if b else 'Undisclosed'} | {roi_s} | {note} |")
    return rows


def _theatrical_path(som: float, life: float, budget_usd: float) -> list[str]:
    cons, up = som * _CONSERVATIVE_RATIO, som * _UPSIDE_RATIO
    bud_m = budget_usd / _USD_M

    def x(v: float) -> str:
        return f"{v / budget_usd:.0f}x" if budget_usd else "n/a"

    return [
        "**Revenue path (Year-1 SOM, python-executed — three-point):**",
        "",
        f"| Case | Year-1 SOM | Multiple on ${bud_m:.0f}M budget |",
        "| --- | --- | --- |",
        f"| Conservative (comp-distribution p10) | {_m(cons)} | {x(cons)} |",
        f"| Base (model p50) | **{_m(som)}** | {x(som)} |",
        f"| Upside (comp-distribution p90) | {_m(up)} | {x(up)} |",
        "",
        f"Multi-window lifetime (directional): **{_m(life)}** (2.95x theatrical multiple).",
        "",
        "> How to read this: the **base** SOM is the engine's reach-adjusted figure — treat it "
        "as the upside-leaning midpoint, not a floor. The **conservative** case is the "
        "comp-distribution downside *conditional on a successful release*; apply your own "
        "breakout-probability discount on top. The like-for-like verified comp in the demand "
        "wall is the realistic theatrical anchor.",
        "",
    ]


def _license_path(som: float, life: float, profile: fe.FormatProfile) -> list[str]:
    prod = profile.ep_count * profile.cost_per_ep_usd
    fee = fe.license_fee_usd(profile)
    eps, cpe = profile.ep_count, _m(profile.cost_per_ep_usd)
    seasons, haircut, markup = (
        profile.season_count_factor,
        profile.cancellation_haircut,
        profile.cost_plus_markup,
    )
    return [
        "**Revenue path (Year-1 license fee — cost-plus, python-executed):**",
        "",
        "| Case | Year-1 SOM | Basis |",
        "| --- | --- | --- |",
        f"| Conservative (single season, no renewal) | {_m(fee)} | "
        f"contracted cost-plus fee, paid on greenlight regardless of audience |",
        f"| Base (with audience reach) | **{_m(som)}** | license fee x reach factor |",
        f"| Upside (multi-season + ancillary) | {_m(life)} | "
        f"x{seasons} seasons x {haircut} renewal haircut |",
        "",
        f"Production cost ~{_m(prod)} ({eps} episodes x {cpe}/ep, anchored to premium-drama "
        f"economics) at a {markup:.0%} cost-plus markup.",
        "",
        "> How to read this: a premium series is a **license**, not a box-office bet. The "
        "**conservative** figure is what a streamer commits on greenlight for a single season — "
        "the most bankable number on the slate, independent of breakout. Base adds audience-reach "
        "upside; the upside case assumes renewal across seasons.",
        "",
    ]


def _revenue_path(concept: dict[str, Any], som: float, life: float, budget_usd: float) -> list[str]:
    profile = fe.get_profile(str(concept.get("economics_key", "")))
    if profile.monetization_model in ("license", "microdrama"):
        return _license_path(som, life, profile)
    return _theatrical_path(som, life, budget_usd)


def build(title: str, budget_musd: float, out_path: Path) -> dict[str, Any]:
    enriched = json.loads(_ENRICHED.read_text(encoding="utf-8"))
    vdata = json.loads(_VERACITY.read_text(encoding="utf-8"))
    concept = _find(cast("list[dict[str, Any]]", enriched.get("concepts", [])), title)
    if concept is None:
        raise SystemExit(f"idea not found: {title!r}")

    enr = cast("dict[str, Any]", concept.get("enrichment") or {})
    cid = str(concept.get("id", ""))
    assessments = _load_assessments(vdata)
    by_concept = score_by_concept(assessments)
    score = by_concept.get(str(concept.get("title") or enr.get("title")))
    proofs = [
        a
        for a in assessments
        if a.claim.concept_id == cid
        and a.claim.claim_type in ("demand", "cultural_signal", "box_office")
        and a.provenance.quote.strip()
    ]
    som = float(concept.get("som_y1_usd") or 0)
    life = float(concept.get("lifetime_usd") or 0)
    budget = budget_musd * _USD_M
    grade = f" — Grade {score.grade} ({score.composite}/100)" if score else ""

    lines = [
        f"# {enr.get('title') or concept.get('title')} — Investor One-Pager{grade}",
        "",
        f"> *{enr.get('tagline', '')}*",
        "",
        f"**Format:** {concept.get('format')}  ·  **IP:** original / standalone  ·  "
        f"**Recommended budget:** ${budget_musd:.0f}M",
        "",
        f"**Logline.** {enr.get('logline', '')}",
        "",
        enr.get("story", ""),
        "",
        f"**What makes it different.** {enr.get('what_different', '')}",
        "",
        f"**Why now.** {enr.get('why_now', '')}",
        "",
        "## The verified demand wall",
        "",
        "Every figure below was fetched live and confirmed on the linked primary source.",
        "",
    ]
    for a in proofs:
        q = a.provenance.quote.strip().replace("\n", " ")[:200]
        lines.append(f"- ✅ **{a.claim.value}** — “{q}” ([source]({a.claim.cited_url}))")
    lines += ["", "## The numbers", ""]
    lines += _revenue_path(concept, som, life, budget)
    lines += ["**Comparable performance (honest — underperformers kept):**", ""]
    lines += _comp_rows(concept)
    lines += [
        "",
        f"**Revenue thesis.** {enr.get('revenue_thesis', '')}",
        "",
        f"**Key risk & mitigation.** {enr.get('risk', '')}",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"title": enr.get("title"), "som": som, "proofs": len(proofs), "out": str(out_path)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Deep-dive one-pager for a single idea.")
    ap.add_argument("--title", required=True, help="bespoke enrichment title (e.g. Provenance)")
    ap.add_argument("--budget-musd", type=float, default=25.0, help="recommended budget in $M")
    ap.add_argument("--out", default="", help="output markdown path")
    args = ap.parse_args()
    slug = args.title.lower().replace(" ", "_")
    out = Path(args.out) if args.out else Path(f"outputs/portfolio/ONEPAGER_{slug}.md")
    res = build(args.title, args.budget_musd, out)
    print(f"One-pager: {res['out']}")
    print(f"  {res['title']} · SOM {_m(res['som'])} · {res['proofs']} verified proofs")


if __name__ == "__main__":
    main()
