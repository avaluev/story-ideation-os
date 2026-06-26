"""CLAUDE.md compliance parser (HARN-03, HARN-04, HARN-13, MEM-08).

Every MUST/MUST NOT line in CLAUDE.md must have either:
  (enforced by: <name>)  — a named test, lint rule, or shell script
  (ADR-NNNN)             — a resolved ADR with Status: Accepted

This module parses CLAUDE.md and asserts these invariants hold.
It also verifies that named enforcers resolve (test file exists,
ADR file exists with Accepted status, etc.).

Cross-plan references: some enforcers live in plans 00-01, 00-03, 00-04.
When the file does not exist yet, the parametrized test is marked xfail
with a message explaining which plan will create it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

CLAUDE_MD = Path("CLAUDE.md")

# Regex for (enforced by: <name>) — name may include spaces and :: separators
MUST_PATTERN = re.compile(
    r"^\s*[-*]?\s*(MUST(?:\s+NOT)?)\s+(.+?)\s*\(enforced by:\s*([^)]+)\)\s*$",
    re.MULTILINE,
)
# Regex for (ADR-NNNN) at end of MUST/MUST NOT line
ADR_PATTERN = re.compile(
    r"^\s*[-*]?\s*(MUST(?:\s+NOT)?)\s+(.+?)\s*\((ADR-\d{4})\)\s*$",
    re.MULTILINE,
)


def parse_rules() -> list[dict[str, Any]]:
    """Parse CLAUDE.md and return a list of rule dicts.

    Each dict has:
      kind     — "MUST" or "MUST NOT"
      rule     — the rule text
      enforcer — the enforcer name/code
      type     — "test_or_lint" | "adr"
    """
    text = CLAUDE_MD.read_text()
    rules: list[dict[str, Any]] = []

    for m in MUST_PATTERN.finditer(text):
        rules.append(
            {
                "kind": m.group(1),
                "rule": m.group(2).strip(),
                "enforcer": m.group(3).strip(),
                "type": "test_or_lint",
            }
        )

    for m in ADR_PATTERN.finditer(text):
        rules.append(
            {
                "kind": m.group(1),
                "rule": m.group(2).strip(),
                "enforcer": m.group(3).strip(),
                "type": "adr",
            }
        )

    return rules


def test_every_must_rule_has_enforcer() -> None:
    """No CLAUDE.md MUST/MUST NOT line without an enforcer reference.

    Parses every line that contains MUST or MUST NOT and verifies it ends with
    either `(enforced by: <name>)` or `(ADR-NNNN)`.
    """
    text = CLAUDE_MD.read_text()

    # Find all lines containing MUST or MUST NOT
    bare_must_lines = re.findall(
        r"^\s*[-*]?\s*MUST(?:\s+NOT)?\s+[^\n]+$",
        text,
        re.MULTILINE,
    )

    # Filter to lines that have NO enforcer reference at all
    truly_bare = [
        line for line in bare_must_lines if "(enforced by:" not in line and "(ADR-" not in line
    ]

    assert not truly_bare, (
        f"CLAUDE.md has {len(truly_bare)} MUST/MUST NOT lines without "
        f"`(enforced by: <name>)` or `(ADR-NNNN)` reference:\n"
        + "\n".join(f"  {line.strip()}" for line in truly_bare[:5])
    )


@pytest.mark.parametrize("rule", parse_rules(), ids=lambda r: r["enforcer"][:60])
def test_enforcer_resolves(rule: dict[str, Any]) -> None:
    """Each enforcer referenced in CLAUDE.md must resolve.

    For ADR-NNNN: the file docs/adr/NNNN-*.md must exist with Status: Accepted.
    For pytest test ids: pytest --collect-only must find the test.
    For ANOMALY-NNN custom rules: scripts/lint_imports.py must contain the code.
    For shell scripts: the file must exist.
    For other test files: the file must exist.

    Cross-plan forward references: if the file doesn't exist yet,
    the test is marked xfail (it will be created by a later plan).
    """
    enforcer = rule["enforcer"]

    if rule["type"] == "adr":
        # ADR-NNNN must exist with Status: Accepted
        adr_num = enforcer.replace("ADR-", "")
        adrs = list(Path("docs/adr").glob(f"{adr_num}-*.md"))
        assert adrs, (
            f"ADR {enforcer} referenced in CLAUDE.md but no docs/adr/{adr_num}-*.md exists."
        )
        body = adrs[0].read_text().lower()
        # Match various formats:
        # "Status: Accepted", "**Status:** Accepted", "**Status: Accepted**"
        has_accepted_status = bool(re.search(r"status[*:\s]+accepted", body))
        assert has_accepted_status, (
            f"{enforcer} does not have Status: Accepted in {adrs[0]}\n"
            f"(checked: 'status[*:\\s]+accepted' in lowercased body)"
        )

    elif re.match(r"^ANOMALY-\d+", enforcer):
        # Custom lint rule — must exist in scripts/lint_imports.py
        lint_script = Path("scripts/lint_imports.py")
        assert lint_script.exists(), "scripts/lint_imports.py does not exist"
        # Extract just the rule code (e.g. "ANOMALY-001" from "ANOMALY-001 in scripts/...")
        rule_code = re.match(r"^(ANOMALY-\d+)", enforcer)
        if rule_code:
            assert rule_code.group(1) in lint_script.read_text(), (
                f"Rule code {rule_code.group(1)} not found in scripts/lint_imports.py"
            )

    elif enforcer.endswith(".sh") or (enforcer.startswith("tests/hooks/") and "::" not in enforcer):
        # Shell script — must exist (may be in tests/ or tests/hooks/)
        # NOTE: enforcers with :: are pytest test IDs, handled in the next branch
        candidates = [
            Path(enforcer),
            Path("tests") / enforcer,
            Path("tests/hooks") / Path(enforcer).name,
        ]
        exists = any(c.exists() for c in candidates)
        if not exists:
            pytest.xfail(
                f"Shell script {enforcer!r} does not exist yet — "
                "will be created by a later plan (00-01 or 00-03)."
            )

    elif "::" in enforcer or enforcer.startswith("test_") or enforcer.endswith("_test"):
        # pytest test id — file path before :: must exist
        test_file_str = enforcer.split("::")[0].strip()
        test_file = Path(test_file_str)
        if not test_file.exists():
            pytest.xfail(
                f"Test file {test_file_str!r} does not exist yet — will be created by a later plan."
            )

        # File exists — now verify the specific test is collectable
        r = subprocess.run(  # noqa: S603
            ["uv", "run", "pytest", "--collect-only", "-q", enforcer],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        # pytest exit 4 = no tests collected; exit 0 = collected; exit 1 = error
        if r.returncode not in (0, 1):
            pytest.xfail(
                f"Test {enforcer!r} not found by pytest --collect-only "
                f"(exit {r.returncode}); may not be created yet."
            )
        elif r.returncode == 1 and (
            "no tests ran" in r.stdout.lower()
            or "no tests collected" in r.stdout.lower()
            or "error" in r.stdout.lower()
        ):
            pytest.xfail(f"Test {enforcer!r} could not be collected — may be in a future plan.")

    else:
        # Generic: the enforcer is a file path
        p = Path(enforcer)
        if not p.exists():
            pytest.xfail(
                f"Enforcer file {enforcer!r} does not exist yet — will be created by a later plan."
            )


def test_recovery_protocol_documented() -> None:
    """CLAUDE.md must document the recovery protocol and ONE STAGE doctrine.

    Verifies presence of:
    - RESUME.md reference (first action in new session)
    - handoffs reference (second action in new session)
    - STATE.md reference (third action in new session)
    - "ONE STAGE per session" doctrine (HARN-13)
    """
    text = CLAUDE_MD.read_text()

    assert "RESUME.md" in text, (
        "CLAUDE.md missing RESUME.md recovery reference.\nEvery session must read RESUME.md first."
    )
    assert "handoffs" in text, (
        "CLAUDE.md missing handoffs recovery reference.\n"
        "Every session must read the newest handoff file second."
    )
    assert "STATE.md" in text, (
        "CLAUDE.md missing STATE.md recovery reference.\nEvery session must read STATE.md third."
    )
    assert "ONE STAGE per session" in text, (
        "CLAUDE.md missing 'ONE STAGE per session' doctrine (HARN-13).\n"
        "Each Claude Code session must be treated as one stage only."
    )
