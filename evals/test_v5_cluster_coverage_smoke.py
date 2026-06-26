"""Stage E1 - v5.0 cluster-coverage empirical smoke (ADR-0012 verification §5).

Runs one ``generate_seed_via_evolve`` with ``n_base=64``, ``top_k=10`` and
asserts the survivor slate covers ``>= 4 of 8`` thematic clusters
(``pipeline.compound_seed._CLUSTER_NAMES``).

This is the runtime evidence that ADR-0012's diversity-floor selector
(:func:`pipeline.select.diversity_select.select_top_k`) is doing its job
on real candidates -- not just on synthetic fixtures.

Scope notes:

- The selector's defaults already require ``cluster_floor=4`` (soft;
  never goes below operator-provided ``k``).  This eval confirms the
  scored population includes enough qualifying anchors to satisfy the
  floor end-to-end, not just structurally.
- Marked ``@pytest.mark.slow`` and gated by ``RUN_V5_EVIDENCE=1`` for
  the same reason as :mod:`evals.test_v5_anti_overfit_smoke`.
- Artifacts land in ``runs/v5-evidence-E1/cluster_coverage.csv`` for the
  FINDINGS.md companion doc.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from pipeline.compound_seed import _CLUSTER_NAMES
from pipeline.single_idea import generate_seed_via_evolve

THEME: str = "scarcity, ritual"
PROBLEM: str = "the cost of being the last person who remembers"
N_BASE: int = 64
TOP_K: int = 10
CLUSTER_FLOOR: int = 4

EVIDENCE_DIR: Path = Path(__file__).resolve().parents[1] / "runs" / "v5-evidence-E1"
CSV_PATH: Path = EVIDENCE_DIR / "cluster_coverage.csv"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_V5_EVIDENCE") != "1",
    reason="Stage E1 evidence smoke; set RUN_V5_EVIDENCE=1 to run.",
)


@pytest.mark.slow
def test_top10_covers_at_least_4_of_8_clusters(tmp_path: Path) -> None:
    """One n_base=64 run -> top-10 covers >= 4 of 8 thematic clusters."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "cluster_smoke"

    seed = generate_seed_via_evolve(
        theme=THEME,
        problem=PROBLEM,
        run_dir=run_dir,
        n_base=N_BASE,
        top_k=TOP_K,
        use_llm_operators=False,
    )

    evolve_run_id: str = str(seed["evolve_run_id"])
    winners_path = Path("runs") / evolve_run_id / "evolve" / "gen0" / "winners.json"
    assert winners_path.exists(), f"winners.json missing at {winners_path}"

    winners = json.loads(winners_path.read_text(encoding="utf-8"))
    assert isinstance(winners, list), "winners.json must be a JSON list"
    assert winners, "winners.json is empty"

    cluster_counts: Counter[str] = Counter()
    for w in winners:
        scores = w.get("candidate", {}).get("scores", {})
        cluster = scores.get("primary_cluster") or "<unknown>"
        cluster_counts[cluster] += 1

    distinct_clusters = sum(1 for k in cluster_counts if k in _CLUSTER_NAMES.values())

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster", "count", "is_canonical"])
        for cluster, count in cluster_counts.most_common():
            w.writerow([cluster, count, cluster in _CLUSTER_NAMES.values()])
        w.writerow([])
        w.writerow(["__top_k", TOP_K, "", ""])
        w.writerow(["__distinct_canonical_clusters", distinct_clusters, "", ""])
        w.writerow(["__evolve_run_id", evolve_run_id, "", ""])

    assert distinct_clusters >= CLUSTER_FLOOR, (
        f"top-{TOP_K} covers only {distinct_clusters} of 8 canonical clusters "
        f"(floor={CLUSTER_FLOOR}); distribution={dict(cluster_counts)}"
    )
