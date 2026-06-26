"""CLI for the veracity subsystem.

Usage::

    uv run python -m pipeline.veracity outputs/portfolio/portfolio_enriched.json
    uv run python -m pipeline.veracity runs/<id>/<slug>-NARRATOR.md --online
    uv run python -m pipeline.veracity <input> --out outputs/veracity --online

Writes ``<stem>.veracity.json`` (full per-claim assessments + scorecard) and
``<stem>.CREDIBILITY.md`` (human report). Offline by default — pass ``--online``
to probe every cited URL. Exit code 1 if any claim is contradicted/fabricated.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

from pipeline.veracity.assess import (
    assess_card,
    assess_markdown,
    assess_portfolio,
    concept_meta,
    merge_agent_judgments,
)
from pipeline.veracity.report import render_credibility_md
from pipeline.veracity.scorecard import (
    MODE_ONLINE,
    ClaimAssessment,
    CredibilityScore,
    grade_meets,
    score_by_concept,
)

logger = logging.getLogger("pipeline.veracity")

#: Max concept names to list in a gate-fail message before truncating.
_GATE_FAIL_LIST_LIMIT: int = 8


def _write_outputs(
    stem: Path,
    assessments: list[ClaimAssessment],
    score: CredibilityScore,
    *,
    title: str,
) -> tuple[Path, Path]:
    json_path = stem.with_suffix(".veracity.json")
    md_path = stem.with_name(stem.stem + ".CREDIBILITY.md")
    payload = {
        "title": title,
        "scorecard": score.to_dict(),
        "assessments": [a.to_dict() for a in assessments],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(
        render_credibility_md(assessments, score, title=f"{title} — Credibility Scorecard"),
        encoding="utf-8",
    )
    return json_path, md_path


_GATE_EXIT_FAIL: int = 3


def _enforce_grade_gate(
    assessments: list[ClaimAssessment],
    score: CredibilityScore,
    *,
    minimum: str,
) -> int:
    """Publication gate (G1): 0 if the slate is publishable at ``minimum``, else
    :data:`_GATE_EXIT_FAIL`.

    Three independent conditions, each a way the old ``gate-publish`` could ship
    an unverified slate:

      1. the run is ONLINE (an offline scorecard reflects citation *form*, not
         confirmed reachability -- see ``scorecard.MODE_OFFLINE``);
      2. every concept reaches ``minimum`` (one weak card cannot hide behind a
         healthy mean);
      3. zero fabricated claims.
    """
    failures: list[str] = []
    if score.mode != MODE_ONLINE:
        failures.append(
            f"run is {score.mode.upper()} -- a grade gate requires --online "
            "(offline reflects citation form, not reachability)"
        )
    if score.fabricated_count:
        failures.append(f"{score.fabricated_count} fabricated claim(s)")
    per_concept = score_by_concept(assessments)
    below = sorted(k for k, s in per_concept.items() if not grade_meets(s.grade, minimum))
    if below:
        extra = "…" if len(below) > _GATE_FAIL_LIST_LIMIT else ""
        shown = ", ".join(below[:_GATE_FAIL_LIST_LIMIT]) + extra
        failures.append(f"{len(below)} concept(s) below grade {minimum}: {shown}")
    if failures:
        logger.error("GATE FAIL (--assert-grade %s): %s", minimum, "; ".join(failures))
        return _GATE_EXIT_FAIL
    logger.info(
        "GATE PASS (--assert-grade %s): %d concept(s) all >= %s, online, 0 fabricated.",
        minimum,
        len(per_concept),
        minimum,
    )
    return 0


def _enforce_density_gate(score: CredibilityScore, *, floor: float) -> int:
    """Evidence-density publication gate: 0 iff VERIFIED/external >= ``floor``
    ONLINE with zero fabrications, else :data:`_GATE_EXIT_FAIL`.

    Like the grade gate, an offline/structural pass has confirmed nothing, so it
    fails outright — a citation that was never re-fetched cannot be VERIFIED.
    """
    if score.mode != MODE_ONLINE:
        logger.error("GATE FAIL (--assert-density): run is %s, requires --online", score.mode)
        return _GATE_EXIT_FAIL
    if score.fabricated_count:
        logger.error("GATE FAIL (--assert-density): %d fabricated claim(s)", score.fabricated_count)
        return _GATE_EXIT_FAIL
    if score.claim_density_pct / 100.0 < floor:
        logger.error(
            "GATE FAIL (--assert-density): %.1f%% verified < %.1f%% required",
            score.claim_density_pct,
            floor * 100,
        )
        return _GATE_EXIT_FAIL
    logger.info(
        "GATE PASS (--assert-density): %.1f%% verified >= %.1f%%",
        score.claim_density_pct,
        floor * 100,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="pipeline.veracity")
    parser.add_argument("input", help="enriched-portfolio .json OR a concept .md")
    parser.add_argument("--online", action="store_true", help="probe cited URLs over the network")
    parser.add_argument("--out", default="", help="output directory (default: alongside input)")
    parser.add_argument(
        "--judgments",
        default="",
        help="path to a veracity-amplify workflow judgments JSON; folds agent "
        "confirmations/refutations into the verdicts and re-scores",
    )
    parser.add_argument(
        "--assert-grade",
        default="",
        choices=["A", "B", "C", "D", "F"],
        help="publication gate: exit non-zero unless the run is ONLINE, every "
        "concept reaches this grade, and zero claims are fabricated. 'make "
        "gate-publish' does NOT prove this; this flag does.",
    )
    parser.add_argument(
        "--card",
        action="store_true",
        help="treat a .md input as a rendered concept card: use the section-aware "
        "enumerator (every external claim) so deep-link density is honest, not the "
        "link-harvester's tautological ~100%%",
    )
    parser.add_argument(
        "--assert-density",
        type=float,
        default=-1.0,
        help="publication gate: exit non-zero unless evidence density "
        "(VERIFIED / external) >= FRACTION, ONLINE, with zero fabrications",
    )
    args = parser.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        logger.error("input not found: %s", src)
        return 2

    offline = not args.online
    title = src.stem
    meta = {}
    if src.suffix.lower() == ".json":
        data = json.loads(src.read_text(encoding="utf-8"))
        assessments, score = assess_portfolio(data, offline=offline)
        meta = concept_meta(data)
    elif args.card:
        md = src.read_text(encoding="utf-8")
        assessments, score = assess_card(
            md, offline=offline, concept_id=src.stem, concept_title=src.stem
        )
    else:
        md = src.read_text(encoding="utf-8")
        assessments, score = assess_markdown(md, offline=offline, concept_id=src.stem)

    # Fold in agent judgments from a veracity-amplify run, if provided.
    if args.judgments:
        jpath = Path(args.judgments)
        raw = json.loads(jpath.read_text(encoding="utf-8"))
        judgments: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict):
            raw_d = cast("dict[str, Any]", raw)
            inner = raw_d.get("judgments", raw_d)
            if isinstance(inner, dict):
                judgments = cast("dict[str, dict[str, Any]]", inner)
        assessments, score = merge_agent_judgments(assessments, judgments, meta)
        title = f"{title} (amplified)"

    out_dir = Path(args.out) if args.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / src.stem
    json_path, md_path = _write_outputs(stem, assessments, score, title=title)

    logger.info(
        "Credibility %s/100 (Grade %s) — %d claims, %d fabricated. %s mode.",
        score.composite,
        score.grade,
        score.n_total,
        score.fabricated_count,
        "OFFLINE" if offline else "ONLINE",
    )
    logger.info("→ %s", json_path)
    logger.info("→ %s", md_path)

    if args.assert_grade:
        gate_rc = _enforce_grade_gate(assessments, score, minimum=args.assert_grade)
        if gate_rc != 0:
            return gate_rc

    if args.assert_density >= 0:
        dens_rc = _enforce_density_gate(score, floor=args.assert_density)
        if dens_rc != 0:
            return dens_rc

    return 1 if score.fabricated_count else 0


if __name__ == "__main__":
    sys.exit(main())
