"""pipeline/index_html.py — static HTML gallery for out/concepts/*.md (PIPE-13)."""

from __future__ import annotations

import html
import re
from pathlib import Path

from pipeline.state import safe_write

_OUT_DIR = Path("out/concepts")
_INDEX_PATH = Path("out/index.html")


def regenerate_index(
    out_dir: Path | None = None,
    index_path: Path | None = None,
) -> None:
    """Regenerate index.html from all concept .md files.

    Parameters
    ----------
    out_dir:
        Directory containing ``*.md`` concept files.  Defaults to ``_OUT_DIR``
        (``out/concepts``).
    index_path:
        Destination path for the generated HTML file.  Defaults to
        ``_INDEX_PATH`` (``out/index.html``).
    """
    src = out_dir if out_dir is not None else _OUT_DIR
    dest = index_path if index_path is not None else _INDEX_PATH

    src.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for md_path in sorted(src.glob("*.md")):
        content = md_path.read_text(encoding="utf-8")
        concept_id = md_path.stem
        title = _extract_field(content, "title") or concept_id
        audience_size = _extract_field(content, "audience_size") or "—"
        final_score = _extract_field(content, "final_score") or "—"
        sdt_score = _extract_field(content, "sdt_score") or "—"
        ajtbd_score = _extract_field(content, "ajtbd_score") or "—"
        rows.append(
            {
                "id": concept_id,
                "title": title,
                "audience_size": audience_size,
                "final_score": final_score,
                "sdt_score": sdt_score,
                "ajtbd_score": ajtbd_score,
                "link": f"concepts/{md_path.name}",
            }
        )

    html = _build_html(rows)
    safe_write(dest, html)


def _extract_field(content: str, field: str) -> str | None:
    m = re.search(rf"^{field}:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def _build_html(rows: list[dict[str, str]]) -> str:
    def _esc(value: str) -> str:
        return html.escape(value, quote=True)

    tr_rows = "\n".join(
        f"<tr><td>{_esc(r['id'])}</td><td>{_esc(r['title'])}</td>"
        f"<td>{_esc(r['final_score'])}</td><td>{_esc(r['sdt_score'])}</td>"
        f"<td>{_esc(r['ajtbd_score'])}</td><td>{_esc(r['audience_size'])}</td>"
        f'<td><a href="{_esc(r["link"])}">view</a></td></tr>'
        for r in rows
    )
    concept_count = len(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Anomaly Engine — Concepts ({concept_count})</title>
<style>
  body {{ font-family: monospace; background: #1a1a1a; color: #e0e0e0; padding: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #444; padding: 0.5rem 1rem; text-align: left; }}
  th {{ background: #2a2a2a; }}
  a {{ color: #7ab8f5; }}
  tr:hover {{ background: #252525; }}
</style>
</head>
<body>
<h1>Anomaly Engine v3.0 — Concepts ({concept_count})</h1>
<table>
<thead><tr>
  <th>ID</th><th>Title</th><th>Score</th>
  <th>SDT</th><th>AJTBD</th><th>Audience</th><th>View</th>
</tr></thead>
<tbody>
{tr_rows}
</tbody>
</table>
</body>
</html>"""
