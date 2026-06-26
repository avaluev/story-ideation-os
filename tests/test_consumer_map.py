"""tests/test_consumer_map.py — NB.3 anti-orphan-artifact enforcement.

Every tracked data file under the watched directories must declare a consumer
in ``data/_consumers.jsonl``. Files without a consumer entry are dead
artifacts and MUST NOT be committed.

Watched directories (configured in scripts/check_consumer_map.py):
  pipeline/data/, frameworks/data/, data/seeds/, Inputs/
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ = sys  # re-export for explicit reference: formatter would otherwise strip the import

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _consumer_map_path() -> Path:
    return _REPO_ROOT / "data" / "_consumers.jsonl"


def test_consumer_map_schema() -> None:
    """data/_consumers.jsonl exists and every row has the required fields."""
    path = _consumer_map_path()
    assert path.exists(), "data/_consumers.jsonl must exist (NB.3 deliverable)"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    ]
    assert rows, "consumer map is empty"
    for row in rows:
        for k in (
            "artifact_path",
            "consumer_module",
            "consumer_function",
            "test_module",
            "test_name",
            "category",
            "owner",
            "added_at",
        ):
            assert k in row, f"row missing key {k}: {row}"
        artifact = _REPO_ROOT / row["artifact_path"]
        assert artifact.exists(), f"artifact missing on disk: {row['artifact_path']}"


def test_no_orphan_data_files() -> None:
    """Every tracked file under watched dirs is either consumed or explicitly excluded."""
    from scripts.check_consumer_map import find_orphans  # noqa: PLC0415

    orphans = find_orphans()
    assert not orphans, f"orphan artifacts (no consumer declared): {[str(p) for p in orphans]}"


def test_script_blocks_on_orphan(tmp_path: Path) -> None:
    """The CLI exits non-zero when an orphan is introduced in a watched dir."""
    fake_data = tmp_path / "pipeline" / "data"
    fake_data.mkdir(parents=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "_consumers.jsonl").write_text("", encoding="utf-8")
    (fake_data / "orphan.json").write_text("{}", encoding="utf-8")
    env = {**os.environ, "CONSUMER_MAP_ROOT": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_consumer_map"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "orphan" in combined, f"output: {result.stdout!r} stderr: {result.stderr!r}"


def test_every_listed_consumer_is_importable() -> None:
    """consumer_module:consumer_function must resolve to a real callable for 'live_data' rows.

    Non-Python categories ('agent_prompt_input', 'reference_intentional') are
    skipped — their consumers are agent .md files or operator-curated references.
    """
    path = _consumer_map_path()
    if not path.exists():
        pytest.skip("consumer map not yet created — covered by test_consumer_map_schema")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        row = json.loads(line)
        if row.get("category") != "live_data":
            continue
        mod = importlib.import_module(row["consumer_module"])
        assert hasattr(mod, row["consumer_function"]), (
            f"consumer {row['consumer_module']}:{row['consumer_function']} not callable"
        )


def test_script_passes_on_clean_repo() -> None:
    """Default invocation against the real repo exits 0 (no orphans today)."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_consumer_map"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"check_consumer_map failed on clean repo:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
