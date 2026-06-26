"""Tests for pyproject.toml invariants (HARN-15)."""
from __future__ import annotations

from pathlib import Path

import pytest
import tomli


@pytest.fixture
def pyproject() -> dict:
    """Load pyproject.toml as a dict."""
    with open("pyproject.toml", "rb") as f:
        return tomli.load(f)


def test_required_tables_present(pyproject: dict) -> None:
    """All required TOML tables must be present."""
    assert "project" in pyproject, "Missing [project] table"
    assert "tool" in pyproject, "Missing [tool] table"
    assert "ruff" in pyproject["tool"], "Missing [tool.ruff] table"
    assert "pyright" in pyproject["tool"], "Missing [tool.pyright] table"
    # pytest config is under tool.pytest.ini_options
    assert "pytest" in pyproject["tool"], "Missing [tool.pytest] table"
    assert "ini_options" in pyproject["tool"]["pytest"], (
        "Missing [tool.pytest.ini_options] table"
    )


def test_python_version_pinned(pyproject: dict) -> None:
    """Python version must be pinned to >=3.11."""
    requires_python = pyproject["project"].get("requires-python", "")
    assert requires_python.startswith(">=3.11"), (
        f"requires-python must start with '>=3.11', got: {requires_python!r}"
    )


def test_no_requirements_txt() -> None:
    """HARN-15: requirements.txt must not exist (use pyproject.toml + uv.lock)."""
    assert not Path("requirements.txt").exists(), (
        "requirements.txt found — forbidden by HARN-15. "
        "Use pyproject.toml + uv.lock instead."
    )


def test_dev_deps_include_pyright_ruff(pyproject: dict) -> None:
    """Dev extras must include pyright, ruff, and pytest."""
    # Check in optional-dependencies.dev or dependency-groups.dev
    dev_deps: list[str] = []

    if "optional-dependencies" in pyproject.get("project", {}):
        dev_deps.extend(pyproject["project"]["optional-dependencies"].get("dev", []))
    if "dependency-groups" in pyproject:
        dev_deps.extend(pyproject["dependency-groups"].get("dev", []))

    dep_names = [d.split(">=")[0].split("==")[0].strip() for d in dev_deps]

    assert any("pyright" in name for name in dep_names), (
        "pyright not found in dev dependencies"
    )
    assert any("ruff" in name for name in dep_names), (
        "ruff not found in dev dependencies"
    )
    assert any("pytest" in name for name in dep_names), (
        "pytest not found in dev dependencies"
    )


def test_testpaths_configured(pyproject: dict) -> None:
    """pytest testpaths must include tests and evals."""
    testpaths = pyproject["tool"]["pytest"]["ini_options"].get("testpaths", [])
    assert "tests" in testpaths, "tests/ not in pytest testpaths"
    assert "evals" in testpaths, "evals/ not in pytest testpaths"
