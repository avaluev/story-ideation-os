"""Deterministic claim extraction for the veracity subsystem.

Pulls every externally-checkable factual claim out of a concept's structured
record (a ``portfolio_enriched.json`` concept dict) or out of rendered markdown
(a NARRATOR / portfolio document). No LLM, no network — pure parsing. The
reality-verifier agent then takes one :class:`Claim` at a time and confirms it
against a primary source.

A :class:`Claim` is *external* (a number that must be proven against the world:
a demand stat, a box-office gross, a market aggregate) or *computed* (a
python-executed derivation — SAM, SOM, lifetime — proven by the calculation, not
by a URL). :data:`COMPUTED_TYPES` marks the latter; :func:`verdict.decide`
routes on it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, cast

#: Every claim type the extractor can emit.
CLAIM_TYPES: frozenset[str] = frozenset(
    {
        "demand",
        "box_office",
        "cultural_signal",
        "comp_roi",
        "market_tam",
        "market_sam",
        "market_som",
        "lifetime",
        "budget",
        # A market *conclusion* / superlative ("the most durable revenue
        # category") — an external claim that still needs a primary source.
        # Emitted by the section-aware enumerator (pipeline.veracity.enumerate).
        "market_claim",
    }
)

#: Claim types that are python-computed derivations, NOT external facts. These
#: are verified by ``calculation_method == "python_executed"`` + the
#: SOM < SAM < TAM invariant, never by fetching a URL (ADR-0011).
COMPUTED_TYPES: frozenset[str] = frozenset({"market_sam", "market_som", "lifetime"})

_USD_PER_MILLION: float = 1_000_000.0
_USD_PER_BILLION: float = 1_000_000_000.0


@dataclass(frozen=True)
class Claim:
    """One externally-checkable assertion lifted out of a concept document.

    ``anchor`` and ``section`` are optional and defaulted so every existing
    positional ``Claim(...)`` construction keeps working. They are populated by
    the section-aware enumerator: ``anchor`` is the exact text span (sentence,
    table row, or comp title) the inline-citation renderer locates to place a
    citation; ``section`` is the card section the claim was found in (used for
    first-occurrence-per-section de-duplication of repeated dollar figures).
    """

    claim_id: str
    concept_id: str
    concept_title: str
    claim_type: str
    text: str
    value: str
    cited_url: str
    date: str = ""
    anchor: str = ""
    section: str = ""

    @property
    def is_computed(self) -> bool:
        """True for python-derived numbers (SAM/SOM/lifetime) — no URL needed."""
        return self.claim_type in COMPUTED_TYPES


def _mk_id(concept_id: str, claim_type: str, text: str) -> str:
    """Stable 12-char id for a claim (sha256 of identity tuple)."""
    raw = f"{concept_id}|{claim_type}|{text}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _fmt_usd(amount: float) -> str:
    """Human ``$NB`` / ``$NM`` rendering of a USD amount."""
    if amount >= _USD_PER_BILLION:
        return f"${amount / _USD_PER_BILLION:.2f}B"
    return f"${amount / _USD_PER_MILLION:.0f}M"


def _classify_demand(stat: str, claim_text: str) -> str:
    """Classify a demand-evidence row into a finer claim type."""
    blob = f"{stat} {claim_text}".lower()
    if "$" in stat and any(
        k in blob for k in ("ww", "worldwide", "box office", "grossed", "per-screen", "opening")
    ):
        return "box_office"
    if "%" in stat or "pts" in stat.lower():
        return "cultural_signal"
    return "demand"


def extract_from_concept(concept: dict[str, Any]) -> list[Claim]:
    """Extract all claims from one enriched-portfolio concept dict."""
    cid = str(concept.get("id") or concept.get("economics_key") or "").strip()
    title = str(concept.get("title") or concept.get("working_title") or "").strip()
    if not cid:
        cid = _mk_id(title, "concept", title)
    out: list[Claim] = []

    # 1. Demand-evidence rows — the present-tense proof-of-demand citations.
    demand_raw = concept.get("demand_evidence")
    if isinstance(demand_raw, list):
        for row_raw in cast("list[object]", demand_raw):
            if not isinstance(row_raw, dict):
                continue
            row = cast("dict[str, Any]", row_raw)
            claim_text = str(row.get("claim", "")).strip()
            stat = str(row.get("stat", "")).strip()
            url = str(row.get("source_url", "")).strip()
            if not claim_text and not stat:
                continue
            ctype = _classify_demand(stat, claim_text)
            out.append(
                Claim(
                    claim_id=_mk_id(cid, ctype, claim_text or stat),
                    concept_id=cid,
                    concept_title=title,
                    claim_type=ctype,
                    text=claim_text or stat,
                    value=stat,
                    cited_url=url,
                    date=str(row.get("date", "")).strip(),
                )
            )

    # 2. Comparables — each box-office gross + ROI is independently checkable.
    comps_raw = concept.get("comps")
    if isinstance(comps_raw, list):
        for comp_raw in cast("list[object]", comps_raw):
            if not isinstance(comp_raw, dict):
                continue
            comp = cast("dict[str, Any]", comp_raw)
            ctitle = str(comp.get("title", "")).strip()
            if not ctitle:
                continue
            gross = _as_float(comp.get("worldwide_gross_usd"))
            roi = _as_float(comp.get("roi"))
            url = str(comp.get("boxofficemojo_url") or comp.get("imdb_url") or "").strip()
            value = _fmt_usd(gross) + " WW" if gross else ""
            roi_txt = f" (ROI {roi:.1f}x)" if roi else ""
            text = f"{ctitle} grossed {value} worldwide{roi_txt}" if value else ctitle
            out.append(
                Claim(
                    claim_id=_mk_id(cid, "comp_roi", ctitle),
                    concept_id=cid,
                    concept_title=title,
                    claim_type="comp_roi",
                    text=text,
                    value=value,
                    cited_url=url,
                    date=str(comp.get("release_year", "")).strip(),
                )
            )

    # 3. Economics — TAM is an external aggregate; SAM/SOM/lifetime are computed.
    out.extend(_economics_claims(concept, cid, title))
    return out


def _economics_claims(concept: dict[str, Any], cid: str, title: str) -> list[Claim]:
    out: list[Claim] = []
    econ: list[tuple[str, str, str]] = [
        ("market_tam", "tam_usd", "tam_source_url"),
        ("market_sam", "sam_usd", ""),
        ("market_som", "som_y1_usd", ""),
        ("lifetime", "lifetime_usd", ""),
    ]
    for ctype, amount_key, url_key in econ:
        amount = _as_float(concept.get(amount_key))
        if not amount:
            continue
        url = str(concept.get(url_key, "")).strip() if url_key else ""
        label = {
            "market_tam": "Total addressable market",
            "market_sam": "Serviceable addressable market",
            "market_som": "Year-1 serviceable obtainable market",
            "lifetime": "Multi-window lifetime value",
        }[ctype]
        out.append(
            Claim(
                claim_id=_mk_id(cid, ctype, amount_key),
                concept_id=cid,
                concept_title=title,
                claim_type=ctype,
                text=f"{label}: {_fmt_usd(amount)}",
                value=_fmt_usd(amount),
                cited_url=url,
            )
        )
    return out


def extract_from_portfolio(data: dict[str, Any]) -> list[Claim]:
    """Extract claims from a full ``portfolio_enriched.json`` dict."""
    concepts_raw = data.get("concepts")
    if not isinstance(concepts_raw, list):
        return []
    out: list[Claim] = []
    for concept_raw in cast("list[object]", concepts_raw):
        if isinstance(concept_raw, dict):
            out.extend(extract_from_concept(cast("dict[str, Any]", concept_raw)))
    return out


# Markdown fallback — any [label](url) citation becomes a claim. ------------- #

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_STAT_RE = re.compile(r"(\$[\d.,]+\s?[BMK]?\b|\d[\d.,]*\s?%|\d[\d.,]*\s?(?:pts|x))")


def extract_from_markdown(md: str, *, concept_id: str = "doc") -> list[Claim]:
    """Fallback extractor: every ``[label](url)`` link becomes a Claim.

    Used for arbitrary NARRATOR markdown where no structured JSON is available.
    The claim ``value`` is the first stat token found in the link label.
    """
    out: list[Claim] = []
    seen: set[str] = set()
    for match in _LINK_RE.finditer(md):
        label, url = match.group(1).strip(), match.group(2).strip()
        if url in seen:
            continue
        seen.add(url)
        stat_match = _STAT_RE.search(label)
        value = stat_match.group(1).strip() if stat_match else ""
        ctype = _classify_markdown(url, label)
        out.append(
            Claim(
                claim_id=_mk_id(concept_id, ctype, label),
                concept_id=concept_id,
                concept_title="",
                claim_type=ctype,
                text=label,
                value=value,
                cited_url=url,
            )
        )
    return out


def _classify_markdown(url: str, label: str) -> str:
    host = url.split("/", 3)[2].lower() if "://" in url else ""
    if "boxofficemojo" in host or "the-numbers" in host:
        return "box_office"
    if "imdb.com" in host:
        return "comp_roi"
    low = label.lower()
    if "%" in label or "pts" in low:
        return "cultural_signal"
    if any(k in low for k in ("tam", "addressable market", "content spend")):
        return "market_tam"
    return "demand"


def _as_float(val: object) -> float:
    if isinstance(val, bool):  # bool is an int subclass — never a money value
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace(",", "").replace("$", "").strip())
        except ValueError:
            return 0.0
    return 0.0
