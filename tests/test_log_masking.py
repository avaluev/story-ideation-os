"""SEC-07: Key prefixes MUST be masked to first 8 chars in all logs.

P0 ships interface contract only. P3 implements pipeline.openrouter_client._mask_key.
Full key-masking test = tests/test_openrouter_client.py::test_log_masks_keys (P4).

This stub documents the contract so:
- CLAUDE.md enforcer reference resolves (tests/test_log_masking.py exists)
- The test SKIPS cleanly in P0 (pipeline.openrouter_client not yet created)
- The test PASSES in P3+ once _mask_key is implemented
- CI does not fail pre-P3 (importorskip causes SKIP, not ERROR)
"""
import pytest


def test_mask_key_contract() -> None:
    """SEC-07: pipeline.openrouter_client._mask_key must exist and mask to <=12 chars.

    Contract:
    - Function signature: _mask_key(key: str) -> str
    - Input: full API key string (e.g. "sk-or-v1-AAAA12345BBBB...")
    - Output: masked string of length <= 12 (e.g. first 8 chars of prefix)
    - Purpose: prevent accidental key leakage in logs and stack traces

    This test SKIPS in P0 (pipeline.openrouter_client not created yet).
    This test PASSES in P3+ once pipeline/openrouter_client.py is implemented.

    See: ADR-0003 (3-key FIFO rotation), SEC-07, PIPE-02
    """
    m = pytest.importorskip(
        "pipeline.openrouter_client",
        reason="P3 implements; this stub documents SEC-07 contract.",
    )
    assert hasattr(m, "_mask_key"), (
        "pipeline.openrouter_client must export _mask_key\n"
        "Signature: _mask_key(key: str) -> str"
    )
    result = m._mask_key("sk-or-v1-AAAA12345BBBBccccddddeeeeffff111122223333")
    assert isinstance(result, str), f"_mask_key must return str, got {type(result)}"
    assert len(result) <= 12, (
        f"key prefix should be masked to <=12 chars, got {result!r} (len={len(result)})\n"
        "Example acceptable outputs: 'sk-or-v1-' (9 chars), 'sk-or-v1-*' (10 chars)"
    )
