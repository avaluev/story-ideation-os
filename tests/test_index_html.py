"""tests/test_index_html.py — unit tests for pipeline/index_html.py (PIPE-13).

Tests:
  test_index_html_generates_table     — regenerate_index produces HTML with concept IDs
  test_index_html_has_score_column    — HTML contains table headers and score value
"""

from __future__ import annotations

from pathlib import Path

import pytest

pipeline_index = pytest.importorskip("pipeline.index_html")


def test_index_html_generates_table(tmp_path: Path) -> None:
    """regenerate_index produces index.html containing both concept IDs (PIPE-13)."""
    out_dir = tmp_path / "concepts"
    out_dir.mkdir()
    (out_dir / "concept-001.md").write_text(
        "---\nconcept_id: concept-001\ntitle: Test Concept\nfinal_score: 96\n---\nBody text.\n"
    )
    (out_dir / "concept-002.md").write_text(
        "---\nconcept_id: concept-002\ntitle: Second Concept\nfinal_score: 87\n---\nBody text.\n"
    )
    index_path = tmp_path / "index.html"
    pipeline_index.regenerate_index(out_dir, index_path)
    html = index_path.read_text()
    assert "concept-001" in html
    assert "concept-002" in html
    assert "<table" in html.lower()


def test_index_html_has_score_column(tmp_path: Path) -> None:
    """Generated HTML contains table headers and the concept score (PIPE-13)."""
    out_dir = tmp_path / "concepts"
    out_dir.mkdir()
    (out_dir / "concept-001.md").write_text(
        "---\nconcept_id: concept-001\ntitle: Test\nfinal_score: 91\n---\nBody.\n"
    )
    index_path = tmp_path / "index.html"
    pipeline_index.regenerate_index(out_dir, index_path)
    html = index_path.read_text()
    assert "91" in html
    assert "<th" in html.lower()
