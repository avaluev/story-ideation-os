"""scripts/amplify_loop.py — the EN amplify loop's deterministic referee (Run B).

The "balanced adversarial loop" (plan: ``~/.claude/plans/recursive-yawning-sunrise.md``)
sources every external claim on a flagship concept card to a real deep-link +
verbatim quote, drives VERIFIED evidence density toward the campaign goal, and
emits an honest below-gate record when reality will not cooperate.

This module is the **deterministic referee** (ADR-0002: no LLM writes a verdict).
It does NOT — and *cannot* — launch the adversarial agents: the find/verify ring
lives in ``.claude/workflows/source-claims.mjs`` and only the Workflow runtime
can spawn it. The orchestrator therefore drives one round as::

    1.  python -m scripts.amplify_loop emit-manifest --concept N --scope full
            -> writes the round's claim manifest
    2.  Workflow({name: 'source-claims', args: <manifest>})    # the agent ring
            -> orchestrator writes the returned {judgments, ...} to a file
    3.  python -m scripts.amplify_loop apply --concept N --judgments j.json
            -> subject-bind -> render_inline ($-guard) -> assess + merge ->
               converge decision + checkpoint (+ below-gate when stalled)

Everything in steps 1 and 3 is pure Python: enumerate, filter, subject-bind,
render, score, decide. Reuse-only — it composes existing referee modules
(``enumerate``, ``render_inline``, ``assess``, ``verdict``/``scorecard`` via
``assess``, ``value_on_page``, ``loop_controller``, ``campaign_goal``) and adds
no new agent.

Honesty guards (plan §4):
  * **Subject-binding** — a ``comp_roi`` judgment is dropped unless the comp
    title (the claim's ``anchor``) appears in the finder's verbatim quote, so the
    sourced number is provably bound to the *right film* (co-located in the same
    <=25 words). This is *stronger* than the plan's "anchor anywhere on the page"
    because co-location rules out an off-scope number from a multi-title table.
  * **$-multiset frozen** — ``render_inline`` raises ``ValueError`` on any ``$``
    change (ADR-0011); the loop treats that as a hard per-concept abort.
  * **below-gate is first-class** — a concept that cannot honestly reach the
    density/link floor ships a ``_below_gate.json`` record naming its blockers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import quota  # noqa: E402
from pipeline.campaign_goal import CampaignGoal, load_campaign_goal  # noqa: E402
from pipeline.loop_controller import patch_budget  # noqa: E402
from pipeline.research.value_on_page import source_tier, subject_on_page  # noqa: E402
from pipeline.state import safe_write  # noqa: E402
from pipeline.veracity.assess import assess_card, merge_agent_judgments  # noqa: E402
from pipeline.veracity.enumerate import enumerate_claims  # noqa: E402
from pipeline.veracity.render_inline import render_inline  # noqa: E402
from pipeline.veracity.scorecard import CredibilityScore  # noqa: E402
from scripts.emit_card_claims import build_manifest  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_EN_DIR: Path = ROOT / "outputs" / "portfolio" / "amplified" / "EN"
DEFAULT_WORKLIST: Path = ROOT / "outputs" / "portfolio" / "amplified" / "_run4_worklist.json"
DEFAULT_OUT_DIR: Path = ROOT / "outputs" / "portfolio" / "amplified" / "_loop"
BELOW_GATE_PATH: Path = ROOT / "outputs" / "portfolio" / "amplified" / "_below_gate.json"

#: Count of deep links in a rendered card (matches build_amplified_reports).
_LINK_COUNT_RE = re.compile(r"\]\(https?://")
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
#: Deep paths that can describe only ONE film. On such a page an off-scope
#: number (the cheat subject-binding guards against) is structurally impossible:
#: the page is the film's own box-office record, so a value-verified judgment is
#: bound to the right film by the URL itself — even when the <=25-word quote is a
#: bare "Worldwide $X" line that omits the title. Multi-title pages (BOM
#: /year/, /chart/, /weekend/, a "top lifetime" list) are deliberately NOT here:
#: they still require the title co-located with the value.
_SINGLE_FILM_URL_RE = re.compile(
    r"(?i)(?:boxofficemojo\.com/(?:title/tt\d+|release/rl\w+)|the-numbers\.com/movie/)"
)
#: A source at tier 4/5 that survives binding is flagged for a human's eyes.
_LOW_TIER_FLOOR: int = 4
#: Conservative per-agent token estimate when the runtime gives no exact count.
_EST_TOKENS_IN_PER_AGENT: int = 40_000
_EST_TOKENS_OUT_PER_AGENT: int = 2_000

CONVERGE_DONE = "DONE"
CONVERGE_CONTINUE = "CONTINUE"
CONVERGE_STOP_BELOW_GATE = "STOP_BELOW_GATE"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("*", "")).strip().lower()


def is_single_film_page(url: str) -> bool:
    """True for a deep path that can only describe one film (BOM title/release,
    The Numbers movie). The URL itself binds the value to the film, so the
    title need not be co-located in the quote (off-scope binding is impossible).
    """
    return bool(url and _SINGLE_FILM_URL_RE.search(url))


def slug_from_stem(stem: str) -> str:
    """``"01_husbandry_EN"`` -> ``"01_husbandry"`` (worklist + display key)."""
    return re.sub(r"_(EN|RU)$", "", stem)


def title_of(md: str, fallback: str) -> str:
    m = _TITLE_RE.search(md)
    return m.group(1).strip() if m else fallback


def deep_link_count(md: str) -> int:
    """Number of inline deep links in *md* (the ``>=12`` campaign-floor metric)."""
    return len(_LINK_COUNT_RE.findall(md))


def load_judgments(path: Path) -> dict[str, dict[str, Any]]:
    """Load the source-claims workflow output; accept the full return or just judgments."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("judgments", raw)
    return inner if isinstance(inner, dict) else {}


def still_unsourced_ids(path: Path) -> list[str]:
    """Pull the ``still_unsourced`` claim_ids from a workflow-return file (empty if absent)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    su = raw.get("still_unsourced", [])
    out: list[str] = []
    if isinstance(su, list):
        for item in su:
            if isinstance(item, dict) and item.get("claim_id"):
                out.append(str(item["claim_id"]))
            elif isinstance(item, str):
                out.append(item)
    return out


def resolve_card(concept: str, en_dir: Path) -> Path:
    """Resolve a ``--concept`` (1-based index, slug, or stem) to a card path."""
    cards = sorted(en_dir.glob("[0-9]*_EN.md"))
    if concept.isdigit():
        idx = int(concept) - 1
        if not 0 <= idx < len(cards):
            raise SystemExit(f"--concept {concept} out of range (1..{len(cards)})")
        return cards[idx]
    want = concept.removesuffix(".md")
    for c in cards:
        if c.stem == want or slug_from_stem(c.stem) == want:
            return c
    raise SystemExit(f"no card matches --concept {concept!r} in {en_dir}")


# --------------------------------------------------------------------------- #
# Round manifest (plan §3 step 1)
# --------------------------------------------------------------------------- #


def _worklist_claim_ids(card_path: Path, worklist: dict[str, list[dict[str, str]]]) -> set[str]:
    """Map the slug's worklist snippets to enumerated claim_ids (type + text prefix)."""
    slug = slug_from_stem(card_path.stem)
    entries = worklist.get(slug, [])
    if not entries:
        return set()
    md = card_path.read_text(encoding="utf-8")
    claims = enumerate_claims(md, concept_id=card_path.stem, concept_title=title_of(md, slug))
    out: set[str] = set()
    for entry in entries:
        etype = entry.get("type", "")
        snippet = _norm(entry.get("snippet", ""))
        if not snippet:
            continue
        for c in claims:
            if c.claim_type != etype:
                continue
            ctext = _norm(c.text)
            if ctext.startswith(snippet) or snippet in ctext:
                out.add(c.claim_id)
                break
    return out


def build_round_manifest(
    card_path: Path,
    *,
    scope: str,
    worklist: dict[str, list[dict[str, str]]] | None = None,
    only_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build the round's claim set for the source-claims workflow.

    scope:
      * ``"full"``     — every external claim on the card (the only scope that
        can reach the >=80% VERIFIED-density DoD: the Run-3 links are structural
        SUPPORTED, not VERIFIED, until an agent confirms them live).
      * ``"worklist"`` — only the still-unlinked claims cached in
        ``_run4_worklist.json`` (cheap; lifts those to VERIFIED but leaves the
        already-linked majority at SUPPORTED).

    *only_ids* (subsequent rounds) further restricts to the still-unsourced set.
    """
    full = build_manifest(card_path.parent, only={card_path.stem})
    claims: list[dict[str, Any]] = list(full.get("claims", []))  # type: ignore[arg-type]

    if scope == "worklist":
        wl_ids = _worklist_claim_ids(card_path, worklist or {})
        claims = [c for c in claims if c["claim_id"] in wl_ids]
    elif scope != "full":
        raise ValueError(f"unknown scope {scope!r} (use 'full' or 'worklist')")

    if only_ids is not None:
        claims = [c for c in claims if c["claim_id"] in only_ids]

    return {
        "slug": slug_from_stem(card_path.stem),
        "stem": card_path.stem,
        "scope": scope,
        "source_dir": str(card_path.parent),
        "n_cards": 1,
        "claims": claims,
    }


# --------------------------------------------------------------------------- #
# Subject-binding (plan §3 step 3 / §4) — the off-scope deep-link guard
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BindResult:
    """Outcome of subject-binding one round's judgments."""

    bound: dict[str, dict[str, Any]]
    dropped: list[dict[str, str]] = field(default_factory=list)
    flagged: list[dict[str, str]] = field(default_factory=list)


def subject_bind(
    judgments: dict[str, dict[str, Any]],
    claims_by_id: dict[str, Any],
) -> BindResult:
    """Drop ``comp_roi`` judgments whose comp title is not co-located with the value.

    A ``comp_roi`` judgment survives when EITHER the source is a single-film deep
    path (BOM ``/title/`` or ``/release/``, The Numbers ``/movie/``) — where the
    URL alone binds the value to the film and off-scope is impossible — OR the
    claim's ``anchor`` (the comp film title) appears in the finder's verbatim
    quote, proving the number belongs to *this* film and not another row of a
    multi-title table (BOM ``/year/``, ``/chart/``, a "top lifetime" list). Other
    claim types pass through (their anchor *is* the sentence). Tier-4/5 survivors
    are flagged for human review (the anchor match can be incidental on a weak
    aggregator page).
    """
    bound: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, str]] = []
    flagged: list[dict[str, str]] = []
    for claim_id, j in judgments.items():
        claim = claims_by_id.get(claim_id)
        url = str(j.get("url", "") or "")
        quote = str(j.get("quote", "") or "")
        if (
            claim is not None
            and claim.claim_type == "comp_roi"
            and not is_single_film_page(url)
            and not subject_on_page(claim.anchor, quote)
        ):
            dropped.append(
                {
                    "claim_id": claim_id,
                    "anchor": getattr(claim, "anchor", ""),
                    "url": url,
                    "reason": "comp title not co-located with value",
                }
            )
            continue
        bound[claim_id] = j
        if url and source_tier(url) >= _LOW_TIER_FLOOR:
            flagged.append({"claim_id": claim_id, "url": url, "tier": str(source_tier(url))})
    return BindResult(bound=bound, dropped=dropped, flagged=flagged)


# --------------------------------------------------------------------------- #
# Score (plan §3 step 5) — assess + merge to surface true in-loop density
# --------------------------------------------------------------------------- #


def score_card(
    md: str, judgments: dict[str, dict[str, Any]], *, stem: str, title: str
) -> CredibilityScore:
    """Return the post-merge :class:`CredibilityScore` for *md*.

    ``assess_card`` gives the structural pass (deep-link claims -> SUPPORTED) and
    folds in the proof-bullet quotes; merging the workflow judgments
    (``agent_supports``) is what lifts a reachable SUPPORTED claim to VERIFIED,
    which is the only thing that raises ``claim_density_pct``. The merge stamps
    the scorecard ``mode="online"`` (the agents fetched the pages live).
    """
    assessments, _structural = assess_card(md, offline=True, concept_id=stem, concept_title=title)
    if not judgments:
        return _structural
    _merged, score = merge_agent_judgments(assessments, judgments)
    return score


# --------------------------------------------------------------------------- #
# Convergence (plan §3 step 6)
# --------------------------------------------------------------------------- #


def converge(
    score: CredibilityScore,
    deep_links: int,
    unsourced_history: list[int],
    round_idx: int,
    goal: CampaignGoal,
) -> tuple[str, str]:
    """Decide DONE / CONTINUE / STOP_BELOW_GATE for the round (deterministic).

    Loop metric is ``len(still_unsourced)`` (monotone -> 0), not the composite
    (noisy on a ~40-claim card). DONE needs the full DoD. STOP_BELOW_GATE fires
    on a 2-round stall in the unsourced count or at the L2 round cap.
    """
    dod = goal.definition_of_done
    density = score.claim_density_pct / 100.0
    grade_ok = score.grade == dod.mean_card_grade
    if (
        grade_ok
        and density >= dod.verified_density_min
        and deep_links >= dod.deep_links_per_report_min
        and score.fabricated_count <= dod.fabricated_count_max
    ):
        return CONVERGE_DONE, (
            f"grade {score.grade} · density {score.claim_density_pct}% · "
            f"{deep_links} links · {score.fabricated_count} fabricated"
        )

    cap = patch_budget("L2")
    if round_idx >= cap:
        return CONVERGE_STOP_BELOW_GATE, f"reached L2 round cap ({cap})"

    if len(unsourced_history) >= 3:  # noqa: PLR2004 — need this + 2 priors to see a 2-round stall
        last3 = unsourced_history[-3:]
        if last3[2] >= last3[1] >= last3[0]:
            return CONVERGE_STOP_BELOW_GATE, (
                f"still_unsourced did not fall for 2 rounds ({last3})"
            )

    return CONVERGE_CONTINUE, (
        f"grade {score.grade} · density {score.claim_density_pct}% · "
        f"{deep_links}/{dod.deep_links_per_report_min} links"
    )


# --------------------------------------------------------------------------- #
# Apply one round (plan §3 steps 3-8)
# --------------------------------------------------------------------------- #


def apply_round(
    card_path: Path,
    judgments: dict[str, dict[str, Any]],
    *,
    scope: str,
    worklist: dict[str, list[dict[str, str]]],
    round_idx: int,
    prior_unsourced: list[int],
    out_dir: Path,
) -> dict[str, Any]:
    """Subject-bind -> render ($-guard) -> checkpoint card -> assess+merge -> converge.

    Raises ``ValueError`` (propagated from ``render_inline``) when a ``$`` token
    would change — a hard per-concept abort, never a retry.
    """
    stem = card_path.stem
    slug = slug_from_stem(stem)
    md = card_path.read_text(encoding="utf-8")
    title = title_of(md, slug)

    claims = enumerate_claims(md, concept_id=stem, concept_title=title)
    claims_by_id = {c.claim_id: c for c in claims}

    bind = subject_bind(judgments, claims_by_id)

    new_md = render_inline(md, bind.bound, concept_id=stem)  # ValueError -> abort (ADR-0011)
    if new_md != md:
        safe_write(card_path, new_md)  # checkpoint the card each round (crash-safe)

    score = score_card(new_md, bind.bound, stem=stem, title=title)
    links = deep_link_count(new_md)

    round_manifest = build_round_manifest(card_path, scope=scope, worklist=worklist)
    manifest_ids = {c["claim_id"] for c in round_manifest["claims"]}
    unsourced = sorted(manifest_ids - set(bind.bound))
    history = [*prior_unsourced, len(unsourced)]

    goal = load_campaign_goal()
    decision, reason = converge(score, links, history, round_idx, goal)

    record = {
        "slug": slug,
        "stem": stem,
        "scope": scope,
        "round": round_idx,
        "decision": decision,
        "reason": reason,
        "grade": score.grade,
        "composite": score.composite,
        "claim_density_pct": score.claim_density_pct,
        "quote_coverage_pct": score.quote_coverage_pct,
        "deep_link_pct": score.deep_link_pct,
        "deep_links": links,
        "fabricated_count": score.fabricated_count,
        "n_external": score.n_external,
        "verdict_counts": score.verdict_counts,
        "bound_count": len(bind.bound),
        "dropped": bind.dropped,
        "flagged_low_tier": bind.flagged,
        "still_unsourced": unsourced,
        "unsourced_history": history,
        "mode": score.mode,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_write(out_dir / f"{slug}.loop.json", json.dumps(record, indent=2, ensure_ascii=False))

    if decision == CONVERGE_STOP_BELOW_GATE:
        write_below_gate(slug, record, claims_by_id, judgments)
    return record


def write_below_gate(
    slug: str,
    record: dict[str, Any],
    claims_by_id: dict[str, Any],
    judgments: dict[str, dict[str, Any]],
) -> None:
    """Append/update the honest below-gate ledger for a stalled concept (plan §4)."""
    BELOG = BELOW_GATE_PATH
    existing: dict[str, Any] = {}
    if BELOG.exists():
        try:
            existing = json.loads(BELOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    blockers: dict[str, str] = {}
    for cid in record.get("still_unsourced", []):
        claim = claims_by_id.get(cid)
        note = str(judgments.get(cid, {}).get("notes", "") or "")
        blockers[cid] = note or (
            f"{getattr(claim, 'claim_type', '?')}: {getattr(claim, 'text', '')[:80]}"
            if claim
            else "no source bound"
        )
    existing[slug] = {
        "rounds": record["round"],
        "grade": record["grade"],
        "density_pct": record["claim_density_pct"],
        "deep_links": record["deep_links"],
        "gate_met": False,
        "reason": record["reason"],
        "verdict_counts": record["verdict_counts"],
        "blockers": blockers,
    }
    safe_write(BELOG, json.dumps(existing, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Quota wiring (plan §3 step 7 / §5) — observability where the spend is
# --------------------------------------------------------------------------- #


def record_round_quota(
    accounting: dict[str, Any],
    *,
    run_id: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    """Record one round's agent burn to ``data/quota.jsonl`` (the mjs cannot).

    Pass measured *tokens_in*/*tokens_out* when the runtime reports them;
    otherwise a deliberately conservative per-agent estimate is used so the Opus
    gate never under-counts. Finders and verifiers are recorded against their
    routed tiers from ``accounting`` (``finder_model`` / ``refuter_model``).
    """
    finder_model = str(accounting.get("finder_model", "sonnet")).lower()
    refuter_model = str(accounting.get("refuter_model", "opus")).lower()
    find_agents = int(accounting.get("find_agents", 0) or 0)
    verify_agents = int(accounting.get("verify_agents", 0) or 0)

    def _tier(model: str) -> quota.ModelTier:
        return "opus" if "opus" in model else ("haiku" if "haiku" in model else "sonnet")

    if find_agents:
        quota.record(
            _tier(finder_model),
            tokens_in if tokens_in is not None else find_agents * _EST_TOKENS_IN_PER_AGENT,
            tokens_out if tokens_out is not None else find_agents * _EST_TOKENS_OUT_PER_AGENT,
            run_id,
            "other",
        )
    if verify_agents:
        quota.record(
            _tier(refuter_model),
            verify_agents * _EST_TOKENS_IN_PER_AGENT,
            verify_agents * _EST_TOKENS_OUT_PER_AGENT,
            run_id,
            "critic",
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _load_worklist(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _cmd_emit_manifest(args: argparse.Namespace) -> int:
    card = resolve_card(args.concept, Path(args.dir))
    worklist = _load_worklist(Path(args.worklist))
    only = set(still_unsourced_ids(Path(args.judgments))) if args.judgments else None
    manifest = build_round_manifest(card, scope=args.scope, worklist=worklist, only_ids=only)
    out = (
        Path(args.out)
        if args.out
        else (Path(args.dir).parent / "_loop" / f"{manifest['slug']}.manifest.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    safe_write(out, json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"{manifest['slug']}: {len(manifest['claims'])} claims (scope={args.scope}) -> {out}")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    card = resolve_card(args.concept, Path(args.dir))
    judgments = load_judgments(Path(args.judgments))
    worklist = _load_worklist(Path(args.worklist))
    record = apply_round(
        card,
        judgments,
        scope=args.scope,
        worklist=worklist,
        round_idx=args.round,
        prior_unsourced=[int(x) for x in args.prior_unsourced.split(",") if x.strip()],
        out_dir=Path(args.out_dir),
    )
    n_flagged = len(record["flagged_low_tier"])
    n_unsourced = len(record["still_unsourced"])
    print(
        f"{record['slug']} round {record['round']}: {record['decision']} — {record['reason']}\n"
        f"  bound={record['bound_count']} dropped={len(record['dropped'])} "
        f"flagged={n_flagged} still_unsourced={n_unsourced}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.amplify_loop", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--concept", required=True, help="1-based index, slug, or stem")
    common.add_argument("--dir", default=str(DEFAULT_EN_DIR))
    common.add_argument("--worklist", default=str(DEFAULT_WORKLIST))
    common.add_argument("--scope", default="full", choices=["full", "worklist"])

    em = sub.add_parser("emit-manifest", parents=[common], help="build the round's claim manifest")
    em.add_argument(
        "--judgments", default="", help="prior workflow return -> restrict to still_unsourced"
    )
    em.add_argument("--out", default="")
    em.set_defaults(func=_cmd_emit_manifest)

    ap = sub.add_parser("apply", parents=[common], help="subject-bind + render + score + converge")
    ap.add_argument("--judgments", required=True, help="source-claims workflow return JSON")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--prior-unsourced", default="", help="comma-separated prior unsourced counts")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.set_defaults(func=_cmd_apply)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
