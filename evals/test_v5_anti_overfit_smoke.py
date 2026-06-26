"""Stage E1 - v5.0 anti-overfit empirical smoke (ADR-0012 verification §4).

Runs ``generate_seed_via_evolve`` 10 times with the SAME theme/problem and
asserts that no single ``(axis, value_id)`` survivor pair exceeds 40%
frequency over the rolling 20-run window the v5 sampler observes.

This is the runtime evidence ADR-0012 was missing on acceptance day --
unit tests covered the math, but no one had exercised the 40% threshold
on the real engine + real corpus.  ADR-0012 v5.1 promotion decisions
(multi-generation evolution, NSGA-II, etc.) hinge on this number.

Scope notes (per the master plan and the v5 skeleton):

- ``pipeline.evolve.one_shot._record_axis_frequencies`` only logs
  *survivors*, not all candidates.  This eval therefore measures the
  survivor axis distribution, which is the right thing to assert for
  cross-run attractor lock-in.
- Marked ``@pytest.mark.slow`` per the v5 plan; gated by the
  ``RUN_V5_EVIDENCE=1`` env var so ``make eval`` stays fast.  Run
  explicitly with::

      RUN_V5_EVIDENCE=1 uv run pytest \\
          evals/test_v5_anti_overfit_smoke.py -v

- Artifacts (CSV summary) land in ``runs/v5-evidence-E1/anti_overfit.csv``
  for the FINDINGS.md companion doc.
"""

from __future__ import annotations

import csv
import os
import time
from collections import Counter
from pathlib import Path

import pytest

from pipeline import diversity
from pipeline.single_idea import generate_seed_via_evolve

THEME: str = "legibility, agency"
PROBLEM: str = "the cost of being legible to algorithms"
N_RUNS: int = 10
N_BASE: int = 16
TOP_K: int = 5
FREQ_THRESHOLD: float = 0.40

EVIDENCE_DIR: Path = Path(__file__).resolve().parents[1] / "runs" / "v5-evidence-E1"
CSV_PATH: Path = EVIDENCE_DIR / "anti_overfit.csv"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_V5_EVIDENCE") != "1",
    reason="Stage E1 evidence smoke; set RUN_V5_EVIDENCE=1 to run.",
)


@pytest.mark.slow
def test_anti_overfit_rolling_window_no_axis_exceeds_40pct(tmp_path: Path) -> None:
    """After 10 same-theme runs, no survivor (axis, value_id) > 40%."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    wall_clock_s: list[float] = []
    for i in range(N_RUNS):
        run_dir = tmp_path / f"run_{i:02d}"
        t0 = time.perf_counter()
        generate_seed_via_evolve(
            theme=THEME,
            problem=PROBLEM,
            run_dir=run_dir,
            n_base=N_BASE,
            top_k=TOP_K,
            use_llm_operators=False,
        )
        wall_clock_s.append(time.perf_counter() - t0)

    freq_table = diversity.load_frequency_table(
        window_runs=diversity.DEFAULT_WINDOW_RUNS,
    )
    total_samples = sum(freq_table.values())
    assert total_samples > 0, "frequency table empty after 10 runs"

    counter: Counter[tuple[str, str]] = Counter()
    for key, count in freq_table.items():
        counter[key] = count

    top20 = counter.most_common(20)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["axis", "value_id", "count", "pct_of_total"])
        for (axis, value_id), count in top20:
            pct = count / total_samples
            w.writerow([axis, value_id, count, f"{pct:.4f}"])
        w.writerow([])
        w.writerow(["__wall_clock_per_run_s", "", "", ""])
        for i, s in enumerate(wall_clock_s):
            w.writerow([f"run_{i:02d}", "", "", f"{s:.2f}"])

    max_key, max_count = counter.most_common(1)[0]
    max_pct = max_count / total_samples
    assert max_pct <= FREQ_THRESHOLD, (
        f"axis {max_key!r} reached {max_pct:.1%} survivor frequency "
        f"(> {FREQ_THRESHOLD:.0%}) after {N_RUNS} runs; "
        f"counts {dict(top20[:5])}; total samples {total_samples}"
    )
