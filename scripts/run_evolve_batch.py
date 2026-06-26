"""scripts/run_evolve_batch.py — batch-run the improved evolve pipeline and report
comp-diversity + SOM uplift on freshly generated ideas.

Exercises every uplift shipped 2026-05-29: R2 (goal.json weights), R4 (tentpole
ProjectionContext), R5 (log-scaled SOM facet), R6a (widened comp genre vocab),
R3 (diversity penalty on the 6 previously-bypassed axes). The numbers reported
are the live before/after evidence for the operator.

Run OFFLINE so premise prose uses the deterministic template fallback and no
302.ai / OpenRouter credit is spent — every metric here (SOM, comps, score) is
genre + revenue based and does not need the premise LLM::

    TAO_AI_API_KEY= TAO_AI_PRIMARY= OPENROUTER_API_KEY= OPENROUTER_KEY_PAID= \
        uv run python scripts/run_evolve_batch.py [N_RUNS]
"""

from __future__ import annotations

import statistics
import sys
from collections import Counter
from pathlib import Path

from pipeline.compound_seed import CompoundSeedEngine
from pipeline.crystallize.comps import match_comps
from pipeline.crystallize.corpus import FilmsCorpus
from pipeline.evolve.one_shot import explore_and_select
from pipeline.operators.mental_models import VariablePools

_THEME_SETS: list[tuple[str, list[str]]] = [
    ("institutional failure", ["power", "accountability", "truth"]),
    ("technological disruption", ["identity", "control", "legacy"]),
    ("ecological collapse", ["survival", "myth", "sacrifice"]),
    ("economic inequality", ["greed", "family", "justice"]),
    ("memory and identity", ["love", "loss", "becoming"]),
    ("frontier exploration", ["wonder", "hubris", "discovery"]),
    ("generational reckoning", ["inheritance", "betrayal", "forgiveness"]),
    ("artificial consciousness", ["soul", "fear", "creation"]),
    ("mythic enchantment", ["magic", "destiny", "courage"]),
    ("political upheaval", ["loyalty", "revolution", "cost"]),
    ("medical frontier", ["mortality", "ethics", "hope"]),
    ("cosmic mystery", ["awe", "isolation", "meaning"]),
]

_BASE_SEED = 20260529
_USD_M = 1_000_000.0


def _comp1(candidate_dict: dict, corpus: FilmsCorpus) -> str:
    res = match_comps(candidate_dict, corpus, k=1)
    comps = res.get("comps") or []
    return str(comps[0]["title"]) if comps else "-"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    corpus = FilmsCorpus.load()
    pools = VariablePools.from_engine_defaults()
    runs_root = Path("runs")

    soms: list[float] = []
    scores: list[float] = []
    comp1s: list[str] = []

    print(f"corpus: {len(corpus)} films | running {n} generations (offline, template premise)\n")
    for i in range(n):
        problem, themes = _THEME_SETS[i % len(_THEME_SETS)]
        engine = CompoundSeedEngine(rng_seed=_BASE_SEED + i)
        result = explore_and_select(
            problem=problem,
            themes=themes,
            engine=engine,
            pools=pools,
            corpus=corpus,
            n_base=24,
            top_k=5,
            use_llm_operators=False,
            runs_root=runs_root,
        )
        for sc in result.top_k:
            soms.append(float(sc.revenue.som_y1_usd or 0.0))
            scores.append(float(sc.crystallization_score))
            comp1s.append(_comp1(sc.candidate.to_dict(), corpus))
        top = result.top_k[0]
        top_comp = _comp1(top.candidate.to_dict(), corpus)[:30]
        top_som = (top.revenue.som_y1_usd or 0) / _USD_M
        print(
            f"  run {i + 1:2d}/{n}  {problem[:26]:26s}  "
            f"top SOM=${top_som:>6,.0f}M  "
            f"score={top.crystallization_score:.3f}  comp1={top_comp}"
        )

    print("\n" + "=" * 70)
    print(f"SURVIVORS: {len(soms)}")
    if soms:
        big = sum(1 for s in soms if s >= 500 * _USD_M)
        print(
            f"SOM        median ${statistics.median(soms) / _USD_M:,.0f}M   "
            f"max ${max(soms) / _USD_M:,.0f}M   >=$500M: {big}/{len(soms)}"
        )
    if scores:
        print(
            f"score      median {statistics.median(scores):.3f}   "
            f"max {max(scores):.3f}   spread {max(scores) - min(scores):.3f}"
        )
    if comp1s:
        c = Counter(comp1s)
        title, count = c.most_common(1)[0]
        print(
            f"comp1      {len(c)} distinct / {len(comp1s)}   "
            f"top comp '{title}' = {count / len(comp1s) * 100:.0f}%"
        )
    print("=" * 70)
    print("baseline (pre-uplift audit): median SOM $211M, comp1 A.I.(2001) = 26%")


if __name__ == "__main__":
    main()
