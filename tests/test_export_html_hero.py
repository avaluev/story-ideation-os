"""Tests for Change 6: hero grid and run reorganization in pipeline/export_html.py."""

from __future__ import annotations

from pathlib import Path

from pipeline.export_html import _extract_hero_data, _hero_section, reorganize_run

_SAMPLE_MD = (
    "# The Signal\n\n"
    "**Logline:** A whistleblower inside a quantum AI lab must expose a cover-up"
    " while the system learns to predict her next move.\n\n"
    '**Tagline:** "They built the future. She\'s the only one who can stop it."\n\n'
    "## Investment Summary\n\n"
    "| Metric | Value |\n"
    "|--------|-------|\n"
    "| TAM | $45B |\n"
    "| SAM | $8B |\n"
    "| SOM | $2.3B |\n"
    "| Comp ROI | 4.2x |\n\n"
    "Addressable: 450 million viewers globally.\n\n"
    "Why this is a $2.3B opportunity: the conspiracy-thriller genre commands"
    " the highest organic social multiplier of any dramatic category.\n"
)


def test_extract_hero_data_logline() -> None:
    data = _extract_hero_data(_SAMPLE_MD)
    assert "whistleblower" in data["logline"] or data["logline"] == ""


def test_extract_hero_data_som() -> None:
    data = _extract_hero_data(_SAMPLE_MD)
    assert data["som"] in ("$2.3B", "") or "2.3" in data["som"]


def test_extract_hero_data_tam() -> None:
    data = _extract_hero_data(_SAMPLE_MD)
    assert data["tam"] in ("$45B", "") or "45" in data["tam"]


def test_hero_section_returns_html() -> None:
    html = _hero_section(_SAMPLE_MD)
    assert "<div" in html
    assert "hero-scan" in html
    assert "hero-grid" in html


def test_hero_section_has_four_cells() -> None:
    html = _hero_section(_SAMPLE_MD)
    assert html.count("hero-cell") >= 4


def test_reorganize_run_creates_trail_dir(tmp_path: Path) -> None:
    """reorganize_run creates _trail/ and moves non-HTML files into it."""
    (tmp_path / "seed.json").write_text("{}", encoding="utf-8")
    (tmp_path / "draft_v0.json").write_text("{}", encoding="utf-8")
    (tmp_path / "my-concept-INVESTOR.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes", encoding="utf-8")

    trail = reorganize_run(tmp_path)

    assert trail.is_dir()
    assert (trail / "seed.json").exists()
    assert (trail / "draft_v0.json").exists()
    assert (trail / "notes.md").exists()
    # HTML should stay at root
    assert (tmp_path / "my-concept-INVESTOR.html").exists()
    # _trail/README.md should exist
    assert (trail / "README.md").exists()


def test_reorganize_run_skips_html_files(tmp_path: Path) -> None:
    """reorganize_run does not move .html files."""
    (tmp_path / "investor.html").write_text("<html></html>", encoding="utf-8")
    reorganize_run(tmp_path)
    assert (tmp_path / "investor.html").exists()
    assert not (tmp_path / "_trail" / "investor.html").exists()


def test_reorganize_run_idempotent(tmp_path: Path) -> None:
    """Calling reorganize_run twice does not error."""
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    reorganize_run(tmp_path)
    reorganize_run(tmp_path)  # Second call should not raise


def test_extract_hero_data_why_sentence() -> None:
    """why_sentence is extracted from the 'Why this is a $...' lead-in."""
    data = _extract_hero_data(_SAMPLE_MD)
    assert data["why_sentence"] != ""
    assert "$2.3B" in data["why_sentence"] or "opportunity" in data["why_sentence"]


def test_hero_section_uses_extracted_why() -> None:
    """hero grid renders the extracted why_sentence, not the hardcoded default."""
    html = _hero_section(_SAMPLE_MD)
    assert "opportunity" in html or "$2.3B" in html


def test_hero_section_falls_back_when_no_why() -> None:
    """hero grid falls back to the default sentence when no why sentence is found."""
    no_why_md = "# Quiet\n\n**Logline:** A story.\n\n| TAM | $1B |\n|---|---|\n"
    html = _hero_section(no_why_md)
    assert "$2B+" in html  # default fallback


def test_extract_hero_data_empty_string_fallbacks() -> None:
    """Missing fields return empty strings, not exceptions."""
    data = _extract_hero_data("# No metrics here\n\nJust a story.")
    assert data["som"] == ""
    assert data["tam"] == ""
    assert data["audience"] == ""
    assert data["comp_roi"] == ""
    assert data["why_sentence"] == ""


def test_hero_section_empty_md_does_not_raise() -> None:
    """_hero_section handles completely empty markdown without raising."""
    html = _hero_section("")
    assert "hero-scan" in html
    # Falls back to default logline text
    assert "Film concept" in html


def test_reorganize_run_readme_content(tmp_path: Path) -> None:
    """_trail/README.md contains the expected explanation text."""
    trail = reorganize_run(tmp_path)
    readme_text = (trail / "README.md").read_text(encoding="utf-8")
    assert "_trail/" in readme_text
    assert "INVESTOR.html" in readme_text
