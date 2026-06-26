"""Unit test for KNOW-05: pipeline/data/oblique_strategies.json schema + cardinality + determinism.

Cardinality is strict-equality locked via EXPECTED_DECK_SIZE imported from the builder
(revision-2 H7) — `len(deck) == EXPECTED_DECK_SIZE`, NOT `>= 80`. Floor (>=80) is enforced
in the builder's module-load assert.

References:
- frameworks/forced-collision.md §Eno Oblique Strategies Hook (the runtime consumer)
- scripts/build_oblique_strategies.py (the deterministic builder)
- .planning/phases/01-knowledge-layer/01-RESEARCH.md §Eno Oblique Strategies
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_oblique_strategies import EXPECTED_DECK_SIZE

DATA_PATH = Path("pipeline/data/oblique_strategies.json")
BUILDER_PATH = Path("scripts/build_oblique_strategies.py")
EXPECTED_LICENSE = (
    "© Brian Eno & Peter Schmidt 1975, 1978, 1979 — included with attribution; "
    "transformative use only (LLM creativity prompt)"
)


@pytest.fixture(scope="module")
def deck_data() -> dict:
    assert DATA_PATH.exists(), f"{DATA_PATH} missing — run scripts/build_oblique_strategies.py"
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_top_level_schema(deck_data: dict) -> None:
    """Top-level keys present per the documented schema (RESEARCH §Eno)."""
    for key in ("schema_version", "license", "source_attestation", "deck"):
        assert key in deck_data, f"missing top-level key: {key}"


def test_license_is_exact_attribution(deck_data: dict) -> None:
    """License field must be the operator-confirmed attribution string."""
    assert deck_data["license"] == EXPECTED_LICENSE, (
        f"License drift: got {deck_data['license']!r}, expected {EXPECTED_LICENSE!r}. "
        f"Review with operator before changing."
    )


def test_deck_size_equals_expected(deck_data: dict) -> None:
    """KNOW-05 (revision-2 H7): len(deck) == EXPECTED_DECK_SIZE (strict equality lock)."""
    assert len(deck_data["deck"]) == EXPECTED_DECK_SIZE, (
        f"Cardinality drift: deck has {len(deck_data['deck'])} cards; "
        f"EXPECTED_DECK_SIZE = {EXPECTED_DECK_SIZE} "
        "(locked in scripts/build_oblique_strategies.py). "
        "If the deck count is supposed to change, update "
        "_CARDS_RAW + EXPECTED_DECK_SIZE in the same commit."
    )


def test_card_schema(deck_data: dict) -> None:
    """Each card has id, text, source_edition, tags, year_first_appeared with correct types."""
    for card in deck_data["deck"]:
        assert isinstance(card.get("id"), int)
        assert isinstance(card.get("text"), str) and len(card["text"]) > 0
        assert isinstance(card.get("source_edition"), list)
        assert all(isinstance(e, str) for e in card["source_edition"])
        assert isinstance(card.get("tags"), list)
        assert isinstance(card.get("year_first_appeared"), int)


def test_card_ids_are_unique(deck_data: dict) -> None:
    """Stable IDs must be unique."""
    ids = [c["id"] for c in deck_data["deck"]]
    assert len(set(ids)) == len(ids), "duplicate card IDs detected"


def test_builder_is_deterministic(deck_data: dict) -> None:
    """Builder --dry-run output must equal the on-disk JSON (determinism check)."""
    assert BUILDER_PATH.exists(), f"{BUILDER_PATH} missing"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(BUILDER_PATH), "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )
    rebuilt = json.loads(result.stdout)
    assert rebuilt == deck_data, (
        "Builder output diverged from on-disk file. "
        "Either re-run scripts/build_oblique_strategies.py to regenerate, "
        "or audit _CARDS_RAW in the builder for a hand-edit."
    )
