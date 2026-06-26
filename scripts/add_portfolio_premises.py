"""scripts/add_portfolio_premises.py — add live 302.ai premises to the winners.

Run AFTER :mod:`scripts.build_portfolio` (which selects offline). Reads the
portfolio JSON, generates a 150-250 word premise for each winning concept's exact
seed axes via the shared 302.ai-primary chat client, and writes the premises back
in place (``concept["engine_premise"]``). Touches only the final winners (K*6
calls), never the selection batch — so it is cheap and offline-selection stays
fast and free.

Best-effort: if 302.ai is unreachable (two consecutive failures), it aborts
early and leaves premises blank — the downstream enrichment grounds on the seed
axes regardless, so a missing premise never blocks the deliverable.

    uv run python -m scripts.add_portfolio_premises [PORTFOLIO.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.build_portfolio import _premise_via_302ai

#: Abort the live step after this many consecutive provider failures.
_MAX_CONSECUTIVE_FAILURES = 2


def _latest_portfolio_json() -> Path:
    pointer = Path("runs/portfolio/latest.json")
    if pointer.exists():
        p = json.loads(pointer.read_text(encoding="utf-8")).get("path")
        if p and Path(p).exists():
            return Path(p)
    candidates = sorted(Path("runs/portfolio").glob("*-portfolio.json"))
    if not candidates:
        raise SystemExit("no portfolio JSON in runs/portfolio/ — run build_portfolio first")
    return candidates[-1]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_portfolio_json()
    data = json.loads(path.read_text(encoding="utf-8"))
    concepts = data.get("concepts", [])
    print(f"adding 302.ai premises to {len(concepts)} concepts in {path.name}")

    consecutive_failures = 0
    ok = 0
    for c in concepts:
        premise = _premise_via_302ai(c)
        c["engine_premise"] = premise
        if premise:
            ok += 1
            consecutive_failures = 0
            print(f"  {c.get('id'):22s} ok  {len(premise)} chars")
        else:
            consecutive_failures += 1
            print(f"  {c.get('id'):22s} —   (failure {consecutive_failures})")
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                print(
                    "  302.ai appears unreachable — aborting premise step (enrichment "
                    "grounds on seed axes regardless)."
                )
                break

    data["premise_302"] = ok > 0
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"done: {ok}/{len(concepts)} premises written -> {path}")


if __name__ == "__main__":
    main()
