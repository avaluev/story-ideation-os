"""EVAL: Research dossier presence and content gate.

Checks that every concept in the latest runs/ folder has a corresponding
[slug]-RESEARCH.md with at least one verified URL.

Run: pytest evals/test_research_verified.py -v
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNS_DIR = REPO_ROOT / "runs"

URL_PATTERN = re.compile(r"https://\S+")
VERDICT_PATTERN = re.compile(r"Research Verdict", re.IGNORECASE)


def get_latest_run_folder() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    folders = sorted(
        [f for f in RUNS_DIR.iterdir() if f.is_dir()],
        key=lambda f: f.name,
        reverse=True,
    )
    return folders[0] if folders else None


def get_concept_files(run_folder: Path) -> list[Path]:
    META_DOCS = {"README.md", "FINDINGS.md"}
    return [
        f
        for f in run_folder.glob("*.md")
        if not any(m in f.name for m in ("-NARRATOR", "-CHALLENGE", "-RESEARCH", "-AMPLIFIED"))
        and f.name not in META_DOCS
    ]


def pytest_generate_tests(metafunc):
    run_folder = get_latest_run_folder()
    if run_folder is None:
        metafunc.parametrize("concept_file", [])
        return
    concept_files = get_concept_files(run_folder)
    if "concept_file" in metafunc.fixturenames:
        metafunc.parametrize("concept_file", concept_files, ids=[f.name for f in concept_files])


def _v4_research_json(concept_file: Path) -> Path | None:
    """Return research.json path if this is a v4 run, else None."""
    p = concept_file.parent / "research.json"
    return p if p.exists() else None


def test_research_dossier_exists(concept_file: Path):
    """Every concept must have research evidence: research.json (v4) or [slug]-RESEARCH.md (v3)."""
    # v4 pipeline writes research.json instead of a markdown dossier
    if _v4_research_json(concept_file):
        return  # v4 format — research.json present, passes
    stem = concept_file.stem
    research_file = concept_file.parent / f"{stem}-RESEARCH.md"
    assert research_file.exists(), (
        f"Missing research dossier for {concept_file.name}. "
        f"Expected: {research_file.name} (v3) or research.json (v4). "
        f"Run concept-researcher agent before publishing."
    )


def test_research_contains_urls(concept_file: Path):
    """Research evidence must contain at least 1 HTTPS URL."""
    v4 = _v4_research_json(concept_file)
    if v4:
        data = json.loads(v4.read_text())
        urls = [v for v in data.values() if isinstance(v, str) and v.startswith("https://")]
        assert len(urls) >= 1, "research.json: no HTTPS URLs found in string fields"
        return
    stem = concept_file.stem
    research_file = concept_file.parent / f"{stem}-RESEARCH.md"
    if not research_file.exists():
        pytest.skip("Research file missing (caught by test_research_dossier_exists)")
    text = research_file.read_text(encoding="utf-8")
    urls = URL_PATTERN.findall(text)
    assert len(urls) >= 1, (
        f"{research_file.name}: must contain at least 1 HTTPS URL. "
        f"Research step may have failed completely."
    )


def test_research_has_verdict(concept_file: Path):
    """Research evidence must reflect a completed research run."""
    v4 = _v4_research_json(concept_file)
    if v4:
        data = json.loads(v4.read_text())
        assert "produced_at" in data, (
            "research.json missing produced_at — research did not complete"
        )
        return
    stem = concept_file.stem
    research_file = concept_file.parent / f"{stem}-RESEARCH.md"
    if not research_file.exists():
        pytest.skip("Research file missing")
    text = research_file.read_text(encoding="utf-8")
    assert VERDICT_PATTERN.search(text), (
        f"{research_file.name}: missing 'Research Verdict' section. "
        f"Research protocol did not complete."
    )


def test_research_not_fully_failed(concept_file: Path):
    """Research must not have all 3 steps marked FAILED (v3 only; v4 uses research.json)."""
    if _v4_research_json(concept_file):
        pytest.skip(
            "v4 format — research.json present; failure detection via audience_size_global field"
        )
    stem = concept_file.stem
    research_file = concept_file.parent / f"{stem}-RESEARCH.md"
    if not research_file.exists():
        pytest.skip("Research file missing")
    text = research_file.read_text(encoding="utf-8")
    failed_count = text.count("Status: FAILED")
    assert failed_count < 3, (
        f"{research_file.name}: all research steps failed. "
        f"Open Router and WebSearch both returned no results. "
        f"Concept cannot be published without any evidence grounding."
    )
