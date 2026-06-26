"""scripts.crystallize.explore — generate N compound seeds, cluster, render.

Operator CLI:

    uv run python -m scripts.crystallize.explore \\
        --problem "AI surveillance vs human autonomy" \\
        --themes  "Korean fertility crisis,climate cascade" \\
        --n       1000

Writes:
    runs/<board_id>/crystal_board.json
    runs/<board_id>/crystal_board.html

Prints a terminal top-10 + cluster summary so the operator gets immediate
feedback without opening the browser.

Offline-resilient by design — CompoundSeedEngine has template fallback for
the LLM-polished premise field, and the corpus + checklist are local JSON.
No network calls.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from pipeline.compound_seed import CompoundSeedEngine
from pipeline.crystallize.board import (
    Candidate,
    CrystalBoard,
    build_cluster_summaries,
    make_board_id,
)
from pipeline.crystallize.cluster import cluster_candidates
from pipeline.crystallize.comps import match_comps
from pipeline.crystallize.corpus import FilmsCorpus
from pipeline.crystallize.greatness import (
    Checklist,
    greatness_subscores,
    load_checklist,
)
from pipeline.crystallize.html_export import render_html
from pipeline.crystallize.score import crystallization_score
from pipeline.state import safe_write

_log = logging.getLogger(__name__)

_DEFAULT_N: int = 1000
_DEFAULT_MAX_ATTEMPTS: int = 20
_RUNS_DIR: Path = Path("runs")
_RNG_MASK: int = 0xFFFFFFFF


def _derive_rng_seeds(board_id: str, n: int) -> list[int]:
    """Derive N distinct deterministic rng seeds from the board id.

    Hashing (board_id, i) lets the operator reproduce the exact set of
    candidates from just the board_id, while keeping every candidate's
    seed independent.
    """
    seeds: list[int] = []
    for i in range(n):
        h = sha256(f"{board_id}|{i}".encode()).hexdigest()
        seeds.append(int(h[:8], 16) & _RNG_MASK)
    return seeds


def _generate_one(args: tuple[int, int, list[str], int]) -> dict[str, Any]:
    """Worker function — runs in a subprocess.

    Returns the CompoundSeedResult as a dict (already serialisable), plus
    the rng_seed and candidate_id so the orchestrator can assemble the board.
    """
    idx, rng_seed, themes, max_attempts = args
    engine = CompoundSeedEngine(rng_seed=rng_seed)
    result = engine.generate(themes=themes, max_attempts=max_attempts)
    return {
        "candidate_id": f"c{idx:04d}",
        "rng_seed": rng_seed,
        "compound_seed": result.to_dict(),
    }


def _build_candidates(
    raw_results: list[dict[str, Any]],
    corpus: FilmsCorpus,
    checklist: Checklist,
) -> list[Candidate]:
    """Score + comp-match + greatness-rate each raw result into a Candidate."""
    out: list[Candidate] = []
    for raw in raw_results:
        compound_seed = raw["compound_seed"]
        scores = compound_seed.get("scores") or {}
        match = match_comps(compound_seed, corpus, k=5)
        cs = crystallization_score(scores, derivative_distance=match["derivative_distance"])
        grt = greatness_subscores(
            compound_seed,
            derivative_distance=match["derivative_distance"],
            checklist=checklist,
        )
        out.append(
            Candidate(
                candidate_id=raw["candidate_id"],
                rng_seed=raw["rng_seed"],
                compound_seed=compound_seed,
                score_vector=scores,
                crystallization_score=cs,
                cluster_id=0,  # filled by cluster_candidates below
                cluster_name="",  # filled by cluster_candidates below
                comps=match["comps"],
                derivative_distance=match["derivative_distance"],
                corpus_grounded_audience_overlap_M=match["corpus_grounded_audience_overlap_M"],
                query_genres=match["query_genres"],
                greatness=grt,
            )
        )
    return out


def _terminal_summary(board: CrystalBoard, top_n: int = 10) -> None:
    """Print a compact summary to stdout for the operator."""
    print()
    print("=" * 80)
    print(f"🎲 Crystal Board — board_id={board.board_id}")
    print(f"   Problem:   {board.problem}")
    themes_str = " | ".join(board.themes) if board.themes else "—"
    print(f"   Themes:    {themes_str}")
    print(
        f"   Sampled:   {board.n_generated}/{board.n_requested} candidates "
        f"in {board.runtime_seconds:.1f}s"
    )
    print(f"   Corpus:    {board.corpus_size} films")
    print(f"   Checklist: v{board.checklist_version}")
    print()
    print(f"Top-{top_n} by crystallization_score:")
    print("  rank  cand   cluster         cryst  grtn   C001   deriv  div    som    closest comps")
    print("  " + "─" * 96)
    sorted_cands = sorted(board.candidates, key=lambda c: c.crystallization_score, reverse=True)
    for i, c in enumerate(sorted_cands[:top_n], start=1):
        grt = c.greatness
        scores = c.score_vector
        comp_titles = ", ".join(
            f"{f.get('title', '?')} ({(f.get('roi') or 0):.1f}x)"
            if f.get("roi") is not None
            else f"{f.get('title', '?')}"
            for f in c.comps[:3]
        )
        som_M = float(scores.get("som_floor_M") or 0)
        div = float(scores.get("divisiveness_score") or 0)
        print(
            f"  {i:>4}  {c.candidate_id:<6} {c.cluster_name:<14}  "
            f"{c.crystallization_score:.3f}  "
            f"{grt.get('weighted_total', 0):.2f}   "
            f"{grt.get('C001', 0):.2f}   "
            f"{c.derivative_distance:.2f}   "
            f"{div:>4.1f}   "
            f"${som_M:>5.0f}M  "
            f"{comp_titles}"
        )
    print()
    print("Clusters (k=8):")
    for s in board.clusters:
        roi = (
            f"corpus_roi {s.avg_corpus_roi:.2f}x"
            if s.avg_corpus_roi is not None
            else "corpus_roi —"
        )
        print(
            f"  {s.cluster_name:<14}  {s.n_members:>4} candidates  "
            f"cryst {s.avg_crystallization_score:.2f}  {roi}"
        )
    kill_count = sum(1 for c in board.candidates if c.greatness.get("kill_switch_failed"))
    if kill_count > 0:
        cnt: Counter[str] = Counter()
        for c in board.candidates:
            for k in c.greatness.get("kill_switch_failed") or []:
                cnt[k] += 1
        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(cnt.items()))
        print()
        print(f"Kill-switch failures: {kill_count} candidates flagged ({breakdown})")
    print()
    print(f"HTML crystal board: runs/{board.board_id}/crystal_board.html")
    print("=" * 80)


def explore(
    problem: str,
    themes: list[str],
    n: int = _DEFAULT_N,
    output_root: Path = _RUNS_DIR,
    workers: int | None = None,
    write_html_file: bool = True,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> CrystalBoard:
    """Core entry point — also called by tests + future callers."""
    start = time.monotonic()
    board_id = make_board_id(problem)
    rng_seeds = _derive_rng_seeds(board_id, n)

    if workers is None:
        workers = min(8, os.cpu_count() or 4)

    _log.info(
        "explore: board_id=%s n=%d workers=%d themes=%s",
        board_id,
        n,
        workers,
        themes,
    )

    corpus = FilmsCorpus.load()
    checklist = load_checklist()

    # Parallel candidate generation. CompoundSeedEngine has no shared state
    # so independent subprocesses are safe.
    raw_results: list[dict[str, Any]] = []
    args_list = [(i, rng_seeds[i], themes, max_attempts) for i in range(n)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_generate_one, a): a for a in args_list}
        for fut in as_completed(futures):
            try:
                raw_results.append(fut.result())
            except Exception as exc:
                _log.warning("explore: candidate failed (%s); skipping", exc)
    raw_results.sort(key=lambda r: r["candidate_id"])

    candidates = _build_candidates(raw_results, corpus, checklist)

    # Cluster on score-vector dicts.
    score_dicts = [c.score_vector for c in candidates]
    cluster_result = cluster_candidates(score_dicts, k=8)
    for c, cid, cname in zip(
        candidates,
        cluster_result["cluster_ids"],
        cluster_result["cluster_names"],
        strict=False,
    ):
        c.cluster_id = cid
        c.cluster_name = cname

    cluster_id_to_name = {
        i: name
        for i, name in enumerate(
            [
                "institutional",
                "emotional",
                "technology",
                "identity",
                "nature",
                "economic",
                "temporal",
                "civilizational",
            ]
        )
    }
    summaries = build_cluster_summaries(
        candidates, cluster_result["cluster_sizes"], cluster_id_to_name
    )

    runtime = time.monotonic() - start
    board = CrystalBoard(
        board_id=board_id,
        problem=problem,
        themes=themes,
        n_requested=n,
        n_generated=len(candidates),
        generated_at=datetime.now(UTC).isoformat(),
        runtime_seconds=runtime,
        candidates=candidates,
        clusters=summaries,
        cluster_collapse=cluster_result["cluster_collapse"],
        corpus_size=len(corpus),
        checklist_version=checklist.version,
    )

    out_dir = output_root / board_id
    out_dir.mkdir(parents=True, exist_ok=True)
    board.write(out_dir / "crystal_board.json")
    if write_html_file:
        safe_write(out_dir / "crystal_board.html", render_html(board))

    return board


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate N compound seeds, cluster them, match each to the "
            "294-film corpus, and render a Crystal Board (JSON + HTML)."
        )
    )
    parser.add_argument("--problem", required=True, help="The operator's problem statement.")
    parser.add_argument(
        "--themes",
        required=True,
        help="Comma-separated themes that bias the engine.",
    )
    parser.add_argument("--n", type=int, default=_DEFAULT_N, help="Number of candidates.")
    parser.add_argument("--output-root", type=Path, default=_RUNS_DIR, help="Root for runs/<id>/.")
    parser.add_argument(
        "--workers", type=int, default=None, help="Process pool size (default = min(8, cpu_count))."
    )
    parser.add_argument(
        "--no-html", action="store_true", help="Skip the HTML render (faster smoke tests)."
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=_DEFAULT_MAX_ATTEMPTS,
        help="Per-candidate engine attempt cap.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show INFO-level logs from the engine."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    themes = [t.strip() for t in str(args.themes).split(",") if t.strip()]
    board = explore(
        problem=args.problem,
        themes=themes,
        n=args.n,
        output_root=args.output_root,
        workers=args.workers,
        write_html_file=not args.no_html,
        max_attempts=args.max_attempts,
    )
    _terminal_summary(board)
    return 0


if __name__ == "__main__":
    sys.exit(main())
