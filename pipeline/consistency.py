"""Cross-phase consistency checker — detect_drift.

Pure Python. No LLM imports. No network I/O.

Public API:
  detect_drift(phase_paths) -> dict[str, str | list[str]]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

# Minimum number of sidecars that must supply a field before drift is checkable.
_MIN_SOURCES_FOR_DRIFT_CHECK: int = 2

# Fields tracked across sidecars, and which sidecar names supply each.
_FIELD_SOURCES: dict[str, list[str]] = {
    "protagonist_name": ["seed", "draft_v0", "challenge"],
    "genre": ["seed", "research", "draft_v0", "amplification", "genius"],
}

# Severity thresholds.
_SEVERITY_HIGH_THRESHOLD: int = 3
_SEVERITY_MAP: dict[int, str] = {0: "none", 1: "low", 2: "medium"}


def _load(path: Path) -> dict[str, object]:
    """Load a JSON sidecar; return {} on missing or parse error."""
    try:
        data: Any = json.loads(path.read_text())
        if isinstance(data, dict):
            return cast(dict[str, object], data)
        return {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def detect_drift(phase_paths: dict[str, Path]) -> dict[str, str | list[str]]:
    """Detect cross-phase drift in canonical fields.

    Returns:
        verdict: "CONSISTENT" | "DRIFT"
        drift_fields: list of field names that drifted
        severity: "none" | "low" | "medium" | "high"
        suggested_resolutions: list of plain-English patch suggestions
    """
    sidecars: dict[str, dict[str, object]] = {
        name: _load(path) for name, path in phase_paths.items()
    }

    drift_fields: list[str] = []
    resolutions: list[str] = []

    for field, sources in _FIELD_SOURCES.items():
        values: dict[str, str] = {
            src: str(sidecars[src][field]).strip().lower()
            for src in sources
            if src in sidecars and field in sidecars[src]
        }
        if len(values) < _MIN_SOURCES_FOR_DRIFT_CHECK:
            continue

        unique = set(values.values())
        if len(unique) > 1:
            drift_fields.append(field)
            by_sidecar = ", ".join(f"{s}={v!r}" for s, v in values.items())
            resolutions.append(
                f"Reconcile '{field}' across phases — found: {by_sidecar}. "
                f"Use seed.json value as canonical."
            )

    n = len(drift_fields)
    severity = "high" if n >= _SEVERITY_HIGH_THRESHOLD else _SEVERITY_MAP.get(n, "medium")

    return {
        "verdict": "DRIFT" if drift_fields else "CONSISTENT",
        "drift_fields": drift_fields,
        "severity": severity,
        "suggested_resolutions": resolutions,
    }
