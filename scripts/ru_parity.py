"""scripts/ru_parity.py — deterministic EN/RU parity guard (Run A; RU-stage dep).

Pure Python. No LLM. No network. Compares a frozen English card against its
Russian translation on three multisets that MUST be identical, and surfaces
(advisory) readability warnings.

The three HARD parity checks (the Run-D stop gate — "0 parity mismatches"):
  1. url-multiset   — every markdown link target, with multiplicity.
  2. ``$``-multiset — every dollar token, via the SAME definition the ADR-0011
     render-time guard uses (``pipeline.veracity.render_inline._money_multiset``),
     so a translation that drops/alters a ``python_executed`` figure is caught.
  3. heading vector — count of ATX headings per level (``#``..``######``);
     catches a demoted ``##`` -> ``###`` that would break the EN/RU mirror.

Readability is REPORTED but NOT gated: ``check_translation_friendly``'s
Flesch-Kincaid grade uses an English syllable counter and is invalid for
Russian, so the FK number is advisory only. Idiom / long-clause warnings are
surfaced to drive the Run-D re-translate loop without failing the parity gate.

Usage:
    uv run python -m scripts.ru_parity <en.md> <ru.md>
    # exit 0 when the 3 hard checks pass, 1 when any mismatches, 2 on bad args.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pipeline.template_filter import check_translation_friendly
from pipeline.veracity.render_inline import _money_multiset  # reuse the ADR-0011 $-token def

_T = TypeVar("_T")

# ── Extractors ────────────────────────────────────────────────────────────────

#: Markdown inline link target: ``[label](https://host/path)``. The URL group
#: tolerates ONE level of balanced parens so Wikipedia film URLs survive intact —
#: ``Coco_(2017_film)`` would otherwise truncate at the inner ``)``.
_LINK_RE: re.Pattern[str] = re.compile(r"\[[^\]]*\]\(((?:[^()\s]|\([^)\s]*\))+)\)")
#: ATX heading line: 1-6 ``#`` followed by a space.
_HEADING_RE: re.Pattern[str] = re.compile(r"^(#{1,6})\s", re.MULTILINE)
#: FK warnings begin with this token (advisory for Russian; never gated).
_FK_WARNING_PREFIX: str = "Flesch-Kincaid"


def url_multiset(text: str) -> Counter[str]:
    """Return a multiset (Counter) of every markdown link URL in *text*."""
    return Counter(_LINK_RE.findall(text))


def money_multiset(text: str) -> Counter[str]:
    """Return a multiset of every ``$`` token, via render_inline's definition."""
    return Counter(_money_multiset(text))


def heading_vector(text: str) -> Counter[int]:
    """Return a Counter mapping heading level (1-6) -> count of headings."""
    return Counter(len(h) for h in _HEADING_RE.findall(text))


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParityResult:
    """Outcome of :func:`check_parity`.

    ``passed`` reflects ONLY the three hard multiset checks (the Run-D gate).
    ``readability_warnings`` and ``fk_grade_advisory`` are informational and
    drive the re-translate loop without failing the gate.
    """

    url_ok: bool
    money_ok: bool
    heading_ok: bool
    mismatches: list[str] = field(default_factory=list)
    readability_warnings: list[str] = field(default_factory=list)
    fk_grade_advisory: float = 0.0

    @property
    def passed(self) -> bool:
        """True iff all three hard parity checks pass."""
        return self.url_ok and self.money_ok and self.heading_ok


def _diff_multiset(label: str, en: Counter[_T], ru: Counter[_T]) -> list[str]:
    """Return human-readable mismatch lines for two multisets (empty when equal)."""
    if en == ru:
        return []
    missing = en - ru  # present in EN, dropped from RU
    extra = ru - en  # present in RU, absent from EN
    out: list[str] = [
        f"{label}: RU is missing {n}x {item!r}"
        for item, n in sorted(missing.items(), key=lambda kv: str(kv[0]))
    ]
    out += [
        f"{label}: RU has {n}x unexpected {item!r}"
        for item, n in sorted(extra.items(), key=lambda kv: str(kv[0]))
    ]
    return out


def check_parity(en_md: str, ru_md: str) -> ParityResult:
    """Compare *en_md* (source of truth) against *ru_md* on the 3 hard checks."""
    en_urls, ru_urls = url_multiset(en_md), url_multiset(ru_md)
    en_money, ru_money = money_multiset(en_md), money_multiset(ru_md)
    en_head, ru_head = heading_vector(en_md), heading_vector(ru_md)

    mismatches: list[str] = []
    mismatches += _diff_multiset("url", en_urls, ru_urls)
    mismatches += _diff_multiset("dollar", en_money, ru_money)
    mismatches += _diff_multiset("heading", en_head, ru_head)

    friendly = check_translation_friendly(ru_md)
    warnings_val = friendly.get("warnings", [])
    all_warnings = [str(w) for w in warnings_val] if isinstance(warnings_val, list) else []
    readability = [w for w in all_warnings if not w.startswith(_FK_WARNING_PREFIX)]
    fk_val = friendly.get("fk_grade", 0.0)
    fk = float(fk_val) if isinstance(fk_val, (int, float)) else 0.0

    return ParityResult(
        url_ok=(en_urls == ru_urls),
        money_ok=(en_money == ru_money),
        heading_ok=(en_head == ru_head),
        mismatches=mismatches,
        readability_warnings=readability,
        fk_grade_advisory=fk,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m scripts.ru_parity <en.md> <ru.md>``. Exit 0 on parity."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:  # noqa: PLR2004 — exactly the (en, ru) pair
        print("usage: python -m scripts.ru_parity <en.md> <ru.md>", file=sys.stderr)
        return 2
    en_md = Path(args[0]).read_text(encoding="utf-8")
    ru_md = Path(args[1]).read_text(encoding="utf-8")
    result = check_parity(en_md, ru_md)
    status = "PASS" if result.passed else "FAIL"
    print(
        f"[{status}] url_ok={result.url_ok} "
        f"money_ok={result.money_ok} heading_ok={result.heading_ok}"
    )
    for m in result.mismatches:
        print(f"  MISMATCH {m}")
    if result.readability_warnings:
        print(f"  readability (advisory): {len(result.readability_warnings)} warning(s)")
        for w in result.readability_warnings:
            print(f"    - {w}")
    print(f"  fk_grade (advisory; English counter — NOT valid for RU): {result.fk_grade_advisory}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
