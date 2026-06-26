# ruff: noqa: E501
"""Build out/best_concepts.html — a curated investor-grade view of the
PASS-band briefs in out/concepts/v3.1-pathc-a4/.

Output is a single self-contained HTML file with:
  * Executive summary header (corpus stats, score bands, model attribution)
  * Sortable + filterable table of every PASS-band brief (score >= 85)
  * Per-brief detail panels (logline, audience, JTBD, asset, key roles, score axes)
  * Direct links to the underlying markdown files

No JS dependencies; vanilla DOM + sort + filter. Drop-in companion to
out/index.html.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
A4_DIR = ROOT / "out" / "concepts" / "v3.1-pathc-a4"
OUT = ROOT / "out" / "best_concepts.html"

PASS_FLOOR = 85
HIGH_REVIEW_FLOOR = 80
ONE_MILLION = 1_000_000
HIGH_REVIEW_PREVIEW_LIMIT = 40
DEPRIVATION_PREVIEW_LEN = 140


def _section(text: str, name: str) -> str:
    """Return body text under a `## name` H2 (until next ##/EOF)."""
    pat = re.compile(
        rf"^##\s+{re.escape(name)}\s*\n(.+?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    m = pat.search(text)
    return m.group(1).strip() if m else ""


def _parse_brief(path: Path) -> dict[str, object] | None:
    text = path.read_text(encoding="utf-8")

    score_m = re.search(r"^\*\*(\d+)/100\*\*\s*$", text, re.MULTILINE)
    if not score_m:
        return None
    score = int(score_m.group(1))

    title_m = re.search(r"^# (.+?)$", text, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else path.stem

    seed_m = re.search(r"\*\*Seed:\*\* `(\d+)`", text)
    seed = int(seed_m.group(1)) if seed_m else 0

    logline_block = _section(text, "High-Concept Logline")
    logline = logline_block.split("\n", 1)[0].strip()

    aud_block = _section(text, "Audience Size & Evidence")
    aud_size_m = re.search(r"Estimated audience:\s*([\d,]+)", aud_block)
    audience_size = int(aud_size_m.group(1).replace(",", "")) if aud_size_m else 0
    aud_url_m = re.search(r"\(source: \[([^\]]+)\]\((https?://[^\)]+)\)", aud_block)
    audience_source_name = aud_url_m.group(1) if aud_url_m else ""
    audience_source_url = aud_url_m.group(2) if aud_url_m else ""
    countries_m = re.search(r"Countries:\s*([^\n]+)", aud_block)
    countries = countries_m.group(1).strip() if countries_m else ""
    trend_m = re.search(r"Trend:\s*([^\n]+)", aud_block)
    trend = trend_m.group(1).strip() if trend_m else ""

    jtbd_block = _section(text, "JTBD")
    jtbd_label_m = re.search(r"\*\*([a-z_]+)\*\*", jtbd_block)
    jtbd_label = jtbd_label_m.group(1) if jtbd_label_m else "?"
    jtbd_dep_m = re.search(r"Deprivation:\s*(.+?)(?:\n|\Z)", jtbd_block, flags=re.DOTALL)
    jtbd_deprivation = jtbd_dep_m.group(1).strip() if jtbd_dep_m else ""

    asset_block = _section(text, "Asset")
    asset_name_m = re.search(r"^\*\*([^*]+)\*\*\s*\(([^)]+)\)", asset_block, re.MULTILINE)
    asset_name = asset_name_m.group(1).strip() if asset_name_m else ""
    asset_kind = asset_name_m.group(2).strip() if asset_name_m else ""
    asset_url_m = re.search(r"Precedent:\s*\[[^\]]+\]\((https?://[^\)]+)\)", asset_block)
    asset_url = asset_url_m.group(1) if asset_url_m else ""

    triz_block = _section(text, "TRIZ Contradiction")
    triz_m = re.search(r"^\*\*([^*]+)\*\*", triz_block, re.MULTILINE)
    triz = triz_m.group(1).strip() if triz_m else ""

    sdt_block = _section(text, "SDT Analysis")
    sdt_need_m = re.search(r"Primary need:\s*(\w+)", sdt_block)
    sdt_primary = sdt_need_m.group(1) if sdt_need_m else "?"
    sdt_strength_m = re.search(r"strength:\s*([\d.]+)", sdt_block)
    sdt_strength = float(sdt_strength_m.group(1)) if sdt_strength_m else 0.0

    critic_block = _section(text, "Critic Verdict")
    axes: dict[str, int] = {}
    for axis_name in ("Novelty", "JTBD", "Contradiction", "Specificity"):
        m = re.search(
            rf"^\|\s*{re.escape(axis_name)}\s*\|\s*(\d+)\s*\|", critic_block, re.MULTILINE
        )
        if m:
            axes[axis_name.lower()] = int(m.group(1))

    return {
        "id": path.stem,
        "score": score,
        "title": title,
        "seed": seed,
        "logline": logline,
        "audience_size": audience_size,
        "audience_source_name": audience_source_name,
        "audience_source_url": audience_source_url,
        "countries": countries,
        "trend": trend,
        "jtbd_label": jtbd_label,
        "jtbd_deprivation": jtbd_deprivation,
        "asset_name": asset_name,
        "asset_kind": asset_kind,
        "asset_url": asset_url,
        "triz": triz,
        "sdt_primary": sdt_primary,
        "sdt_strength": sdt_strength,
        "axes": axes,
        "path": str(path.relative_to(ROOT)),
    }


def _band(score: int) -> str:
    if score >= PASS_FLOOR:
        return "PASS"
    if score >= HIGH_REVIEW_FLOOR:
        return "HIGH-REVIEW"
    return "REVIEW"


def main() -> int:  # noqa: PLR0915 — long but linear HTML rendering, splitting hurts readability
    if not A4_DIR.is_dir():
        print(f"FAIL: {A4_DIR} missing", file=sys.stderr)
        return 1

    briefs: list[dict[str, object]] = []
    for path in sorted(A4_DIR.glob("*.md")):
        parsed = _parse_brief(path)
        if parsed is not None:
            briefs.append(parsed)

    pass_briefs = [b for b in briefs if b["score"] >= PASS_FLOOR]  # type: ignore[operator]
    high_review = [b for b in briefs if HIGH_REVIEW_FLOOR <= b["score"] < PASS_FLOOR]  # type: ignore[operator]

    pass_briefs.sort(key=lambda b: (-b["score"], b["id"]))  # type: ignore[arg-type, operator]
    high_review.sort(key=lambda b: (-b["score"], b["id"]))  # type: ignore[arg-type, operator]

    jtbd_dist = Counter(b["jtbd_label"] for b in pass_briefs)

    n_total = len(briefs)
    n_pass = len(pass_briefs)
    n_high = len(high_review)
    pass_pct = 100 * n_pass / n_total if n_total else 0
    mean_score = sum(b["score"] for b in briefs) / n_total if n_total else 0  # type: ignore[misc]

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append("<title>Best Concepts — FilmIntel A4 Portfolio</title>")
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append("<style>")
    parts.append("""
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0a0a0e; color: #e8e8ec; max-width: 1200px; margin: 0 auto;
       padding: 32px 24px; line-height: 1.55; }
h1 { font-size: 32px; margin: 0 0 8px; letter-spacing: -0.5px; }
h2 { font-size: 22px; margin: 32px 0 12px; border-bottom: 1px solid #2a2a32; padding-bottom: 6px; }
h3 { font-size: 18px; margin: 20px 0 8px; color: #c4d0e6; }
.subtitle { color: #888; margin-bottom: 20px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 12px; margin: 20px 0; }
.kpi { background: #131319; padding: 14px 16px; border-radius: 8px; border: 1px solid #2a2a32; }
.kpi .v { font-size: 24px; font-weight: 600; color: #fff; }
.kpi .l { font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; }
.controls { margin: 12px 0; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.controls input { background: #131319; color: #e8e8ec; border: 1px solid #2a2a32;
                  padding: 8px 12px; border-radius: 6px; font-size: 14px; flex: 1; min-width: 200px; }
.controls select { background: #131319; color: #e8e8ec; border: 1px solid #2a2a32;
                   padding: 8px 12px; border-radius: 6px; font-size: 14px; }
.brief { background: #131319; border: 1px solid #2a2a32; border-radius: 10px;
         padding: 18px 22px; margin: 16px 0; }
.brief.pass { border-color: #5a8e6a; }
.brief.high-review { border-color: #8e7a4a; }
.brief-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.score { font-weight: 600; color: #b8e0c4; min-width: 60px; }
.score.pass { color: #b8e0c4; }
.score.high-review { color: #e0d4a4; }
.band-tag { font-size: 10px; padding: 2px 8px; border-radius: 4px;
            text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
.band-tag.pass { background: #2a4a32; color: #c8f0d4; }
.band-tag.high-review { background: #4a3a1c; color: #f0e0a4; }
.cid { font-family: monospace; font-size: 11px; color: #666; }
.logline { font-size: 16px; margin: 10px 0 14px; color: #fff; line-height: 1.5; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
          gap: 8px 24px; font-size: 13px; }
.field { line-height: 1.4; }
.field b { color: #aaa; font-weight: 500; }
.axes { display: flex; gap: 14px; margin-top: 10px; font-size: 12px; color: #999; }
.axes b { color: #c4d0e6; }
a { color: #7eb8e8; text-decoration: none; }
a:hover { text-decoration: underline; }
.muted { color: #888; font-size: 12px; }
.jtbd-badge { font-family: monospace; font-size: 11px; background: #1f1f28;
              color: #c4d0e6; padding: 2px 8px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #2a2a32; }
th { background: #131319; color: #aaa; font-weight: 500; font-size: 11px;
     text-transform: uppercase; letter-spacing: 0.4px; }
""")
    parts.append("</style>")
    parts.append("</head><body>")

    parts.append("<h1>Best Concepts — A4 Portfolio</h1>")
    parts.append(
        '<div class="subtitle">Investor-grade concept portfolio. Curated from out/concepts/v3.1-pathc-a4/. Each brief is one of 247+ machine-generated A4-format pitch documents; this view shows the PASS-band (≥85/100) and high-REVIEW (80-84/100) tiers.</div>'
    )

    parts.append('<div class="kpis">')
    parts.append(
        f'<div class="kpi"><div class="v">{n_total:,}</div><div class="l">Total briefs</div></div>'
    )
    parts.append(
        f'<div class="kpi"><div class="v">{n_pass}</div><div class="l">PASS (≥85)</div></div>'
    )
    parts.append(
        f'<div class="kpi"><div class="v">{n_high}</div><div class="l">High-REVIEW (80-84)</div></div>'
    )
    parts.append(
        f'<div class="kpi"><div class="v">{pass_pct:.0f}%</div><div class="l">PASS rate</div></div>'
    )
    parts.append(
        f'<div class="kpi"><div class="v">{mean_score:.1f}</div><div class="l">Mean score</div></div>'
    )
    parts.append("</div>")

    parts.append("<h2>JTBD distribution (PASS-band)</h2>")
    parts.append("<table>")
    parts.append("<tr><th>JTBD label</th><th>Count</th></tr>")
    for label, count in jtbd_dist.most_common():
        parts.append(f"<tr><td>{escape(str(label))}</td><td>{count}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>PASS band (≥85/100) — sorted by score</h2>")
    parts.append('<div class="controls">')
    parts.append(
        '<input type="text" id="filter" placeholder="Filter by title, JTBD, country, asset…" oninput="filt()">'
    )
    parts.append('<select id="jtbd-filter" onchange="filt()"><option value="">All JTBDs</option>')
    for label in sorted(str(k) for k in jtbd_dist):
        parts.append(f'<option value="{escape(label)}">{escape(label)}</option>')
    parts.append("</select>")
    parts.append("</div>")

    for tier_name, all_tier in (("PASS", pass_briefs), ("High-REVIEW", high_review)):
        if tier_name == "High-REVIEW":
            tier_briefs = all_tier[:HIGH_REVIEW_PREVIEW_LIMIT]
            parts.append(f"<h2>High-REVIEW band (80-84/100) — top {len(tier_briefs)}</h2>")
        else:
            tier_briefs = all_tier
        for b in tier_briefs:
            band_class = "pass" if b["score"] >= PASS_FLOOR else "high-review"  # type: ignore[operator]
            jtbd = str(b["jtbd_label"])
            countries = str(b["countries"])
            parts.append(
                f'<div class="brief {band_class}" data-jtbd="{escape(jtbd)}" '
                f'data-search="{escape((str(b["title"]) + " " + jtbd + " " + countries + " " + str(b["asset_name"])).lower())}">'
            )
            parts.append('<div class="brief-head">')
            parts.append(f'<span class="score {band_class}">{b["score"]}/100</span>')
            band_label = "PASS" if b["score"] >= PASS_FLOOR else "HIGH-REVIEW"  # type: ignore[operator]
            parts.append(f'<span class="band-tag {band_class}">{band_label}</span>')
            parts.append(f'<span class="jtbd-badge">{escape(jtbd)}</span>')
            parts.append(
                f'<a class="cid" href="../{escape(str(b["path"]))}" target="_blank">{escape(str(b["id"]))}.md →</a>'
            )
            parts.append("</div>")

            parts.append(f'<div class="logline">{escape(str(b["logline"]))}</div>')

            aud_size = int(b["audience_size"])  # type: ignore[arg-type]
            aud_str = (
                f"{aud_size / ONE_MILLION:.0f}M" if aud_size >= ONE_MILLION else f"{aud_size:,}"
            )
            aud_url = str(b["audience_source_url"])
            aud_name = str(b["audience_source_name"])

            parts.append('<div class="fields">')
            parts.append(
                f'<div class="field"><b>Audience:</b> {aud_str} (<a href="{escape(aud_url)}" target="_blank">{escape(aud_name)}</a>)</div>'
            )
            parts.append(
                f'<div class="field"><b>Countries:</b> {escape(countries)} · <b>Trend:</b> {escape(str(b["trend"]))}</div>'
            )
            asset_url = str(b["asset_url"])
            parts.append(
                f'<div class="field"><b>Asset:</b> <a href="{escape(asset_url)}" target="_blank">{escape(str(b["asset_name"]))}</a> ({escape(str(b["asset_kind"]))})</div>'
            )
            parts.append(f'<div class="field"><b>TRIZ:</b> {escape(str(b["triz"]))}</div>')
            sdt_strength = float(b["sdt_strength"])  # type: ignore[arg-type]
            parts.append(
                f'<div class="field"><b>SDT:</b> {escape(str(b["sdt_primary"]))} ({sdt_strength:.2f})</div>'
            )
            dep = str(b["jtbd_deprivation"])
            dep_short = dep[:DEPRIVATION_PREVIEW_LEN]
            dep_ellipsis = "…" if len(dep) > DEPRIVATION_PREVIEW_LEN else ""
            parts.append(
                f'<div class="field"><b>Deprivation:</b> {escape(dep_short)}{dep_ellipsis}</div>'
            )
            parts.append("</div>")

            axes = b["axes"]
            if isinstance(axes, dict) and axes:
                ax_str = " · ".join(f"<b>{escape(k)}</b> {v}" for k, v in axes.items())
                parts.append(f'<div class="axes">{ax_str}</div>')
            parts.append("</div>")

    parts.append("<script>")
    parts.append("""
function filt() {
  var q = document.getElementById('filter').value.toLowerCase();
  var jt = document.getElementById('jtbd-filter').value;
  document.querySelectorAll('.brief').forEach(function(el) {
    var match = (!q || el.dataset.search.indexOf(q) >= 0)
              && (!jt || el.dataset.jtbd === jt);
    el.style.display = match ? '' : 'none';
  });
}
""")
    parts.append("</script>")
    parts.append("</body></html>")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"  PASS band: {n_pass}")
    print(f"  high-REVIEW: {n_high}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
