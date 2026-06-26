"""Template filter for investor-facing .md files.

Pure Python. No LLM imports. No network I/O. ADR-0010.

Public API:
  strip_internal_ids(md_text)         -> str
  scan_for_internal_ids(md_text)      -> list[dict[str, str | int]]
  enforce_v2_sections(md_text)        -> list[str]
  check_template_compliance(md_text)  -> dict[str, bool | list[str]]
  check_narrator_compliance(md_text)  -> dict[str, bool | list[str]]
  check_amplified_compliance(md_text) -> dict[str, bool | list[str]]
  parse_som(md_text)                  -> tuple[float, int] | None
  check_translation_friendly(md_text) -> dict[str, bool | float | list[str]]
"""

from __future__ import annotations

import re

# ── Named thresholds (PLR2004 compliance) ─────────────────────────────────────

FK_GRADE_MAX: float = 13.5
CLAUSE_WORD_LIMIT: int = 55

# ── Banned-term patterns (from Inputs/STYLE_GUIDE.md) ────────────────────────

_BANNED: list[tuple[str, re.Pattern[str]]] = [
    ("Cell-ID", re.compile(r"Cell-ID:", re.IGNORECASE)),
    ("Per L\\d+", re.compile(r"Per\s+L\d+", re.IGNORECASE)),
    ("iter-N", re.compile(r"iter-\d+", re.IGNORECASE)),
    ("BT-ID", re.compile(r"\bBT-\d+\b")),
    ("PS-ID", re.compile(r"\bPS-\d+\b")),
    ("PA-ID", re.compile(r"\bPA-\d+\b")),
    ("US-ID", re.compile(r"\bUS-\d+\b")),
    ("TRIZ", re.compile(r"\bTRIZ\b")),
    ("JTBD", re.compile(r"\bJTBD\b")),
    ("Booker", re.compile(r"\bBooker\b")),
    ("McKee", re.compile(r"\bMcKee\b")),
    ("Boden", re.compile(r"\bBoden\b")),
    ("Csikszentmihalyi", re.compile(r"\bCsikszentmihalyi\b")),
    # Reagan and Pearson are kept phrase-qualified ONLY because they are real
    # comp-film surnames (Reagan-era films, Pearson Pictures) that appear
    # legitimately in investor markdown. Only the framework-specific phrases
    # (arc/plot/2016 for Reagan; archetype for Pearson) are banned.
    ("Reagan arc", re.compile(r"\bReagan\s+(arc|plot|2016)\b", re.IGNORECASE)),
    ("Pearson archetype", re.compile(r"\bPearson\s+archetype\b", re.IGNORECASE)),
    # Egri, Polti, Haidt, Mednick, Stanton: bare surnames are banned (no
    # legitimate comp-film usage) — mirror the existing bare Wundt/Simonton
    # entries below.
    ("Egri", re.compile(r"\bEgri\b")),
    ("Polti", re.compile(r"\bPolti\b")),
    ("Haidt", re.compile(r"\bHaidt\b")),
    ("Mednick", re.compile(r"\bMednick\b")),
    ("Wundt-Berlyne", re.compile(r"\bWundt-Berlyne\b")),
    ("Simonton type", re.compile(r"\bSimonton\s+type\b", re.IGNORECASE)),
    ("Wundt", re.compile(r"\bWundt\b")),
    ("Simonton", re.compile(r"\bSimonton\b")),
    ("Stanton", re.compile(r"\bStanton\b")),
    ("SIT Operator", re.compile(r"\bSIT\s+Operator\b", re.IGNORECASE)),
    ("Conceptual Blend", re.compile(r"\bConceptual\s+Blend\b", re.IGNORECASE)),
    ("Macro Resonance Weight", re.compile(r"\bMacro\s+Resonance\s+Weight\b", re.IGNORECASE)),
    ("Anti-slop", re.compile(r"\bAnti-slop\b", re.IGNORECASE)),
    ("ten-school", re.compile(r"\bten-school\b", re.IGNORECASE)),
    ("Lessons consulted", re.compile(r"\bLessons\s+consulted\b", re.IGNORECASE)),
    ("Working title", re.compile(r"\bWorking\s+title\b", re.IGNORECASE)),
    ("run-id", re.compile(r"\brun-id:", re.IGNORECASE)),
    ("Run ID", re.compile(r"\bRun\s+ID:", re.IGNORECASE)),
]

# ── Required V2 section patterns ─────────────────────────────────────────────

_REQ_H1: list[tuple[str, re.Pattern[str]]] = [
    (
        "Market & Audience",
        re.compile(r"^#\s+1\.\s+Market\s*[&and]+\s*Audience", re.MULTILINE | re.IGNORECASE),
    ),
    ("The Concept", re.compile(r"^#\s+2\.\s+The\s+Concept", re.MULTILINE | re.IGNORECASE)),
    ("Story", re.compile(r"^#\s+3\.\s+Story", re.MULTILINE | re.IGNORECASE)),
    ("Characters", re.compile(r"^#\s+4\.\s+Characters", re.MULTILINE | re.IGNORECASE)),
]

_REQ_H2: list[tuple[str, re.Pattern[str]]] = [
    ("Revenue Thesis", re.compile(r"^##\s+Revenue\s+Thesis", re.MULTILINE | re.IGNORECASE)),
    ("Why Now", re.compile(r"^##\s+Why\s+Now", re.MULTILINE | re.IGNORECASE)),
    ("Audience Sizing", re.compile(r"^##\s+Audience\s+Sizing", re.MULTILINE | re.IGNORECASE)),
    ("Synopsis", re.compile(r"^##\s+Synopsis", re.MULTILINE | re.IGNORECASE)),
    ("Protagonist", re.compile(r"^##\s+Protagonist", re.MULTILINE | re.IGNORECASE)),
]

# SOM line. Canonical form: **SOM (Year 1):** $NNN[M|B]
#
# NB-PARSE-SOM-WIDEN (Cycle 1 Session 6): also accept the non-canonical
# variants the drafter actually produces on real runs, caught by the NB.10
# first instrumented end-to-end. Specifically:
#
#   - Optional qualifier:     (Year 1) | (Y1) | (Year One) | absent
#   - Optional colon position: **SOM (Year 1):** $120M
#                              **SOM:** $120M
#                              **SOM: $1,540M**   ← colon + bold close after
#   - Comma-separated thousands: $1,540M  (drafter writes this naturally)
#   - Whitespace tolerant.
#
# Strip commas before float-conversion in :func:`parse_som`.
_SOM_RE: re.Pattern[str] = re.compile(
    r"\*\*SOM"
    r"(?:\s*\((?:Year\s*1|Y1|Year\s*One)\))?"  # optional qualifier
    r"\s*:?\s*"  # optional colon (may sit before or after bold close)
    r"(?:\*\*\s*)?"  # optional closing bold pair
    r"\$\s*"
    r"([\d,]+(?:\.\d+)?)"  # number with optional thousands separators
    r"\s*"
    r"([MB])"
    r"(?:\s*\*\*)?",  # optional trailing closing bold
    re.IGNORECASE,
)

# Canonical-form sentinel — surfaced by :func:`is_som_line_canonical` so the
# eval gate can emit a soft warning when SOM is found but not in canonical
# shape. The widened regex preserves backward compatibility; this constant
# lets downstream callers nudge the drafter toward the preferred form.
_SOM_CANONICAL_RE: re.Pattern[str] = re.compile(
    r"\*\*SOM\s*\(Year\s*1\):\*\*\s*\$(\d+(?:\.\d+)?)\s*([MB])",
    re.IGNORECASE,
)

# ── Translation idiom blocklist ───────────────────────────────────────────────

_IDIOMS: list[tuple[str, re.Pattern[str]]] = [
    ("home run", re.compile(r"\bhome\s+run\b", re.IGNORECASE)),
    ("Hail Mary", re.compile(r"\bHail\s+Mary\b", re.IGNORECASE)),
    ("move the goalposts", re.compile(r"\bmoving?\s+the\s+goalposts?\b", re.IGNORECASE)),
    ("ground zero", re.compile(r"\bground\s+zero\b", re.IGNORECASE)),
    ("in the trenches", re.compile(r"\bin\s+the\s+trenches\b", re.IGNORECASE)),
    ("flagship", re.compile(r"\bflagship\b", re.IGNORECASE)),
    ("hits the ground running", re.compile(r"\bhits?\s+the\s+ground\s+running\b", re.IGNORECASE)),
]


# ── Public functions ──────────────────────────────────────────────────────────


def strip_internal_ids(md_text: str) -> str:
    """Remove all banned internal IDs and framework labels from md_text."""
    result = md_text
    for _label, pattern in _BANNED:
        result = pattern.sub("", result)
    return result


def scan_for_internal_ids(md_text: str) -> list[dict[str, str | int]]:
    """Return list of {line, match, pattern} dicts for every banned term found."""
    findings: list[dict[str, str | int]] = []
    for line_no, line in enumerate(md_text.splitlines(), start=1):
        for label, pattern in _BANNED:
            m = pattern.search(line)
            if m:
                findings.append({"line": line_no, "match": m.group(0), "pattern": label})
    return findings


def enforce_v2_sections(md_text: str) -> list[str]:
    """Return issue strings for missing required V2 H1 sections; [] if valid."""
    return [
        f"Missing required H1 section: {name}"
        for name, pattern in _REQ_H1
        if not pattern.search(md_text)
    ]


def check_template_compliance(md_text: str) -> dict[str, bool | list[str]]:
    """Check full V2 template structure. Returns {passed, failures}."""
    failures: list[str] = [
        f"Missing H1 section: {name}" for name, pattern in _REQ_H1 if not pattern.search(md_text)
    ]
    failures += [
        f"Missing H2 section: {name}" for name, pattern in _REQ_H2 if not pattern.search(md_text)
    ]
    return {"passed": len(failures) == 0, "failures": failures}


# ── NARRATOR.md schema (concept-narrator.md:73-110) ───────────────────────────
#
# Canonical narrator header:
#   # [Title]            ← single H1 with the film title
#   #### Logline         ← H4 anchor, body on next line
#   [logline body]
#   #### Tagline         ← H4 anchor, body on next line in quotes
#   "[tagline body]"
#
# Pre-v4 narrator outputs (May 11 2026) emitted free prose with no logline
# anchor at all, making mechanical extraction (e.g. rating worksheets) impossible.
# Two May 12 outputs used a transitional `**LOGLINE**` bold-paragraph form,
# explicitly deprecated at concept-narrator.md:287. The two anchors below pin
# the canonical form so future drift is caught at write time.

_NARRATOR_H1_RE: re.Pattern[str] = re.compile(r"^#\s+\S", re.MULTILINE)
_NARRATOR_LOGLINE_RE: re.Pattern[str] = re.compile(r"^####\s+Logline\s*$", re.MULTILINE)
_NARRATOR_TAGLINE_RE: re.Pattern[str] = re.compile(r"^####\s+Tagline\s*$", re.MULTILINE)
_NARRATOR_LEGACY_LOGLINE_RE: re.Pattern[str] = re.compile(r"^\*\*LOGLINE\*\*\s*$", re.MULTILINE)
_NARRATOR_LEGACY_TAGLINE_RE: re.Pattern[str] = re.compile(r"^\*\*TAGLINE\*\*\s*$", re.MULTILINE)


def check_narrator_compliance(md_text: str) -> dict[str, bool | list[str]]:
    """Check NARRATOR.md canonical header schema. Returns {passed, failures}.

    Requires the three anchors that make a NARRATOR.md mechanically parseable
    by downstream tools (rating worksheets, leaderboard, investor summary):
      - exactly one H1 title line (``# [Title]``)
      - ``#### Logline`` H4 heading
      - ``#### Tagline`` H4 heading

    Detects and reports the legacy ``**LOGLINE**`` / ``**TAGLINE**`` bold-
    paragraph form (May 12 outputs) so the failure message is actionable.
    """
    failures: list[str] = []
    if not _NARRATOR_H1_RE.search(md_text):
        failures.append("Missing H1 title (line starting with `# `)")
    if not _NARRATOR_LOGLINE_RE.search(md_text):
        if _NARRATOR_LEGACY_LOGLINE_RE.search(md_text):
            failures.append("Uses legacy `**LOGLINE**` bold-paragraph; expected `#### Logline` H4")
        else:
            failures.append("Missing `#### Logline` H4 anchor")
    if not _NARRATOR_TAGLINE_RE.search(md_text):
        if _NARRATOR_LEGACY_TAGLINE_RE.search(md_text):
            failures.append("Uses legacy `**TAGLINE**` bold-paragraph; expected `#### Tagline` H4")
        else:
            failures.append("Missing `#### Tagline` H4 anchor")
    return {"passed": len(failures) == 0, "failures": failures}


# ── AMPLIFIED.md schema (audience_amplifier.py:render_trail) ─────────────────
#
# Canonical AMPLIFIED.md is now emitted by pipeline.audience_amplifier.render_trail
# (Python writer at lines 206-264). Every v4 run produces this exact form:
#
#   # Audience Amplification Trail — <slug>
#
#   | Metric | Value |
#   |--------|-------|
#   | Base audience | **NM** |
#   ...
#
#   ## Decision Trail
#   ## Vectors Applied (N)
#   ## Vectors Remaining — Untapped Upside (N)
#
# Two pre-canonical May 13 runs used a different agent-prompt-driven format
# ("# Audience Amplification — <Title>" with "## Starting State" / "## The
# Loop Result" sections from .claude/agents/audience-amplifier.md:127-152).
# Those are pinned in the test allow-list; this checker validates the
# canonical Python-emitted form.

_AMPLIFIED_H1_RE: re.Pattern[str] = re.compile(
    r"^#\s+Audience Amplification Trail\s+—\s+\S", re.MULTILINE
)
_AMPLIFIED_METRIC_TABLE_RE: re.Pattern[str] = re.compile(
    r"^\|\s*Metric\s*\|\s*Value\s*\|\s*$", re.MULTILINE
)
_AMPLIFIED_DECISION_TRAIL_RE: re.Pattern[str] = re.compile(
    r"^##\s+Decision Trail\s*$", re.MULTILINE
)
_AMPLIFIED_VECTORS_APPLIED_RE: re.Pattern[str] = re.compile(
    r"^##\s+Vectors Applied\s*\(\d+\)\s*$", re.MULTILINE
)
_AMPLIFIED_VECTORS_REMAINING_RE: re.Pattern[str] = re.compile(
    r"^##\s+Vectors Remaining\s+—\s+Untapped Upside\s*\(\d+\)\s*$", re.MULTILINE
)


def check_amplified_compliance(md_text: str) -> dict[str, bool | list[str]]:
    """Check AMPLIFIED.md canonical schema. Returns {passed, failures}.

    Pins the 5 anchors emitted by
    :func:`pipeline.audience_amplifier.render_trail` -- if the Python writer
    drifts, this gate catches it. The check is intentionally tight on the
    Python-emitted form (single source of truth) rather than the looser
    agent-prompt form -- the agent prompt at
    ``.claude/agents/audience-amplifier.md`` is now reference material,
    not the generator.
    """
    failures: list[str] = []
    if not _AMPLIFIED_H1_RE.search(md_text):
        failures.append("Missing canonical H1 (`# Audience Amplification Trail — <slug>`)")
    if not _AMPLIFIED_METRIC_TABLE_RE.search(md_text):
        failures.append("Missing metric table header (`| Metric | Value |`)")
    if not _AMPLIFIED_DECISION_TRAIL_RE.search(md_text):
        failures.append("Missing `## Decision Trail` H2")
    if not _AMPLIFIED_VECTORS_APPLIED_RE.search(md_text):
        failures.append("Missing `## Vectors Applied (N)` H2")
    if not _AMPLIFIED_VECTORS_REMAINING_RE.search(md_text):
        failures.append("Missing `## Vectors Remaining — Untapped Upside (N)` H2")
    return {"passed": len(failures) == 0, "failures": failures}


def parse_som(md_text: str) -> tuple[float, int] | None:
    """Parse the SOM line. Returns ``(millions_usd, line_no)`` or ``None``.

    Accepts both the canonical form (``**SOM (Year 1):** $120M``) and the
    widened forms documented at :data:`_SOM_RE` — including the
    comma-separated thousands and colon-inside-bold variants the drafter
    produces on real runs. Strips commas before float conversion.

    NB-PARSE-SOM-WIDEN (Cycle 1 Session 6): widened the regex so the eval
    gate stops rejecting investor-readable lines like
    ``**SOM: $1,540M**`` and ``**SOM:** $1540M``. Use
    :func:`is_som_line_canonical` if you need to know whether the line was
    in the preferred shape.
    """
    for line_no, line in enumerate(md_text.splitlines(), start=1):
        m = _SOM_RE.search(line)
        if m:
            raw = m.group(1).replace(",", "")
            value = float(raw)
            if m.group(2).upper() == "B":
                value *= 1000.0
            return (value, line_no)
    return None


def is_som_line_canonical(md_text: str) -> bool:
    """Return True iff at least one SOM line matches the canonical
    ``**SOM (Year 1):** $NNN[M|B]`` form.

    Returns False when SOM is parseable but only via the widened forms
    (no Year-1 qualifier, comma in number, colon inside bold, etc.) — so
    the eval gate can emit a soft "consider rewriting to canonical form"
    warning without rejecting the run.
    """
    return any(_SOM_CANONICAL_RE.search(line) for line in md_text.splitlines())


# ── Flesch-Kincaid grade (pure Python, no external dependencies) ──────────────


def _count_syllables(word: str) -> int:
    """Count syllables via vowel-group heuristic."""
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 0
    count = 0
    prev_vowel = False
    for ch in cleaned:
        is_vowel = ch in "aeiouy"
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if cleaned.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def _fk_grade(text: str) -> float:
    """Compute Flesch-Kincaid grade level (FK formula: 0.39*ASL + 11.8*ASW - 15.59)."""
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"\b[a-zA-Z]+\b", text)
    if not sentences or not words:
        return 0.0
    n_syl = sum(_count_syllables(w) for w in words)
    asl = len(words) / len(sentences)
    asw = n_syl / len(words)
    return 0.39 * asl + 11.8 * asw - 15.59


def check_translation_friendly(md_text: str) -> dict[str, bool | float | list[str]]:
    """Check FK grade, compound clauses, and translation-hostile idioms.

    Returns {passed: bool, fk_grade: float, warnings: list[str]}.
    """
    warnings: list[str] = []

    fk = _fk_grade(md_text)
    if fk > FK_GRADE_MAX:
        warnings.append(
            f"Flesch-Kincaid grade {fk:.1f} exceeds {FK_GRADE_MAX} (readability threshold)"
        )

    for segment in re.split(r"[.!?]", md_text):
        word_count = len(segment.split())
        if word_count > CLAUSE_WORD_LIMIT:
            preview = " ".join(segment.split()[:8])
            warnings.append(f"Compound clause too long ({word_count} words): '{preview}...'")

    for label, pattern in _IDIOMS:
        if pattern.search(md_text):
            warnings.append(f"Translation-hostile idiom: '{label}'")

    return {"passed": len(warnings) == 0, "fk_grade": round(fk, 2), "warnings": warnings}
