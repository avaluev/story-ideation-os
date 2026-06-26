"""pipeline/micro_amplify.py — Per-phase micro-amplification step (Change 5).

After phases 2, 3, 5, and 6, a single Haiku prompt asks: "Given this sidecar,
propose ONE change that expands the addressable audience by >=20% without
altering the core premise." If the response cites a real comp and is not NONE,
the sidecar dict is updated in-place (in memory; caller is responsible for
writing to disk via safe_write).

The multiplier field records the self-reported audience expansion factor. It is
NOT a verified financial figure — it is a seed hint for the amplification loop.
Scoring (pipeline/scoring.py) never reads this field (ADR-0002 lock).

ADR-0007: model call is routed through openrouter_client (not direct httpx).
ADR-0001: caller must write updated sidecar to disk after apply() returns.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

_log = logging.getLogger(__name__)

_HAIKU_MODEL: str = "anthropic/claude-haiku-4.5"

_MULTIPLIER_FLOOR: float = 1.0
_MULTIPLIER_CAP: float = 5.0
_NONE_RESPONSES: frozenset[str] = frozenset({"NONE", "none", "None", "NONE.", "none."})

# Prompt split across continuation lines so no single source line exceeds 100 chars.
_PROMPT_TEMPLATE: str = (
    "You are a commercial audience expansion analyst. Read this concept sidecar.\n"
    "Propose exactly ONE change that would expand the addressable audience by at least 20%\n"
    "without altering the core premise, genre, or logline structure.\n"
    "\n"
    "Rules:\n"
    "1. If you propose a change, cite one real film or series as a comp"
    " (Title, Year, gross/audience).\n"
    "2. Estimate the audience expansion multiplier (1.2 to 5.0).\n"
    "3. If no such change exists or the concept is already maximally broad,"
    " respond with exactly: NONE\n"
    "\n"
    "Respond in JSON with keys: change (string or null), comp (string or null),"
    " multiplier (float), reason (string).\n"
    'If no change: {{"change": null, "comp": null, "multiplier": 1.0, "reason": "NONE"}}\n'
    "\n"
    "Sidecar:\n"
    "{sidecar_json}\n"
)


def _clamp_multiplier(raw: object) -> float:
    """Clamp multiplier to [_MULTIPLIER_FLOOR, _MULTIPLIER_CAP]."""
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _MULTIPLIER_FLOOR
    return max(_MULTIPLIER_FLOOR, min(_MULTIPLIER_CAP, v))


def apply(
    sidecar: dict[str, Any],
    *,
    phase_name: str = "unknown",
    enabled: bool = True,
) -> dict[str, Any]:
    """Attempt one micro-amplification pass on sidecar.

    Adds a `micro_amplification` block to sidecar and returns the (possibly
    updated) sidecar. Does NOT write to disk — caller handles safe_write.

    Args:
        sidecar: The phase sidecar dict (draft_v0, challenge, etc.).
        phase_name: Human-readable phase name for logging.
        enabled: If False, skip and add a no-op block.

    Returns:
        Updated sidecar dict with `micro_amplification` key added.
    """
    if not enabled:
        sidecar["micro_amplification"] = {
            "applied": False,
            "reason": "disabled",
            "multiplier": 1.0,
            "phase": phase_name,
        }
        return sidecar

    try:
        from pipeline.llm_client import build_chat_client  # noqa: PLC0415

        client = build_chat_client()
        sidecar_json = json.dumps(sidecar, indent=2, ensure_ascii=False)[:3000]
        prompt = _PROMPT_TEMPLATE.format(sidecar_json=sidecar_json)
        response = client.chat(
            model=_HAIKU_MODEL,
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        parsed = cast("dict[str, Any]", response)
    except Exception as exc:
        _log.warning("micro_amplify phase=%s failed: %s", phase_name, exc)
        sidecar["micro_amplification"] = {
            "applied": False,
            "reason": f"api_error: {exc!s:.80}",
            "multiplier": 1.0,
            "phase": phase_name,
        }
        return sidecar

    change = parsed.get("change")
    multiplier = _clamp_multiplier(parsed.get("multiplier", 1.0))
    reason = str(parsed.get("reason", "") or "")
    comp = str(parsed.get("comp", "") or "")

    is_none = (
        change is None or str(change).strip().upper() == "NONE" or reason.strip() in _NONE_RESPONSES
    )

    if is_none or multiplier <= _MULTIPLIER_FLOOR:
        sidecar["micro_amplification"] = {
            "applied": False,
            "reason": reason or "NONE",
            "multiplier": 1.0,
            "phase": phase_name,
        }
    else:
        note = f"[micro_amplify] {change}"
        if comp:
            note += f" (comp: {comp})"
        raw_notes: Any = sidecar.get("micro_amplify_notes", [])
        existing: list[str] = (
            list(cast("list[str]", raw_notes)) if isinstance(raw_notes, list) else []
        )
        sidecar["micro_amplify_notes"] = [*existing, note]
        sidecar["micro_amplification"] = {
            "applied": True,
            "reason": str(change),
            "comp": comp,
            "multiplier": multiplier,
            "phase": phase_name,
        }
        _log.info(
            "micro_amplify phase=%s: applied x%.2f (comp: %s)",
            phase_name,
            multiplier,
            comp,
        )

    return sidecar


__all__ = ["apply"]
