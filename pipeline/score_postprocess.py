"""pipeline/score_postprocess.py — replace [SCORE_PLACEHOLDER] in A4 markdowns.

The Phase 6 formatter agent (.claude/agents/phase-6-formatter.md) is forbidden
from doing arithmetic per ADR-0002. It writes the literal string
`**[SCORE_PLACEHOLDER]/100**` into Section 12 of every A4 concept it produces.

This module is the deterministic Python step that:
1. Reads each `out/concepts/*.md`.
2. Looks up the matching `concept_id` in `data/05_critiques.jsonl`.
3. Replaces `[SCORE_PLACEHOLDER]` with the actual `overall_score.final` value.

Invoked from the /anomaly skill orchestrator AFTER phase-6-formatter completes:

    uv run python -c 'from pipeline.score_postprocess import apply; apply()'

Returns the count of files updated.

ADR-0002 compliance: this module does NOT compute scores — it only reads scores
already produced by `pipeline/scoring.py` and persisted to `05_critiques.jsonl`.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path("out/concepts")
CRITIQUES_PATH = Path("data/05_critiques.jsonl")
PLACEHOLDER = "[SCORE_PLACEHOLDER]"


def _load_scores_by_concept_id(critiques_path: Path = CRITIQUES_PATH) -> dict[str, float]:
    """Load `overall_score.final` per concept_id from the critiques JSONL."""
    scores: dict[str, float] = {}
    if not critiques_path.exists():
        return scores
    for line in critiques_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row: dict[str, object] = json.loads(line)
        concept_id = str(row.get("concept_id", "") or "")
        score_dict_raw: object = row.get("overall_score", {})
        if not isinstance(score_dict_raw, dict):
            continue
        final_raw: object = score_dict_raw.get("final")  # type: ignore[reportUnknownMemberType]
        if final_raw is None or not concept_id:
            continue
        try:
            scores[concept_id] = float(str(final_raw))  # type: ignore[reportUnknownArgumentType]
        except (TypeError, ValueError):
            continue
    return scores


def apply(out_dir: Path = OUT_DIR, critiques_path: Path = CRITIQUES_PATH) -> int:
    """Replace [SCORE_PLACEHOLDER] in every out/concepts/*.md with the real score.

    Args:
        out_dir: directory containing A4 markdown files.
        critiques_path: data/05_critiques.jsonl with `overall_score.final` per row.

    Returns:
        Count of files where placeholder was successfully replaced.
    """
    scores = _load_scores_by_concept_id(critiques_path)
    if not out_dir.exists():
        return 0

    updated = 0
    for md_path in out_dir.glob("*.md"):
        concept_id = md_path.stem
        score = scores.get(concept_id)
        if score is None:
            continue
        content = md_path.read_text(encoding="utf-8")
        if PLACEHOLDER not in content:
            continue
        # Render the score as integer if exact, else 1 decimal.
        score_str = str(int(score)) if score == int(score) else f"{score:.1f}"
        new_content = content.replace(PLACEHOLDER, score_str)
        md_path.write_text(new_content, encoding="utf-8")
        updated += 1
    return updated


def main() -> None:
    n = apply()
    print(f"score_postprocess: replaced [SCORE_PLACEHOLDER] in {n} file(s).")


if __name__ == "__main__":
    main()
