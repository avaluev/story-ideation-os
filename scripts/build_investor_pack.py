"""Build one merged investor document from the two pipeline outputs,
then translate to Russian via OpenRouter Gemini 2.0 Flash.

Usage:
    uv run python scripts/build_investor_pack.py --run-id <RUN_ID>

Produces:
    runs/<RUN_ID>/INVESTOR_EN.md
    runs/<RUN_ID>/INVESTOR_RU.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

from pipeline.openrouter_client import OpenRouterClient

# ---------------------------------------------------------------------------
# Key helper
# ---------------------------------------------------------------------------


def _get_or_key() -> str:
    c = OpenRouterClient()
    k = c._select_key(paid_required=False)
    return k.key if hasattr(k, "key") else str(k)


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------


def _parse_sections(text: str) -> dict[str, str]:
    """Split a markdown file into {heading: body} for every ## section.

    Key "" holds everything before the first ## heading.
    Body does NOT include the heading line itself.
    """
    result: dict[str, str] = {}
    current_key = ""
    current_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            result[current_key] = "".join(current_lines)
            current_key = line.rstrip()
            current_lines = []
        else:
            current_lines.append(line)
    result[current_key] = "".join(current_lines)
    return result


def _parse_subsections(text: str) -> dict[str, str]:
    """Split a markdown block into {heading: body} for every ### subsection."""
    result: dict[str, str] = {}
    current_key = ""
    current_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("### "):
            result[current_key] = "".join(current_lines)
            current_key = line.rstrip()
            current_lines = []
        else:
            current_lines.append(line)
    result[current_key] = "".join(current_lines)
    return result


_TEMPLATE_MARKER = re.compile(r"^# \d+\.", re.MULTILINE)


def _clean(text: str) -> str:
    """Remove numbered template-marker H1 lines (# 1. …, # 2. …, etc.)."""
    lines = [ln for ln in text.splitlines(keepends=True) if not _TEMPLATE_MARKER.match(ln)]
    return "".join(lines)


def _get(sections: dict[str, str], heading: str) -> str:
    """Return heading + cleaned body, stripped. Empty string if not found."""
    body = sections.get(heading, "")
    if not body.strip():
        return ""
    return f"{heading}\n{_clean(body).rstrip()}"


def _before_first_h2(text: str) -> str:
    """Pre-## content: strip the H1 title line and template markers."""
    m = re.search(r"(?m)^## ", text)
    raw = text[: m.start()] if m else text
    # drop the first line if it's an H1 title (# Word …)
    lines = raw.splitlines(keepends=True)
    if lines and lines[0].startswith("# ") and not lines[0].startswith("## "):
        lines = lines[1:]
    return _clean("".join(lines)).strip()


# ---------------------------------------------------------------------------
# Build merged English document
# Decision table (one source per content block, no duplicates):
#
#  Block                    Source        Reason
#  ─────────────────────    ──────────    ──────────────────────────────────
#  Summary card             NARRATOR      Has TAM/SAM/SOM, logline, ask
#  The Story                NARRATOR      Clean 3-para investor prose
#  Synopsis                 concept       Has executed franchise scaffold scene
#  Emotional Arc            concept       Unique — not in NARRATOR
#  Tonal Contract           concept       Unique — not in NARRATOR
#  Characters               NARRATOR      Cleaner prose; avoids triple split
#  What Makes It Different  NARRATOR      Best differentiation prose
#  Why Now                  concept       4 sourced URLs (McKinsey/RAND/Pew/FRED)
#  Audience Sizing          concept       3 sourced URLs (Gallup/Collider/Nielsen)
#  Market Size TAM/SAM/SOM  NARRATOR      Arithmetic derivation shown
#  Comparables table        NARRATOR      Has hyperlinks; Format/Budget/Revenue
#  Platform Fit             NARRATOR      Best version
#  Risks                    NARRATOR      Complete 3-risk section
#  In Brief                 NARRATOR      Closing summary
#
#  DROPPED (redundant/internal):
#  Mass-Appeal Theme        —             Covered by What Makes It Different
#  Format & Genre (conc)    —             Covered inside The Numbers (NARRATOR)
#  Revenue Thesis (conc)    —             Covered by Revenue Path (NARRATOR)
#  Comparables (conc)       —             Weaker; no hyperlinks
#  Protagonist/Antagonist   —             Covered by Characters (NARRATOR)
#  Key Characters (conc)    —             Covered by Characters (NARRATOR)
#  MASTER_QUESTIONS         —             Internal — never in investor doc
# ---------------------------------------------------------------------------


def build_english(run_dir: Path) -> str:
    narr = (run_dir / "unclassified-NARRATOR.md").read_text(encoding="utf-8")
    conc = (run_dir / "unclassified.md").read_text(encoding="utf-8")

    ns = _parse_sections(narr)  # NARRATOR sections
    cs = _parse_sections(conc)  # concept doc sections

    # Market Size is a ### subsection inside ## The Market (NARRATOR)
    market_block = ns.get("## The Market", "")
    market_subs = _parse_subsections(market_block)
    market_size = _get(market_subs, "### Market Size")

    summary_card = _before_first_h2(narr)
    story = _get(ns, "## The Story")
    synopsis = _get(cs, "## Synopsis")
    emotional = _get(cs, "## Emotional Arc")
    tonal = _get(cs, "## Tonal Contract")
    characters = _get(ns, "## Characters")
    different = _get(ns, "## What Makes It Different")
    why_now = _get(cs, "## Why Now")
    audience = _get(cs, "## Audience Sizing")
    numbers = _get(ns, "## The Numbers")
    risks = _get(ns, "## Risks")
    brief = _get(ns, "## In Brief")

    # Sanity-check: abort if any critical block is empty
    missing = [
        name
        for name, val in [
            ("summary_card", summary_card),
            ("story", story),
            ("synopsis", synopsis),
            ("characters", characters),
            ("market_size", market_size),
            ("numbers", numbers),
            ("risks", risks),
        ]
        if not val.strip()
    ]
    if missing:
        raise RuntimeError(f"build_english: missing blocks: {missing}")

    blocks = [
        summary_card,
        story,
        synopsis,
        emotional,
        tonal,
        characters,
        different,
        why_now,
        audience,
        market_size,
        numbers,
        risks,
        brief,
    ]

    # Build the document with clean separators. Each block is followed by a
    # single horizontal rule on its own line; the final block has no trailing
    # rule. Source blocks may carry their own trailing `---` from upstream
    # markdown — strip those to avoid stacked rules.
    def _strip_trailing_rule(block: str) -> str:
        b = block.strip()
        while b.endswith("---"):
            b = b[: -len("---")].rstrip()
        return b

    header = "# UNCLASSIFIED\n\n#### Investor Document — Confidential"
    non_empty = [_strip_trailing_rule(block) for block in blocks if block.strip()]
    non_empty = [b for b in non_empty if b]  # re-filter in case strip emptied a block
    body = "\n\n---\n\n".join(non_empty)
    footer = (
        "*All financial figures are projections based on documented "
        "comparable film performance. Sources are hyperlinked inline.*"
    )
    return f"{header}\n\n---\n\n{body}\n\n---\n\n{footer}\n"


# ---------------------------------------------------------------------------
# Translation via OpenRouter (direct httpx, no JSON-parse wrapper)
# ---------------------------------------------------------------------------

TRANSLATE_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """\
You are a professional film industry translator specialising in investor \
and pitch documents. Translate the following Markdown document from English \
to Russian. Rules:
- Preserve ALL Markdown formatting: headings (#, ##, ###, ####), bold (**), \
  italics (*), tables, bullet lists, blockquotes (>), horizontal rules (---).
- Preserve ALL hyperlinks exactly as written — do not translate URLs.
- Preserve ALL numbers, dollar amounts, percentages, and dates exactly.
- Use professional investor / film industry Russian register (деловой стиль).
- Do NOT add explanations, commentary, or translator notes.
- Output ONLY the translated Markdown — nothing else.
"""

CHUNK_CHARS = 6000  # stay well inside context window per request


def _translate_chunk(chunk: str, key: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chunk},
        ],
    }
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/avaluev/big-ideas",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _split_into_chunks(text: str) -> list[str]:
    """Split on --- separators into chunks within CHUNK_CHARS."""
    raw_chunks = re.split(r"(?m)^---\s*$", text)
    chunks: list[str] = []
    current = ""
    for part in raw_chunks:
        if len(current) + len(part) < CHUNK_CHARS:
            current += ("---\n" if current else "") + part
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def translate_to_russian(text: str, key: str, model: str) -> str:
    """Translate the full document with the named model. No fallback —
    each model produces its own deliverable per the investor-pack contract."""
    chunks = _split_into_chunks(text)
    print(f"  Translating {len(chunks)} chunks with {model}…", flush=True)
    translated: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  chunk {i}/{len(chunks)} ({model})…", end=" ", flush=True)
        result = _translate_chunk(chunk, key, model)
        translated.append(result)
        print("done", flush=True)
    return "\n\n---\n\n".join(translated)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    run_dir = Path("runs") / args.run_id
    if not run_dir.exists():
        sys.exit(f"Run directory not found: {run_dir}")

    print("Building merged English document…")
    en_doc = build_english(run_dir)
    en_path = run_dir / "INVESTOR_EN.md"
    en_path.write_text(en_doc, encoding="utf-8")
    print(f"  Written: {en_path}  ({len(en_doc):,} chars)")

    key = _get_or_key()

    # Russian translation via OpenAI GPT-4o-mini (sole translator).
    # Gemini 2.0 Flash was previously the primary; removed because output
    # quality lagged behind GPT-4o-mini on investor-register Russian.
    print(f"Translating to Russian with {TRANSLATE_MODEL}…")
    ru_doc = translate_to_russian(en_doc, key, TRANSLATE_MODEL)
    ru_path = run_dir / "INVESTOR_RU.md"
    ru_path.write_text(ru_doc, encoding="utf-8")
    print(f"  Written: {ru_path}  ({len(ru_doc):,} chars)")

    print("\n✓  Done.")
    print(f"   EN: {en_path}")
    print(f"   RU: {ru_path}")


if __name__ == "__main__":
    main()
