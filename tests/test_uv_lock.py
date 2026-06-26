"""Tests for uv.lock reproducibility (HARN-16)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_uv_lock_exists() -> None:
    """uv.lock must exist in the project root."""
    assert Path("uv.lock").exists(), "uv.lock not found. Run `uv sync --dev` to generate it."


def test_uv_sync_check_passes() -> None:
    """uv sync --check must exit 0 (lock file is up to date)."""
    result = subprocess.run(
        ["uv", "sync", "--check"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"uv sync --check failed (exit {result.returncode}).\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}\n"
        "Run `uv sync --dev` to regenerate uv.lock."
    )
