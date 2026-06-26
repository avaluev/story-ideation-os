"""tests/test_lint_prompts.py — pytest wrapper for scripts/lint_prompts.py CI integration.

Runs lint_prompts.py via subprocess and asserts return codes and error outputs.
This keeps the test fabric separate from the linter logic (no import coupling).
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


def _run_linter(*extra_args: str) -> tuple[int, str]:
    """Run lint_prompts.py via subprocess; return (returncode, combined stdout+stderr)."""
    result = subprocess.run(  # noqa: S603
        ["uv", "run", "python", "scripts/lint_prompts.py", *extra_args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def test_lint_passes_on_all_prompts() -> None:
    """All 6 prompt files from plans 02-01 and 02-02 pass the linter."""
    rc, output = _run_linter()
    assert rc == 0, f"Linter failed:\n{output}"


def test_lint_catches_cot_phrase(tmp_path: Path) -> None:
    """Linter exits 1 with ANOMALY-003 when reasoning prompt has banned CoT phrase."""
    bad_prompt = tmp_path / "bad_prompt.md"
    bad_prompt.write_text(
        textwrap.dedent("""\
        <!--
        target_model: anthropic/claude-sonnet-4.6
        reasoning_level: XHIGH
        phase: 99
        temperature: 1.0
        output_format: JSON
        output_schema: TestSchema
        version: 1.0.0
        last_updated: 2026-05-07
        injects:
          - frameworks/sdt-spine.md
        golden_fixture: tests/fixtures/test.json
        banned_cot_instructions: true
        -->

        <system>
        You are a test agent.
        </system>

        <user_template>

        # Goal
        Test.

        # Constraints
        - Think step by step about the problem before answering.
        - MUST produce exactly 1 result.

        # Schema
        {"result": "string"}
        </user_template>
        """)
    )
    rc, output = _run_linter("--file", str(bad_prompt))
    assert rc == 1, f"Expected exit 1 for CoT phrase, got {rc}\n{output}"
    assert "ANOMALY-003" in output, f"Expected ANOMALY-003 in output:\n{output}"


def test_lint_catches_missing_golden_fixture(tmp_path: Path) -> None:
    """Linter exits 1 with KARPATHY-K7 when golden_fixture is missing."""
    bad_prompt = tmp_path / "no_fixture.md"
    bad_prompt.write_text(
        textwrap.dedent("""\
        <!--
        target_model: anthropic/claude-haiku-4.5
        reasoning_level: NONE
        phase: 06
        temperature: 0.0
        output_format: MARKDOWN
        output_schema: A4Document
        version: 1.0.0
        last_updated: 2026-05-07
        injects:
          - (none)
        banned_cot_instructions: false
        -->

        <system>
        You are a formatter.
        </system>

        <user_template>
        # Goal
        Format.
        # Constraints
        - MUST produce exactly 12 sections.
        </user_template>
        """)
    )
    rc, output = _run_linter("--file", str(bad_prompt))
    assert rc == 1, f"Expected exit 1 for missing golden_fixture, got {rc}\n{output}"
    assert "KARPATHY-K7" in output, f"Expected KARPATHY-K7 in output:\n{output}"


def test_antislop_pattern_count() -> None:
    """anti_slop.md has >= 80 patterns; linter reports no PROMPT-07 error."""
    rc, output = _run_linter()
    assert "PROMPT-07" not in output or rc == 0, f"PROMPT-07 pattern count failure:\n{output}"


def test_lint_catches_missing_target_model(tmp_path: Path) -> None:
    """Linter exits 1 with KARPATHY-K1 when target_model is missing."""
    bad_prompt = tmp_path / "no_target.md"
    bad_prompt.write_text("# Just a plain markdown file\nNo frontmatter here.\n")
    rc, output = _run_linter("--file", str(bad_prompt))
    assert rc == 1, f"Expected exit 1 for missing target_model, got {rc}"
    assert "KARPATHY-K1" in output, f"Expected KARPATHY-K1:\n{output}"
