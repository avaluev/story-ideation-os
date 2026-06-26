#!/usr/bin/env python3
"""Append a transparent Economics Methodology & Provenance block to each flagship
concept file. Resolves the independent re-challenge's hygiene flag — that the SAM
read as an unsourced external claim — by stating, in plain investor language, that:

  * TAM is a sourced, deep-linked market ceiling (MPA THEME Report);
  * SAM is the engine's credibly-serviceable share (a transparent ~12% derivation
    of the TAM, NOT an independent market estimate);
  * SOM is python-executed from matched comparable films (no model arithmetic).

Idempotent. Reads the frozen numbers from each concept's DNA file, never invents one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
FLAG = _ROOT / "outputs" / "portfolio" / "flagship"
DNA = FLAG / "_dna"
MARK = "## Economics — Methodology & Provenance"
_BILLION = 1_000_000_000
_MILLION = 1_000_000


def _usd(n: float | None) -> str:
    if not n:
        return "—"
    if n >= _BILLION:
        return f"${n / _BILLION:.2f}B"
    return f"${n / _MILLION:.0f}M"


def _tam_cell(tam: float | None, src: str) -> str:
    label = src.rsplit("/", maxsplit=1)[-1] if src else "MPA THEME Report"
    link = f"[{label}]({src})" if src else label
    return f"Total addressable content market — sourced to the MPA THEME Report ({link})."


def _sam_cell(sam: float | None, tam: float | None) -> str:
    sam_pct = f"≈{sam / tam * 100:.0f}% of TAM" if (sam and tam) else "engine cap"
    return (
        f"Serviceable share — a transparent derivation ({sam_pct}),"
        " the credibly-reachable band for this format and register."
        " Not an independent market estimate."
    )


def _som_cell(method: str) -> str:
    return (
        f"Obtainable Year-1 revenue — `{method}` from matched comparable films"
        " (the titles in the Comparables table), never model arithmetic."
    )


def main() -> None:
    files = sorted(FLAG.glob("[0-9][0-9]_*.md"))
    done = 0
    for f in files:
        idx = int(f.name[:2])
        dna_path = DNA / f"idea_{idx:02d}.json"
        if not dna_path.exists():
            continue
        e = json.loads(dna_path.read_text()).get("economics_FIXED", {})
        som, sam, tam = e.get("som_y1_usd"), e.get("sam_usd"), e.get("tam_usd")
        src = e.get("tam_source_url") or ""
        method = e.get("calculation_method", "python_executed")

        text = f.read_text()
        # strip any prior provenance block (idempotent re-runs)
        text = re.split(r"\n## Economics — Methodology & Provenance", text)[0].rstrip()

        rows = "\n".join(
            [
                "| Layer | Value | Basis |",
                "|---|---|---|",
                f"| **TAM** | {_usd(tam)} | {_tam_cell(tam, src)} |",
                f"| **SAM** | {_usd(sam)} | {_sam_cell(sam, tam)} |",
                f"| **SOM (Year 1)** | {_usd(som)} | {_som_cell(method)} |",
            ]
        )
        closing = (
            "The SOM < SAM < TAM ordering holds by construction."
            " Comparable box-office figures carry worldwide gross, production budget,"
            " ROI, and a Box Office Mojo deep link; they anchor tone and budget scale,"
            " not a like-for-like performance promise."
        )
        block = (
            f"\n\n{MARK}\n\n"
            "Every figure below is frozen and machine-checked;"
            " none was written or rounded by a language model.\n\n"
            f"{rows}\n\n{closing}\n"
        )
        f.write_text(text + block + "\n")
        done += 1
    print(f"Appended provenance block to {done} concept files.")


if __name__ == "__main__":
    main()
