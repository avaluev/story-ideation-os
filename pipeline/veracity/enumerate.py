"""Section-aware claim ENUMERATOR — the fix for the deep-link-density tautology.

``pipeline.veracity.claims.extract_from_markdown`` only harvests assertions that
already carry a ``[label](url)`` link, so it can never *find* an unsourced number
— it measures (linked claims)/(linked claims) ≈ 100%. This module instead walks
a rendered concept card and emits one :class:`~pipeline.veracity.claims.Claim`
per *distinct externally-checkable assertion* — comp grosses (even in tables with
no inline link), the TAM aggregate, demand/salience statistics, and market
*conclusions* — giving an honest denominator for density.

Pure parsing — no network, no LLM (ADR-0002). It does NOT alter, invent, or
round any dollar figure; it only locates claims. The python-executed economics
(SAM/SOM/lifetime, ADR-0011) are emitted as COMPUTED claims (proven by the
calculation, not a URL) and are excluded from the external denominator.

Design (deliberately NOT a markdown AST — header-split + per-line regex is
sufficient for these templated cards and far lower risk):

  * **Outline scope** — a heading stack marks which lines are inside an
    evidence-bearing section (Market & Audience / Audience Sizing / Revenue
    Thesis / Why Now / Comparables / Verified Proof of Demand / Economics). A
    deeper IN heading (``## Comparables`` under ``# 3. Story``) overrides a
    shallower OUT one. Narrative sections (synopsis, characters, tonal contract,
    why-not-generic, logline) are never scanned.
  * **Economics table first** — learn the frozen ``{tam, sam, som, lifetime}``
    values so a prose dollar figure matching one of them is recognised as a
    computed echo (skipped) rather than double-counted as a new external claim.
  * **De-dup** — comps by title, economics by layer, prose by normalised text;
    a comp restatement in Revenue Thesis collapses into the comp-table row.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from pipeline.veracity.claims import Claim

# --------------------------------------------------------------------------- #
# Section scope
# --------------------------------------------------------------------------- #

#: Normalised headings whose body is scanned for external claims (allowlist).
_IN_SECTIONS: frozenset[str] = frozenset(
    {
        "market & audience",
        "audience sizing",
        "revenue thesis",
        "why now",
        "comparables",
        "verified proof of demand",
    }
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _normalize_heading(text: str) -> str:
    """Lower-case, drop a leading ``N. `` ordinal and markdown emphasis."""
    t = re.sub(r"^\s*\d+\.\s*", "", text)
    return t.replace("*", "").strip().lower()


def _heading_scope(text: str) -> bool:
    """True iff this heading opens an evidence-bearing section (allowlist-only)."""
    norm = _normalize_heading(text)
    return norm in _IN_SECTIONS or "economics" in norm


def _section_key(text: str) -> str:
    """Canonical section name for a Claim.section field."""
    norm = _normalize_heading(text)
    return "economics" if "economics" in norm else norm


# --------------------------------------------------------------------------- #
# Money / number parsing
# --------------------------------------------------------------------------- #

_MONEY_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(trillion|billion|million|thousand|[bmkt])?\b",
    re.IGNORECASE,
)
#: A bare large number with a magnitude word, NOT part of a $ figure ("11 million").
_BIGNUM_RE = re.compile(
    r"(?<![$\d.])\b(\d[\d,]*(?:\.\d+)?)\s+(trillion|billion|million|thousand)\b",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"\b(\d[\d.,]*)\s?(?:%|pts\b|percentage points\b)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_ROI_RE = re.compile(r"(\d[\d.]*)\s?x\b", re.IGNORECASE)

#: A market *conclusion* worth a source: a superlative tied to a market noun.
_SUPERLATIVE_RE = re.compile(
    r"\b(most|largest|biggest|highest|fastest[- ]growing|leading|strongest|"
    r"greatest|number[- ]one|top|durable)\b[^.]*?\b(category|categor|market|"
    r"format|genre|segment|revenue|audience|demand|growth|grossing|franchise|"
    r"performing)\b",
    re.IGNORECASE,
)
#: Sentences that *restate* the python-executed economics — their dollars are
#: computed echoes, not independent external facts.
_COMPUTED_CTX_RE = re.compile(
    r"\b(obtainable market|serviceable addressable|serviceable share|"
    r"lifetime value|modeled floor|modeled at|upside (?:near|of)|capture rate|"
    r"python[_ ]executed|realistic obtainable|first-year theatrical window)\b",
    re.IGNORECASE,
)

_UNIT_TO_MILLIONS: dict[str, float] = {
    "trillion": 1_000_000.0,
    "t": 1_000_000.0,
    "billion": 1_000.0,
    "b": 1_000.0,
    "million": 1.0,
    "m": 1.0,
    "thousand": 0.001,
    "k": 0.001,
}

#: Minimum pipe-cells for a parseable Economics / Comparables data row.
_MIN_ECON_CELLS = 2
_MIN_COMP_CELLS = 3
#: Default WW-revenue column index when no header maps it (Title|Year|WW|Budget|ROI).
_DEFAULT_GROSS_COL = 2


def _money_to_millions(num: str, unit: str | None) -> float | None:
    """Convert a parsed ``$`` figure to a float number of USD millions."""
    try:
        value = float(num.replace(",", ""))
    except ValueError:
        return None
    if not unit:
        return value / 1_000_000.0  # bare dollars
    return value * _UNIT_TO_MILLIONS.get(unit.lower(), 1.0)


def _close(a: float, b: float) -> bool:
    """Two money magnitudes (in millions) refer to the same figure (2% / $0.5M)."""
    return abs(a - b) <= max(0.5, 0.02 * b)


# --------------------------------------------------------------------------- #
# Claim id / dedup
# --------------------------------------------------------------------------- #


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("*", "")).strip().lower()


def _stable_id(concept_id: str, claim_type: str, text: str) -> str:
    raw = f"{concept_id}|{claim_type}|{_norm_text(text)}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _classify_demand(value: str, text: str) -> str:
    blob = f"{value} {text}".lower()
    if "$" in value and any(
        k in blob for k in ("ww", "worldwide", "box office", "grossed", "opening", "per-screen")
    ):
        return "box_office"
    if "%" in value or "pts" in value.lower() or "percentage points" in blob:
        return "cultural_signal"
    return "demand"


# --------------------------------------------------------------------------- #
# Line tagging (which section is each line in?)
# --------------------------------------------------------------------------- #


def _tag_lines(md: str) -> list[tuple[str, bool, str]]:
    """Return ``[(line, in_scope, section_key)]`` for every line of the card."""
    out: list[tuple[str, bool, str]] = []
    # stack of (heading_level, in_scope, section_key)
    stack: list[tuple[int, bool, str]] = []
    for line in md.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            scope = _heading_scope(text)
            stack.append((level, scope, _section_key(text) if scope else ""))
            out.append((line, False, ""))  # the heading line itself is not scanned
            continue
        in_scope = False
        section = ""
        for _lvl, scope, key in reversed(stack):
            in_scope = scope
            section = key
            break
        out.append((line, in_scope, section))
    return out


def tag_lines(md: str) -> list[tuple[str, bool, str]]:
    """Public view of the section-scope tagger: ``[(line, in_scope, section_key)]``.

    Exposed for the inline renderer (``render_inline``) so it can locate which
    rendered lines sit inside an evidence section without re-implementing the
    heading walk.
    """
    return _tag_lines(md)


# --------------------------------------------------------------------------- #
# Table + bullet parsers
# --------------------------------------------------------------------------- #


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _is_separator_row(cells: list[str]) -> bool:
    return all(set(c) <= set("-: ") and c for c in cells) if cells else False


def _parse_economics(
    tagged: list[tuple[str, bool, str]], cid: str, title: str
) -> tuple[list[Claim], dict[str, float]]:
    """Parse the Economics table → (claims, frozen {tam,sam,som,lifetime} millions)."""
    claims: list[Claim] = []
    frozen: dict[str, float] = {}
    layer_map = {
        "tam": ("market_tam", "Total addressable market"),
        "sam": ("market_sam", "Serviceable addressable market"),
        "som": ("market_som", "Year-1 serviceable obtainable market"),
        "lifetime": ("lifetime", "Multi-window lifetime value"),
    }
    for line, in_scope, section in tagged:
        if not (in_scope and section == "economics" and line.lstrip().startswith("|")):
            continue
        cells = _split_row(line)
        if len(cells) < _MIN_ECON_CELLS or _is_separator_row(cells):
            continue
        label = cells[0].replace("*", "").strip().lower()
        value = cells[1].strip()
        basis = cells[2] if len(cells) > _MIN_ECON_CELLS else ""
        key = next((k for k in layer_map if k in label), None)
        if key is None:
            continue
        money = _MONEY_RE.search(value)
        if money:
            mm = _money_to_millions(money.group(1), money.group(2))
            if mm is not None:
                frozen[key] = mm
        ctype, human = layer_map[key]
        link = _LINK_RE.search(basis)
        url = link.group(2) if (ctype == "market_tam" and link) else ""
        claims.append(
            Claim(
                claim_id=_stable_id(cid, ctype, human),
                concept_id=cid,
                concept_title=title,
                claim_type=ctype,
                text=f"{human}: {value}",
                value=value,
                cited_url=url,
                anchor=value,
                section="economics",
            )
        )
    return claims, frozen


def _comp_header_index(cells: list[str]) -> dict[str, int]:
    """Map a Comparables header row to {gross, budget, roi} column indices."""
    col: dict[str, int] = {}
    for i, c in enumerate(cells):
        cl = c.strip().lower()
        if ("gross" in cl or "revenue" in cl or cl == "ww") and "gross" not in col:
            col["gross"] = i
        elif ("budget" in cl or "cost" in cl) and "budget" not in col:
            col["budget"] = i
        elif ("roi" in cl or "multiple" in cl or "return" in cl) and "roi" not in col:
            col["roi"] = i
    return col


def _row_money(cells: list[str], idx: int | None) -> str:
    """The first $ token in column ``idx`` (the WW-revenue column), else first in row."""
    if idx is not None and 0 <= idx < len(cells):
        m = _MONEY_RE.search(cells[idx])
        if m:
            return m.group(0)
    for c in cells[1:]:
        m = _MONEY_RE.search(c)
        if m:
            return m.group(0)
    return ""


def _row_roi(cells: list[str], idx: int | None) -> str:
    target = cells[idx] if (idx is not None and 0 <= idx < len(cells)) else " ".join(cells)
    m = _ROI_RE.search(target)
    return m.group(0) if m else ""


def _comp_row_claim(
    cells: list[str], col: dict[str, int], cid: str, title: str, values: set[float]
) -> Claim | None:
    link = _LINK_RE.search(cells[0])
    comp_title = (link.group(1) if link else cells[0]).replace("*", "").strip()
    if not comp_title:
        return None
    comp_url = link.group(2) if link else ""
    for c in cells[1:]:  # record every $ (gross + budget) for restatement dedup
        for mny in _MONEY_RE.finditer(c):
            mm = _money_to_millions(mny.group(1), mny.group(2))
            if mm is not None:
                values.add(mm)
    default_gross = _DEFAULT_GROSS_COL if len(cells) > _DEFAULT_GROSS_COL else 1
    gross = _row_money(cells, col.get("gross", default_gross))
    roi = _row_roi(cells, col.get("roi"))
    roi_txt = f" (ROI {roi})" if roi else ""
    gross_txt = f" grossed {gross} worldwide" if gross else ""
    return Claim(
        claim_id=_stable_id(cid, "comp_roi", comp_title),
        concept_id=cid,
        concept_title=title,
        claim_type="comp_roi",
        text=f"{comp_title}{gross_txt}{roi_txt}".strip(),
        value=gross,
        cited_url=comp_url,
        anchor=comp_title,
        section="comparables",
    )


def _parse_comparables(
    tagged: list[tuple[str, bool, str]], cid: str, title: str
) -> tuple[list[Claim], set[float]]:
    """Parse Comparables table rows → (comp_roi claims, {gross/budget millions})."""
    claims: list[Claim] = []
    values: set[float] = set()
    seen: set[str] = set()
    col: dict[str, int] = {}
    for line, in_scope, section in tagged:
        if not (in_scope and section == "comparables" and line.lstrip().startswith("|")):
            continue
        cells = _split_row(line)
        if len(cells) < _MIN_COMP_CELLS or _is_separator_row(cells):
            continue
        first = cells[0].replace("*", "").strip().lower()
        if first in {"title", "film", ""}:
            col = _comp_header_index(cells)
            continue
        claim = _comp_row_claim(cells, col, cid, title, values)
        if claim is None or claim.anchor.lower() in seen:
            continue
        seen.add(claim.anchor.lower())
        claims.append(claim)
    return claims, values


def _parse_proof_bullets(tagged: list[tuple[str, bool, str]], cid: str, title: str) -> list[Claim]:
    """Parse the Verified Proof of Demand bullets (already carry url + quote)."""
    claims: list[Claim] = []
    for line, in_scope, section in tagged:
        if not (in_scope and section == "verified proof of demand"):
            continue
        stripped = line.lstrip()
        if not stripped.startswith(("-", "*")) or stripped.startswith("---"):
            continue
        bold = re.search(r"\*\*(.+?)\*\*", line)
        claim_text = (bold.group(1) if bold else stripped.lstrip("-* ").split("—")[0]).strip()
        if not claim_text:
            continue
        link = _LINK_RE.search(line)
        url = link.group(2) if link else ""
        dm = re.search(r"(\d{4}(?:-\d{2}(?:-\d{2})?)?)\s*\)?\s*$", line)
        date = dm.group(1) if dm else ""
        money = _MONEY_RE.search(claim_text)
        value = money.group(0) if money else ""
        ctype = _classify_demand(value, claim_text)
        claims.append(
            Claim(
                claim_id=_stable_id(cid, ctype, claim_text),
                concept_id=cid,
                concept_title=title,
                claim_type=ctype,
                text=claim_text,
                value=value,
                cited_url=url,
                date=date,
                anchor=claim_text,
                section="verified proof of demand",
            )
        )
    return claims


# --------------------------------------------------------------------------- #
# Prose scan
# --------------------------------------------------------------------------- #

_SENTENCE_SPLIT = re.compile(r"(?<=[.;:])\s+")
_SKIP_PREFIXES = ("|", "#", ">", "_", "```")


def _parse_prose(
    tagged: list[tuple[str, bool, str]],
    cid: str,
    title: str,
    frozen: dict[str, float],
    comp_values: set[float],
) -> list[Claim]:
    """Scan in-scope prose for demand stats, salience numbers, and conclusions."""
    claims: list[Claim] = []
    seen: set[str] = set()
    frozen_mm = list(frozen.values())

    def _is_computed_echo(mm: float | None) -> bool:
        if mm is None:
            return False
        return any(_close(mm, f) for f in frozen_mm) or any(_close(mm, c) for c in comp_values)

    for line, in_scope, section in tagged:
        if not in_scope:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(_SKIP_PREFIXES) or stripped.startswith(("-", "*")):
            continue
        if section in {"comparables", "economics", "verified proof of demand"}:
            continue  # handled by the dedicated parsers
        for sentence in _SENTENCE_SPLIT.split(stripped):
            _scan_sentence(sentence, section, cid, title, claims, seen, _is_computed_echo)
    return claims


def _scan_sentence(
    sentence: str,
    section: str,
    cid: str,
    title: str,
    claims: list[Claim],
    seen: set[str],
    is_computed_echo: Callable[[float | None], bool],
) -> None:
    s = sentence.strip()
    if not s:
        return
    computed_ctx = bool(_COMPUTED_CTX_RE.search(s))
    if not computed_ctx:
        for mny in _MONEY_RE.finditer(s):  # 1. dollar figures
            if is_computed_echo(_money_to_millions(mny.group(1), mny.group(2))):
                continue
            _add(
                claims,
                seen,
                cid,
                title,
                _classify_demand(mny.group(0), s),
                s,
                mny.group(0),
                section,
            )
        for bn in _BIGNUM_RE.finditer(s):  # 2. bare large numbers ("11 million people")
            if is_computed_echo(_money_to_millions(bn.group(1), bn.group(2))):
                continue
            _add(claims, seen, cid, title, "demand", s, bn.group(0), section)
    for pct in _PCT_RE.finditer(s):  # 3. percentages (cultural signals)
        _add(claims, seen, cid, title, "cultural_signal", s, pct.group(0), section)
    if _SUPERLATIVE_RE.search(s):  # 4. market conclusions / superlatives
        _add(claims, seen, cid, title, "market_claim", s, "", section)


def _add(
    claims: list[Claim],
    seen: set[str],
    cid: str,
    title: str,
    ctype: str,
    sentence: str,
    value: str,
    section: str,
) -> None:
    text = sentence.strip()
    key = f"{ctype}|{_norm_text(text)}"
    if key in seen:
        return
    seen.add(key)
    claims.append(
        Claim(
            claim_id=_stable_id(cid, ctype, text),
            concept_id=cid,
            concept_title=title,
            claim_type=ctype,
            text=text,
            value=value,
            cited_url="",
            anchor=text,
            section=section,
        )
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def enumerate_claims(md: str, *, concept_id: str = "doc", concept_title: str = "") -> list[Claim]:
    """Enumerate every externally-checkable + computed claim in a rendered card.

    Returns EXTERNAL claims (comps, TAM, demand stats, market conclusions —
    each needing a primary source + quote) and COMPUTED claims (SAM/SOM/lifetime
    — proven by ``python_executed`` calculation, excluded from the external
    density denominator). Narrative numbers are never emitted.
    """
    tagged = _tag_lines(md)
    econ_claims, frozen = _parse_economics(tagged, concept_id, concept_title)
    comp_claims, comp_values = _parse_comparables(tagged, concept_id, concept_title)
    proof_claims = _parse_proof_bullets(tagged, concept_id, concept_title)
    prose_claims = _parse_prose(tagged, concept_id, concept_title, frozen, comp_values)

    # Order: economics, comps, proof, prose — stable + deduped by claim_id.
    out: list[Claim] = []
    seen_ids: set[str] = set()
    for c in (*econ_claims, *comp_claims, *proof_claims, *prose_claims):
        if c.claim_id in seen_ids:
            continue
        seen_ids.add(c.claim_id)
        out.append(c)
    return out


def frozen_economics(md: str) -> dict[str, float]:
    """Return the card's frozen ``{tam, sam, som, lifetime}`` values (USD millions).

    Lets the card-scoring path confirm the SOM < SAM < TAM invariant for the
    COMPUTED claims without re-implementing the table parser.
    """
    return _parse_economics(_tag_lines(md), "", "")[1]


def card_quote_judgments(md: str, *, concept_id: str = "doc") -> dict[str, dict[str, str]]:
    """Bind the verbatim quotes ALREADY rendered in Verified Proof of Demand bullets.

    Returns ``{claim_id: {"quote": <verbatim>}}`` keyed by the SAME claim_id the
    enumerator assigns each bullet, so :func:`merge_agent_judgments` lifts the
    quote onto the claim's provenance (raising quote coverage). ``supports`` is
    deliberately omitted: a quote that the card already carries is evidence the
    text *exists*, but only a live re-fetch (Movement 5) can set agent_supports
    and promote SUPPORTED -> VERIFIED. Offline binding never mints a VERIFIED.
    """
    out: dict[str, dict[str, str]] = {}
    for line, in_scope, section in _tag_lines(md):
        if not (in_scope and section == "verified proof of demand"):
            continue
        stripped = line.lstrip()
        if not stripped.startswith(("-", "*")) or stripped.startswith("---"):
            continue
        bold = re.search(r"\*\*(.+?)\*\*", line)
        claim_text = (bold.group(1) if bold else stripped.lstrip("-* ").split("—")[0]).strip()
        qm = re.search(r"[“\"]([^”\"]{3,})[”\"]", line)
        if not claim_text or not qm:
            continue
        money = _MONEY_RE.search(claim_text)
        ctype = _classify_demand(money.group(0) if money else "", claim_text)
        out[_stable_id(concept_id, ctype, claim_text)] = {"quote": qm.group(1).strip()}
    return out
