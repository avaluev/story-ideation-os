"""V4A-004 Stage 3 - v3.1 vs v4 pipeline comparison harness.

Reads BOTH v3.1 production outputs and v4 alternative outputs (READ-ONLY)
and emits a side-by-side metric report under
`outputs/comparisons/v3-vs-v4-<run_id>.md`.

This is the only module allowed to read both partitions in a single
invocation per `docs/v4_isolation.md` "Comparison Harness" section.

Metrics compared:
  - score distribution (mean, median, stddev, p10, p90, min, max)
  - readiness pass-rate (concept count with PASS / total)
  - cinema-school floor pass-rate (rows passing >=7/10 schools)
  - logline word-count distribution (target: 25-35 words)
  - audience-floor pass rate (>=50M)
  - cost per concept (v3 OpenRouter $; v4 subscription $0)

Usage::

    uv run python scripts/compare_pipelines.py \\
        --v3-manifest data/runs/v3.1-pathc-a4/<run>/manifest.jsonl \\
        --v3-briefs out/concepts/v3.1-pathc-a4 \\
        --v4-manifest data/runs/v4-genius-cc/<run>/manifest.jsonl \\
        --v4-briefs out/concepts/v4-genius-cc \\
        --out outputs/comparisons/v3-vs-v4-<run_id>.md

Exit codes:
    0 - report written successfully
    2 - at least one input path missing
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIN_SAMPLE_PER_SIDE = 20  # below this the comparison is noise
LOGLINE_TARGET_MIN = 25
LOGLINE_TARGET_MAX = 35
SCHOOL_FLOOR = 7  # 7/10 schools must pass
AUDIENCE_FLOOR = 50_000_000
PASS_RATE_PARITY_PP = 5.0  # +/- 5 percentage points = parity band

LOGLINE_HEADER_RE = re.compile(
    r"^## High-Concept Logline\s*\n+(.+?)(?=\n## |\Z)", re.DOTALL | re.MULTILINE
)
SCHOOL_TABLE_RE = re.compile(
    r"^## Cinema-School Floor\s*\n.*?(?=\n## |\Z)", re.DOTALL | re.MULTILINE
)
TRUE_ROW_RE = re.compile(r"\|\s*\w[\w\s-]*\|\s*true\s*\|", re.IGNORECASE)
# v3.1 simplified format: single row "seven_school_floor_met | True". When the
# 10-row table is absent we fall back to this boolean sentinel = SCHOOL_FLOOR.
V3_SEVEN_SCHOOL_FLOOR_RE = re.compile(r"seven_school_floor_met\s*\|\s*(true|false)", re.IGNORECASE)
AUDIENCE_SIZE_RE = re.compile(r"Estimated audience:\s*([\d,]+)", re.IGNORECASE)
SCORE_LITERAL_RE = re.compile(r"\*\*\[?(\d+)/100\]?\*\*")


@dataclass(frozen=True)
class ConceptMetrics:
    concept_id: str
    score: float | None
    readiness: str | None
    cost_usd: float | None
    logline_word_count: int | None
    schools_passed: int | None
    audience_size: int | None


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _logline_word_count(brief_text: str) -> int | None:
    m = LOGLINE_HEADER_RE.search(brief_text)
    if not m:
        return None
    body = m.group(1).strip()
    return len(body.split())


def _schools_passed(brief_text: str) -> int | None:
    """Extract schools-passed count from the Cinema-School Floor section.

    v3 schema (priority): 1-row simplified table
      `| seven_school_floor_met | True |`. The boolean maps to SCHOOL_FLOOR (=7)
      when True or 0 when False. Detected first because the v3 row would also
      match the generic TRUE_ROW_RE and produce a misleading count of 1.
    v4 schema (fallback): 10-row table (School | Passes); count truthy rows.
    None: neither pattern matched.
    """
    m = SCHOOL_TABLE_RE.search(brief_text)
    if not m:
        return None
    section = m.group(0)
    v3 = V3_SEVEN_SCHOOL_FLOOR_RE.search(section)
    if v3:
        return SCHOOL_FLOOR if v3.group(1).lower() == "true" else 0
    truthy_rows = TRUE_ROW_RE.findall(section)
    return len(truthy_rows) if truthy_rows else None


def _audience_size(brief_text: str) -> int | None:
    m = AUDIENCE_SIZE_RE.search(brief_text)
    return int(m.group(1).replace(",", "")) if m else None


def _score_from_brief(brief_text: str) -> float | None:
    m = SCORE_LITERAL_RE.search(brief_text)
    return float(m.group(1)) if m else None


def _read_brief(briefs_dir: Path, concept_id: str) -> str:
    path = briefs_dir / f"{concept_id}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _build_metrics(manifest: list[dict[str, Any]], briefs_dir: Path) -> list[ConceptMetrics]:
    out: list[ConceptMetrics] = []
    for row in manifest:
        cid = str(row.get("concept_id", ""))
        brief_text = _read_brief(briefs_dir, cid)
        score: float | None
        if isinstance(row.get("score"), int | float):
            score = float(row["score"])
        else:
            score = _score_from_brief(brief_text)
        readiness = row.get("readiness")
        cost_usd: float | None = None
        if isinstance(row.get("cost_usd"), int | float):
            cost_usd = float(row["cost_usd"])
        out.append(
            ConceptMetrics(
                concept_id=cid,
                score=score,
                readiness=str(readiness) if readiness else None,
                cost_usd=cost_usd,
                logline_word_count=_logline_word_count(brief_text),
                schools_passed=_schools_passed(brief_text),
                audience_size=_audience_size(brief_text),
            )
        )
    return out


# -- Aggregation helpers ------------------------------------------------------


def _safe_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "n": 0,
            "mean": 0.0,
            "median": 0.0,
            "stddev": 0.0,
            "p10": 0.0,
            "p90": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    sv = sorted(values)
    n = len(sv)
    return {
        "n": n,
        "mean": statistics.fmean(sv),
        "median": statistics.median(sv),
        "stddev": statistics.pstdev(sv) if n > 1 else 0.0,
        "p10": sv[max(0, int(0.10 * (n - 1)))],
        "p90": sv[min(n - 1, int(0.90 * (n - 1)))],
        "min": sv[0],
        "max": sv[-1],
    }


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return 100.0 * numerator / denominator


def _row(label: str, *cells: str) -> str:
    return "| " + " | ".join((label, *cells)) + " |"


def _build_score_table(s3: dict[str, float], s4: dict[str, float]) -> str:
    lines = [
        "| Stat | v3.1 | v4 | delta (v4 - v3) |",
        "|---|---|---|---|",
    ]
    keys = ("n", "mean", "median", "stddev", "p10", "p90", "min", "max")
    for k in keys:
        v3v = s3[k]
        v4v = s4[k]
        delta = v4v - v3v
        if k == "n":
            lines.append(_row(k, f"{v3v:.0f}", f"{v4v:.0f}", f"{delta:+.0f}"))
        else:
            lines.append(_row(k, f"{v3v:.2f}", f"{v4v:.2f}", f"{delta:+.2f}"))
    return "\n".join(lines)


def _build_passrate_table(
    v3: list[ConceptMetrics],
    v4: list[ConceptMetrics],
    v3_logline: list[int],
    v4_logline: list[int],
    v3_schools: list[int],
    v4_schools: list[int],
    v3_aud: list[int],
    v4_aud: list[int],
) -> str:
    v3_pass = sum(1 for m in v3 if m.readiness and m.readiness.upper() == "PASS")
    v4_pass = sum(1 for m in v4 if m.readiness and m.readiness.upper() == "PASS")
    v3_school_floor = sum(1 for s in v3_schools if s >= SCHOOL_FLOOR)
    v4_school_floor = sum(1 for s in v4_schools if s >= SCHOOL_FLOOR)
    v3_logline_ok = sum(1 for w in v3_logline if LOGLINE_TARGET_MIN <= w <= LOGLINE_TARGET_MAX)
    v4_logline_ok = sum(1 for w in v4_logline if LOGLINE_TARGET_MIN <= w <= LOGLINE_TARGET_MAX)
    v3_aud_floor = sum(1 for a in v3_aud if a >= AUDIENCE_FLOOR)
    v4_aud_floor = sum(1 for a in v4_aud if a >= AUDIENCE_FLOOR)

    def cell(num: int, den: int) -> str:
        return f"{num}/{den} ({_pct(num, den):.1f}%)"

    def delta(num1: int, den1: int, num2: int, den2: int) -> str:
        return f"{_pct(num2, den2) - _pct(num1, den1):+.1f}pp"

    lines = [
        "| Gate | v3.1 | v4 | delta |",
        "|---|---|---|---|",
        _row(
            "Readiness == PASS",
            cell(v3_pass, len(v3)),
            cell(v4_pass, len(v4)),
            delta(v3_pass, len(v3), v4_pass, len(v4)),
        ),
        _row(
            f">={SCHOOL_FLOOR}/10 cinema-school floor",
            cell(v3_school_floor, len(v3_schools)),
            cell(v4_school_floor, len(v4_schools)),
            delta(v3_school_floor, len(v3_schools), v4_school_floor, len(v4_schools)),
        ),
        _row(
            f"Logline {LOGLINE_TARGET_MIN}-{LOGLINE_TARGET_MAX} words",
            cell(v3_logline_ok, len(v3_logline)),
            cell(v4_logline_ok, len(v4_logline)),
            delta(v3_logline_ok, len(v3_logline), v4_logline_ok, len(v4_logline)),
        ),
        _row(
            f"Audience >={AUDIENCE_FLOOR // 1_000_000}M",
            cell(v3_aud_floor, len(v3_aud)),
            cell(v4_aud_floor, len(v4_aud)),
            delta(v3_aud_floor, len(v3_aud), v4_aud_floor, len(v4_aud)),
        ),
    ]
    return "\n".join(lines)


def _build_report(v3: list[ConceptMetrics], v4: list[ConceptMetrics]) -> str:
    v3_scores = [float(m.score) for m in v3 if m.score is not None]
    v4_scores = [float(m.score) for m in v4 if m.score is not None]
    v3_logline = [m.logline_word_count for m in v3 if m.logline_word_count is not None]
    v4_logline = [m.logline_word_count for m in v4 if m.logline_word_count is not None]
    v3_schools = [m.schools_passed for m in v3 if m.schools_passed is not None]
    v4_schools = [m.schools_passed for m in v4 if m.schools_passed is not None]
    v3_aud = [m.audience_size for m in v3 if m.audience_size is not None]
    v4_aud = [m.audience_size for m in v4 if m.audience_size is not None]

    v3_pass = sum(1 for m in v3 if m.readiness and m.readiness.upper() == "PASS")
    v4_pass = sum(1 for m in v4 if m.readiness and m.readiness.upper() == "PASS")
    v3_cost = sum(m.cost_usd for m in v3 if m.cost_usd is not None)
    v4_cost = sum(m.cost_usd for m in v4 if m.cost_usd is not None)

    s3 = _safe_stats(v3_scores)
    s4 = _safe_stats(v4_scores)

    sample_table = (
        "| Pipeline | Total | Scored | Logline | Schools | Audience |\n"
        "|---|---|---|---|---|---|\n"
        f"| v3.1 (main) | {len(v3)} | {len(v3_scores)} | {len(v3_logline)} "
        f"| {len(v3_schools)} | {len(v3_aud)} |\n"
        f"| v4 (alt) | {len(v4)} | {len(v4_scores)} | {len(v4_logline)} "
        f"| {len(v4_schools)} | {len(v4_aud)} |\n"
    )

    score_table = _build_score_table(s3, s4)
    passrate_table = _build_passrate_table(
        v3, v4, v3_logline, v4_logline, v3_schools, v4_schools, v3_aud, v4_aud
    )

    cost_table = (
        "| Pipeline | Total cost | Per-concept avg | Backend |\n"
        "|---|---|---|---|\n"
        f"| v3.1 (main) | ${v3_cost:.2f} | ${v3_cost / max(1, len(v3)):.4f} "
        f"| OpenRouter (Sonnet 4.6) |\n"
        f"| v4 (alt) | ${v4_cost:.2f} | ${v4_cost / max(1, len(v4)):.4f} "
        f"| Pure-CC subscription (no $ external) |\n"
        f"| **Savings** | **${v3_cost - v4_cost:.2f}** "
        f"| **${(v3_cost - v4_cost) / max(1, len(v3)):.4f}** | -- |\n"
    )

    verdict = _verdict(s3, s4, v3_pass, len(v3), v4_pass, len(v4))

    return (
        "# v3.1 vs v4 - Pipeline Parity Report\n\n"
        "> Generated by `scripts/compare_pipelines.py` (V4A-004 Stage 3).\n"
        "> v3.1 production flow vs v4 alternative flow (Pure-CC subscription).\n"
        "> See `docs/v4_isolation.md` for the path partition contract.\n\n"
        "## Sample sizes\n\n"
        f"{sample_table}\n"
        "## Score distribution (0-100, higher better)\n\n"
        f"{score_table}\n\n"
        "## Pass rates\n\n"
        f"{passrate_table}\n\n"
        "## Cost (USD, lower better)\n\n"
        f"{cost_table}\n"
        "## Verdict\n\n"
        f"{verdict}\n\n"
        "## Provenance\n\n"
        f"- v3 manifest: counted {len(v3)} concept rows\n"
        f"- v4 manifest: counted {len(v4)} concept rows\n"
        "- Tool: `scripts/compare_pipelines.py` (V4A-004 Stage 3)\n"
        "- Plan: `~/.claude/plans/i-need-you-to-crystalline-tower.md`\n"
    )


def _verdict(
    s3: dict[str, float],
    s4: dict[str, float],
    v3_pass: int,
    v3_n: int,
    v4_pass: int,
    v4_n: int,
) -> str:
    if s3["n"] < MIN_SAMPLE_PER_SIDE or s4["n"] < MIN_SAMPLE_PER_SIDE:
        return (
            f"INSUFFICIENT SAMPLE: comparison needs >={MIN_SAMPLE_PER_SIDE} scored "
            f"rows per side; v3 has {s3['n']:.0f}, v4 has {s4['n']:.0f}. "
            f"Run more concepts before drawing conclusions."
        )
    delta_mean = s4["mean"] - s3["mean"]
    delta_pass = _pct(v4_pass, v4_n) - _pct(v3_pass, v3_n)
    if abs(delta_mean) <= s3["stddev"] and abs(delta_pass) <= PASS_RATE_PARITY_PP:
        return (
            "PARITY: v4 mean score within 1 stddev of v3, pass-rate within "
            f"{PASS_RATE_PARITY_PP:.0f}pp. v4 (subscription, no $) is "
            "statistically interchangeable with v3.1 (OpenRouter, paid)."
        )
    if delta_mean > s3["stddev"] or delta_pass > PASS_RATE_PARITY_PP:
        return (
            "v4 OUTPERFORMS: distribution shifts above v3 baseline. "
            "Investigate which forger features drove the gain before "
            "declaring victory."
        )
    return (
        "v4 UNDERPERFORMS: distribution shifts below v3 baseline. "
        "Investigate forger prompt drift, persona/operator misuse, or "
        "audience-pool selection bias before promoting v4."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v3.1 vs v4 pipeline comparison")
    parser.add_argument("--v3-manifest", required=True, type=Path)
    parser.add_argument("--v3-briefs", required=True, type=Path)
    parser.add_argument("--v4-manifest", required=True, type=Path)
    parser.add_argument("--v4-briefs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    for p in (args.v3_manifest, args.v3_briefs, args.v4_manifest, args.v4_briefs):
        if not p.exists():
            print(f"FAIL: input path missing: {p}", file=sys.stderr)
            return 2

    v3 = _build_metrics(_load_manifest(args.v3_manifest), args.v3_briefs)
    v4 = _build_metrics(_load_manifest(args.v4_manifest), args.v4_briefs)

    if len(v3) < MIN_SAMPLE_PER_SIDE or len(v4) < MIN_SAMPLE_PER_SIDE:
        print(
            f"WARN: sample size below {MIN_SAMPLE_PER_SIDE} per side "
            f"(v3={len(v3)}, v4={len(v4)}); report flags insufficient sample.",
            file=sys.stderr,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_build_report(v3, v4), encoding="utf-8")
    print(f"OK: wrote {args.out} (v3={len(v3)}, v4={len(v4)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
