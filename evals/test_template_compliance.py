"""EVAL -- V2 template structure compliance.

Checks that investor-facing .md files have all 4 required H1 sections
and their mandatory H2 children.

SKIP until Wave C creates pipeline/template_filter.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_tf = pytest.importorskip("pipeline.template_filter", reason="defensive import guard")
check_template_compliance = _tf.check_template_compliance
check_narrator_compliance = _tf.check_narrator_compliance
check_amplified_compliance = _tf.check_amplified_compliance

# ── Valid fixture ─────────────────────────────────────────────────────────────

_VALID = """\
# Station Tolerance

- **Logline:** A station master uncovers evidence that rewrites history.
- **Tagline:** Every delay has a reason.

# 1. Market & Audience

## Revenue Thesis (Anchored to Comps)
Detailed projection.

## Primary Audience Segment
### Who They Are
Adults 25-45.
### Job-to-Be-Done
Understanding systems.
### Tonal Contract
Cerebral thriller.
### What Loses Them
Pacing issues.

## Why Now (Market Timing)
Data-driven timing.

## Audience Sizing
### TAM
**TAM:** $4.8B
### SAM
**SAM:** $800M
### SOM -- Serviceable Obtainable Market (Year 1 realistic capture)
**SOM (Year 1):** $120M

## Comparables
### Financial Comps
| Title | Year | Format | Budget | WW Revenue | Why Comparable | Source |
### Tonal Comps
Three films.
### Structural Comps
Three more.

# 2. The Concept

## Format & Genre
Feature thriller.

## The Contradiction
The central tension.

## Psychological Tension
The inner conflict.

## Indelible Image
The single visual.

## Mass-Appeal Theme
The universal question.

## Fact-Fiction Blend
The real case.

# 3. Story

## Synopsis
The full synopsis here.

## Emotional Arc
The arc.

## Cinematic Parallels
Similar films.

## Visual Style & Tone
The look.

# 4. Characters

## Protagonist
**Name | Age | Identity**

## Antagonist
**Name | Age | Identity**

## Ally / Supporting
Supporting characters.

## References
1. [Source](https://example.com/deep/path) -- context.
"""

_MISSING_MARKET = _VALID.replace("# 1. Market & Audience", "## 1 removed")
_MISSING_CONCEPT = _VALID.replace("# 2. The Concept", "## 2 removed")
_MISSING_STORY = _VALID.replace("# 3. Story", "## 3 removed")
_MISSING_CHARACTERS = _VALID.replace("# 4. Characters", "## 4 removed")
_MISSING_REVENUE_THESIS = _VALID.replace("## Revenue Thesis (Anchored to Comps)\n", "")
_MISSING_WHY_NOW = _VALID.replace("## Why Now (Market Timing)\n", "")
_MISSING_AUDIENCE_SIZING = _VALID.replace("## Audience Sizing\n", "")
_MISSING_SYNOPSIS = _VALID.replace("## Synopsis\n", "")
_MISSING_PROTAGONIST = _VALID.replace("## Protagonist\n", "")


class TestCheckTemplateCompliance:
    def test_valid_doc_passes(self) -> None:
        result = check_template_compliance(_VALID)
        assert result["passed"] is True
        assert result["failures"] == []

    def test_missing_market_section_fails(self) -> None:
        result = check_template_compliance(_MISSING_MARKET)
        assert result["passed"] is False
        assert any("Market" in f for f in result["failures"])

    def test_missing_concept_section_fails(self) -> None:
        result = check_template_compliance(_MISSING_CONCEPT)
        assert result["passed"] is False
        assert any("Concept" in f for f in result["failures"])

    def test_missing_story_section_fails(self) -> None:
        result = check_template_compliance(_MISSING_STORY)
        assert result["passed"] is False
        assert any("Story" in f for f in result["failures"])

    def test_missing_characters_section_fails(self) -> None:
        result = check_template_compliance(_MISSING_CHARACTERS)
        assert result["passed"] is False
        assert any("Characters" in f for f in result["failures"])

    def test_missing_revenue_thesis_fails(self) -> None:
        result = check_template_compliance(_MISSING_REVENUE_THESIS)
        assert result["passed"] is False

    def test_missing_why_now_fails(self) -> None:
        result = check_template_compliance(_MISSING_WHY_NOW)
        assert result["passed"] is False

    def test_missing_audience_sizing_fails(self) -> None:
        result = check_template_compliance(_MISSING_AUDIENCE_SIZING)
        assert result["passed"] is False

    def test_missing_synopsis_fails(self) -> None:
        result = check_template_compliance(_MISSING_SYNOPSIS)
        assert result["passed"] is False

    def test_missing_protagonist_fails(self) -> None:
        result = check_template_compliance(_MISSING_PROTAGONIST)
        assert result["passed"] is False

    def test_result_has_passed_key(self) -> None:
        result = check_template_compliance(_VALID)
        assert "passed" in result
        assert isinstance(result["passed"], bool)

    def test_result_has_failures_list(self) -> None:
        result = check_template_compliance(_VALID)
        assert "failures" in result
        assert isinstance(result["failures"], list)

    def test_empty_doc_fails_all_four_sections(self) -> None:
        result = check_template_compliance("")
        assert result["passed"] is False
        assert len(result["failures"]) >= 4


# ── NARRATOR.md schema tests ─────────────────────────────────────────────────

_VALID_NARRATOR = """\
# The Tally Room

#### Logline
A young deputy director risks her career to expose the real ledger.

#### Tagline
"The numbers never lie. People do."

---
"""

_NARRATOR_LEGACY_BOLD = """\
═══════════════════════════════════════════════════════════════════
STATION TOLERANCE — INVESTOR SUMMARY
═══════════════════════════════════════════════════════════════════

**LOGLINE**
A transit compliance officer who secretly maps city soundscapes.

**TAGLINE**
"Endure long enough and the system becomes you."
"""

_NARRATOR_NO_LOGLINE = """\
# The Contamination Faith — Investor Companion

You know the contamination movie. A corporation poisons a town's water...
"""


class TestCheckNarratorCompliance:
    def test_canonical_narrator_passes(self) -> None:
        result = check_narrator_compliance(_VALID_NARRATOR)
        assert result["passed"] is True, result["failures"]

    def test_legacy_bold_logline_fails_with_actionable_message(self) -> None:
        result = check_narrator_compliance(_NARRATOR_LEGACY_BOLD)
        assert result["passed"] is False
        assert any("legacy `**LOGLINE**`" in f for f in result["failures"])
        assert any("legacy `**TAGLINE**`" in f for f in result["failures"])

    def test_no_logline_anchor_fails(self) -> None:
        result = check_narrator_compliance(_NARRATOR_NO_LOGLINE)
        assert result["passed"] is False
        assert any("Logline" in f for f in result["failures"])
        assert any("Tagline" in f for f in result["failures"])

    def test_missing_h1_fails(self) -> None:
        no_h1 = _VALID_NARRATOR.replace("# The Tally Room", "## Subtitle")
        result = check_narrator_compliance(no_h1)
        assert result["passed"] is False
        assert any("H1 title" in f for f in result["failures"])

    def test_empty_doc_fails_all_three_anchors(self) -> None:
        result = check_narrator_compliance("")
        assert result["passed"] is False
        assert len(result["failures"]) == 3


# ── AMPLIFIED.md schema tests ────────────────────────────────────────────────

_VALID_AMPLIFIED = """\
# Audience Amplification Trail — the-tally-room

| Metric | Value |
|--------|-------|
| Base audience | **180.0M** |
| Final audience | **720.0M** |
| Total compound multiplier | **4.0x** |
| Revenue implication | $250M-$500M+ theatrical |

---

## Decision Trail

```
the-tally-room
│  Base: 180.0M addressable
```

---

## Vectors Applied (11)

- `A1`

## Vectors Remaining — Untapped Upside (38)

- `A2`
"""

_AMPLIFIED_LEGACY_AGENT_FORM = """\
# Audience Amplification — The Locard Variable
*Generated: 2026-05-13T12:01:18+00:00*

---

## Starting State

- Current addressable audience: 135M
"""


class TestCheckAmplifiedCompliance:
    def test_canonical_amplified_passes(self) -> None:
        result = check_amplified_compliance(_VALID_AMPLIFIED)
        assert result["passed"] is True, result["failures"]

    def test_legacy_agent_form_fails(self) -> None:
        result = check_amplified_compliance(_AMPLIFIED_LEGACY_AGENT_FORM)
        assert result["passed"] is False
        # 4 of 5 anchors missing -- has the metric table absent too
        assert len(result["failures"]) >= 4

    def test_missing_metric_table_fails(self) -> None:
        no_table = _VALID_AMPLIFIED.replace("| Metric | Value |", "")
        result = check_amplified_compliance(no_table)
        assert result["passed"] is False
        assert any("metric table" in f for f in result["failures"])

    def test_missing_decision_trail_fails(self) -> None:
        no_trail = _VALID_AMPLIFIED.replace("## Decision Trail", "## Something Else")
        result = check_amplified_compliance(no_trail)
        assert result["passed"] is False
        assert any("Decision Trail" in f for f in result["failures"])

    def test_empty_doc_fails_all_five_anchors(self) -> None:
        result = check_amplified_compliance("")
        assert result["passed"] is False
        assert len(result["failures"]) == 5


# ── Output-scan tests (v4 runs only — identified by eval.json sidecar) ───────

_RUNS_DIR = Path("runs")
_V4_RUN_DIRS = (
    [d for d in _RUNS_DIR.glob("*/") if (d / "eval.json").exists()] if _RUNS_DIR.exists() else []
)

# Pre-canonical narrator outputs (May 12 2026) that emit **LOGLINE** / **TAGLINE**
# bold-paragraph form instead of the canonical `#### Logline` H4. Pinned here so
# the scan stays green while a regression on any NEWER narrator output will fail.
_NARRATOR_LEGACY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "runs/2026-05-12-171157-station-tolerance/station-tolerance-NARRATOR.md",
        "runs/2026-05-12-204819-a-federal-quota-analyst-who-studies-star/the-quota-NARRATOR.md",
    }
)

# Pre-canonical AMPLIFIED.md outputs (May 13 2026) that use the
# .claude/agents/audience-amplifier.md agent-prompt format ("# Audience
# Amplification — <Title>" with "## Starting State" / "## The Loop Result"
# sections) instead of the canonical Python-emitted form from
# pipeline.audience_amplifier.render_trail. Pinned so the scan stays green
# while a regression on any NEWER amplified output will fail.
_AMPLIFIED_LEGACY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "runs/2026-05-13-063827-compound-genesis/the-locard-variable-AMPLIFIED.md",
        "runs/2026-05-13-120118-dr-sarah-chen-has-spent-twenty-eight-yea/the-locard-variable-AMPLIFIED.md",
    }
)


@pytest.mark.skipif(
    not _V4_RUN_DIRS,
    reason="No v4 runs (eval.json) in runs/ yet — template compliance applies to v4 output only",
)
class TestOutputScanCompliance:
    def test_all_investor_mds_comply(self) -> None:
        non_md = {"draft.v0.md", "eval.md"}
        for run_dir in _V4_RUN_DIRS:
            for md_path in run_dir.glob("*.md"):
                if md_path.name in non_md:
                    continue
                # Non-concept docs use different formats (audit, companion, amplification)
                _sidecars = ("-NARRATOR", "-CHALLENGE", "-RESEARCH", "-AMPLIFIED")
                if any(m in md_path.name for m in _sidecars):
                    continue
                result = check_template_compliance(md_path.read_text())
                assert result["passed"], (
                    f"{md_path}: failures: " + "; ".join(result["failures"])  # type: ignore[arg-type]
                )

    def test_all_narrator_mds_use_canonical_schema(self) -> None:
        """Every v4 NARRATOR.md uses the canonical `#### Logline` / `#### Tagline` H4
        schema, except the pre-canonical May 12 stragglers pinned in the allow-list."""
        violations: list[str] = []
        for run_dir in _V4_RUN_DIRS:
            for md_path in run_dir.glob("*-NARRATOR.md"):
                rel = md_path.as_posix()
                if rel in _NARRATOR_LEGACY_ALLOWLIST:
                    continue
                result = check_narrator_compliance(md_path.read_text())
                if not result["passed"]:
                    failures = "; ".join(result["failures"])  # type: ignore[arg-type]
                    violations.append(f"{rel}: {failures}")
        assert not violations, "Narrator schema drift:\n  " + "\n  ".join(violations)

    def test_all_amplified_mds_use_canonical_schema(self) -> None:
        """Every v4 AMPLIFIED.md matches the Python writer at
        pipeline.audience_amplifier.render_trail. May-13 stragglers that use
        the agent-prompt-driven format are pinned in the allow-list."""
        violations: list[str] = []
        for run_dir in _V4_RUN_DIRS:
            for md_path in run_dir.glob("*-AMPLIFIED.md"):
                rel = md_path.as_posix()
                if rel in _AMPLIFIED_LEGACY_ALLOWLIST:
                    continue
                result = check_amplified_compliance(md_path.read_text())
                if not result["passed"]:
                    failures = "; ".join(result["failures"])  # type: ignore[arg-type]
                    violations.append(f"{rel}: {failures}")
        assert not violations, "Amplified schema drift:\n  " + "\n  ".join(violations)
