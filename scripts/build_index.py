# ruff: noqa: E501
"""Build a single browsable out/index.html that lists all 1200 literary
stories and 133 A4 investor briefs in sortable + searchable tables.

No JS dependencies; vanilla DOM + sort + filter. Click a row's concept_id
to open the underlying markdown file in the browser.
"""

from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LITERARY_DIR = ROOT / "out" / "concepts" / "v3.1-pathc"
A4_DIR = ROOT / "out" / "concepts" / "v3.1-pathc-a4"
OUT = ROOT / "out" / "index.html"

# Late import so the script can be exercised even outside the engine tree.
sys.path.insert(0, str(ROOT))
from pipeline.seed_engine import sample  # noqa: E402


def _parse_literary(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    title_m = re.search(r"^# (.+?)\s*$", text, re.MULTILINE)
    seed_m = re.search(r"\*\*Seed:\*\* `(\d+)`", text)
    band_m = re.search(r"\*\*Score Band:\s*([A-D])\*\*", text)
    op_m = re.search(r"\*\*Mutation operator:\*\*\s+([^\n]+)", text)
    tagline_m = re.search(r"^# .+?\n\n\*([^*]+)\*", text, re.MULTILINE | re.DOTALL)
    geography_m = re.search(r"sits in \*\*([^*]+)\*\*", text)
    tension_m = re.search(r"contradiction at its heart - \*([^*]+)\*", text)

    seed_int = int(seed_m.group(1)) if seed_m else 0
    ip_label = "?"
    if seed_int:
        try:
            pkg = sample(seed_int)
            ip_label = pkg.irreversibility_pattern.label
        except Exception:
            ip_label = "?"

    return {
        "id": path.stem,
        "title": title_m.group(1).strip() if title_m else "?",
        "tagline": (tagline_m.group(1).strip() if tagline_m else "")[:140],
        "seed": seed_int,
        "band": band_m.group(1) if band_m else "?",
        "operator": op_m.group(1).strip().rstrip(".").lower() if op_m else "?",
        "ip": ip_label,
        "geography": geography_m.group(1).strip() if geography_m else "?",
        "tension": tension_m.group(1).strip().replace("_", " ") if tension_m else "?",
        "path": str(path.relative_to(ROOT)),
    }


def _parse_a4(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    title_m = re.search(r"^# (.+?)\s*$", text, re.MULTILINE)
    seed_m = re.search(r"\*\*Seed:\*\* `(\d+)`", text)
    score_m = re.search(r"##\s+Score\s*\n+\s*\*\*(\d{1,3})/100\*\*", text)
    jtbd_m = re.search(r"##\s+JTBD\s*\n+\s*\*\*([^*]+)\*\*", text)
    aud_m = re.search(r"Estimated audience:\s*([\d,]+)", text)
    countries_m = re.search(r"Countries:\s*([^\n]+)", text)
    readiness_m = re.search(r"Investment readiness:\s*\*\*([A-Z]+)\*\*", text)
    asset_m = re.search(r"##\s+Asset\s*\n+\s*\*\*([^*]+)\*\*", text)
    src_url_m = re.search(r"source:\s*\[[^\]]+\]\((https?://[^)]+)\)", text)

    seed_int = int(seed_m.group(1)) if seed_m else 0
    return {
        "id": path.stem,
        "title": (title_m.group(1).strip() if title_m else "?")[:120],
        "seed": seed_int,
        "score": int(score_m.group(1)) if score_m else 0,
        "jtbd": jtbd_m.group(1).strip() if jtbd_m else "?",
        "audience": aud_m.group(1) if aud_m else "?",
        "countries": countries_m.group(1).strip() if countries_m else "?",
        "readiness": readiness_m.group(1) if readiness_m else "?",
        "asset": asset_m.group(1).strip() if asset_m else "?",
        "source_url": src_url_m.group(1) if src_url_m else "",
        "path": str(path.relative_to(ROOT)),
    }


HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Anomaly Engine v3.1 — Path C output (1200 literary + 133 A4)</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
    background: #0e1116; color: #e6edf3; margin: 0; padding: 0;
  }
  header { padding: 20px 28px 10px; border-bottom: 1px solid #2d333b; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .subtitle { color: #8b949e; font-size: 12px; }
  nav { padding: 12px 28px; background: #161b22; border-bottom: 1px solid #2d333b; display: flex; gap: 12px; align-items: center; }
  nav button {
    background: #21262d; color: #e6edf3; border: 1px solid #30363d; padding: 6px 14px;
    border-radius: 6px; cursor: pointer; font-size: 13px;
  }
  nav button.active { background: #1f6feb; border-color: #1f6feb; }
  nav input[type=search] {
    flex: 1; max-width: 480px; background: #0d1117; color: #e6edf3;
    border: 1px solid #30363d; padding: 6px 10px; border-radius: 6px; font-size: 13px;
  }
  nav .stat { color: #8b949e; font-size: 12px; }
  .filters { padding: 10px 28px; background: #0d1117; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; border-bottom: 1px solid #2d333b; }
  .filters select {
    background: #161b22; color: #e6edf3; border: 1px solid #30363d; padding: 5px 8px;
    border-radius: 4px; font-size: 12px;
  }
  .filters .pill { background: #1f2937; padding: 3px 8px; border-radius: 12px; color: #c9d1d9; font-size: 11px; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #161b22; color: #c9d1d9; text-align: left; padding: 8px 10px; font-weight: 600; font-size: 12px; cursor: pointer; user-select: none; border-bottom: 1px solid #30363d; position: sticky; top: 0; z-index: 1; }
  th:hover { background: #1c2128; }
  th.sorted::after { content: " \\25B2"; }
  th.sorted-desc::after { content: " \\25BC"; }
  td { padding: 8px 10px; border-bottom: 1px solid #21262d; vertical-align: top; font-size: 13px; }
  tr:hover { background: #161b22; }
  td.id a { color: #58a6ff; text-decoration: none; font-family: ui-monospace, "SF Mono", monospace; font-size: 11px; }
  td.title { font-weight: 500; max-width: 380px; }
  .badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .badge-A { background: #1a7f37; color: #fff; }
  .badge-B { background: #9e6a03; color: #fff; }
  .badge-C { background: #6e7681; color: #fff; }
  .badge-D { background: #cf222e; color: #fff; }
  .score { font-family: ui-monospace, monospace; font-weight: 600; }
  .score-pass { color: #3fb950; }
  .score-review { color: #d29922; }
  .score-reject { color: #f85149; }
  .pill-readiness { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 10px; font-weight: 700; }
  .pill-PASS { background: #1a7f37; color: #fff; }
  .pill-REVIEW { background: #9e6a03; color: #fff; }
  .pill-REJECT { background: #cf222e; color: #fff; }
  .has-a4 { color: #3fb950; }
  .no-a4 { color: #6e7681; }
  .source-link { color: #58a6ff; text-decoration: none; font-size: 11px; }
  .source-link:hover { text-decoration: underline; }
  .table-wrap { overflow: auto; max-height: calc(100vh - 230px); }
  .hidden { display: none; }
  .empty { padding: 40px; color: #6e7681; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Anomaly Engine v3.1 — Path C output</h1>
  <div class="subtitle">__SUBTITLE__</div>
</header>
<nav>
  <button id="tab-lit" class="active">Literary (1200)</button>
  <button id="tab-a4">A4 investor brief (133)</button>
  <input id="q" type="search" placeholder="filter title / id / asset / operator / IP / geography…" />
  <span class="stat" id="visible-count"></span>
</nav>
<div class="filters" id="filters-lit">
  <span class="pill">Operator</span>
  <select id="f-operator"><option value="">all</option></select>
  <span class="pill">IP</span>
  <select id="f-ip"><option value="">all</option></select>
  <span class="pill">Band</span>
  <select id="f-band"><option value="">all</option></select>
</div>
<div class="filters hidden" id="filters-a4">
  <span class="pill">JTBD</span>
  <select id="f-jtbd"><option value="">all</option></select>
  <span class="pill">Readiness</span>
  <select id="f-readiness"><option value="">all</option></select>
  <span class="pill">Score</span>
  <select id="f-score">
    <option value="">all</option>
    <option value="pass">PASS (≥85)</option>
    <option value="review">REVIEW (70-84)</option>
    <option value="reject">REJECT (<70)</option>
  </select>
</div>
<div class="table-wrap" id="wrap-lit">
  <table id="t-lit">
    <thead><tr>
      <th data-sort="id">id</th>
      <th data-sort="title">title</th>
      <th data-sort="operator">operator</th>
      <th data-sort="ip">irreversibility</th>
      <th data-sort="band">band</th>
      <th data-sort="geography">geography</th>
      <th data-sort="tension">tension</th>
      <th>A4</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>
<div class="table-wrap hidden" id="wrap-a4">
  <table id="t-a4">
    <thead><tr>
      <th data-sort="id">id</th>
      <th data-sort="title">title</th>
      <th data-sort="score">score</th>
      <th data-sort="readiness">readiness</th>
      <th data-sort="jtbd">JTBD</th>
      <th data-sort="audience">audience</th>
      <th data-sort="asset">asset</th>
      <th>source</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>
<script>
const LIT = __LIT_JSON__;
const A4 = __A4_JSON__;
"""

HTML_TAIL = r"""
function bandClass(b) { return 'badge badge-' + (b || 'C'); }
function scoreClass(s) { return s >= 85 ? 'score score-pass' : s >= 70 ? 'score score-review' : 'score score-reject'; }
function uniq(rows, key) { return [...new Set(rows.map(r => r[key]).filter(Boolean))].sort(); }

function fillSelect(id, values) {
  const el = document.getElementById(id);
  for (const v of values) {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v;
    el.appendChild(opt);
  }
}

let sortState = { lit: { col: 'operator', dir: 1 }, a4: { col: 'score', dir: -1 } };

function render() {
  const isA4 = document.getElementById('tab-a4').classList.contains('active');
  const wrap = document.getElementById(isA4 ? 'wrap-a4' : 'wrap-lit');
  const tbody = wrap.querySelector('tbody');
  const q = document.getElementById('q').value.toLowerCase();
  const rows = isA4 ? A4 : LIT;
  const filters = isA4
    ? {
        jtbd: document.getElementById('f-jtbd').value,
        readiness: document.getElementById('f-readiness').value,
        score: document.getElementById('f-score').value,
      }
    : {
        operator: document.getElementById('f-operator').value,
        ip: document.getElementById('f-ip').value,
        band: document.getElementById('f-band').value,
      };
  const filtered = rows.filter(r => {
    if (q) {
      const blob = JSON.stringify(r).toLowerCase();
      if (!blob.includes(q)) return false;
    }
    for (const [k, v] of Object.entries(filters)) {
      if (!v) continue;
      if (k === 'score') {
        if (v === 'pass' && r.score < 85) return false;
        if (v === 'review' && (r.score < 70 || r.score >= 85)) return false;
        if (v === 'reject' && r.score >= 70) return false;
        continue;
      }
      if (String(r[k] || '') !== v) return false;
    }
    return true;
  });
  const ss = isA4 ? sortState.a4 : sortState.lit;
  filtered.sort((a, b) => {
    const av = a[ss.col], bv = b[ss.col];
    if (av == null || bv == null) return 0;
    if (typeof av === 'number') return (av - bv) * ss.dir;
    return String(av).localeCompare(String(bv)) * ss.dir;
  });
  tbody.innerHTML = '';
  for (const r of filtered) {
    const tr = document.createElement('tr');
    if (isA4) {
      tr.innerHTML =
        `<td class="id"><a href="../${r.path}" target="_blank">${r.id}</a></td>` +
        `<td class="title">${escapeHTML(r.title)}</td>` +
        `<td><span class="${scoreClass(r.score)}">${r.score}/100</span></td>` +
        `<td><span class="pill-readiness pill-${r.readiness}">${r.readiness}</span></td>` +
        `<td>${escapeHTML(r.jtbd)}</td>` +
        `<td>${escapeHTML(r.audience)} <span style="color:#6e7681;font-size:10px;">(${escapeHTML(r.countries||'')})</span></td>` +
        `<td>${escapeHTML(r.asset)}</td>` +
        `<td>${r.source_url ? `<a class="source-link" href="${escapeHTML(r.source_url)}" target="_blank">link</a>` : ''}</td>`;
    } else {
      const a4Cell = r.has_a4
        ? `<a class="has-a4" href="../out/concepts/v3.1-pathc-a4/${r.id}.md" target="_blank">✓</a>`
        : '<span class="no-a4">—</span>';
      tr.innerHTML =
        `<td class="id"><a href="../${r.path}" target="_blank">${r.id}</a></td>` +
        `<td class="title">${escapeHTML(r.title)}<div style="color:#8b949e;font-size:11px;font-style:italic;">${escapeHTML(r.tagline||'')}</div></td>` +
        `<td>${escapeHTML(r.operator)}</td>` +
        `<td>${escapeHTML(r.ip)}</td>` +
        `<td><span class="${bandClass(r.band)}">${r.band}</span></td>` +
        `<td>${escapeHTML(r.geography)}</td>` +
        `<td>${escapeHTML(r.tension)}</td>` +
        `<td>${a4Cell}</td>`;
    }
    tbody.appendChild(tr);
  }
  document.getElementById('visible-count').textContent =
    `${filtered.length} of ${rows.length} visible`;
  // Update sort indicator
  document.querySelectorAll('th').forEach(th => { th.classList.remove('sorted','sorted-desc'); });
  const tab = isA4 ? 't-a4' : 't-lit';
  document.querySelectorAll(`#${tab} th[data-sort]`).forEach(th => {
    if (th.dataset.sort === ss.col) {
      th.classList.add(ss.dir === 1 ? 'sorted' : 'sorted-desc');
    }
  });
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function setupTabs() {
  const litBtn = document.getElementById('tab-lit');
  const a4Btn = document.getElementById('tab-a4');
  litBtn.onclick = () => switchTab('lit');
  a4Btn.onclick = () => switchTab('a4');
}

function switchTab(t) {
  const isA4 = t === 'a4';
  document.getElementById('tab-lit').classList.toggle('active', !isA4);
  document.getElementById('tab-a4').classList.toggle('active', isA4);
  document.getElementById('wrap-lit').classList.toggle('hidden', isA4);
  document.getElementById('wrap-a4').classList.toggle('hidden', !isA4);
  document.getElementById('filters-lit').classList.toggle('hidden', isA4);
  document.getElementById('filters-a4').classList.toggle('hidden', !isA4);
  render();
}

function setupSort() {
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.onclick = () => {
      const isA4 = document.getElementById('tab-a4').classList.contains('active');
      const ss = isA4 ? sortState.a4 : sortState.lit;
      if (ss.col === th.dataset.sort) ss.dir *= -1;
      else { ss.col = th.dataset.sort; ss.dir = 1; }
      render();
    };
  });
}

function init() {
  fillSelect('f-operator', uniq(LIT, 'operator'));
  fillSelect('f-ip', uniq(LIT, 'ip'));
  fillSelect('f-band', uniq(LIT, 'band'));
  fillSelect('f-jtbd', uniq(A4, 'jtbd'));
  fillSelect('f-readiness', uniq(A4, 'readiness'));
  document.getElementById('q').oninput = render;
  ['f-operator','f-ip','f-band','f-jtbd','f-readiness','f-score'].forEach(id => {
    document.getElementById(id).onchange = render;
  });
  setupTabs();
  setupSort();
  render();
}
init();
</script>
</body>
</html>
"""


def main() -> int:
    if not LITERARY_DIR.is_dir():
        print(f"ERROR: {LITERARY_DIR} not found", file=sys.stderr)
        return 2
    print("scanning literary…", flush=True)
    lit = [_parse_literary(p) for p in sorted(LITERARY_DIR.glob("*.md"))]
    print(f"  {len(lit)} literary stories parsed", flush=True)
    print("scanning A4…", flush=True)
    a4 = [_parse_a4(p) for p in sorted(A4_DIR.glob("*.md"))] if A4_DIR.is_dir() else []
    print(f"  {len(a4)} A4 briefs parsed", flush=True)

    a4_ids = {r["id"] for r in a4}
    for r in lit:
        r["has_a4"] = r["id"] in a4_ids

    subtitle = (
        f"{len(lit)} literary 14-section stories &middot; "
        f"{len(a4)} v1-spec 12-section A4 briefs &middot; "
        f"{sum(1 for r in lit if r['has_a4'])} stories with paired A4 brief"
    )
    head = HTML_HEAD.replace("__SUBTITLE__", escape(subtitle))
    head = head.replace(
        "__LIT_JSON__",
        json.dumps(lit, ensure_ascii=False),
    ).replace(
        "__A4_JSON__",
        json.dumps(a4, ensure_ascii=False),
    )

    OUT.write_text(head + HTML_TAIL, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
