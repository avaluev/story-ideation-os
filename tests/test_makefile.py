"""Tests for Makefile invariants (HARN-14)."""

from __future__ import annotations

import subprocess
from pathlib import Path

EXPECTED_TARGETS = [
    "install",
    "lint",
    "typecheck",
    "test",
    "eval",
    "audit",
    "run",
    "refresh-prices",
    "clean",
    "pre-stage-0",
    "stabilize",
    "pathc-eval",
    "pathc-index",
    "pathc-a4",
]


def _run_make(target: str, timeout: int = 30) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Run a make target and return the CompletedProcess."""
    return subprocess.run(  # noqa: S603
        ["make", target],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=str(Path.cwd()),
    )


def test_makefile_exists() -> None:
    """Makefile must exist in the project root."""
    assert Path("Makefile").exists(), "Makefile not found in project root."


def test_help_lists_10_targets() -> None:
    """make help must list all 10 required targets."""
    result = _run_make("help", timeout=10)
    assert result.returncode == 0, (
        f"make help failed with exit {result.returncode}:\n{result.stderr}"
    )
    stdout = result.stdout
    for target in EXPECTED_TARGETS:
        assert target in stdout, (
            f"Target '{target}' not listed in `make help` output.\nFull output:\n{stdout}"
        )


def test_clean_succeeds() -> None:
    """make clean must exit 0."""
    result = _run_make("clean", timeout=10)
    assert result.returncode == 0, (
        f"make clean failed with exit {result.returncode}:\n{result.stderr}"
    )


def test_install_resolves() -> None:
    """make install must exit 0 (uv sync already ran; this is a no-op check)."""
    result = _run_make("install", timeout=60)
    assert result.returncode == 0, (
        f"make install failed with exit {result.returncode}:\n{result.stderr}"
    )
