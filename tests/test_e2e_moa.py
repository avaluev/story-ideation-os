"""tests/test_e2e_moa.py — Issue #16: E2E structural test for use_moa=True pipeline.

Verifies the full Phase 0 → HTML output path with use_moa=True:
  1. seed.json written with moa_candidates in hidden_attributes
  2. export_html.convert() produces HTML with hero grid from a $2B+ NARRATOR.md
  3. HTML has why_sentence extracted dynamically (not the hardcoded default)
  4. reorganize_run() moves all sidecars into _trail/
  5. empirical_genius._check_C008_commercial_scale passes when projected_som ≥ 1000M

All LLM calls are mocked so the test runs offline without API keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.empirical_genius import _check_C008_commercial_scale, _som_band
from pipeline.export_html import _extract_hero_data, _hero_section, convert, reorganize_run
from pipeline.run_single_idea import _write_seed

# ── Rich NARRATOR.md fixture ──────────────────────────────────────────────────

_NARRATOR_MD = """\
# The Fractured Signal

**Logline:** A quantum-AI whistleblower discovers the network has already modelled
her betrayal and is three moves ahead.

**Tagline:** "They built the future. She's the only one who can stop it."

## Investment Summary Card

| Metric | Value |
|--------|-------|
| TAM | $42B |
| SAM | $9.8B |
| SOM | $2.4B |
| Comp ROI | 5.1x |
| Addressable Audience | 520M viewers |

Why this is a $2.4B opportunity: the AI-paranoia thriller is the fastest-growing
genre in prestige streaming, commanding the highest organic social multiplier
of any dramatic category as of 2026.

## The Story

A senior alignment researcher at a classified quantum AI lab discovers that the
system she built to detect deception has been quietly running predictive models
on every employee — including her. The film opens on the day she decides to leak.
By then the system already knows.

Audiences enter through three doors: the AI-safety community who live this fear
professionally; the thriller crowd who want a Bourne-level chase where the
antagonist is invisible; and the philosophy-of-mind audience who want the story to
genuinely interrogate whether a machine that predicts you constitutes surveillance
or prophecy.

## Commercial Model

Day-and-date theatrical + streaming. Target platforms: Netflix global, Apple TV+
co-production. Budget range $38M-$45M. International pre-sales addressable: $14M.
Franchise extension: limited series covering the 72 hours before the leak.

Trailing (2024): 480M | CAGR: +8% | Projected (2026): 560M prestige-thriller viewers.

## Risks

1. **Competitive**: three AI-paranoia films in development at major studios. Mitigant:
   none have the quantum angle; position as the technically credible entry.
2. **Regulatory**: AI regulatory climate shifts could date the premise. Mitigant:
   story is character-driven; tech is backdrop not plot engine.
3. **Budget creep**: VFX for network visualisations. Mitigant: production design
   approach uses UI-level abstraction rather than CGI environments.
"""

# Minimum expected HTML size for a fixture-based test.
# Full pipeline runs produce ≥50 KB; this floor just confirms the converter
# emitted substantive HTML (CSS + hero grid + body), not an empty shell.
_MIN_HTML_BYTES = 4_000


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mock_moa_result(theme: str = "quantum ai whistleblower") -> MagicMock:
    """Return a MoASeedResult mock that mimics a real MoA generation."""
    mock_selected = MagicMock()
    mock_selected.to_dict.return_value = {
        "theme": theme,
        "intersection_premise": "A whistleblower races against a system that already knows.",
        "hidden_attrs": {"force_conspiracy": True},
    }
    mock_result = MagicMock()
    mock_result.selected = mock_selected
    mock_result.seeder_names = ["conspiracy_mind", "open_science_mind", "reptile_fear_mind"]
    mock_result.judge_rationale = "Highest SOM floor with AI-paranoia angle."
    return mock_result


# ── Phase 0 tests ─────────────────────────────────────────────────────────────


def test_phase0_use_moa_writes_moa_candidates(tmp_path: Path) -> None:
    """Phase 0 with use_moa=True writes moa_candidates into hidden_attributes."""
    mock_module = MagicMock()
    mock_module.generate.return_value = _make_mock_moa_result()

    with patch("pipeline.run_single_idea._seed_moa", mock_module):
        _write_seed(tmp_path, theme="quantum ai whistleblower", use_moa=True)

    seed = json.loads((tmp_path / "seed.json").read_text())
    assert "moa_candidates" in seed["hidden_attributes"]
    assert seed["hidden_attributes"]["moa_candidates"] == [
        "conspiracy_mind",
        "open_science_mind",
        "reptile_fear_mind",
    ]
    assert "moa_judge_rationale" in seed["hidden_attributes"]
    assert seed["theme"] == "quantum ai whistleblower"
    assert seed["target_format"] == "feature"


def test_phase0_use_moa_calls_generate_with_theme(tmp_path: Path) -> None:
    """seed_moa.generate() is called with the operator theme forwarded."""
    mock_module = MagicMock()
    mock_module.generate.return_value = _make_mock_moa_result()

    with patch("pipeline.run_single_idea._seed_moa", mock_module):
        _write_seed(tmp_path, theme="quantum ai whistleblower", use_moa=True)

    mock_module.generate.assert_called_once()
    call_kwargs = mock_module.generate.call_args
    themes_arg = call_kwargs.kwargs.get("themes") or call_kwargs.args[0]
    assert "quantum ai whistleblower" in themes_arg


# ── HTML output tests ─────────────────────────────────────────────────────────


def test_narrator_md_hero_extraction() -> None:
    """_extract_hero_data pulls correct metrics from the $2B+ NARRATOR fixture."""
    data = _extract_hero_data(_NARRATOR_MD)
    assert data["som"] != "", "SOM should be extracted"
    assert "2.4" in data["som"] or "2" in data["som"]
    assert data["tam"] != "", "TAM should be extracted"
    assert data["why_sentence"] != "", "why_sentence should be extracted from 'Why this is' lead"
    assert "2.4B" in data["why_sentence"] or "opportunity" in data["why_sentence"]


def test_hero_section_shows_dynamic_why() -> None:
    """Hero grid uses the extracted why_sentence, not the hardcoded fallback."""
    html = _hero_section(_NARRATOR_MD)
    assert "opportunity" in html or "$2.4B" in html
    assert "A $2B+ concept built for mass-market global audiences." not in html


def test_convert_produces_html_with_hero_grid(tmp_path: Path) -> None:
    """export_html.convert() on the rich NARRATOR fixture produces sizeable HTML with hero grid."""
    md_path = tmp_path / "the-fractured-signal-NARRATOR.md"
    md_path.write_text(_NARRATOR_MD, encoding="utf-8")

    html_path = convert(md_path)

    assert html_path.exists(), "HTML file must be created"
    content = html_path.read_text(encoding="utf-8")
    assert len(content.encode()) >= _MIN_HTML_BYTES, (
        f"HTML must be ≥{_MIN_HTML_BYTES} bytes; got {len(content.encode())}"
    )
    assert "hero-scan" in content, "Hero grid div must be present"
    assert "hero-grid" in content, "Hero grid metrics must be present"
    assert "hero-why" in content, "Why sentence div must be present"


def test_convert_with_organize_moves_sidecars_to_trail(tmp_path: Path) -> None:
    """--organize flag: after convert(), all non-HTML files land in _trail/."""
    md_path = tmp_path / "the-fractured-signal-NARRATOR.md"
    md_path.write_text(_NARRATOR_MD, encoding="utf-8")

    # Place sidecar files that reorganize_run should move
    sidecars = ["seed.json", "draft_v0.json", "challenge.json", "genius.json"]
    for name in sidecars:
        (tmp_path / name).write_text("{}", encoding="utf-8")

    convert(md_path, organize=True)

    trail = tmp_path / "_trail"
    assert trail.is_dir(), "_trail/ must be created"
    for name in sidecars:
        assert (trail / name).exists(), f"{name} must be in _trail/"
        assert not (tmp_path / name).exists(), f"{name} must not remain at root"

    # HTML stays at root
    html_files = list(tmp_path.glob("*.html"))
    assert html_files, "HTML must remain at run root"


def test_reorganize_run_contains_narrator_md(tmp_path: Path) -> None:
    """reorganize_run() moves the NARRATOR.md into _trail/ alongside other sidecars."""
    (tmp_path / "seed.json").write_text("{}", encoding="utf-8")
    (tmp_path / "the-fractured-signal-NARRATOR.md").write_text(_NARRATOR_MD, encoding="utf-8")
    (tmp_path / "the-fractured-signal-INVESTOR.html").write_text("<html></html>", encoding="utf-8")

    reorganize_run(tmp_path)

    trail = tmp_path / "_trail"
    assert (trail / "seed.json").exists()
    assert (trail / "the-fractured-signal-NARRATOR.md").exists()
    assert (tmp_path / "the-fractured-signal-INVESTOR.html").exists()


# ── SOM gate tests (projected_som_usd_m ≥ 1000M) ────────────────────────────


def test_c008_passes_when_som_above_1b() -> None:
    """empirical_genius C008 passes when projected_som_usd_m ≥ 1000M."""
    audience = {"projected_som_usd_m": 2400.0, "cited_audience": 520_000_000}
    assert _check_C008_commercial_scale(audience) is True


def test_c008_fails_when_som_below_1b() -> None:
    """empirical_genius C008 fails when projected_som_usd_m < 1000M."""
    audience = {"projected_som_usd_m": 450.0, "cited_audience": 50_000_000}
    assert _check_C008_commercial_scale(audience) is False


def test_som_band_above_2b_for_2b_plus_concept() -> None:
    """$2.4B SOM resolves to som_band == 'above_2b'."""
    audience = {"projected_som_usd_m": 2400.0}
    assert _som_band(audience) == "above_2b"


def test_full_use_moa_phase0_to_html_pipeline(tmp_path: Path) -> None:
    """Integration: Phase 0 with use_moa=True → HTML output ≥ MIN_HTML_BYTES."""
    mock_module = MagicMock()
    mock_module.generate.return_value = _make_mock_moa_result()

    # Phase 0: write seed with MoA
    with patch("pipeline.run_single_idea._seed_moa", mock_module):
        _write_seed(tmp_path, theme="quantum ai whistleblower", use_moa=True)

    seed = json.loads((tmp_path / "seed.json").read_text())
    assert "moa_candidates" in seed["hidden_attributes"]

    # Simulate Phase 7 output: write NARRATOR.md
    md_path = tmp_path / "the-fractured-signal-NARRATOR.md"
    md_path.write_text(_NARRATOR_MD, encoding="utf-8")

    # Convert to HTML
    html_path = convert(md_path)
    html_content = html_path.read_text(encoding="utf-8")

    assert len(html_content.encode()) >= _MIN_HTML_BYTES
    assert "hero-scan" in html_content

    # SOM gate: verify $2B+ concept passes C008
    audience_row = {"projected_som_usd_m": 2400.0, "cited_audience": 520_000_000}
    assert _check_C008_commercial_scale(audience_row) is True
    assert _som_band(audience_row) == "above_2b"
