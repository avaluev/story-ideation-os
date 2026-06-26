"""scripts/refresh_prices.py — OPS-02: Diff MODELS registry pricing vs OpenRouter API.

Fetches GET https://openrouter.ai/api/v1/models and compares each model's
pricing against the stored MODELS registry in pipeline/openrouter_client.py.

MODELS stores pricing as input_usd_per_1m / output_usd_per_1m (floats).
OpenRouter API returns pricing.prompt / pricing.completion as strings
representing dollars-per-token (i.e. value / 1_000_000 == usd_per_1m).

Exit 0 if no diff found.
Exit 1 if any pricing difference or missing model detected.

Usage:
    python scripts/refresh_prices.py
    python -m scripts.refresh_prices
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from pipeline.openrouter_client import MODELS

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_DIFF_OUT_DIR = Path("data")
_TOLERANCE = 1e-12  # float comparison tolerance for per-token price


def _usd_per_1m_from_api(per_token_str: str) -> float:
    """Convert OpenRouter per-token price string to usd_per_1m float."""
    try:
        return float(per_token_str) * 1_000_000
    except (ValueError, TypeError):
        return 0.0


def main() -> int:
    """Fetch OpenRouter /models, diff against MODELS registry. Exit 1 on diff."""
    try:
        resp = httpx.get(_OPENROUTER_MODELS_URL, timeout=30.0)
        resp.raise_for_status()
    except Exception as exc:
        print(f"ERROR: failed to fetch {_OPENROUTER_MODELS_URL}: {exc}", file=sys.stderr)
        return 1

    api_data: list[dict] = resp.json().get("data", [])
    api_by_id: dict[str, dict] = {m["id"]: m for m in api_data}

    diffs: list[str] = []

    for model_id, stored in MODELS.items():
        if model_id not in api_by_id:
            msg = f"DIFF missing_model: {model_id!r} not in OpenRouter response"
            diffs.append(msg)
            print(msg)
            continue

        api_pricing = api_by_id[model_id].get("pricing", {})
        api_input = _usd_per_1m_from_api(api_pricing.get("prompt", "0"))
        api_output = _usd_per_1m_from_api(api_pricing.get("completion", "0"))

        stored_input: float = stored.get("input_usd_per_1m", 0.0)
        stored_output: float = stored.get("output_usd_per_1m", 0.0)

        # Special check: :free models must remain free (pricing.prompt parses to 0.0)
        if (
            model_id.endswith(":free")
            and _usd_per_1m_from_api(api_pricing.get("prompt", "0")) != 0.0
        ):
            msg = (
                f"DIFF free_tier_lost: {model_id!r} — "
                f"stored=0.0 api_prompt={api_pricing.get('prompt')!r}"
            )
            diffs.append(msg)
            print(msg)
            continue

        if abs(api_input - stored_input) > _TOLERANCE:
            msg = f"DIFF input_price: {model_id!r} — stored={stored_input} api={api_input}"
            diffs.append(msg)
            print(msg)

        if abs(api_output - stored_output) > _TOLERANCE:
            msg = f"DIFF output_price: {model_id!r} — stored={stored_output} api={api_output}"
            diffs.append(msg)
            print(msg)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    _DIFF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _DIFF_OUT_DIR / f"refresh_prices_{ts}.txt"
    out_path.write_text("\n".join(diffs) + ("\n" if diffs else ""), encoding="utf-8")

    if diffs:
        print(f"{len(diffs)} diff(s) found — see {out_path}", file=sys.stderr)
        return 1

    print(f"No pricing diffs found. Report at {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
