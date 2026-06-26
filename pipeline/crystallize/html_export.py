"""pipeline.crystallize.html_export — self-contained Crystal Board HTML.

Renders a CrystalBoard to a single HTML file that opens in any modern
browser with zero network calls. The file is self-contained: vanilla
JavaScript, inline CSS, and an SVG scatter plot drawn from the embedded
JSON data. No external CDN, no fonts beyond the system default stack.

Layout:
  * Header — problem, themes, n_generated, runtime, corpus_size,
    checklist_version.
  * SVG scatter - genius_score (Y) vs goldilocks_score (X), coloured by
    cluster_id, radius scaled by derivative_distance. Click -> side panel.
  * Side panel - top-5 comps, C001-C007 mini-bars, full compound_seed JSON.
  * Sortable table — every candidate, every key score column.
  * Cluster summary — 8 rows with size, avg score, avg corpus ROI.
  * Kill-switch lane — collapsed list of candidates whose
    ``greatness.kill_switch_failed`` is non-empty.

ADR-0001: writes go through ``pipeline.state.safe_write``.
MUST NOT import LLM clients. MUST NOT import from frameworks/.
"""
# This module is a single large literal template for HTML / CSS / JS.
# Breaking CSS rules across multiple Python lines harms readability without
# changing the rendered output (browsers ignore whitespace in CSS / JS),
# so E501 is disabled file-wide.
# RUF001 / RUF003 (ambiguous Unicode in strings / comments) are allowed for
# typographic chars (multiplication, arrow, em-dash, middle-dot) that we
# render to HTML.
# ruff: noqa: E501, RUF001

from __future__ import annotations

import html
import json
from pathlib import Path

from pipeline.crystallize.board import CrystalBoard
from pipeline.state import safe_write

# 8-colour palette, one per cluster id. Distinct hues that print well on
# dark and light backgrounds.
_CLUSTER_PALETTE: tuple[str, ...] = (
    "#4c8bf5",  # 0 institutional - blue
    "#e6754d",  # 1 emotional - coral
    "#8b5cf6",  # 2 technology - violet
    "#22c55e",  # 3 identity - green
    "#0ea5e9",  # 4 nature - sky
    "#eab308",  # 5 economic - amber
    "#ec4899",  # 6 temporal - pink
    "#14b8a6",  # 7 civilizational - teal
)


def _esc(text: str) -> str:
    """HTML-escape a string for safe inline injection."""
    return html.escape(str(text), quote=True)


def render_html(board: CrystalBoard) -> str:
    """Return the full crystal_board.html as a single string."""
    board_dict = board.to_dict()
    # Serialise the board so client-side JS has the full dataset for the
    # sortable table + side panel; safe because we wrap in <script type="application/json">.
    board_json = json.dumps(board_dict, ensure_ascii=False, indent=None, sort_keys=False)
    # Defang any </script> sequences so a malicious problem string can't break out.
    board_json_safe = board_json.replace("</", "<\\/")

    palette_js = json.dumps(list(_CLUSTER_PALETTE))

    return _TEMPLATE.format(
        title=_esc(f"Crystal Board — {board.board_id}"),
        board_id=_esc(board.board_id),
        problem=_esc(board.problem),
        themes=_esc(" | ".join(board.themes) if board.themes else "—"),
        n_generated=board.n_generated,
        n_requested=board.n_requested,
        runtime_seconds=f"{board.runtime_seconds:.1f}",
        corpus_size=board.corpus_size,
        checklist_version=_esc(board.checklist_version),
        generated_at=_esc(board.generated_at),
        cluster_collapse_class=" collapsed" if board.cluster_collapse else "",
        cluster_collapse_text=(
            "⚠ CLUSTER COLLAPSE — one cluster holds >60% of candidates. "
            "Theme may be over-constraining the sampler."
            if board.cluster_collapse
            else ""
        ),
        board_json=board_json_safe,
        palette_js=palette_js,
    )


def write_html(board: CrystalBoard, path: Path) -> None:
    """Atomically write the rendered HTML to ``path``."""
    safe_write(path, render_html(board))


__all__ = ["render_html", "write_html"]


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
#
# Embedded JS reads the inlined JSON to build:
#   - the SVG scatter (one <circle> per candidate)
#   - the sortable table (one <tr> per candidate)
#   - the side panel (populated on click)
#
# All text values are JSON-encoded so we don't need to re-escape on the
# Python side beyond the initial </ defang above.
#
# Style is intentionally minimal — operator should be able to print this
# or open it on a tablet without surprises.

_TEMPLATE: str = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #0f172a;
    --panel: #1e293b;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --border: #334155;
    --red: #ef4444;
    --green: #22c55e;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    font-size: 14px;
    line-height: 1.4;
  }}
  header {{
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  }}
  header h1 {{ margin: 0 0 8px 0; font-size: 18px; font-weight: 600; color: var(--accent); }}
  header .meta {{ color: var(--muted); font-size: 12px; }}
  header .meta strong {{ color: var(--text); }}
  .layout {{
    display: grid;
    grid-template-columns: 1fr 360px;
    gap: 16px;
    padding: 16px 24px;
  }}
  .col-main, .col-side {{ background: var(--panel); border-radius: 8px; padding: 16px; }}
  h2 {{
    font-size: 14px;
    margin: 0 0 12px 0;
    color: var(--accent);
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }}
  .scatter-wrap {{ position: relative; }}
  svg {{ width: 100%; height: 360px; display: block; background: #0a1020; border-radius: 6px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th, td {{ border-bottom: 1px solid var(--border); padding: 6px 8px; text-align: left; }}
  th {{ cursor: pointer; user-select: none; color: var(--muted); font-weight: 500; }}
  th.sorted {{ color: var(--accent); }}
  tbody tr {{ cursor: pointer; }}
  tbody tr:hover {{ background: rgba(56, 189, 248, 0.08); }}
  tbody tr.selected {{ background: rgba(56, 189, 248, 0.18); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .cluster-pill {{
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    color: #0f172a;
    font-weight: 600;
  }}
  .kill {{ color: var(--red); font-weight: 600; }}
  .ok {{ color: var(--green); }}
  .cluster-collapse-banner {{
    margin: 0 0 16px 0;
    padding: 8px 12px;
    background: rgba(239, 68, 68, 0.12);
    border-left: 3px solid var(--red);
    color: var(--text);
    font-size: 12px;
  }}
  .cluster-collapse-banner.collapsed {{ display: none; }}
  .side-section {{ margin-bottom: 18px; }}
  .greatness-bars {{ display: grid; gap: 2px; }}
  .greatness-bars .row {{
    display: grid;
    grid-template-columns: 36px 1fr 38px;
    align-items: center;
    gap: 8px;
    font-size: 11px;
  }}
  .greatness-bars .bar {{ height: 8px; background: var(--green); border-radius: 2px; }}
  .greatness-bars .bar.kill {{ background: var(--red); }}
  .greatness-bars .bar.bg {{ background: var(--border); position: relative; }}
  .comp-row {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 4px;
    padding: 6px 0;
    border-bottom: 1px dashed var(--border);
    font-size: 11px;
  }}
  .comp-row .title {{ color: var(--text); font-weight: 500; }}
  .comp-row .meta {{ color: var(--muted); }}
  .comp-row a {{ color: var(--accent); text-decoration: none; margin-right: 6px; }}
  .comp-row a:hover {{ text-decoration: underline; }}
  details {{
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 10px;
    margin-top: 8px;
  }}
  details summary {{ cursor: pointer; font-size: 11px; color: var(--muted); }}
  pre {{
    margin: 8px 0 0 0;
    padding: 10px;
    background: #0a1020;
    border-radius: 4px;
    color: var(--text);
    font-size: 11px;
    max-height: 260px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .cluster-summary table th, .cluster-summary table td {{ font-size: 11px; padding: 4px 6px; }}
  .empty-panel {{ color: var(--muted); font-style: italic; font-size: 12px; }}
  @media (max-width: 1024px) {{
    .layout {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<header>
  <h1>🎲 Crystal Board — {board_id}</h1>
  <div class="meta">
    <strong>Problem:</strong> {problem}<br>
    <strong>Themes:</strong> {themes}<br>
    <strong>Sampled:</strong> {n_generated} / {n_requested} candidates in {runtime_seconds}s
    &nbsp;·&nbsp;
    <strong>Corpus:</strong> {corpus_size} films
    &nbsp;·&nbsp;
    <strong>Checklist:</strong> v{checklist_version}
    &nbsp;·&nbsp;
    <span style="color: var(--muted);">{generated_at}</span>
  </div>
</header>

<div class="cluster-collapse-banner{cluster_collapse_class}">{cluster_collapse_text}</div>

<div class="layout">
  <div class="col-main">
    <div class="scatter-wrap">
      <h2>Genius × Goldilocks landscape (n={n_generated})</h2>
      <svg id="scatter" viewBox="0 0 800 360" preserveAspectRatio="none"></svg>
    </div>

    <div style="margin-top: 24px;">
      <h2>All candidates · click row for details</h2>
      <table id="candidate-table">
        <thead>
          <tr>
            <th data-key="candidate_id">id</th>
            <th data-key="cluster_name">cluster</th>
            <th data-key="crystallization_score" data-sorted="desc" class="sorted">cryst ↓</th>
            <th data-key="greatness.weighted_total">grtn</th>
            <th data-key="score_vector.genius_score">genius</th>
            <th data-key="derivative_distance">deriv</th>
            <th data-key="score_vector.divisiveness_score">div</th>
            <th data-key="score_vector.som_floor_M">som $M</th>
            <th data-key="corpus_grounded_audience_overlap_M">audience $M</th>
          </tr>
        </thead>
        <tbody id="candidate-tbody"></tbody>
      </table>
    </div>

    <div class="cluster-summary" style="margin-top: 24px;">
      <h2>Cluster summary</h2>
      <table>
        <thead><tr><th>cluster</th><th>size</th><th>avg cryst</th><th>avg roi</th><th>top candidate</th></tr></thead>
        <tbody id="cluster-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="col-side">
    <div id="side-panel">
      <p class="empty-panel">Click a dot on the scatter or a row in the table to inspect a candidate.</p>
    </div>
  </div>
</div>

<script id="board-data" type="application/json">{board_json}</script>
<script>
(function() {{
  const board = JSON.parse(document.getElementById('board-data').textContent);
  const palette = {palette_js};
  const cands = board.candidates || [];
  const clusters = board.clusters || [];

  function safeGet(obj, path, fallback) {{
    if (!obj) return fallback;
    const parts = path.split('.');
    let cur = obj;
    for (const p of parts) {{
      if (cur == null) return fallback;
      cur = cur[p];
    }}
    return cur == null ? fallback : cur;
  }}

  function fmtNum(v, digits) {{
    if (v == null || isNaN(v)) return '—';
    return Number(v).toFixed(digits == null ? 2 : digits);
  }}

  function fmtMoneyM(v) {{
    if (v == null || isNaN(v)) return '—';
    return '$' + Math.round(v) + 'M';
  }}

  function esc(s) {{
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {{
      return {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[ch];
    }});
  }}

  function colorFor(cid) {{
    if (cid == null || cid < 0 || cid >= palette.length) return '#94a3b8';
    return palette[cid];
  }}

  // ---- SVG scatter ----
  function drawScatter() {{
    const svg = document.getElementById('scatter');
    const w = 800, h = 360, margin = 40;
    svg.innerHTML = '';
    // Axes
    const xAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    xAxis.setAttribute('x1', margin); xAxis.setAttribute('y1', h - margin);
    xAxis.setAttribute('x2', w - 10); xAxis.setAttribute('y2', h - margin);
    xAxis.setAttribute('stroke', '#334155'); svg.appendChild(xAxis);
    const yAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    yAxis.setAttribute('x1', margin); yAxis.setAttribute('y1', 10);
    yAxis.setAttribute('x2', margin); yAxis.setAttribute('y2', h - margin);
    yAxis.setAttribute('stroke', '#334155'); svg.appendChild(yAxis);
    // Labels
    const xLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    xLabel.setAttribute('x', w / 2); xLabel.setAttribute('y', h - 8);
    xLabel.setAttribute('fill', '#94a3b8'); xLabel.setAttribute('font-size', '11');
    xLabel.setAttribute('text-anchor', 'middle');
    xLabel.textContent = 'goldilocks_score →'; svg.appendChild(xLabel);
    const yLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    yLabel.setAttribute('x', -h / 2); yLabel.setAttribute('y', 14);
    yLabel.setAttribute('fill', '#94a3b8'); yLabel.setAttribute('font-size', '11');
    yLabel.setAttribute('transform', 'rotate(-90)'); yLabel.setAttribute('text-anchor', 'middle');
    yLabel.textContent = 'genius_score →'; svg.appendChild(yLabel);
    // Dots
    cands.forEach(c => {{
      const x = margin + ((safeGet(c, 'score_vector.goldilocks_score', 0)) * (w - margin - 20));
      const y = (h - margin) - ((safeGet(c, 'score_vector.genius_score', 0)) * (h - margin - 20));
      const r = 3 + 4 * (safeGet(c, 'derivative_distance', 0));
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', x); dot.setAttribute('cy', y); dot.setAttribute('r', r);
      dot.setAttribute('fill', colorFor(c.cluster_id));
      dot.setAttribute('opacity', '0.78');
      dot.setAttribute('stroke', '#0f172a');
      dot.setAttribute('stroke-width', '0.5');
      dot.style.cursor = 'pointer';
      dot.addEventListener('click', () => selectCandidate(c.candidate_id));
      svg.appendChild(dot);
    }});
  }}

  // ---- Sortable table ----
  let sortKey = 'crystallization_score';
  let sortDir = 'desc';

  function renderTable() {{
    const tbody = document.getElementById('candidate-tbody');
    const rows = cands.slice().sort((a, b) => {{
      const av = safeGet(a, sortKey, 0);
      const bv = safeGet(b, sortKey, 0);
      const cmp = (typeof av === 'number' && typeof bv === 'number')
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortDir === 'asc' ? cmp : -cmp;
    }});
    tbody.innerHTML = rows.map(c => `
      <tr data-cid="${{c.candidate_id}}">
        <td><code>${{c.candidate_id}}</code></td>
        <td><span class="cluster-pill" style="background:${{colorFor(c.cluster_id)}}">${{esc(c.cluster_name || '—')}}</span></td>
        <td class="num">${{fmtNum(c.crystallization_score, 3)}}</td>
        <td class="num">${{fmtNum(safeGet(c, 'greatness.weighted_total', 0), 2)}}</td>
        <td class="num">${{fmtNum(safeGet(c, 'score_vector.genius_score', 0), 2)}}</td>
        <td class="num">${{fmtNum(c.derivative_distance, 2)}}</td>
        <td class="num">${{fmtNum(safeGet(c, 'score_vector.divisiveness_score', 0), 1)}}</td>
        <td class="num">${{fmtMoneyM(safeGet(c, 'score_vector.som_floor_M'))}}</td>
        <td class="num">${{fmtMoneyM(c.corpus_grounded_audience_overlap_M)}}</td>
      </tr>
    `).join('');
    tbody.querySelectorAll('tr').forEach(tr => {{
      tr.addEventListener('click', () => selectCandidate(tr.dataset.cid));
    }});
  }}

  document.querySelectorAll('#candidate-table th').forEach(th => {{
    th.addEventListener('click', () => {{
      const k = th.dataset.key;
      if (sortKey === k) {{
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      }} else {{
        sortKey = k;
        sortDir = 'desc';
      }}
      document.querySelectorAll('#candidate-table th').forEach(h => h.classList.remove('sorted'));
      th.classList.add('sorted');
      renderTable();
    }});
  }});

  // ---- Cluster summary ----
  function renderClusters() {{
    const tb = document.getElementById('cluster-tbody');
    tb.innerHTML = clusters.map(s => `
      <tr>
        <td><span class="cluster-pill" style="background:${{colorFor(s.cluster_id)}}">${{s.cluster_name}}</span></td>
        <td class="num">${{s.n_members}}</td>
        <td class="num">${{fmtNum(s.avg_crystallization_score, 3)}}</td>
        <td class="num">${{s.avg_corpus_roi == null ? '—' : fmtNum(s.avg_corpus_roi, 2) + '×'}}</td>
        <td>${{s.top_candidate_id == null ? '—' : '<code>' + s.top_candidate_id + '</code>'}}</td>
      </tr>
    `).join('');
  }}

  // ---- Side panel ----
  function selectCandidate(cid) {{
    const c = cands.find(x => x.candidate_id === cid);
    if (!c) return;
    document.querySelectorAll('#candidate-tbody tr').forEach(tr => tr.classList.toggle('selected', tr.dataset.cid === cid));
    const panel = document.getElementById('side-panel');
    const grt = c.greatness || {{}};
    const kill = (grt.kill_switch_failed || []).length > 0;
    const greatRows = ['C001','C002','C003','C004','C005','C006','C007'].map(k => {{
      const v = grt[k] || 0;
      const isKill = (grt.kill_switch_failed || []).indexOf(k) >= 0;
      return `<div class="row">
        <code>${{k}}</code>
        <div class="bar bg"><div class="bar ${{isKill ? 'kill' : ''}}" style="width:${{(v*100).toFixed(0)}}%;height:8px"></div></div>
        <span class="num">${{fmtNum(v,2)}}</span>
      </div>`;
    }}).join('');
    const comps = (c.comps || []).slice(0, 5).map(f => {{
      const ww = f.worldwide_gross_usd == null ? null : (f.worldwide_gross_usd / 1e6);
      const bdg = f.budget_usd == null ? null : (f.budget_usd / 1e6);
      const roi = f.roi == null ? '—' : fmtNum(f.roi,2) + '×';
      const genres = (f.genres || []).slice(0,3).join(', ');
      return `<div class="comp-row">
        <div class="title">${{esc(f.title || '—')}} <span style="color:var(--muted);">(${{esc(f.release_year || '')}})</span></div>
        <div class="meta">${{ww == null ? '—' : '$'+Math.round(ww)+'M ww'}} / ${{bdg == null ? '—' : '$'+Math.round(bdg)+'M budget'}} = ROI ${{roi}} · ${{esc(genres)}}
          ${{f.imdb_url ? ('<a href="'+esc(f.imdb_url)+'" target="_blank">IMDb</a>') : ''}}
          ${{f.boxofficemojo_url ? ('<a href="'+esc(f.boxofficemojo_url)+'" target="_blank">BOM</a>') : ''}}
        </div>
      </div>`;
    }}).join('');
    panel.innerHTML = `
      <div class="side-section">
        <h2>Candidate ${{c.candidate_id}}</h2>
        <div style="font-size: 12px; color: var(--muted);">
          <span class="cluster-pill" style="background:${{colorFor(c.cluster_id)}}">${{esc(c.cluster_name)}}</span>
          &nbsp;cryst=${{fmtNum(c.crystallization_score, 3)}} ·
          deriv=${{fmtNum(c.derivative_distance, 2)}} ·
          query=${{esc((c.query_genres||[]).join(', ') || '—')}}
        </div>
      </div>
      <div class="side-section">
        <h2>C001–C007 rubric ${{kill ? '<span class="kill">⚠ kill-switch failed</span>' : '<span class="ok">✓ ok</span>'}}</h2>
        <div class="greatness-bars">${{greatRows}}</div>
        <div style="font-size: 11px; color: var(--muted); margin-top: 8px;">
          weighted_total = <strong style="color: var(--text);">${{fmtNum(grt.weighted_total || 0, 3)}}</strong>
          ${{kill ? '· failed: ' + (grt.kill_switch_failed || []).join(', ') : ''}}
        </div>
      </div>
      <div class="side-section">
        <h2>Top-5 corpus comps</h2>
        ${{comps || '<p class="empty-panel">No comps matched.</p>'}}
      </div>
      <details>
        <summary>Full compound_seed JSON</summary>
        <pre>${{JSON.stringify(c.compound_seed || {{}}, null, 2)}}</pre>
      </details>
    `;
  }}

  // Initial render
  drawScatter();
  renderTable();
  renderClusters();
  if (cands.length > 0) {{
    // Auto-select highest crystallization_score on load for instant context.
    const top = cands.slice().sort((a,b) => (b.crystallization_score || 0) - (a.crystallization_score || 0))[0];
    if (top) selectCandidate(top.candidate_id);
  }}
}})();
</script>
</body>
</html>
"""
