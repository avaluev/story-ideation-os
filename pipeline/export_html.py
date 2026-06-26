"""Convert a pipeline NARRATOR.md to a self-contained HTML file.

Google Docs renders raw Markdown ``#`` symbols as plain text.
This module converts the investor document to clean HTML so that
File → Open in Google Docs (or a browser) shows proper formatting
with clickable hyperlinks, bold/italic, and styled tables.

Usage (CLI)::

    uv run python -m pipeline.export_html runs/<run_id>/<slug>-NARRATOR.md

Usage (Python)::

    from pipeline.export_html import convert
    html_path = convert(Path("runs/.../slug-NARRATOR.md"))
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

# ── Inline CSS ────────────────────────────────────────────────────────────────

_CSS = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
    "font-size:16px;line-height:1.7;color:#1a1a1a;max-width:860px;"
    "margin:48px auto;padding:0 24px;background:#fff}"
    "h1{font-size:2em;font-weight:700;margin-top:1.2em;margin-bottom:.3em;"
    "border-bottom:2px solid #1a1a1a;padding-bottom:.2em}"
    "h2{font-size:1.4em;font-weight:700;margin-top:1.8em;margin-bottom:.4em;color:#111}"
    "h3{font-size:1.15em;font-weight:600;margin-top:1.3em;margin-bottom:.2em;color:#333}"
    "h4{font-size:1em;font-weight:600;margin-top:1em;margin-bottom:.15em;color:#555}"
    "p{margin:.6em 0}"
    "a{color:#0055cc;text-decoration:underline}"
    "a:visited{color:#551a8b}"
    "blockquote{border-left:4px solid #ccc;margin:1em 0;padding:.5em 1em;"
    "background:#f9f9f9;color:#444}"
    "table{border-collapse:collapse;width:100%;margin:1.2em 0;font-size:.93em}"
    "th,td{border:1px solid #ccc;padding:8px 14px;text-align:left}"
    "th{background:#f0f0f0;font-weight:700}"
    "tr:nth-child(even){background:#fafafa}"
    "hr{border:none;border-top:1px solid #ddd;margin:2.5em 0}"
    "ul,ol{margin:.5em 0;padding-left:1.8em}"
    "li{margin:.3em 0}"
    "code{font-family:monospace;background:#f4f4f4;padding:1px 4px;border-radius:3px}"
    "pre{background:#f4f4f4;padding:12px;border-radius:4px;overflow-x:auto}"
    ".hero-scan{background:#0a0a0a;color:#f0f0f0;padding:48px 32px 40px;margin:-48px -24px 40px;"
    "border-bottom:3px solid #c9a84c}"
    ".hero-title{font-size:2.4em;font-weight:900;color:#fff;margin:0 0 8px;letter-spacing:-0.02em}"
    ".hero-tagline{font-size:1.2em;color:#c9a84c;font-style:italic;margin:0 0 28px}"
    ".hero-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}"
    ".hero-cell{background:#1a1a1a;border:1px solid #333;border-radius:6px;"
    "padding:16px 14px;text-align:center}"
    ".hero-cell .metric{font-size:1.9em;font-weight:800;color:#c9a84c;"
    "display:block;margin-bottom:4px}"
    ".hero-cell .label{font-size:.78em;color:#888;text-transform:uppercase;letter-spacing:.05em}"
    ".hero-why{font-size:1.15em;color:#ddd;line-height:1.5;border-left:3px solid #c9a84c;"
    "padding-left:16px;margin:0}"
)

# ── Regex patterns ────────────────────────────────────────────────────────────

# Handles URLs that contain balanced single-level parentheses (e.g. /movie/Title-(2019))
_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:[^()]+|\([^()]*\))+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_HR_RE = re.compile(r"^[-*_]{3,}\s*$")
_UL_RE = re.compile(r"^[-*+]\s+")
_OL_RE = re.compile(r"^\d+\.\s+")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[-:| ]+\|?\s*$")


# ── Inline rendering ──────────────────────────────────────────────────────────


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    """Convert inline markdown to HTML within a single text span."""
    text = _LINK_RE.sub(
        lambda m: '<a href="' + _escape(m.group(2)) + '">' + _escape(m.group(1)) + "</a>",
        text,
    )
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = _CODE_RE.sub(lambda m: "<code>" + _escape(m.group(1)) + "</code>", text)
    return text


# ── Block-level helpers ───────────────────────────────────────────────────────


def _render_table(table_lines: list[str]) -> str:
    rows: list[list[str]] = []
    for line in table_lines:
        if _TABLE_SEP_RE.match(line):
            continue
        cells = [c.strip() for c in re.split(r"\|", line.strip().strip("|"))]
        rows.append(cells)
    if not rows:
        return ""
    parts = ["<table><thead><tr>"]
    for cell in rows[0]:
        parts.append("<th>" + _inline(cell) + "</th>")
    parts.append("</tr></thead>")
    if len(rows) > 1:
        parts.append("<tbody>")
        for row in rows[1:]:
            parts.append("<tr>")
            for cell in row:
                parts.append("<td>" + _inline(cell) + "</td>")
            parts.append("</tr>")
        parts.append("</tbody>")
    parts.append("</table>")
    return "\n".join(parts)


def _render_list(lines: list[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    strip_pat = _OL_RE if ordered else _UL_RE
    items = ["<" + tag + ">"]
    for line in lines:
        content = strip_pat.sub("", line)
        items.append("<li>" + _inline(content) + "</li>")
    items.append("</" + tag + ">")
    return "".join(items)


# ── Hero grid ────────────────────────────────────────────────────────────────


def _extract_hero_data(md_text: str) -> dict[str, str]:
    """Extract hero grid metrics from the NARRATOR.md text.

    Looks for TAM/SAM/SOM values, logline, tagline, and investment thesis in the
    markdown. Returns a dict with keys: logline, tagline, som, tam, audience,
    comp_roi, why_sentence.  Falls back to empty strings when fields are not found.
    """
    data: dict[str, str] = {
        "logline": "",
        "tagline": "",
        "som": "",
        "tam": "",
        "audience": "",
        "comp_roi": "",
        "why_sentence": "",
    }

    # Logline: first non-empty line after a "Logline" heading
    logline_match = re.search(r"(?:Logline|LOGLINE)[:\s*_]*\n+([^\n]+)", md_text, re.IGNORECASE)
    if logline_match:
        data["logline"] = logline_match.group(1).strip().strip("*_")

    # Tagline: first line after "Tagline" heading
    tagline_match = re.search(r"(?:Tagline|TAGLINE)[:\s*_]*\n+([^\n]+)", md_text, re.IGNORECASE)
    if tagline_match:
        data["tagline"] = tagline_match.group(1).strip().strip("*_\"'")

    # SOM: look for "$X.XB" or "$XXM" pattern near "SOM"
    som_match = re.search(r"SOM[^\n$]*\$([0-9.,]+\s*[BMK])", md_text, re.IGNORECASE)
    if som_match:
        data["som"] = "$" + som_match.group(1).strip()

    # TAM: similar pattern near "TAM"
    tam_match = re.search(r"TAM[^\n$]*\$([0-9.,]+\s*[BMK])", md_text, re.IGNORECASE)
    if tam_match:
        data["tam"] = "$" + tam_match.group(1).strip()

    # Audience: look for "NNM viewers" or "NNN million"
    audience_match = re.search(
        r"(\d[\d,.]+\s*[Mm]illion|\d+M)\s*"
        r"(?:viewers|addressable|audience|fans|users)",
        md_text,
        re.IGNORECASE,
    )
    if audience_match:
        data["audience"] = audience_match.group(1).replace(" million", "M").replace(" Million", "M")

    # Comp ROI: look for "X.Xx" or "Xx ROI" pattern near "comp" or "ROI"
    roi_match = re.search(r"(\d+\.?\d*)[xX]\s*(?:ROI|return|comp)", md_text, re.IGNORECASE)
    if not roi_match:
        roi_match = re.search(r"(?:ROI|return)[^\n]*?(\d+\.?\d*)[xX]", md_text, re.IGNORECASE)
    if roi_match:
        data["comp_roi"] = roi_match.group(1) + "x"

    # Why sentence: first sentence near investment thesis that mentions scale or dollars.
    # Tries several lead-in patterns then falls back to first sentence after the
    # Investment Summary Card table that contains a dollar sign or scale word.
    _SCALE_RE = re.compile(
        r"(?:Why this|This is a \$|Investment thesis|The case for|Why \$)[^\n]{0,200}",
        re.IGNORECASE,
    )
    why_match = _SCALE_RE.search(md_text)
    if why_match:
        # Split on ". " (period-space) or ".\n" to avoid splitting on decimal points.
        sentence = re.split(r"\.\s", why_match.group(0), maxsplit=1)[0].strip(" *_")
        data["why_sentence"] = sentence[:120]
    else:
        # Fallback: first sentence after an Investment Summary Card table that has $ or scale word
        post_table = re.split(r"\|\s*\n\n", md_text, maxsplit=1)
        if len(post_table) > 1:
            after = post_table[1]
            for sent in re.split(r"(?<=[.!?])\s+", after):
                if re.search(r"\$|\bbillion\b|\bmillion\b", sent, re.IGNORECASE):
                    data["why_sentence"] = sent.strip()[:120]
                    break

    return data


def _hero_section(md_text: str) -> str:
    """Render the 10-second scan hero grid as an HTML string."""
    d = _extract_hero_data(md_text)
    logline = _escape(d["logline"]) if d["logline"] else "Film concept"
    tagline = _escape(d["tagline"]) if d["tagline"] else ""

    cells = [
        (d["som"] or "—", "SOM"),
        (d["tam"] or "—", "TAM"),
        (d["audience"] or "—", "Audience"),
        (d["comp_roi"] or "—", "Comp ROI"),
    ]
    grid_html = "".join(
        f'<div class="hero-cell"><span class="metric">{_escape(v)}</span>'
        f'<span class="label">{_escape(lbl)}</span></div>'
        for v, lbl in cells
    )
    _DEFAULT_WHY = "A $2B+ concept built for mass-market global audiences."
    why = d["why_sentence"] if d["why_sentence"] else _DEFAULT_WHY

    return (
        '<div class="hero-scan">'
        f'<p class="hero-title">{logline}</p>'
        + (f'<p class="hero-tagline">{tagline}</p>' if tagline else "")
        + f'<div class="hero-grid">{grid_html}</div>'
        f'<p class="hero-why">{_escape(why)}</p>'
        "</div>\n"
    )


# ── Main converter ────────────────────────────────────────────────────────────


def _parse_blocks(lines: list[str]) -> list[str]:  # noqa: PLR0912, PLR0915
    """Walk *lines* and return a list of HTML fragment strings."""
    out: list[str] = []
    i = 0
    in_pre = False
    pre_buf: list[str] = []
    tbl_buf: list[str] = []

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            if in_pre:
                in_pre = False
                out.append("<pre><code>" + _escape("\n".join(pre_buf)) + "</code></pre>")
                pre_buf = []
            else:
                in_pre = True
            i += 1
            continue
        if in_pre:
            pre_buf.append(line)
            i += 1
            continue

        # Table rows
        next_is_table = i + 1 < len(lines) and (
            lines[i + 1].strip().startswith("|") or _TABLE_SEP_RE.match(lines[i + 1])
        )
        if tbl_buf or line.strip().startswith("|") or (tbl_buf and _TABLE_SEP_RE.match(line)):
            tbl_buf.append(line)
            i += 1
            if i < len(lines) and (
                lines[i].strip().startswith("|") or _TABLE_SEP_RE.match(lines[i])
            ):
                continue
            out.append(_render_table(tbl_buf))
            tbl_buf = []
            continue
        _ = next_is_table  # suppress unused-variable warning

        # Headings
        m = _HEADING_RE.match(line)
        if m:
            lvl = len(m.group(1))
            out.append("<h" + str(lvl) + ">" + _inline(m.group(2)) + "</h" + str(lvl) + ">")
            i += 1
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if line.startswith(">"):
            out.append("<blockquote><p>" + _inline(line.lstrip("> ").strip()) + "</p></blockquote>")
            i += 1
            continue

        if _UL_RE.match(line):
            buf: list[str] = []
            while i < len(lines) and _UL_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            out.append(_render_list(buf, ordered=False))
            continue

        if _OL_RE.match(line):
            buf = []
            while i < len(lines) and _OL_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            out.append(_render_list(buf, ordered=True))
            continue

        if not line.strip():
            out.append("")
        else:
            out.append("<p>" + _inline(line) + "</p>")
        i += 1

    return out


def convert(md_path: Path, organize: bool = False) -> Path:
    """Convert *md_path* to an HTML file alongside it.

    Args:
        md_path: Path to the NARRATOR.md file to convert.
        organize: If True, reorganize the run directory to move artifacts to _trail/.

    Returns:
        Path to the generated HTML file.
    """
    text = md_path.read_text(encoding="utf-8")
    fragments = _parse_blocks(text.splitlines())
    body = "\n".join(fragments)

    title_match = re.search(r"<h1>(.*?)</h1>", body)
    title = _escape(title_match.group(1)) if title_match else _escape(md_path.stem)

    hero = _hero_section(text)
    html = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "  <title>" + title + "</title>\n"
        "  <style>" + _CSS + "</style>\n"
        "</head>\n<body>\n" + hero + body + "\n</body>\n</html>"
    )

    stem = md_path.stem.replace("-NARRATOR", "-INVESTOR").replace("-narrator", "-INVESTOR")
    out_path = md_path.with_name(stem + ".html")
    out_path.write_text(html, encoding="utf-8")

    if organize:
        reorganize_run(out_path.parent)

    return out_path


def reorganize_run(run_dir: Path) -> Path:
    """Move all non-HTML artifacts from run_dir into run_dir/_trail/.

    This keeps only the single investor HTML at the slug root, with all
    sidecars, intermediate markdowns, and eval logs under _trail/.

    Args:
        run_dir: Path to the run directory (e.g. runs/2026-05-13-slug/).

    Returns:
        Path to the _trail/ subdirectory (created if needed).
    """
    trail_dir = run_dir / "_trail"
    trail_dir.mkdir(exist_ok=True)

    readme = trail_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "# _trail/\n\n"
            "Internal pipeline artifacts — sidecars, eval logs, intermediate markdowns.\n"
            "Not intended for external distribution.\n"
            "The investor-facing deliverable is the `*-INVESTOR.html` file"
            " in the parent directory.\n",
            encoding="utf-8",
        )

    moved: list[str] = []
    for item in sorted(run_dir.iterdir()):
        if item.name == "_trail":
            continue
        if item.is_file() and item.suffix in {".json", ".md", ".txt", ".log", ".jsonl"}:
            dest = trail_dir / item.name
            item.rename(dest)
            moved.append(item.name)

    if moved:
        _log.info("reorganize_run: moved %d files to _trail/: %s", len(moved), moved)

    return trail_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert NARRATOR.md to investor-grade HTML.")
    parser.add_argument("md_path", help="Path to the NARRATOR.md file to convert")
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Move non-HTML artifacts to _trail/ subdirectory after conversion",
    )

    args = parser.parse_args()
    md_path = Path(args.md_path)

    if not md_path.exists():
        print(f"File not found: {md_path}")
        sys.exit(1)

    out = convert(md_path, organize=args.organize)
    print(f"HTML written to: {out}")


if __name__ == "__main__":
    main()
