"""Unit tests for scripts/ru_pipeline.py — the deterministic RU-pipeline referee.

Offline, no network, no LLM, no API key. Covers the integrity-critical paths:
sentinel protect/restore round-trip, the parity guarantee under a simulated
translation, glossary upsert + versioning, and task init / apply (parity gate).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import ru_pipeline as rp

CARD = """# Husbandry

#### Logline
An engineer eases a living world's pain.

# 1. Market & Audience

The total addressable market is $328.2 billion ([MPA](https://www.motionpictures.org/x.pdf)).

| Title | WW Revenue | ROI |
|---|---|---|
| [Ghost](https://www.boxofficemojo.com/title/tt0099653/) | $505.0M | 22.0x |

**SOM (Year 1):** $675M
"""


# ── protect / restore (pure) ─────────────────────────────────────────────────


def test_protect_restore_roundtrip_is_byte_identical() -> None:
    prot, store = rp.protect(CARD)
    assert rp.restore(prot, store) == CARD


def test_protect_makes_heading_url_money_sentinels() -> None:
    prot, store = rp.protect(CARD)
    assert "@@H0@@ Husbandry" in prot  # the title marker is protected at line start
    assert any(k.startswith("@@U") for k in store)
    assert any(k.startswith("@@D") for k in store)
    # the two real link URLs survive as protected values
    assert "https://www.boxofficemojo.com/title/tt0099653/" in store.values()


def test_simulated_translation_preserves_parity() -> None:
    prot, store = rp.protect(CARD)
    # a GOOD translation keeps every sentinel, only changes prose
    sim = prot.replace("An engineer eases a living world's pain.", "Инженер облегчает боль мира.")
    sim = sim.replace("Market & Audience", "Рынок и аудитория")
    assert rp.check_parity(CARD, rp.restore(sim, store)).passed


def test_dropped_dollar_fails_parity() -> None:
    prot, store = rp.protect(CARD)
    broken = prot.replace("@@D", "@@X", 1)  # corrupt one $ sentinel -> $ goes missing on restore
    assert not rp.check_parity(CARD, rp.restore(broken, store)).passed


# ── glossary ─────────────────────────────────────────────────────────────────


@pytest.fixture
def _amp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    en, ru, tasks, glo = (tmp_path / d for d in ("EN", "RU", "_ru_tasks", "_glossary"))
    en.mkdir()
    monkeypatch.setattr(rp, "EN_DIR", en)
    monkeypatch.setattr(rp, "RU_DIR", ru)
    monkeypatch.setattr(rp, "TASKS_DIR", tasks)
    monkeypatch.setattr(rp, "GLOSSARY_DIR", glo)
    monkeypatch.setattr(rp, "GLOSSARY_PATH", glo / "terms_en_ru.json")
    monkeypatch.setattr(rp, "PROPOSALS_DIR", glo / "proposals")
    (en / "01_husbandry_EN.md").write_text(CARD, encoding="utf-8")
    return tmp_path


def test_seed_then_merge_canonical_bumps_version(_amp: Path) -> None:
    g = rp.seed_glossary()
    assert g["version"] == 1
    assert "worldwide gross" in g["terms"]
    g2 = rp.merge_canonical([{"en": "third door", "ru": "третья дверь", "domain": "story"}])
    assert g2["version"] == 2
    assert g2["terms"]["third door"]["ru"] == "третья дверь"
    # re-merging the identical decision does NOT bump the version
    assert rp.merge_canonical([{"en": "third door", "ru": "третья дверь"}])["version"] == 2


def test_render_glossary_block_lists_seed_terms(_amp: Path) -> None:
    rp.seed_glossary()
    block = rp.render_glossary_block()
    assert "worldwide gross → мировые сборы" in block


# ── tasks + apply ────────────────────────────────────────────────────────────


def test_init_tasks_creates_one_file_per_card(_amp: Path) -> None:
    assert rp.init_tasks() == 1
    t = rp.load_task("01_husbandry")
    assert t["status"] == "pending"
    assert t["stages"]["translate"]["model"] == "sonnet"
    assert (rp.TASKS_DIR / "INDEX.md").exists()


def test_apply_good_translation_passes_and_writes_ru(_amp: Path) -> None:
    rp.seed_glossary()
    rp.init_tasks()
    rp.card_prompt("01_husbandry")  # writes payload + store
    prot = (rp.TASKS_DIR / "01_husbandry.payload.md").read_text(encoding="utf-8")
    # extract the protected markdown the agent would translate, change only prose
    body = prot.split("BEGIN MARKDOWN TO TRANSLATE -----\n", 1)[1]
    ru_in = body.replace("An engineer eases a living world's pain.", "Инженер облегчает боль.")
    res = rp.apply_translation("01_husbandry", ru_in)
    assert res["passed"]
    assert (rp.RU_DIR / "01_husbandry_RU.md").exists()
    assert rp.load_task("01_husbandry")["stages"]["parity"]["status"] == "pass"


def test_apply_bad_translation_fails_and_parks_failed(_amp: Path) -> None:
    rp.seed_glossary()
    rp.init_tasks()
    rp.card_prompt("01_husbandry")
    res = rp.apply_translation("01_husbandry", "completely unrelated text with no sentinels")
    assert not res["passed"]
    assert (rp.RU_DIR / "01_husbandry_RU.FAILED.md").exists()
    assert not (rp.RU_DIR / "01_husbandry_RU.md").exists()
