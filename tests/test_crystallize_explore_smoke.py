"""End-to-end smoke test for scripts/crystallize/explore.py.

Generates 16 candidates against a fixed problem + themes, then verifies:
- crystal_board.json has 16 candidates split across 8 clusters
- every candidate has comps (list) and greatness (dict) fields
- crystal_board.html exists, is non-empty, contains the SVG scatter +
  at least one C001 substring (proves greatness rendering wired through)

The test is OFFLINE-RESILIENT — CompoundSeedEngine's template fallback +
seed_moa's python-judge fallback + FilmsCorpus's empty-corpus graceful
degrade all kick in when the network or LLM credits are unavailable.

Skipped if sklearn or the films corpus is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Skip the whole module if sklearn is not importable in this env.
# This MUST run before importing scripts.crystallize.explore, which
# transitively imports sklearn via pipeline.crystallize.cluster.
pytest.importorskip("sklearn")

from scripts.crystallize.explore import explore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_ROOT = _REPO_ROOT / "Inputs" / "10May" / "knowledge" / "corpus" / "deep_data" / "films"
_CHECKLIST = _REPO_ROOT / "Inputs" / "GeniusFilm" / "GREATNESS_CHECKLIST.json"

_assets_present = pytest.mark.skipif(
    not (_CORPUS_ROOT.exists() and _CHECKLIST.exists()),
    reason="Films corpus or GREATNESS_CHECKLIST.json missing",
)


@_assets_present
def test_explore_n16_writes_board_and_html(tmp_path: Path) -> None:

    board = explore(
        problem="smoke test problem statement",
        themes=["theme alpha", "theme beta"],
        n=16,
        output_root=tmp_path,
        workers=2,
        write_html_file=True,
        max_attempts=10,
    )

    # --- board structure ---
    assert board.n_generated == 16
    assert board.n_requested == 16
    assert len(board.candidates) == 16
    assert len(board.clusters) == 8
    assert sum(c.n_members for c in board.clusters) == 16

    # --- candidate fields ---
    for c in board.candidates:
        assert c.candidate_id.startswith("c")
        assert isinstance(c.comps, list)
        assert isinstance(c.greatness, dict)
        assert 0.0 <= c.crystallization_score <= 1.0
        assert 0.0 <= c.derivative_distance <= 1.0
        # Every candidate must have all 7 C-keys
        for k in ("C001", "C002", "C003", "C004", "C005", "C006", "C007"):
            assert k in c.greatness, f"{c.candidate_id} missing {k}"
            assert 0.0 <= c.greatness[k] <= 1.0
        assert "weighted_total" in c.greatness

    # --- JSON file written ---
    out_dir = tmp_path / board.board_id
    json_path = out_dir / "crystal_board.json"
    assert json_path.exists()
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    assert raw["n_generated"] == 16
    assert len(raw["candidates"]) == 16
    assert raw["corpus_size"] > 0

    # --- HTML file written + contains scatter + greatness markers ---
    html_path = out_dir / "crystal_board.html"
    assert html_path.exists()
    html_text = html_path.read_text(encoding="utf-8")
    assert len(html_text) > 5000, f"HTML suspiciously short: {len(html_text)} chars"
    assert '<svg id="scatter"' in html_text
    # C001 ID must leak through into the rendered HTML (proves the rubric
    # wiring reached the template, not just the JSON).
    assert "C001" in html_text


@_assets_present
def test_explore_rng_seeds_are_unique(tmp_path: Path) -> None:
    """16 candidates must have 16 distinct rng_seeds — regression guard
    against parallel-worker bugs that could share seeds."""

    board = explore(
        problem="rng uniqueness test",
        themes=["theme x"],
        n=16,
        output_root=tmp_path,
        workers=2,
        write_html_file=False,
        max_attempts=10,
    )
    rng_seeds = [c.rng_seed for c in board.candidates]
    assert len(set(rng_seeds)) == len(rng_seeds)


@_assets_present
def test_explore_no_html_flag_skips_html(tmp_path: Path) -> None:

    board = explore(
        problem="no html test",
        themes=["theme y"],
        n=8,
        output_root=tmp_path,
        workers=2,
        write_html_file=False,
        max_attempts=10,
    )
    out_dir = tmp_path / board.board_id
    assert (out_dir / "crystal_board.json").exists()
    assert not (out_dir / "crystal_board.html").exists()
