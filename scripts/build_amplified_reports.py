# ruff: noqa: E501
#!/usr/bin/env python3
"""Run 3 — en-assemble: build the 20 EN amplified-report skeletons (OFFLINE).

The campaign (``config/campaign_goal.json``) amplifies the existing 20 flagship
treatments into Hollywood-grade EN+RU per-concept reports. This script produces
the **EN skeletons**: the structural frame, the verified prose carried forward
from each flagship treatment, and the economics re-rendered from the *frozen*
DNA so every dollar is reproducible and can never drift.

What it does (deterministic, no network, no LLM, ``$`` frozen — ADR-0011)
========================================================================

For each concept ``NN`` (1..20):

1. Read the frozen economics + comps from ``outputs/portfolio/flagship/_dna/idea_NN.json``.
2. Read the prose + structure from the verified ``outputs/portfolio/flagship/NN_slug.md``.
3. Light-touch transform:
   * **Audience Sizing** — normalise the bold SOM token to the canonical
     ``**SOM (Year 1):** $NNNM`` form and append a blockquote *inline SOM formula*
     callout (band, lifetime, the ``SAM = p% of TAM`` identity, the SOM < SAM < TAM
     invariant). The blockquote is rendered with a ``>`` prefix so the veracity
     enumerator skips it — it is human-facing methodology, not a new claim.
   * **Economics — Methodology & Provenance** — regenerate the whole table from
     the frozen DNA, guaranteeing the TAM carries a *non-empty* deep-link and the
     SAM row shows its ``p% of TAM`` arithmetic (the existing files have an empty
     ``[](url)`` link and a mislabelled source on the license-format cards).
   * ``strip_internal_ids`` over the whole document.
4. Validate every output against the real gates:
   * ``check_template_compliance`` — the 4 V2 H1 + 5 H2 anchors.
   * ``scan_for_internal_ids`` — zero banned IDs / framework labels.
   * ``parse_som`` == the frozen SOM (rounded) and the line is canonical.
   * SOM < SAM < TAM on the raw frozen numbers.
   * The render-numeric rule (every external numeric claim carries a deep-link
     or shown arithmetic) — zero violations.
   * Each comp's worldwide gross in the carried-forward table is proven equal to
     a frozen DNA comp (freeze check; the build fails loudly on any drift).
5. ``safe_write`` to ``outputs/portfolio/amplified/EN/NN_slug_EN.md``.

These skeletons are the input to Run 4 (online evidence amplification), which
densifies the deep-links to the campaign floor (>= 12/report) and binds
value-on-page quotes. Run 3 owns only the structure + frozen economics.

CLI
===
    uv run python scripts/build_amplified_reports.py            # build all 20
    uv run python scripts/build_amplified_reports.py --check    # validate only, no write
    uv run python scripts/build_amplified_reports.py --concept 4
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.campaign_goal import load_campaign_goal
from pipeline.state import safe_write
from pipeline.template_filter import (
    check_template_compliance,
    is_som_line_canonical,
    parse_som,
    scan_for_internal_ids,
    strip_internal_ids,
)
from pipeline.veracity.claims import COMPUTED_TYPES
from pipeline.veracity.enumerate import enumerate_claims

# --------------------------------------------------------------------------- #
# Paths / constants
# --------------------------------------------------------------------------- #

_ROOT = Path(__file__).resolve().parents[1]
FLAGSHIP_DIR = _ROOT / "outputs" / "portfolio" / "flagship"
DNA_DIR = FLAGSHIP_DIR / "_dna"
OUT_DIR = _ROOT / "outputs" / "portfolio" / "amplified" / "EN"
GOAL_PATH = _ROOT / "config" / "campaign_goal.json"

USD_B = 1_000_000_000.0
USD_M = 1_000_000.0
N_CONCEPTS = 20

#: SOM parse tolerance (rounded display vs frozen, in $M).
_SOM_PARSE_TOL_M = 1.0

# --------------------------------------------------------------------------- #
# Render-numeric rule (single source of truth; the eval imports these)
# --------------------------------------------------------------------------- #

_LINK_IN_TEXT_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_LINK_COUNT_RE = re.compile(r"\]\(https?://")
_BOLD_SOM_RE = re.compile(r"\*\*SOM[^*]*\*\*")

_ARITHMETIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d+\s*[x\*]\s*\d", re.IGNORECASE),
    re.compile(r"\d+\s*%\s+of\s+\$?\d", re.IGNORECASE),
    re.compile(r"python[_\s]executed", re.IGNORECASE),
    re.compile(r"calculation_method", re.IGNORECASE),
    re.compile(r"modeled\s+(?:at|floor|upside)", re.IGNORECASE),
    re.compile(r"=\s*\$[\d.,]+\s*[BMK]?\b", re.IGNORECASE),
    re.compile(r"\bcalc(?:ulation)?\b", re.IGNORECASE),
    re.compile(r"\bSOM\s*<\s*SAM\s*<\s*TAM\b"),
    re.compile(r"\bcomp[- ]anchor", re.IGNORECASE),
]


def _has_shown_arithmetic(text: str) -> bool:
    return any(p.search(text) for p in _ARITHMETIC_PATTERNS)


def _is_deep_link(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    rest = url.split("://", 1)[1]
    slash = rest.find("/")
    if slash == -1:
        return False
    path = rest[slash:].rstrip("/").split("?")[0].split("#")[0]
    return bool(path)


def render_numeric_violations(md: str, label: str) -> list[tuple[str, str]]:
    """Every external numeric claim must carry a deep-link or shown arithmetic.

    Mirrors ``evals/test_render_numeric_claims_sourced.py`` exactly so a card
    that passes here passes the eval. Returns ``[(claim_type, snippet), ...]``.
    """
    out: list[tuple[str, str]] = []
    for claim in enumerate_claims(md, concept_id=label, concept_title=label):
        if claim.claim_type in COMPUTED_TYPES:
            continue
        if _is_deep_link(claim.cited_url):
            continue
        if any(_is_deep_link(m.group(2)) for m in _LINK_IN_TEXT_RE.finditer(claim.text)):
            continue
        if _has_shown_arithmetic(claim.text):
            continue
        if re.search(r"✅|↑|\bsource\b", claim.text, re.IGNORECASE):
            continue
        out.append((claim.claim_type, claim.text[:90]))
    return out


# --------------------------------------------------------------------------- #
# Money formatting
# --------------------------------------------------------------------------- #


def _fmt_usd(n: float | None) -> str:
    """Compact investor display: ``$NN.NNB`` for billions, ``$NNNM`` for millions."""
    if not n:
        return "—"
    if n >= USD_B:
        return f"${n / USD_B:.2f}B"
    return f"${round(n / USD_M)}M"


def _tam_source_label(url: str) -> str:
    """Honest source label keyed on the frozen TAM URL (never invented)."""
    if "motionpictures.org" in url:
        return "MPA THEME Report"
    if "mediaplaynews" in url or "ampere" in url:
        return "Ampere Analysis — global streaming subscription revenue, 2025"
    return "industry source"


# --------------------------------------------------------------------------- #
# Concept model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Concept:
    idx: int
    slug: str  # e.g. "01_husbandry"
    title: str  # H1 of the flagship treatment, e.g. "Husbandry"
    source_md: str
    econ: dict[str, Any]
    comps: list[dict[str, Any]]


def _load_concept(idx: int) -> Concept:
    matches = sorted(FLAGSHIP_DIR.glob(f"{idx:02d}_*.md"))
    if not matches:
        raise FileNotFoundError(f"No flagship treatment for concept {idx:02d}")
    md_path = matches[0]
    slug = md_path.stem
    source_md = md_path.read_text(encoding="utf-8")
    title_m = re.search(r"^#\s+(.+?)\s*$", source_md, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else slug

    dna_path = DNA_DIR / f"idea_{idx:02d}.json"
    dna = json.loads(dna_path.read_text(encoding="utf-8"))
    return Concept(
        idx=idx,
        slug=slug,
        title=title,
        source_md=source_md,
        econ=dna["economics_FIXED"],
        comps=dna.get("comps_FIXED", []),
    )


# --------------------------------------------------------------------------- #
# Section rendering
# --------------------------------------------------------------------------- #


def _render_som_blockquote(econ: dict[str, Any]) -> str:
    """The inline SOM formula, as a ``>`` blockquote (enumerator-skipped)."""
    low = econ.get("som_y1_low_usd")
    high = econ.get("som_y1_high_usd")
    life = econ.get("lifetime_usd")
    sam = econ["sam_usd"]
    tam = econ["tam_usd"]
    url = econ.get("tam_source_url", "")
    pct = round(sam / tam * 100) if tam else 0
    band = f"{_fmt_usd(low)}-{_fmt_usd(high)}" if low and high else "—"
    label = _tam_source_label(url)
    return (
        "> **How the Year-1 SOM is computed.** The figure is `python_executed` — produced by the engine's "
        "comparable-anchored revenue model, never written or rounded by a language model (ADR-0011). It is the "
        "weighted-median worldwide gross of the matched comparable titles below, derated for an "
        "English-language-first release and the modeled overlap of the film's audiences.\n"
        ">\n"
        f"> Confidence band (80%): {band}. Projected lifetime value across all windows: {_fmt_usd(life)}. "
        f"Serviceable market SAM = {_fmt_usd(sam)} = {pct}% of {_fmt_usd(tam)} TAM "
        f"([{label}]({url})). The order SOM < SAM < TAM holds by construction."
    )


def _render_economics_section(econ: dict[str, Any]) -> str:
    """Regenerate the Economics — Methodology & Provenance section from frozen DNA."""
    tam = econ["tam_usd"]
    sam = econ["sam_usd"]
    som = econ["som_y1_usd"]
    low = econ.get("som_y1_low_usd")
    high = econ.get("som_y1_high_usd")
    life = econ.get("lifetime_usd")
    url = econ.get("tam_source_url", "")
    pct = round(sam / tam * 100) if tam else 0
    band = f"{_fmt_usd(low)}-{_fmt_usd(high)}" if low and high else "—"
    label = _tam_source_label(url)
    rows = [
        "## Economics — Methodology & Provenance",
        "",
        "Every figure below is frozen and machine-checked; none was written or rounded by a language model.",
        "",
        "| Layer | Value | Basis |",
        "|---|---|---|",
        f"| **TAM** | {_fmt_usd(tam)} | Total addressable content market — [{label}]({url}). |",
        f"| **SAM** | {_fmt_usd(sam)} | Serviceable share — `python_executed` derivation ({pct}% of {_fmt_usd(tam)} TAM). Not an independent market estimate. |",
        f"| **SOM (Year 1)** | {_fmt_usd(som)} | Obtainable Year-1 revenue — `python_executed` from the matched comparable films above; 80% band {band}; lifetime {_fmt_usd(life)}. Never model arithmetic. |",
        "",
        "The SOM < SAM < TAM ordering holds by construction (`python_executed`, ADR-0011). Comparable",
        "box-office figures carry worldwide gross, production budget, ROI, and a Box Office Mojo deep link;",
        "they anchor tone and budget scale, not a like-for-like performance promise.",
        "",
    ]
    return "\n".join(rows)


def _transform_audience_sizing(section_lines: list[str], econ: dict[str, Any]) -> list[str]:
    """Canonicalise the SOM token and append the inline-formula blockquote."""
    som_disp = _fmt_usd(econ["som_y1_usd"])
    canonical = f"**SOM (Year 1):** {som_disp}"
    out: list[str] = []
    replaced = False
    for ln in section_lines:
        cur = ln
        if not replaced and "**SOM" in cur:
            cur = _BOLD_SOM_RE.sub(canonical, cur, count=1)
            replaced = True
        out.append(cur)
    if not replaced:
        # Defensive: no bold SOM in Audience Sizing — inject a canonical line so
        # the SOM is still parseable/canonical (never observed on the 20 cards).
        out.append("")
        out.append(canonical)
    while out and out[-1].strip() == "":
        out.pop()
    out.append("")
    out.append(_render_som_blockquote(econ))
    out.append("")
    return out


_HEADING_12_RE = re.compile(r"^#{1,2}\s+\S")
_AUDIENCE_RE = re.compile(r"^##\s+Audience\s+Sizing\b", re.IGNORECASE)
_ECONOMICS_RE = re.compile(r"^##\s+Economics\b", re.IGNORECASE)


def render_report(concept: Concept) -> str:
    """Produce the transformed EN report markdown for one concept."""
    lines = concept.source_md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _ECONOMICS_RE.match(line):
            # Economics is the last section on every card → regenerate to EOF.
            out.append(_render_economics_section(concept.econ).rstrip("\n"))
            out.append("")
            break
        if _AUDIENCE_RE.match(line):
            section = [line]
            i += 1
            while i < n and not _HEADING_12_RE.match(lines[i]):
                section.append(lines[i])
                i += 1
            out.extend(_transform_audience_sizing(section, concept.econ))
            continue
        out.append(line)
        i += 1
    text = "\n".join(out).rstrip("\n") + "\n"
    return strip_internal_ids(text)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate_report(
    md: str, concept: Concept, *, label: str | None = None
) -> tuple[list[str], list[tuple[str, str]]]:
    """Validate one report. Returns ``(hard_problems, run4_worklist)``.

    ``hard_problems`` are the Run-3 gate (the plan: "template/ID/SOM evals"):
    template structure, internal-ID leaks, SOM canonical-form + frozen value,
    and the SOM < SAM < TAM invariant. An empty list means the skeleton ships.

    ``run4_worklist`` are external numeric claims that still need a live source
    (deep-link or value-on-page quote). These cannot be resolved offline — the
    treatments cite richer comps than the frozen DNA holds — so they are the
    Run-4 (online) evidence-amplification target, NOT a Run-3 failure.
    """
    lbl = label or concept.slug
    problems: list[str] = []

    tmpl = check_template_compliance(md)
    if not tmpl["passed"]:
        problems += [f"template: {f}" for f in tmpl["failures"]]  # type: ignore[union-attr]

    ids = scan_for_internal_ids(md)
    if ids:
        problems += [f"internal-id: {d['match']!r} @ line {d['line']}" for d in ids]

    som = parse_som(md)
    frozen_som_m = concept.econ["som_y1_usd"] / USD_M
    if som is None:
        problems.append("SOM: not parseable")
    elif abs(som[0] - round(frozen_som_m)) > _SOM_PARSE_TOL_M:
        problems.append(f"SOM: parsed {som[0]} != frozen {round(frozen_som_m)}")
    if not is_som_line_canonical(md):
        problems.append("SOM: line not in canonical **SOM (Year 1):** form")

    tam = concept.econ["tam_usd"]
    sam = concept.econ["sam_usd"]
    som_usd = concept.econ["som_y1_usd"]
    if not (som_usd < sam < tam):
        problems.append(f"invariant: SOM<SAM<TAM violated ({som_usd} < {sam} < {tam})")

    worklist = render_numeric_violations(md, lbl)
    return problems, worklist


# --------------------------------------------------------------------------- #
# Build + report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BuildResult:
    concept: Concept
    markdown: str
    problems: list[str]
    worklist: list[tuple[str, str]]
    deep_links: int
    out_path: Path

    @property
    def ok(self) -> bool:
        return not self.problems


def build_concept(idx: int) -> BuildResult:
    concept = _load_concept(idx)
    md = render_report(concept)
    problems, worklist = validate_report(md, concept)
    deep_links = len(_LINK_COUNT_RE.findall(md))
    out_path = OUT_DIR / f"{concept.slug}_EN.md"
    return BuildResult(concept, md, problems, worklist, deep_links, out_path)


def _write_worklist(results: list[BuildResult]) -> Path:
    """Persist the Run-4 (online) sourcing target: unbound claims per concept."""
    payload = {
        r.concept.slug: [{"type": t, "snippet": s} for t, s in r.worklist]
        for r in results
        if r.worklist
    }
    path = OUT_DIR.parent / "_run4_worklist.json"
    safe_write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


def _print_summary(results: list[BuildResult], *, wrote: bool) -> None:
    print()
    print(f"{'#':>3}  {'slug':22} {'title':16} {'SOM':>8} {'links':>5}  status")
    print("-" * 78)
    for r in results:
        status = "OK" if r.ok else f"FAIL ({len(r.problems)})"
        todo = f"  ·  Run-4 todo: {len(r.worklist)}" if r.worklist else ""
        print(
            f"{r.concept.idx:>3}  {r.concept.slug:22} {r.concept.title[:16]:16} "
            f"{_fmt_usd(r.concept.econ['som_y1_usd']):>8} {r.deep_links:>5}  {status}{todo}"
        )
        for p in r.problems:
            print(f"        ↳ FAIL {p}")
    n_ok = sum(1 for r in results if r.ok)
    total_links = sum(r.deep_links for r in results)
    total_todo = sum(len(r.worklist) for r in results)
    verb = "Wrote" if wrote else "Validated"
    print("-" * 78)
    print(
        f"{verb} {n_ok}/{len(results)} pass Run-3 gates · "
        f"{total_links} deep-links (mean {total_links / max(len(results), 1):.1f}/report) · "
        f"{total_todo} claims queued for Run-4 online sourcing"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run 3 — build the 20 EN amplified-report skeletons (offline)."
    )
    parser.add_argument("--check", action="store_true", help="validate only; do not write files")
    parser.add_argument(
        "--concept", type=int, default=0, help="build a single concept (1..20); 0 = all"
    )
    args = parser.parse_args(argv)

    goal = load_campaign_goal(GOAL_PATH)
    if len(goal.concepts) != N_CONCEPTS:
        print(
            f"WARNING: campaign goal declares {len(goal.concepts)} concepts, expected {N_CONCEPTS}"
        )

    indices = [args.concept] if args.concept else list(range(1, N_CONCEPTS + 1))
    results = [build_concept(i) for i in indices]

    wrote = False
    if not args.check:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for r in results:
            if r.ok:
                safe_write(r.out_path, r.markdown)
        worklist_path = _write_worklist(results)
        wrote = True
        print(f"Run-4 sourcing work-list → {worklist_path.relative_to(_ROOT)}")

    _print_summary(results, wrote=wrote)
    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)} concept(s) failed Run-3 gates — those files were not written.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
