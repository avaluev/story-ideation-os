"""CLI contract test for scripts/audit.py -- subparser name `sources` (not --check-sources).

References:
- scripts/audit.py (under test)
- .planning/phases/01-knowledge-layer revision-2 BLOCKER H5 (subparser name `sources`)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_audit_sources_offline_exits_zero() -> None:
    """`python -m scripts.audit sources --offline` is the contract; exit 0 on a healthy registry."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.audit", "sources", "--offline"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"`python -m scripts.audit sources --offline` exited {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_audit_check_sources_legacy_form_does_not_exist() -> None:
    """Confirm the legacy `--check-sources` form is NOT registered (would silently misroute)."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.audit", "--check-sources"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    # Argparse should reject this -- exit 2 (usage error).
    assert result.returncode != 0, (
        "`--check-sources` is the legacy form and must NOT be wired as a real flag. "
        "Argparse should reject it; if it accepts, the contract is broken."
    )
