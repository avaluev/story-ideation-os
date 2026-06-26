"""EVAL -- Translation-friendly prose checker.

Checks Flesch-Kincaid grade <= ``FK_GRADE_MAX`` and flags compound clauses
longer than ``CLAUSE_WORD_LIMIT`` (defined in pipeline/template_filter.py)
plus idioms that translate poorly into Russian.

SKIP until Wave C creates pipeline/template_filter.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_tf = pytest.importorskip("pipeline.template_filter", reason="defensive import guard")
FK_GRADE_MAX = _tf.FK_GRADE_MAX
check_translation_friendly = _tf.check_translation_friendly

# ── Fixtures ──────────────────────────────────────────────────────────────────

# Simple clear prose -- should pass FK <= 12
_SIMPLE = """\
A station master discovers a document that changes everything.
She must decide whether to publish the findings.
The truth will cost her career.
The silence will cost her soul.
She chooses to act.
The system fights back.
She wins.
"""

# Dense academic prose -- should fail FK <= 12
_COMPLEX = (
    "The epistemological underpinnings of the protagonist's circumspect determination "
    "to substantiate the multifaceted veracity of bureaucratic obfuscation within the "
    "institutional framework necessitate a comprehensive reconceptualization of the "
    "fundamental assumptions underlying conventional investigative methodologies as "
    "traditionally practiced within governmental administrative contexts, particularly "
    "vis-a-vis the disambiguation of temporally sequenced evidentiary concatenations "
    "that simultaneously implicate both the substantive and procedural dimensions of "
    "the aforementioned systemic malfeasance.\n"
)

# Prose with a very long compound clause (> 40 words in one sentence)
_LONG_CLAUSE = (
    "The station master, having discovered the document in the lower archive "
    "where it had been hidden by the former director who retired in 1987 after "
    "covering up the incident, decides to publish it despite knowing that doing "
    "so will end her career and potentially expose her to criminal liability "
    "under the outdated secrecy statutes still technically in force.\n"
)

# Sports idioms that translate poorly
_SPORTS_IDIOM = "This is a home run concept that moves the goalposts for the genre.\n"
_MILITARY_METAPHOR = "This is the flagship project that hits the ground running.\n"


class TestCheckTranslationFriendly:
    def test_simple_prose_passes(self) -> None:
        result = check_translation_friendly(_SIMPLE)
        assert result["passed"] is True

    def test_complex_prose_fails_fk_grade(self) -> None:
        result = check_translation_friendly(_COMPLEX)
        assert result["passed"] is False
        assert any(
            "grade" in w.lower() or "flesch" in w.lower() or "readability" in w.lower()
            for w in result["warnings"]
        )

    def test_long_compound_clause_generates_warning(self) -> None:
        result = check_translation_friendly(_LONG_CLAUSE)
        assert len(result["warnings"]) > 0

    def test_sports_idiom_generates_warning(self) -> None:
        result = check_translation_friendly(_SPORTS_IDIOM)
        assert any(
            "home run" in w.lower() or "idiom" in w.lower() or "metaphor" in w.lower()
            for w in result["warnings"]
        )

    def test_result_has_passed_key(self) -> None:
        result = check_translation_friendly(_SIMPLE)
        assert "passed" in result
        assert isinstance(result["passed"], bool)

    def test_result_has_fk_grade(self) -> None:
        result = check_translation_friendly(_SIMPLE)
        assert "fk_grade" in result
        assert isinstance(result["fk_grade"], (float, int))

    def test_result_has_warnings_list(self) -> None:
        result = check_translation_friendly(_SIMPLE)
        assert "warnings" in result
        assert isinstance(result["warnings"], list)

    def test_simple_prose_fk_below_threshold(self) -> None:
        result = check_translation_friendly(_SIMPLE)
        assert result["fk_grade"] <= FK_GRADE_MAX

    def test_empty_string_handled(self) -> None:
        result = check_translation_friendly("")
        assert "passed" in result


# ── Output scan (v4 runs only — identified by eval.json sidecar) ─────────────

_RUNS_DIR = Path("runs")
_V4_RUN_DIRS = (
    [d for d in _RUNS_DIR.glob("*/") if (d / "eval.json").exists()] if _RUNS_DIR.exists() else []
)


@pytest.mark.skipif(
    not _V4_RUN_DIRS,
    reason="No v4 runs (eval.json) in runs/ yet — translation check applies to v4 output only",
)
class TestOutputTranslationScan:
    def test_all_investor_mds_translation_friendly(self) -> None:
        non_md = {"draft.v0.md", "eval.md"}
        for run_dir in _V4_RUN_DIRS:
            for md_path in run_dir.glob("*.md"):
                if md_path.name in non_md:
                    continue
                # Internal audit docs and narrative companions are not translation-gated
                _sidecars = ("-NARRATOR", "-CHALLENGE", "-RESEARCH", "-AMPLIFIED")
                if any(m in md_path.name for m in _sidecars):
                    continue
                text = md_path.read_text()
                # Strip Section 15 (internal audit appendix) before readability check
                cutoff = text.find("## MASTER_QUESTIONS Challenge Results")
                if cutoff != -1:
                    text = text[:cutoff]
                # Strip markdown structural lines (headers, tables, lists) so the
                # compound-clause checker only sees narrative prose
                prose_lines = [
                    ln
                    for ln in text.splitlines()
                    if ln.strip()
                    and not ln.lstrip().startswith("#")
                    and not ln.lstrip().startswith("|")
                    and not ln.lstrip().startswith("-")
                    and not ln.lstrip().startswith("*")
                    and not ln.lstrip().startswith(">")
                ]
                result = check_translation_friendly("\n".join(prose_lines))
                assert result["passed"], (
                    f"{md_path}: translation warnings: " + "; ".join(result["warnings"])  # type: ignore[arg-type]
                )
