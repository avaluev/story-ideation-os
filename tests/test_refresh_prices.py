"""tests/test_refresh_prices.py — RED/GREEN tests for OPS-02 price diff detection.

Tests scripts/refresh_prices.py behavior:
- no diff → exit 0
- diff detected (prompt price changed) → exit 1
- model missing from OpenRouter response → exit 1

Uses monkeypatch to mock httpx.get to avoid real network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# scripts.refresh_prices does not exist yet in RED state — ImportError expected
# pipeline.openrouter_client.MODELS is available
from pipeline.openrouter_client import MODELS

# ---------------------------------------------------------------------------
# Helpers: build a mock httpx response
# ---------------------------------------------------------------------------


def _make_mock_response(models_data: list[dict]) -> MagicMock:
    """Build a mock httpx.Response wrapping an OpenRouter /models payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": models_data}
    return mock_resp


def _openrouter_model(model_id: str, prompt: str, completion: str) -> dict:
    """Build an OpenRouter /api/v1/models data entry."""
    return {
        "id": model_id,
        "pricing": {
            "prompt": prompt,
            "completion": completion,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_diff_exits_0() -> None:
    """When all MODELS IDs have matching pricing in the API response, exits 0."""
    from scripts.refresh_prices import main as refresh_main  # noqa: PLC0415

    # Build an OpenRouter response that matches the stored MODELS pricing exactly.
    # MODELS stores values as floats (input_usd_per_1m), while OpenRouter returns
    # pricing.prompt as a string in dollars-per-token (1/1_000_000 scale).
    or_models = []
    for model_id, price_info in MODELS.items():
        prompt_per_token = price_info["input_usd_per_1m"] / 1_000_000
        completion_per_token = price_info["output_usd_per_1m"] / 1_000_000
        or_models.append(
            _openrouter_model(model_id, str(prompt_per_token), str(completion_per_token))
        )

    with patch("scripts.refresh_prices.httpx") as mock_httpx:
        mock_httpx.get.return_value = _make_mock_response(or_models)
        result = refresh_main()

    assert result == 0, "Expected exit 0 when no pricing diff found"


def test_diff_detected_exits_1(capsys: pytest.CaptureFixture) -> None:
    """When a free model has pricing.prompt != '0', exits 1 and reports diff."""
    from scripts.refresh_prices import main as refresh_main  # noqa: PLC0415

    or_models = []
    for model_id, price_info in MODELS.items():
        prompt_per_token = price_info["input_usd_per_1m"] / 1_000_000
        completion_per_token = price_info["output_usd_per_1m"] / 1_000_000
        or_models.append(
            _openrouter_model(model_id, str(prompt_per_token), str(completion_per_token))
        )

    # Mutate a :free model to have non-zero pricing (lost free tier)
    free_model = next((m for m in or_models if m["id"].endswith(":free")), None)
    if free_model is None:
        pytest.skip("No :free model in MODELS registry — test not applicable")

    free_model["pricing"]["prompt"] = "0.000001"  # no longer free

    with patch("scripts.refresh_prices.httpx") as mock_httpx:
        mock_httpx.get.return_value = _make_mock_response(or_models)
        result = refresh_main()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert result == 1, "Expected exit 1 when free model loses free tier"
    assert "DIFF" in combined or "diff" in combined.lower(), (
        f"Expected diff output, got: {combined!r}"
    )


def test_missing_model_exits_1(capsys: pytest.CaptureFixture) -> None:
    """When a MODELS key is absent from OpenRouter response, exits 1."""
    from scripts.refresh_prices import main as refresh_main  # noqa: PLC0415

    model_ids = list(MODELS.keys())
    if not model_ids:
        pytest.skip("MODELS registry is empty — test not applicable")

    excluded_id = model_ids[0]
    or_models = []
    for model_id, price_info in MODELS.items():
        if model_id == excluded_id:
            continue  # intentionally omit
        prompt_per_token = price_info["input_usd_per_1m"] / 1_000_000
        completion_per_token = price_info["output_usd_per_1m"] / 1_000_000
        or_models.append(
            _openrouter_model(model_id, str(prompt_per_token), str(completion_per_token))
        )

    with patch("scripts.refresh_prices.httpx") as mock_httpx:
        mock_httpx.get.return_value = _make_mock_response(or_models)
        result = refresh_main()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert result == 1, "Expected exit 1 when a model is absent from OpenRouter"
    assert (
        "missing" in combined.lower() or "absent" in combined.lower() or excluded_id in combined
    ), f"Expected missing model report, got: {combined!r}"
