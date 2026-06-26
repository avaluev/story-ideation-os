"""Subscription-quota tracker for Genius Engine v4.0.

ADR-0008: Opus weekly quota gates Phase-4 KeepBest promotion (supersedes the
ADR-0006 dollar-budget gate). All Task subagent dispatches that consume
LLM context are recorded here as append-only JSONL events; weekly burn is
computed deterministically from those events.

This module is pure-Python: no anthropic, no httpx, no openrouter_client
imports. Enforced by ANOMALY-001 in scripts/lint_imports.py.

Schema of one row in `data/quota.jsonl` (ADR-0001 append-only):

    {
        "ts": "2026-05-09T18:00:00+00:00",
        "model": "opus" | "sonnet" | "haiku",
        "tokens_in": 12345,
        "tokens_out": 678,
        "week_iso": "2026-W19",
        "run_id": "<uuid hex>",
        "phase": "miner" | "mapper" | "validator" | "forger" | "critic"
                 | "judge" | "formatter" | "mutation" | "other"
    }

Public surface:
    record(model, tokens_in, tokens_out, run_id, phase)
    consumed_this_week(model) -> int          # total tokens this ISO week
    remaining_fraction(model) -> float         # in [0.0, 1.0]
    gate(model, expected_tokens, floor=0.05) -> bool
    print_status() -> str                       # CLI helper for /genius

Tier caps are read from environment (override sensible defaults):
    OPUS_WEEKLY_TOKEN_CAP    (default  2_000_000)
    SONNET_WEEKLY_TOKEN_CAP  (default 20_000_000)
    HAIKU_WEEKLY_TOKEN_CAP   (default 100_000_000)

The caps are operator-tunable: Pro/Max/Team subscriptions expose different
weekly Opus ceilings; the operator overrides the default in `.env` or the
shell.

IMPORTANT — cap == 0 semantics:
    A zero cap does NOT silently disable gating (fail-open is a security risk
    that would allow unbounded token spend).  When cap == 0, gate() returns
    False (hard-fail) UNLESS the operator has explicitly set the environment
    variable  ANOMALY_QUOTA_DISABLED=1, which is the documented dev escape
    hatch for local test environments where no real tokens are consumed.
    remaining_fraction() still returns 1.0 for cap == 0 (no quota consumed).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pipeline.state import append_jsonl

_log = logging.getLogger(__name__)

QUOTA_LOG: Path = Path("data/quota.jsonl")

ModelTier = Literal["opus", "sonnet", "haiku"]
PhaseLabel = Literal[
    "miner",
    "mapper",
    "validator",
    "forger",
    "critic",
    "judge",
    "formatter",
    "mutation",
    "other",
]

_DEFAULT_CAPS: dict[str, int] = {
    "opus": 2_000_000,
    "sonnet": 20_000_000,
    "haiku": 100_000_000,
}


def _cap_for(model: ModelTier) -> int:
    """Return per-tier weekly token cap.

    A value of 0 triggers a hard-fail in gate() unless ANOMALY_QUOTA_DISABLED=1.
    """
    env_key = f"{model.upper()}_WEEKLY_TOKEN_CAP"
    raw = os.environ.get(env_key)
    if raw is None:
        return _DEFAULT_CAPS[model]
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_CAPS[model]


def _current_week_iso(now: datetime | None = None) -> str:
    """Return ISO week label like '2026-W19' for the given (or current) UTC time."""
    when = now or datetime.now(UTC)
    iso_year, iso_week, _ = when.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def record(
    model: ModelTier,
    tokens_in: int,
    tokens_out: int,
    run_id: str,
    phase: PhaseLabel,
) -> None:
    """Append one quota event to QUOTA_LOG. Pure JSONL; no rotation, no compaction."""
    if tokens_in < 0 or tokens_out < 0:
        raise ValueError("tokens_in and tokens_out must be non-negative")
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "model": model,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "week_iso": _current_week_iso(),
        "run_id": run_id,
        "phase": phase,
    }
    append_jsonl(QUOTA_LOG, row)


def consumed_this_week(model: ModelTier, now: datetime | None = None) -> int:
    """Sum tokens (in + out) for `model` in the current ISO week. Returns 0 if no log."""
    if not QUOTA_LOG.exists():
        return 0
    target = _current_week_iso(now)
    total = 0
    for line in QUOTA_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("week_iso") == target and row.get("model") == model:
            total += int(row.get("tokens_in", 0)) + int(row.get("tokens_out", 0))
    return total


def remaining_fraction(model: ModelTier, now: datetime | None = None) -> float:
    """Return remaining-week fraction in [0.0, 1.0]. Returns 1.0 if cap is 0 (disabled)."""
    cap = _cap_for(model)
    if cap == 0:
        return 1.0
    used = consumed_this_week(model, now=now)
    if used >= cap:
        return 0.0
    return max(0.0, 1.0 - (used / cap))


def gate(
    model: ModelTier,
    expected_tokens: int,
    floor: float = 0.05,
    now: datetime | None = None,
) -> bool:
    """Return True if dispatching `expected_tokens` keeps remaining > floor.

    cap == 0 special case:
        Without ANOMALY_QUOTA_DISABLED=1 in the environment this is a
        hard-fail (returns False and logs a loud WARNING).  Set
        ANOMALY_QUOTA_DISABLED=1 only in dev/test environments where no
        real LLM tokens are consumed.
    """
    if expected_tokens < 0:
        raise ValueError("expected_tokens must be non-negative")
    cap = _cap_for(model)
    if cap == 0:
        if os.environ.get("ANOMALY_QUOTA_DISABLED") == "1":
            return True
        _log.warning(
            "quota cap is 0 for model %r and ANOMALY_QUOTA_DISABLED is unset; "
            "refusing to fail-open — set ANOMALY_QUOTA_DISABLED=1 to bypass "
            "in dev/test environments",
            model,
        )
        return False
    used = consumed_this_week(model, now=now)
    after = used + expected_tokens
    if after >= cap:
        return False
    return ((cap - after) / cap) > floor


def print_status() -> str:
    """Return a one-paragraph status string for /genius pre-run banner."""
    lines = [f"Quota status (ISO week {_current_week_iso()}):"]
    quota_disabled = os.environ.get("ANOMALY_QUOTA_DISABLED") == "1"
    for tier in ("opus", "sonnet", "haiku"):
        cap = _cap_for(tier)  # type: ignore[arg-type]
        used = consumed_this_week(tier)  # type: ignore[arg-type]
        if cap == 0:
            if quota_disabled:
                lines.append(
                    f"  {tier:<6}: cap=0, ANOMALY_QUOTA_DISABLED=1 "
                    f"(dev bypass active; used {used:,} tokens this week)"
                )
            else:
                lines.append(
                    f"  {tier:<6}: cap=0, ANOMALY_QUOTA_DISABLED unset "
                    f"— gate() will hard-fail (used {used:,} tokens this week)"
                )
            continue
        pct = 100.0 * used / cap
        lines.append(f"  {tier:<6}: {used:>12,} / {cap:>12,} tokens ({pct:5.1f}% used)")
    return "\n".join(lines)


if __name__ == "__main__":
    print(print_status())
