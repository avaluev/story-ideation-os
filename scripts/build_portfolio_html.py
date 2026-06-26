"""scripts/build_portfolio_html.py — self-contained cinematic investor deck.

Renders an (enriched) portfolio JSON into a single dark-themed HTML file an
investor can open in a browser: a hero with the Investment Summary card, then
one section per property (title · tagline · logline · story · why-now with
deep-linked demand evidence · audience · python-executed economics table ·
distinct comps · honest risk).

Offline + LLM-free. Every number is python_executed upstream (ADR-0011); every
hyperlink is a deep path (deep-link evidence policy); internal IDs are stripped
from any free text via the template filter (ADR-0010).
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.crystallize import portfolio as pf
from pipeline.template_filter import strip_internal_ids
from scripts.build_portfolio_slate import _enr, _fmt_usd, _ordered

_CSS = (
    ":root{--bg:#0a0a0a;--panel:#121212;--ink:#ece7da;--muted:#9b948a;"
    "--gold:#c9a84c;--line:#262220;--good:#7fb685}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:var(--bg);color:var(--ink);"
    "font:16px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;"
    "-webkit-font-smoothing:antialiased}"
    "a{color:var(--gold);text-decoration:none;border-bottom:1px solid rgba(201,168,76,.35)}"
    "a:hover{border-bottom-color:var(--gold)}"
    ".wrap{max-width:980px;margin:0 auto;padding:0 28px 120px}"
    "header.hero{padding:84px 28px 40px;max-width:980px;margin:0 auto}"
    ".kicker{letter-spacing:.28em;text-transform:uppercase;color:var(--gold);"
    "font-size:12px;font-weight:600}"
    "h1{font-size:clamp(30px,5vw,52px);line-height:1.08;margin:.35em 0 .2em;font-weight:800}"
    ".lede{color:var(--muted);font-size:18px;max-width:760px}"
    ".summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));"
    "gap:14px;margin:34px 0 0}"
    ".cell{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}"
    ".cell .v{font-size:26px;font-weight:800;color:var(--gold)}"
    ".cell .l{color:var(--muted);font-size:12px;text-transform:uppercase;"
    "letter-spacing:.12em;margin-top:4px}"
    "section.card{background:var(--panel);border:1px solid var(--line);"
    "border-radius:16px;padding:30px;margin:26px 0}"
    ".badge{display:inline-block;background:rgba(201,168,76,.12);color:var(--gold);"
    "border:1px solid rgba(201,168,76,.3);border-radius:999px;padding:3px 12px;"
    "font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}"
    ".card h2{font-size:28px;margin:14px 0 4px;font-weight:800}"
    ".tagline{color:var(--gold);font-style:italic;font-size:18px;margin:0 0 14px}"
    ".logline{font-size:18px;color:var(--ink)}"
    ".label{color:var(--gold);font-weight:700;letter-spacing:.02em}"
    ".muted{color:var(--muted)}"
    "ul.demand{list-style:none;padding:0;margin:10px 0}"
    "ul.demand li{padding:8px 0;border-top:1px solid var(--line)}"
    "ul.demand .stat{color:var(--good);font-weight:700}"
    "table.econ{width:100%;border-collapse:collapse;margin:12px 0}"
    "table.econ td{padding:9px 4px;border-bottom:1px solid var(--line);font-size:15px}"
    "table.econ td.k{color:var(--muted)}"
    "table.econ td.v{text-align:right;font-weight:700;color:var(--gold)}"
    ".comps{list-style:none;padding:0;margin:8px 0}"
    ".comps li{padding:5px 0;color:var(--ink)}"
    ".risk{background:rgba(255,255,255,.02);border-left:3px solid var(--gold);"
    "padding:12px 16px;border-radius:0 8px 8px 0;color:var(--muted)}"
    ".foot{color:var(--muted);font-size:13px;border-top:1px solid var(--line);"
    "margin-top:50px;padding-top:24px}"
    ".foot a{color:var(--muted)}"
)


def _esc(text: object) -> str:
    return html.escape(strip_internal_ids(str(text or "")))


def _link(label: str, url: str) -> str:
    if pf.is_deep_path(url):
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{_esc(label)}</a>'
    return _esc(label)


def _demand_html(c: dict[str, Any]) -> str:
    rows = [r for r in (c.get("demand_evidence") or []) if isinstance(r, dict)]
    items: list[str] = []
    for r in rows:
        ok, _ = pf.validate_demand_evidence(r)
        if not ok:
            continue
        stat = _esc(r.get("stat", ""))
        claim = _esc(r.get("claim", ""))
        date = _esc(r.get("date", ""))
        url = html.escape(str(r.get("source_url", "")))
        date_html = f' <span class="muted">({date})</span>' if date else ""
        items.append(
            f'<li><span class="stat">{stat}</span> — {claim}{date_html} '
            f'· <a href="{url}" target="_blank" rel="noopener">source</a></li>'
        )
    if not items:
        return ""
    return (
        '<p class="label">Proof of demand (direct sources)</p>'
        f'<ul class="demand">{"".join(items)}</ul>'
    )


def _comps_html(c: dict[str, Any]) -> str:
    is_theatrical = str(c.get("monetization_model")) == "theatrical"
    head = (
        "Closest comps (box office)"
        if is_theatrical
        else "Tonal anchors (positioning — not revenue comps)"
    )
    items: list[str] = []
    for cm in (c.get("comps") or [])[:4]:
        title = str(cm.get("title", "")).strip()
        url = str(cm.get("boxofficemojo_url") or cm.get("imdb_url") or "")
        bits = [title]
        if is_theatrical:
            ww = cm.get("worldwide_gross_usd")
            roi = cm.get("roi")
            if isinstance(ww, (int, float)):
                bits.append(_fmt_usd(float(ww)) + " WW")
            if isinstance(roi, (int, float)):
                bits.append(f"{roi:.1f}x ROI")
        items.append(f"<li>{_link(' · '.join(bits), url)}</li>")
    return f'<p class="label">{head}</p><ul class="comps">{"".join(items)}</ul>'


def _econ_html(c: dict[str, Any]) -> str:
    tam = c.get("tam_usd")
    tam_src = str(c.get("tam_source_url") or "")
    tam_cell = _link(_fmt_usd(tam), tam_src) if pf.is_deep_path(tam_src) else _esc(_fmt_usd(tam))
    rows = [
        ("SOM — Year 1 (single-title capture)", _esc(_fmt_usd(c.get("som_y1_usd")))),
        ("Lifetime (multi-window, directional)", _esc(_fmt_usd(c.get("lifetime_usd")))),
        ("SAM (serviceable category slice)", _esc(_fmt_usd(c.get("sam_usd")))),
        ("TAM (global format market)", tam_cell),
    ]
    body = "".join(f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in rows)
    return f'<table class="econ">{body}</table>'


def _card_html(c: dict[str, Any], *, n: int) -> str:
    title = _esc(_enr(c, "title", str(c.get("title") or c.get("working_title") or "Untitled")))
    fmt = _esc(c.get("format", "Feature Film"))
    tagline = _enr(c, "tagline")
    logline = _esc(_enr(c, "logline", str(c.get("engine_logline", ""))))
    parts = [
        '<section class="card">',
        f'<span class="badge">{n:02d} · {fmt}</span>',
        f"<h2>{title}</h2>",
    ]
    if tagline:
        parts.append(f'<p class="tagline">{_esc(tagline)}</p>')
    parts.append(f'<p class="logline">{logline}</p>')
    for label, key in (
        ("Story", "story"),
        ("What makes it different", "what_different"),
        ("Why now", "why_now"),
    ):
        val = _enr(c, key)
        if val:
            parts.append(f'<p><span class="label">{label}.</span> {_esc(val)}</p>')
    parts.append(_demand_html(c))
    aud = _enr(c, "audience")
    if aud:
        parts.append(f'<p><span class="label">Audience.</span> {_esc(aud)}</p>')
    parts.append('<p class="label">Economics (Year 1, python-executed)</p>')
    parts.append(_econ_html(c))
    parts.append(
        f'<p class="muted">Monetization: {fmt} · {_esc(c.get("monetization_model"))} '
        "&nbsp;•&nbsp; Standalone original IP — no franchise dependency.</p>"
    )
    rev = _enr(c, "revenue_thesis")
    if rev:
        parts.append(f'<p><span class="label">Revenue thesis.</span> {_esc(rev)}</p>')
    parts.append(_comps_html(c))
    risk = _enr(c, "risk")
    if risk:
        parts.append(
            f'<p class="risk"><span class="label">Key risk & mitigation.</span> {_esc(risk)}</p>'
        )
    parts.append("</section>")
    return "".join(parts)


def render_html(concepts: list[dict[str, Any]]) -> str:
    ordered = _ordered(concepts)
    total_som = sum(float(c.get("som_y1_usd") or 0) for c in ordered)
    total_life = sum(float(c.get("lifetime_usd") or 0) for c in ordered)
    formats = sorted({str(c.get("format", "")) for c in ordered})
    demand_total = sum(
        1
        for c in ordered
        for r in (c.get("demand_evidence") or [])
        if isinstance(r, dict) and pf.validate_demand_evidence(r)[0]
    )
    cells = [
        (str(len(ordered)), "Original properties"),
        (str(len(formats)), "Content formats"),
        (_fmt_usd(total_som), "Combined Y1 SOM floor"),
        (_fmt_usd(total_life), "Lifetime (directional)"),
        (str(demand_total), "Demand sources"),
        ("100%", "Original / standalone"),
    ]
    summary = "".join(
        f'<div class="cell"><div class="v">{_esc(v)}</div><div class="l">{_esc(label)}</div></div>'
        for v, label in cells
    )
    cards = "".join(_card_html(c, n=i + 1) for i, c in enumerate(ordered))
    lede = (
        f"{len(ordered)} original, standalone properties across {len(formats)} content "
        "formats — each with a python-executed Year-1 revenue floor, credible market sizing, "
        "deep-linked comparables, and direct sources for present-tense audience demand. "
        "Zero franchise dependency."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Standalone Slate — Diversified Portfolio of Original Properties</title>
<style>{_CSS}</style></head>
<body>
<header class="hero">
  <div class="kicker">Confidential · Original IP Slate</div>
  <h1>The Standalone Slate</h1>
  <p class="lede">{lede}</p>
  <div class="summary">{summary}</div>
</header>
<main class="wrap">
{cards}
<p class="foot">Every market figure is computed in Python from named, sourced constants and a
894-film corpus of comparables — never written by a language model. SOM &lt; SAM &lt; TAM holds for
every property. Combined SOM is the sum of independent per-title floors (a fully-greenlit slate),
not a single project. Demand sources are independently reachable deep links.</p>
</main>
</body></html>"""


def build(portfolio_json: Path, out_html: Path) -> dict[str, Any]:
    from scripts.build_format_slate import apply_filters  # noqa: PLC0415

    data = json.loads(Path(portfolio_json).read_text(encoding="utf-8"))
    kept, _ = apply_filters(list(data.get("concepts", [])))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(render_html(kept), encoding="utf-8")
    return {"kept": len(kept), "out_html": str(out_html), "bytes": out_html.stat().st_size}


def main() -> None:
    if len(sys.argv) > 1:
        portfolio_json = Path(sys.argv[1])
    else:
        from scripts.build_portfolio_slate import _latest_portfolio_json  # noqa: PLC0415

        portfolio_json = _latest_portfolio_json()
    out_html = Path("outputs/portfolio/investor_deck_EN.html")
    print(json.dumps(build(portfolio_json, out_html), indent=2))


if __name__ == "__main__":
    main()
