"""scripts/check_consumer_map.py — anti-orphan artifact gate (Cycle 1 NB.3).

Reads ``data/_consumers.jsonl`` and verifies that every tracked file under the
watched directories has a declared consumer. Exits 1 (with a human-readable
diff) when orphans are detected.

Usage::

    uv run python -m scripts.check_consumer_map           # repo root
    CONSUMER_MAP_ROOT=/tmp/x uv run python -m scripts.check_consumer_map  # tests

The watched-directory list is intentionally narrow: only places where
operator-curated knowledge or framework data live. Generated artifacts under
``data/runs/``, ``data/_attic/``, ``data/state/`` are excluded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Directories under which every tracked file must declare a consumer.
_WATCHED_DIRS: tuple[str, ...] = (
    "pipeline/data",
    "frameworks/data",
    "data/seeds",
    "Inputs",
)

# Single-file allowlist beyond the watched dirs.
_EXTRA_TRACKED: frozenset[str] = frozenset({"data/glossary_master.json"})

# Exclusions: paths under watched dirs that intentionally have no consumer.
_EXCLUDED: frozenset[str] = frozenset(
    {
        "pipeline/data/.gitkeep",
    }
)


def _repo_root() -> Path:
    env = os.environ.get("CONSUMER_MAP_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def _tracked_files(root: Path) -> list[str]:
    """Return git-tracked files. Falls back to a filesystem walk when git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        files = [line for line in result.stdout.splitlines() if line.strip()]
        if files:
            return files
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # Filesystem fallback (used by tests with a synthetic tmp_path).
    out: list[str] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(str(p.relative_to(root)))
    return out


def _consumed_artifacts(root: Path) -> set[str]:
    path = root / "data" / "_consumers.jsonl"
    if not path.exists():
        return set()
    consumed: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        artifact = row.get("artifact_path")
        if isinstance(artifact, str):
            consumed.add(artifact)
    return consumed


def _is_watched(path: str) -> bool:
    if path in _EXCLUDED:
        return False
    if path in _EXTRA_TRACKED:
        return True
    return any(path.startswith(d + "/") for d in _WATCHED_DIRS)


def find_orphans(root: Path | None = None) -> list[Path]:
    """Return the list of watched, tracked files without a consumer entry."""
    r = root if root is not None else _repo_root()
    tracked = _tracked_files(r)
    consumed = _consumed_artifacts(r)
    orphans: list[Path] = []
    for f in tracked:
        if _is_watched(f) and f not in consumed:
            orphans.append(Path(f))
    return sorted(orphans)


def main(argv: list[str] | None = None) -> int:
    _ = argv  # currently no flags
    root = _repo_root()
    orphans = find_orphans(root)
    if not orphans:
        print("[consumer-map] OK — no orphan artifacts under watched dirs.")
        return 0
    print("[consumer-map] FAIL — orphan artifacts found (no consumer declared):")
    for o in orphans:
        print(f"  - {o}")
    print()
    print("Fix one of:")
    print("  1. Add a row to data/_consumers.jsonl describing the consumer.")
    print("  2. Move the file to data/_attic/ if it is intentionally unused.")
    print("  3. Add it to _EXCLUDED in scripts/check_consumer_map.py with justification.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
