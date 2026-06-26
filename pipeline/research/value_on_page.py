"""pipeline/research/value_on_page.py — Anti-hallucination core for claim verification.

Promoted from scripts/source_claims_302.py. Re-imported back by that script so
behaviour is byte-identical. callers that previously used ``source_claims_302``
helpers directly should migrate to this module instead.

Functions promoted (no behaviour change):
    is_credible(url, claim_type) -> bool
    is_deep_link(url) -> bool
    _fragment_on_page(quote, page) -> bool          (package-private)
    _digits(text) -> str                             (package-private)
    _digits_only(text) -> str                        (package-private)
    _best_quote(sonar_quote, blob, core) -> str      (package-private)

New functions:
    number_variants(raw) -> list[str]
        Expand a human-readable number string into every surface form that
        might appear on a page:
            '$1.2B'  → ['$1.2B', '1.2 billion', '1,200,000,000',
                        '1200000000', '$1,200,000,000']
            '40%'    → ['40%', '40 percent']
            '$758.5M'→ ['$758.5M', '758.5 million', '758,500,000',
                        '758500000', '$758,500,000']
        Scale suffixes: K (thousands), M (millions), B (billions).
        Thousands-separator and rounding-tolerance variants included.

    value_on_page(value, page_text, *, max_quote_words=25) -> ValueMatch
        Refute-by-default substring search.
        Tries each variant from number_variants(); on a hit, extracts the
        surrounding sentence and trims it to max_quote_words.
        Returns ValueMatch(matched=False) when no variant is found.
        NEVER returns a quote that does not contain the matched variant.

    source_tier(url) -> int (1..5)
        Map a URL to the deep-link-evidence tier ladder:
            1 = government / regulatory feeds
            2 = primary platform APIs / Box Office Mojo / The Numbers / major trades
            3 = industry archives and data agencies
            4 = commercial APIs and research aggregators
            5 = everything else (aggregators, scrapers, unclassified)

    build_provenance(value, page, match) -> pipeline.veracity.provenance.Provenance
        Convenience factory: given a value string, the raw page text, and a
        ValueMatch, return a fully-populated Provenance record.  url,
        http_status, fetched_at, and content_sha256 are not known at this level
        — callers that have a full FetchedPage should populate those fields
        manually via Provenance(...) directly.  This helper sets sensible
        empty-string / None defaults for those transport fields.

ADR-0007: this module is in pipeline/research/ — HTTP is allowed here but
    none of these helpers need it; they are pure text utilities.
ADR-0005: MUST NOT import from frameworks/.
ANOMALY-001: MUST NOT import anthropic, httpx, pipeline.run, or
    openrouter_client from this module (pure text helpers — no HTTP).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pipeline.veracity.provenance import Provenance

# ── Named constants ───────────────────────────────────────────────────────────

_SEARCH_HOST_MARKERS: Final[tuple[str, ...]] = (
    "google.",
    "bing.",
    "duckduckgo.",
    "search.brave.",
    "yandex.",
    "yahoo.",
)

_MIN_FRAGMENT_WORDS: Final[int] = 5
_SENT_MIN_WORDS: Final[int] = 3
_SENT_MAX_WORDS: Final[int] = 40
_QUOTE_MAX_CHARS: Final[int] = 240

# ── Source-authority catalogs (mirrors source_claims_302.py) ──────────────────

_BOXOFFICE_AUTH: Final[tuple[str, ...]] = ("boxofficemojo.com", "the-numbers.com")
_TRADE: Final[tuple[str, ...]] = (
    "variety.com",
    "deadline.com",
    "hollywoodreporter.com",
    "screendaily.com",
    "screenrant.com",
    "collider.com",
    "mumbrella.com.au",
    "frontofficesports.com",
    "americanfilmmarket.com",
    "screendollars.com",
    "indiewire.com",
    "thewrap.com",
    "movieweb.com",
    "mediaplaynews.com",
)
_DATA_AUTH: Final[tuple[str, ...]] = (
    ".gov",
    "motionpictures.org",
    "pewresearch.org",
    "gallup.com",
    "kff.org",
    "nielsen.com",
    "parrotanalytics.com",
    "yougov.com",
    "statista.com",
    "internal-displacement.org",
    "preventionweb.net",
    "en.wikipedia.org",
    "netflix.com",
    "disney.co.uk",
    "thewaltdisneycompany.com",
    "ampereanalysis.com",
    "stlouisfed.org",
    "unesco.org",
    "who.int",
    "oecd.org",
    "nature.com",
)

# ── Tier-1 government / regulatory ───────────────────────────────────────────

_TIER_1_HOSTS: Final[tuple[str, ...]] = (
    ".gov",
    "fred.stlouisfed.org",
    "api.stlouisfed.org",
    "census.gov",
    "sec.gov",
    "film.ca.gov",
    "gov.br",
    "ancine.gov.br",
    "who.int",
    "oecd.org",
    "un.org",
    "unesco.org",
    "worldbank.org",
    "imf.org",
    "europa.eu",
    "nber.org",
)

# ── Tier-2 primary platform APIs / box-office authorities / major trades ──────

_TIER_2_HOSTS: Final[tuple[str, ...]] = (
    "boxofficemojo.com",
    "the-numbers.com",
    "variety.com",
    "deadline.com",
    "hollywoodreporter.com",
    "screendaily.com",
    "indiewire.com",
    "thewrap.com",
    "api.themoviedb.org",
    "themoviedb.org",
    "imdb.com",
    "youtube.com",
    "youtu.be",
    "spotify.com",
    "github.com",
    "en.wikipedia.org",
    "motionpictures.org",
    "parrotanalytics.com",
    "pewresearch.org",
    "gallup.com",
    "kff.org",
    "nielsen.com",
)

# ── Tier-3 industry archives / data agencies ──────────────────────────────────

_TIER_3_HOSTS: Final[tuple[str, ...]] = (
    "statista.com",
    "ampereanalysis.com",
    "screendollars.com",
    "screenrant.com",
    "collider.com",
    "thewaltdisneycompany.com",
    "netflix.com",
    "disney.co.uk",
    "nature.com",
    "yougov.com",
    "internal-displacement.org",
    "preventionweb.net",
    "mumbrella.com.au",
    "frontofficesports.com",
    "americanfilmmarket.com",
    "movieweb.com",
    "mediaplaynews.com",
    "papers.ssrn.com",
    "arxiv.org",
    "sagaftra.org",
    "dga.org",
    "wga.org",
    "ascap.com",
    "bmi.com",
    "sesac.com",
    "letterboxd.com",
    "kinopoisk.ru",
    "flixpatrol.com",
    "reelgood.com",
    "stlouisfed.org",
)

# ── Tier-4 commercial APIs ────────────────────────────────────────────────────

_TIER_4_HOSTS: Final[tuple[str, ...]] = (
    "comscore.com",
    "nielsen.com/solutions",
    "sprinklr.com",
    "rapidapi.com",
)


# ── Promoted pure helpers from source_claims_302.py ──────────────────────────


def _norm(text: str) -> str:
    """Normalise whitespace and lower-case for substring matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _digits(text: str) -> str:
    """Integer core of the first number, commas removed.

    Examples::

        _digits('$505.0M') -> '505'
        _digits('40%')     -> '40'
        _digits('')        -> ''
    """
    m = re.search(r"\d[\d,]*", text)
    return m.group(0).replace(",", "") if m else ""


def _digits_only(text: str) -> str:
    """Strip every non-digit character from *text*."""
    return re.sub(r"\D", "", text)


def is_deep_link(url: str) -> bool:
    """Return True iff the URL is https/http, not a search engine, and has a path.

    A 'deep' URL has a non-empty path beyond ``/`` (e.g. ``/article/123``).
    Bare domains such as ``https://example.com`` or ``https://example.com/``
    return False.

    Args:
        url: The URL string to evaluate.

    Returns:
        True when the URL passes all deep-link criteria; False otherwise.
    """
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    if any(marker in p.netloc.lower() for marker in _SEARCH_HOST_MARKERS):
        return False
    return len(p.path.strip("/")) > 0


def is_credible(url: str, claim_type: str) -> bool:
    """Return True when the URL is an acceptable source for *claim_type*.

    Box-office / ROI claims must cite a box-office authority (Box Office Mojo,
    The Numbers) or a major trade (Variety, Deadline, …).  Demand / market /
    cultural claims may also cite government and research sources.

    Args:
        url:        The source URL to evaluate.
        claim_type: Category string, e.g. ``"comp_roi"``, ``"box_office"``,
                    ``"market_data"``.

    Returns:
        True when the host is on the appropriate authority list.
    """
    host = urlparse(url).netloc.lower() if url else ""
    if not host:
        return False
    if claim_type in ("comp_roi", "box_office"):
        return any(h in host for h in _BOXOFFICE_AUTH + _TRADE)
    return any(h in host for h in _BOXOFFICE_AUTH + _TRADE + _DATA_AUTH)


def _fragment_on_page(quote: str, page: str) -> bool:
    """Return True when a >=5-word fragment of *quote* appears verbatim in *page*.

    Comparison is case-insensitive with whitespace normalisation.

    Args:
        quote: The candidate quote string.
        page:  The full page text to search within.

    Returns:
        True when any contiguous :data:`_MIN_FRAGMENT_WORDS`-word window from
        *quote* is found in *page*; False otherwise.
    """
    nq, npage = _norm(quote), _norm(page)
    if not nq:
        return False
    if nq in npage:
        return True
    words = nq.split()
    if len(words) < _MIN_FRAGMENT_WORDS:
        return False
    return any(
        " ".join(words[i : i + _MIN_FRAGMENT_WORDS]) in npage
        for i in range(len(words) - _MIN_FRAGMENT_WORDS + 1)
    )


def subject_on_page(anchor: str, page_text: str) -> bool:
    """Return True when the claim's subject *anchor* appears on *page_text*.

    Closes the off-scope deep-link gap: :func:`value_on_page` confirms the
    NUMBER is present, but on an in-host page that lists many titles (e.g. a Box
    Office Mojo yearly table) the number may belong to a DIFFERENT film than the
    claim is about. ``subject_on_page`` requires the claim's subject text — its
    ``anchor`` (the comp title from
    :func:`pipeline.veracity.enumerate.enumerate_claims`) — to also appear,
    binding the number to the right subject before a ``comp_roi`` judgment is
    trusted.

    Reuses :func:`_fragment_on_page` (full-string containment, else a
    :data:`_MIN_FRAGMENT_WORDS`-word window). An empty/whitespace *anchor*
    returns ``False``: a ``comp_roi`` claim with no bindable subject cannot be
    proven on-scope, so refute-by-default applies.

    Note:
        A very short / common anchor (e.g. a one-word title) can match
        incidentally; the driver should flag tier-4/5 survivors for human review.

    Args:
        anchor:    The claim's subject string (comp film title, topic).
        page_text: Full text content of the fetched evidence page.

    Returns:
        True when the subject is found on the page; False otherwise.
    """
    if not anchor or not anchor.strip():
        return False
    return _fragment_on_page(anchor, page_text)


def _best_quote(sonar_quote: str, blob: str, core: str) -> str:
    """Return the best evidence quote for a value.

    Prefer *sonar_quote* when it is grounded in *blob*; otherwise scan *blob*
    for a sentence carrying *core* (the digit-core of the value).

    Args:
        sonar_quote: LLM-suggested quote (may be empty).
        blob:        Concatenated crawl + SERP text.
        core:        Digit-core string (e.g. ``"1200000000"``); may be empty.

    Returns:
        The best available quote string; may be empty when nothing is found.
    """
    if sonar_quote and _fragment_on_page(sonar_quote, blob):
        return sonar_quote
    if core:
        for sent in re.split(r"(?<=[.;!?])\s+", blob):
            words = sent.split()
            if core in _digits_only(sent) and _SENT_MIN_WORDS <= len(words) <= _SENT_MAX_WORDS:
                return sent.strip()[:_QUOTE_MAX_CHARS]
    return sonar_quote


# ── number_variants ───────────────────────────────────────────────────────────

_SCALE: Final[dict[str, int]] = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
}
_SCALE_WORDS: Final[dict[str, str]] = {
    "K": "thousand",
    "M": "million",
    "B": "billion",
}


def _format_with_commas(n: int) -> str:
    """Return a comma-separated integer string, e.g. 1200000000 -> '1,200,000,000'."""
    return f"{n:,}"


def number_variants(raw: str) -> list[str]:
    """Expand a human-readable number into every plausible surface form.

    Handles:
    - Dollar amounts with B/M/K scale: ``$1.2B``, ``$758.5M``, ``$50K``
    - Bare percentages: ``40%``
    - Returns the original *raw* string as the first element so callers can
      always fall back to it.

    Scale expansions produced for ``$1.2B``:
        - ``'$1.2B'``            (original)
        - ``'1.2 billion'``      (word form)
        - ``'1,200,000,000'``    (comma integer)
        - ``'1200000000'``       (plain integer)
        - ``'$1,200,000,000'``   (dollar + comma integer)

    For rounding tolerance the integer is derived from the raw float via
    ``round(magnitude * scale)`` so ``$758.5M`` → 758,500,000 (not 758,539,785;
    the near-match test demonstrates that integer equality is required).

    Percentage: ``'40%'`` → ``['40%', '40 percent']``.

    Args:
        raw: The raw value string exactly as it appears in the claim manifest.

    Returns:
        List of non-empty, deduplicated surface variants; always starts with
        *raw* when non-empty.
    """
    if not raw or not raw.strip():
        return []

    variants: list[str] = [raw]
    stripped = raw.strip()

    # ── Percentage ────────────────────────────────────────────────────────────
    pct_m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", stripped)
    if pct_m:
        num = pct_m.group(1)
        variants.append(f"{num} percent")
        return _dedupe(variants)

    # ── Dollar / plain number with optional B/M/K suffix ─────────────────────
    # Pattern: optional '$', a decimal number, optional scale letter
    num_m = re.fullmatch(r"(\$?)(\d+(?:\.\d+)?)\s*([BbMmKk]?)", stripped)
    if not num_m:
        return _dedupe(variants)

    dollar_sign = num_m.group(1)
    magnitude = float(num_m.group(2))
    suffix = num_m.group(3).upper()

    if suffix not in _SCALE:
        # No recognised scale — just return the original
        return _dedupe(variants)

    scale_val = _SCALE[suffix]
    scale_word = _SCALE_WORDS[suffix]
    int_val = round(magnitude * scale_val)

    comma_int = _format_with_commas(int_val)
    plain_int = str(int_val)

    # e.g. '1.2 billion', '758.5 million'
    variants.append(f"{magnitude:g} {scale_word}")
    # e.g. '1,200,000,000'
    variants.append(comma_int)
    # e.g. '1200000000'
    variants.append(plain_int)
    # e.g. '$1,200,000,000'
    if dollar_sign:
        variants.append(f"${comma_int}")

    return _dedupe(variants)


def _dedupe(items: list[str]) -> list[str]:
    """Return items with duplicates removed, preserving insertion order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ── ValueMatch ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValueMatch:
    """Result of :func:`value_on_page`.

    Attributes:
        matched:         True when *value* was found on the page.
        quote:           Sentence carrying the matched variant (≤ *max_quote_words*
                         words); empty string when ``matched=False``.
        matched_variant: The specific surface form that was found; empty when
                         ``matched=False``.
        char_offset:     Character offset of *matched_variant* in *page_text*;
                         -1 when not matched.
    """

    matched: bool
    quote: str
    matched_variant: str
    char_offset: int


_NO_MATCH: Final[ValueMatch] = ValueMatch(
    matched=False, quote="", matched_variant="", char_offset=-1
)


# ── value_on_page ─────────────────────────────────────────────────────────────


def value_on_page(
    value: str,
    page_text: str,
    *,
    max_quote_words: int = 25,
) -> ValueMatch:
    """Search for *value* (and all its number variants) in *page_text*.

    Refute-by-default: returns ``ValueMatch(matched=False, ...)`` unless a
    variant is found as a literal substring (case-insensitive, whitespace
    normalised).

    When a variant is found, the surrounding sentence is extracted and trimmed
    to *max_quote_words* words.  The returned quote is guaranteed to contain
    *matched_variant* (case-insensitive check).

    Args:
        value:           The claim value, e.g. ``"$1.2B"``, ``"40%"``.
        page_text:       Full text content of the fetched page.
        max_quote_words: Maximum word count for the extracted quote (default 25).

    Returns:
        :class:`ValueMatch` with ``matched=True`` and a non-empty *quote* on
        success, or ``_NO_MATCH`` (``matched=False``) when the value is absent.
    """
    if not value or not page_text:
        return _NO_MATCH

    variants = number_variants(value)
    if not variants:
        return _NO_MATCH

    norm_page = _norm(page_text)

    for variant in variants:
        norm_variant = _norm(variant)
        if not norm_variant:
            continue
        idx = norm_page.find(norm_variant)
        if idx == -1:
            continue

        # ── Digit-core safety check ───────────────────────────────────────────
        # Reject if the variant's digit core appears but in a different magnitude
        # context.  E.g. '$1.2B' must NOT match '$1.2M' on the page.
        # We verify by checking that the exact normalised variant string appears
        # (the find above already confirmed this), AND that the digit core of the
        # variant is present in the surrounding token — the literal find is
        # sufficient; we just need to confirm it is exact (not a sub-numeric).
        # The literal substring match is already exact; we do an additional
        # check: the variant found must not be a numeric sub-match of a larger
        # number on the page (e.g. '1200' inside '12000').  We validate by
        # ensuring the character immediately before and after the match is not
        # a digit.
        start = idx
        end = idx + len(norm_variant)
        pre_char = norm_page[start - 1] if start > 0 else " "
        post_char = norm_page[end] if end < len(norm_page) else " "
        if pre_char.isdigit() or post_char.isdigit():
            continue

        # ── Extract surrounding sentence ───────────────────────────────────────
        quote = _extract_sentence(page_text, idx, variant, max_quote_words)

        # ── Invariant: quote must contain the matched variant ─────────────────
        if not quote or _norm(variant) not in _norm(quote):
            # Sentence extraction failed to include the match — use window fallback
            quote = _window_quote(page_text, idx, variant, max_quote_words)
            if _norm(variant) not in _norm(quote):
                # Still no match in quote — skip this variant to avoid a bad quote
                continue

        return ValueMatch(
            matched=True,
            quote=quote,
            matched_variant=variant,
            char_offset=idx,
        )

    return _NO_MATCH


def _extract_sentence(
    page_text: str,
    norm_idx: int,
    variant: str,
    max_words: int,
) -> str:
    """Extract the sentence containing the match and trim to *max_words*.

    Works on the original (non-normalised) *page_text* by finding the
    nearest sentence boundary around *norm_idx*.

    Args:
        page_text: Original (non-normalised) page text.
        norm_idx:  Character offset in the *normalised* page (approximate;
                   used to locate the region in the original text).
        variant:   The matched variant string (used for ratio estimation).
        max_words: Maximum words in the output quote.

    Returns:
        Trimmed sentence string; may be empty if extraction fails.
    """
    # Estimate position in original text (normalised is usually shorter).
    # Walk sentences in the original and pick the one containing the variant.
    norm_variant = _norm(variant)
    sentences = re.split(r"(?<=[.;!?])\s+", page_text)
    for sent in sentences:
        if norm_variant in _norm(sent):
            words = sent.split()
            if len(words) <= max_words:
                return sent.strip()
            # Trim to max_words words but keep the sentence start (most readable).
            trimmed = " ".join(words[:max_words])
            # Ensure variant is still present after trim
            if norm_variant in _norm(trimmed):
                return trimmed
            # Variant was in the tail — find it and build a window
            return _window_quote(page_text, norm_idx, variant, max_words)
    return ""


def _window_quote(
    page_text: str,
    norm_idx: int,
    variant: str,
    max_words: int,
) -> str:
    """Build a fallback word-window quote centred on the match.

    Splits *page_text* into words, estimates the token index of the match,
    and returns up to *max_words* words centred on that token.

    Args:
        page_text: Original page text.
        norm_idx:  Character offset in normalised text (used as a rough ratio).
        variant:   Matched variant string.
        max_words: Maximum words in the output quote.

    Returns:
        Word-window string guaranteed to contain *variant* (if possible).
    """
    norm_variant = _norm(variant)
    words = page_text.split()
    # Scan words for the first window containing norm_variant
    half = max_words // 2
    for i, _ in enumerate(words):
        window = words[max(0, i - half) : i + half + 1]
        window_text = " ".join(window)
        if norm_variant in _norm(window_text):
            return window_text
    return ""


# ── source_tier ───────────────────────────────────────────────────────────────


def source_tier(url: str) -> int:
    """Map a URL to the deep-link-evidence tier ladder (1 = best, 5 = weakest).

    Tier definitions (from deep-link-evidence policy):
        1 = Government / regulatory feeds (SEC EDGAR, FRED, Census, WHO, etc.)
        2 = Primary platform APIs + box-office authorities + major trades
        3 = Industry archives / data agencies
        4 = Commercial APIs (Comscore, Nielsen solutions, SerpApi, etc.)
        5 = Aggregators / scrapers / unclassified

    Args:
        url: The source URL.

    Returns:
        Integer tier 1-5 (5 when no tier matches).
    """
    host = urlparse(url).netloc.lower() if url else ""
    if not host:
        return 5
    for h in _TIER_1_HOSTS:
        if h in host:
            return 1
    for h in _TIER_2_HOSTS:
        if h in host:
            return 2
    for h in _TIER_3_HOSTS:
        if h in host:
            return 3
    for h in _TIER_4_HOSTS:
        if h in host:
            return 4
    return 5


# ── build_provenance ──────────────────────────────────────────────────────────


def build_provenance(
    value: str,
    page: str,
    match: ValueMatch,
    *,
    url: str = "",
    http_status: int | None = None,
    fetched_at: str = "",
    content_sha256: str | None = None,
) -> Provenance:
    """Build a :class:`~pipeline.veracity.provenance.Provenance` from a ValueMatch.

    Transport fields (*url*, *http_status*, *fetched_at*, *content_sha256*) are
    optional here because this helper is used in contexts where the page text
    was already fetched separately.  Callers with a full
    :class:`~pipeline.research.providers.types.FetchedPage` should pass those
    fields to get a complete provenance record.

    Args:
        value:          The claim value (e.g. ``"$1.2B"``).
        page:           The raw page text (used if re-verification is needed).
        match:          :class:`ValueMatch` returned by :func:`value_on_page`.
        url:            URL that was fetched (optional; defaults to ``""``).
        http_status:    HTTP status code of the fetch (optional).
        fetched_at:     ISO-8601 UTC timestamp (optional; defaults to ``""``).
        content_sha256: SHA-256 hex of the fetched content (optional).

    Returns:
        A frozen :class:`~pipeline.veracity.provenance.Provenance` instance.
    """
    from pipeline.veracity.provenance import Provenance  # noqa: PLC0415

    return Provenance(
        url=url,
        http_status=http_status,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
        quote=match.quote,
        supports_claim=match.matched,
    )


__all__ = [
    "ValueMatch",
    "_best_quote",
    "_digits",
    "_digits_only",
    "_fragment_on_page",
    "build_provenance",
    "is_credible",
    "is_deep_link",
    "number_variants",
    "source_tier",
    "subject_on_page",
    "value_on_page",
]
