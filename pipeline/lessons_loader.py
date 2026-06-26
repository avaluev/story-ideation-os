"""pipeline/lessons_loader.py — Load prior-run failure summaries for Phase 0 negative prompts.

Scans all runs/ subdirectories for lessons.json files, collects key_failures
strings, and returns the most-recent unique items so the seed generator can
avoid repeating known failure modes.

MUST NOT import anthropic, httpx, or openrouter_client (ANOMALY-001).
All I/O uses standard library only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

_RUNS_DIR = Path("runs")
_LESSONS_FILENAME = "lessons.json"


def _find_lesson_files(root: Path) -> list[tuple[float, Path]]:
    """Return (mtime, path) pairs for every lessons.json found under root."""
    pairs: list[tuple[float, Path]] = []
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        for candidate in (
            run_dir / _LESSONS_FILENAME,
            run_dir / "_trail" / _LESSONS_FILENAME,
        ):
            if candidate.is_file():
                pairs.append((candidate.stat().st_mtime, candidate))
                break
    return pairs


def _read_failures(path: Path) -> list[str]:
    """Parse lessons.json and return the key_failures list (strings only)."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.debug("lessons_loader: skipping %s — %s", path, exc)
        return []
    if not isinstance(raw, dict):
        return []
    failures: object = raw.get("key_failures") or []  # type: ignore[union-attr]
    if not isinstance(failures, list):
        return []
    return [item for item in failures if isinstance(item, str)]  # type: ignore[union-attr]


def load_failures(
    run_root: Path | None = None,
    max_items: int = 5,
) -> list[str]:
    """Collect key_failures from all lessons.json files across prior runs.

    Scans `run_root` (defaults to `runs/`) for subdirectories that contain a
    `lessons.json` file with a `key_failures` list. Returns at most `max_items`
    unique failure summaries, ordered newest-run-first (by directory mtime).

    Returns an empty list when no lessons exist (first-run case) — callers
    must treat [] as a no-op, not an error.
    """
    root = Path(run_root) if run_root is not None else _RUNS_DIR
    if not root.is_dir():
        return []

    lesson_files = sorted(_find_lesson_files(root), key=lambda t: t[0], reverse=True)
    if not lesson_files:
        return []

    seen: set[str] = set()
    results: list[str] = []
    for _mtime, path in lesson_files:
        if len(results) >= max_items:
            break
        for raw_item in _read_failures(path):
            stripped = raw_item.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                results.append(stripped)
                if len(results) >= max_items:
                    break

    return results
