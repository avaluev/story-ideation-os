#!/usr/bin/env python3
"""lint_prompts.py — PROMPT-01..08 + Karpathy K1..K10 linter for prompts/*.md

Exit codes:
  0  all prompts pass all rules
  1  one or more rules failed (errors printed to stderr)

Error format: ANOMALY-003 or KARPATHY-Kn or PROMPT-XX style (HARN-11 pattern).

ADR-0005: this module MUST NOT import from frameworks/ in any Python module.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROMPTS_DIR = Path("prompts")

# K9 temperature ladder (Karpathy K9 rule).
# 1.0 is required for Anthropic extended-thinking API calls:
# JTBD-mapper, Concept Forger, and Adversarial Critic all declare temperature: 1.0.
ALLOWED_TEMPERATURES = {"0.0", "0.2", "0.3", "0.4", "0.9", "1.0"}

# K3: banned CoT phrases for reasoning-model prompts.
# Extended thinking generates its own reasoning chain; these phrases are
# redundant and counterproductive (AF-013, Anthropic official docs).
BANNED_COT_PHRASES = [
    "think step by step",
    "let's think this through",
    "reason carefully before answering",
    "take a deep breath",
    "think this through carefully",
    "step by step approach",
    "let me think through",
    "reason step by step",
]

# K3: model IDs that trigger the no-CoT reasoning check.
REASONING_MODEL_IDS = [
    "claude-sonnet-4.6",
    "claude-opus-4.7",
    "claude-haiku-4.5",
]

# Minimum anti-slop pattern count (PROMPT-07).
ANTISLOP_MIN_PATTERNS = 80


@dataclass
class LintError:
    """A single lint rule violation."""

    rule: str  # e.g. "ANOMALY-003" or "KARPATHY-K3" or "PROMPT-07"
    file: str
    line: int | None = None  # None = file-level error
    message: str = ""
    fix: str = ""
    extra: list[str] = field(default_factory=list)

    def format(self) -> str:
        """Return the HARN-11 formatted error string."""
        lines = [f"{self.rule}: {self.message}"]
        if self.file:
            loc = f"  File: {self.file}"
            if self.line is not None:
                loc += f", Line {self.line}"
            lines.append(loc)
        lines.extend(f"  {e}" for e in self.extra)
        if self.fix:
            lines.append(f"  Fix: {self.fix}")
        return "\n".join(lines)


def _extract_frontmatter(text: str) -> dict[str, str]:
    """Extract key: value pairs from the HTML comment frontmatter block.

    Handles multi-line YAML-style comment blocks at the start of the file.
    Returns a flat dict of {key: value} for single-line values only.
    """
    m = re.match(r"<!--\s*(.*?)-->", text, flags=re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, str] = {}
    for raw_line in block.splitlines():
        stripped = raw_line.strip()
        if ":" in stripped and not stripped.startswith("#") and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            result[key.strip()] = val.strip()
    return result


def _is_reasoning_model(fm: dict[str, str]) -> bool:
    """Return True if the prompt targets a reasoning model AND reasoning is enabled."""
    model = fm.get("target_model", "")
    # K3: check BOTH reasoning_level and reasoning_level_keepbest.
    # If either declares a non-NONE reasoning level, the file is subject to the
    # no-CoT guarantee regardless of which model path executes.
    level = fm.get("reasoning_level", "NONE").upper()
    level_kb = fm.get("reasoning_level_keepbest", "NONE").upper()
    has_reasoning_level = level not in ("NONE", "")
    has_kb_reasoning = level_kb not in ("NONE", "")
    if not (has_reasoning_level or has_kb_reasoning):
        return False
    return any(mid in model for mid in REASONING_MODEL_IDS)


def check_k1(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K1: frontmatter parses + target_model + version present."""
    errors: list[LintError] = []
    if not fm:
        errors.append(
            LintError(
                rule="KARPATHY-K1",
                file=str(path),
                message="prompt missing frontmatter (HTML comment block with key: value pairs)",
                fix=(
                    "Add an HTML comment block at the top with"
                    " target_model:, version:, reasoning_level:, etc."
                ),
            )
        )
        return errors
    if "target_model" not in fm:
        errors.append(
            LintError(
                rule="KARPATHY-K1",
                file=str(path),
                message="prompt frontmatter missing required field: target_model",
                fix="Add target_model: <model-id> to the frontmatter block",
            )
        )
    if "version" not in fm:
        errors.append(
            LintError(
                rule="KARPATHY-K1",
                file=str(path),
                message="prompt frontmatter missing required field: version",
                fix="Add version: X.Y.Z to the frontmatter block",
            )
        )
    if "reasoning_level" not in fm:
        errors.append(
            LintError(
                rule="KARPATHY-K1",
                file=str(path),
                message="prompt frontmatter missing required field: reasoning_level",
                fix="Add reasoning_level: XHIGH|DEFAULT|NONE to the frontmatter block",
            )
        )
    return errors


def check_k2(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K2: injects: block present."""
    if "injects" not in fm and "injects:" not in text:
        return [
            LintError(
                rule="KARPATHY-K2",
                file=str(path),
                message="prompt missing context-injection declaration (injects: block)",
                fix=(
                    "Add injects: block to frontmatter listing frameworks"
                    " or data files injected at runtime"
                ),
            )
        ]
    return []


def check_k3(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K3: reasoning prompts have G/C/S skeleton + no banned CoT phrases."""
    errors: list[LintError] = []
    if not _is_reasoning_model(fm):
        return errors

    # Check for Goal / Constraints / Schema sections (case-insensitive)
    body_lower = text.lower()
    missing = []
    for section in ("# goal", "# constraints", "# schema"):
        if section not in body_lower:
            missing.append(section.lstrip("# ").title())
    if missing:
        errors.append(
            LintError(
                rule="KARPATHY-K3",
                file=str(path),
                message=f"reasoning prompt missing G/C/S skeleton sections: {', '.join(missing)}",
                fix="Add # Goal, # Constraints, and # Schema sections to the prompt body",
            )
        )

    # Check for banned CoT phrases
    for i, line in enumerate(text.splitlines(), start=1):
        line_lower = line.lower()
        for phrase in BANNED_COT_PHRASES:
            if phrase in line_lower:
                errors.append(
                    LintError(
                        rule="ANOMALY-003",
                        file=str(path),
                        line=i,
                        message="Banned CoT instruction in reasoning-model prompt",
                        extra=[
                            f'Found: "{phrase}"',
                            "Why: Extended thinking generates its own reasoning chain;",
                            "     adding explicit CoT instructions is redundant and",
                            "     disrupts the model's internal reasoning (AF-013).",
                            "Ref: platform.claude.com/docs/en/build-with-claude/extended-thinking",
                            "     REQUIREMENTS.md PROMPT-08",
                        ],
                        fix=(
                            "Remove the CoT instruction."
                            " State your goal, constraints, and output schema only."
                        ),
                    )
                )
    return errors


def check_k4(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K4 (advisory): every Constraints bullet has measurable threshold or pattern ID."""
    errors: list[LintError] = []
    # Find the # Constraints section
    m = re.search(r"# Constraints\s*\n(.*?)(?=\n#|\Z)", text, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return errors
    constraints_block = m.group(1)
    vague_pattern = re.compile(
        r"^\s*-\s+(?:be helpful|be creative|be concise|be thorough|be accurate|be good)\s*$",
        flags=re.IGNORECASE,
    )
    _MEASURABLE_BULLET_MIN_LEN = 40
    measurable_pattern = re.compile(
        r"\d+|word|count|floor|>=|<=|>|<|MUST be|FORBIDDEN"
        r"|anti_slop|Category \d+|JTBD-\d+|pattern|forbidden|>=|<=",
        flags=re.IGNORECASE,
    )
    for line in constraints_block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        bullet_text = stripped[2:]
        if vague_pattern.match(stripped) or (
            not measurable_pattern.search(bullet_text)
            and len(bullet_text) < _MEASURABLE_BULLET_MIN_LEN
            and not any(c in bullet_text for c in (":", "|", "(", "["))
        ):
            errors.append(
                LintError(
                    rule="KARPATHY-K4",
                    file=str(path),
                    message=(
                        f"vague constraint without measurable threshold [WARNING]: {bullet_text!r}"
                    ),
                    fix=(
                        "Add a numeric threshold, unit, or anti_slop"
                        " pattern reference to the constraint"
                    ),
                )
            )
    return errors


def check_k5(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K5: examples policy per target model.

    Counts only explicit ``## Example`` / ``## Sample`` section headers as inline
    examples. A ``# Schema`` section that uses a fenced ``` ```json ``` template
    with ``<placeholder>`` values is the schema declaration (Karpathy K3),
    not an example, so it does not count toward K5.
    """
    errors: list[LintError] = []
    model = fm.get("target_model", "")

    example_headers = re.findall(
        r"^#{1,3}\s*(?:Example|Sample)\b", text, flags=re.IGNORECASE | re.MULTILINE
    )
    has_examples = len(example_headers) >= 1

    # sonar targets: 0 inline examples (schema-only)
    if "sonar" in model and has_examples:
        errors.append(
            LintError(
                rule="KARPATHY-K5",
                file=str(path),
                message=(
                    "examples policy violation: Perplexity sonar targets"
                    " must use 0 inline examples (schema-only output)"
                ),
                fix="Remove inline example blocks; Sonar uses response_format JSON schema only",
            )
        )
    return errors


def check_k6(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K6: output_schema: is a single name (no commas, no list syntax)."""
    errors: list[LintError] = []
    if "output_schema" not in fm:
        errors.append(
            LintError(
                rule="KARPATHY-K6",
                file=str(path),
                message="prompt missing output_schema field in frontmatter",
                fix="Add output_schema: <SingleSchemaName> to frontmatter",
            )
        )
        return errors
    schema_val = fm["output_schema"]
    if "," in schema_val or "[" in schema_val:
        errors.append(
            LintError(
                rule="KARPATHY-K6",
                file=str(path),
                message=f"prompt declares >1 output schema: {schema_val!r}",
                fix="output_schema: must be a single identifier (one schema per prompt)",
            )
        )
    return errors


def check_k7(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K7: golden_fixture: path declared (file existence not checked)."""
    gf = fm.get("golden_fixture", "").strip()
    if not gf:
        return [
            LintError(
                rule="KARPATHY-K7",
                file=str(path),
                message="prompt missing golden_fixture path in frontmatter",
                fix=(
                    "Add golden_fixture: tests/fixtures/<name>.json"
                    " (or .md) to frontmatter; stub paths are valid"
                ),
            )
        ]
    return []


def check_k8(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K8: system and user_template blocks visibly separated."""
    has_system = bool(re.search(r"<system>|&lt;system&gt;|##\s*System", text, flags=re.IGNORECASE))
    has_user = bool(
        re.search(
            r"<user_template>|&lt;user_template&gt;|user_template|##\s*User",
            text,
            flags=re.IGNORECASE,
        )
    )
    if not has_system or not has_user:
        missing = []
        if not has_system:
            missing.append("<system>")
        if not has_user:
            missing.append("<user_template>")
        return [
            LintError(
                rule="KARPATHY-K8",
                file=str(path),
                message=(
                    "prompt missing system/user_template separation"
                    f" — not found: {', '.join(missing)}"
                ),
                fix="Add <system>...</system> and <user_template>...</user_template> blocks",
            )
        ]
    return []


def check_k9(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K9: temperature in allowed ladder."""
    temp = fm.get("temperature", "").strip()
    if not temp:
        return [
            LintError(
                rule="KARPATHY-K9",
                file=str(path),
                message="missing temperature field in frontmatter",
                fix="Add temperature: <value> where value is in {0.0, 0.2, 0.3, 0.4, 0.9, 1.0}",
            )
        ]
    if temp not in ALLOWED_TEMPERATURES and temp.lower() not in ("api-default", "api_default"):
        return [
            LintError(
                rule="KARPATHY-K9",
                file=str(path),
                message=(
                    f"temperature {temp!r} not in allowed ladder"
                    " (allowed: 0.0, 0.2, 0.3, 0.4, 0.9, 1.0)"
                ),
                fix="Set temperature to one of: 0.0, 0.2, 0.3, 0.4, 0.9, 1.0",
            )
        ]
    return []


def check_k10(path: Path, text: str, fm: dict[str, str]) -> list[LintError]:
    """K10: version X.Y.Z semver + last_updated YYYY-MM-DD."""
    errors: list[LintError] = []
    version = fm.get("version", "")
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        errors.append(
            LintError(
                rule="KARPATHY-K10",
                file=str(path),
                message=f"version {version!r} is not semver X.Y.Z format",
                fix="Set version: X.Y.Z in frontmatter (e.g. version: 1.0.0)",
            )
        )
    last_updated = fm.get("last_updated", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", last_updated):
        errors.append(
            LintError(
                rule="KARPATHY-K10",
                file=str(path),
                message=f"last_updated {last_updated!r} is not ISO-8601 YYYY-MM-DD format",
                fix="Set last_updated: YYYY-MM-DD in frontmatter (e.g. last_updated: 2026-05-07)",
            )
        )
    return errors


def check_antislop_count() -> list[LintError]:
    """PROMPT-07: count bullet patterns in prompts/anti_slop.md; fail if < 80.

    GUARD: if prompts/anti_slop.md does not exist, return a clean LintError
    instead of raising FileNotFoundError. This prevents linter crashes during
    partial execution, isolated tests, or a clean repo state.
    """
    antislop_path = PROMPTS_DIR / "anti_slop.md"
    if not antislop_path.exists():
        return [
            LintError(
                rule="PROMPT-07",
                file="prompts/anti_slop.md",
                message="prompts/anti_slop.md not found — create it with >=80 patterns",
                fix="Run plan 02-03 Task 1 to generate the anti-slop registry",
            )
        ]
    text = antislop_path.read_text(encoding="utf-8")
    bullets = [ln for ln in text.splitlines() if ln.strip().startswith("- ")]
    count = len(bullets)
    if count < ANTISLOP_MIN_PATTERNS:
        return [
            LintError(
                rule="PROMPT-07",
                file="prompts/anti_slop.md",
                message=f"anti_slop.md has {count} patterns, requires >={ANTISLOP_MIN_PATTERNS}",
                fix=(
                    "Add more bullet patterns to prompts/anti_slop.md"
                    " (through the STAB-02 human-gate in Phase 5)"
                ),
            )
        ]
    return []


# Ordered rule checks — run in this sequence for every prompt file.
RULE_CHECKS = [
    check_k1,
    check_k2,
    check_k3,
    check_k4,
    check_k5,
    check_k6,
    check_k7,
    check_k8,
    check_k9,
    check_k10,
]


def check_prompt_file(path: Path) -> list[LintError]:
    """Run all K1..K10 + PROMPT-* rules on a single prompt file.

    Returns a list of LintError objects. Empty list = file passes all rules.
    """
    text = path.read_text(encoding="utf-8")
    fm = _extract_frontmatter(text)
    errors: list[LintError] = []
    for check_fn in RULE_CHECKS:
        errors.extend(check_fn(path, text, fm))
    return errors


def main() -> int:
    """Lint prompts/*.md files. Return 0 on pass, 1 on any failure.

    GUARD: if the glob returns no prompt files, emit a PROMPT-01 LintError and
    return 1 immediately rather than silently passing. This prevents a
    vacuously-green linter on a clean repo or partial execution state.
    """
    ap = argparse.ArgumentParser(
        description="PROMPT-01..08 + Karpathy K1..K10 linter for prompts/*.md"
    )
    ap.add_argument(
        "--file",
        metavar="PATH",
        help="Lint a single file instead of all prompts/*.md",
    )
    args = ap.parse_args()

    if args.file:
        single_path = Path(args.file)
        if not single_path.exists():
            err = LintError(
                rule="PROMPT-01",
                file=args.file,
                message=f"file not found: {args.file}",
                fix="Check the file path and try again",
            )
            print(err.format(), file=sys.stderr)
            return 1
        prompt_files = [single_path]
        # When linting a single file, still check anti_slop count
        all_errors = check_antislop_count()
        for pf in prompt_files:
            all_errors.extend(check_prompt_file(pf))
    else:
        glob_results = list(PROMPTS_DIR.glob("*.md"))
        # Exclude anti_slop.md from per-file K1..K10 checks:
        # it is a registry file, not a prompt file; checked by check_antislop_count()
        prompt_files = [p for p in glob_results if p.name != "anti_slop.md"]

        if not prompt_files:
            err = LintError(
                rule="PROMPT-01",
                file=str(PROMPTS_DIR),
                message="prompts/ directory contains no prompt files — create prompt files first",
                fix="Run plans 02-01 and 02-02 to generate the 6 prompt files",
            )
            print(err.format(), file=sys.stderr)
            return 1

        all_errors = check_antislop_count()
        for pf in sorted(prompt_files):
            all_errors.extend(check_prompt_file(pf))

    file_count = len(prompt_files)
    error_count = len(all_errors)

    if error_count == 0:
        print(f"scripts/lint_prompts.py: {file_count} files checked, 0 errors")
        return 0

    print(
        f"scripts/lint_prompts.py: {file_count} files checked, {error_count} errors:",
        file=sys.stderr,
    )
    for err in all_errors:
        print("", file=sys.stderr)
        print(err.format(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
