"""Unit tests for scripts/amplify_loop.py — the EN amplify loop's deterministic referee.

Offline, deterministic, no network, no LLM. Covers the honesty-critical paths:
worklist-scoped manifest, subject-binding (the off-scope deep-link guard),
assess+merge density lift, the converge state machine, the $-frozen render abort,
the below-gate ledger, and quota recording.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.campaign_goal import load_campaign_goal
from pipeline.veracity.enumerate import enumerate_claims
from pipeline.veracity.scorecard import CredibilityScore
from scripts import amplify_loop as al

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

#: A minimal but structurally faithful card: one unlinked comp (the worklist
#: target), one already-linked comp, a linked TAM, and python_executed SAM/SOM.
CARD = """# Irreversible

## Comparables

| Title | Year | WW Revenue | Budget | ROI | Notes |
|---|---|---|---|---|---|
| Blade Runner 2049 | 2017 | $277.9M | $150M | 0.85x | Comp. |
| [The Tourist](https://boxofficemojo.com/title/tt124/) | 2010 | $278.8M | $100M | 1.8x | Comp. |

## Economics — Methodology & Provenance

| Layer | Value | Basis |
|---|---|---|
| **TAM** | $157.10B | Content market — [Ampere](https://mediaplaynews.com/ampere-2025/). |
| **SAM** | $3.14B | `python_executed` derivation (2% of $157.10B TAM). |
| **SOM (Year 1)** | $166M | `python_executed` from the comparables; lifetime $166M. |
"""

STEM = "19_irreversible_EN"


def _claim_id(card: str, claim_type: str, anchor_substr: str) -> str:
    for c in enumerate_claims(card, concept_id=STEM, concept_title="Irreversible"):
        if c.claim_type == claim_type and anchor_substr.lower() in c.anchor.lower():
            return c.claim_id
    raise AssertionError(f"no {claim_type} claim matching {anchor_substr!r}")


@pytest.fixture
def card_path(tmp_path: Path) -> Path:
    p = tmp_path / "EN" / f"{STEM}.md"
    p.parent.mkdir(parents=True)
    p.write_text(CARD, encoding="utf-8")
    return p


def _score(**kw: object) -> CredibilityScore:
    base: dict[str, object] = {
        "composite": 95.0,
        "grade": "A",
        "n_total": 5,
        "n_external": 3,
        "n_computed": 2,
        "claim_density_pct": 85.0,
        "fabricated_count": 0,
        "mode": "online",
    }
    base.update(kw)
    return CredibilityScore(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def test_slug_from_stem() -> None:
    assert al.slug_from_stem("19_irreversible_EN") == "19_irreversible"
    assert al.slug_from_stem("01_husbandry_RU") == "01_husbandry"
    assert al.slug_from_stem("12_ledger") == "12_ledger"


def test_deep_link_count() -> None:
    assert al.deep_link_count(CARD) == 2  # The Tourist + Ampere
    assert al.deep_link_count("no links here") == 0


def test_title_of() -> None:
    assert al.title_of(CARD, "fallback") == "Irreversible"
    assert al.title_of("no heading", "fallback") == "fallback"


# --------------------------------------------------------------------------- #
# Round manifest (worklist scope)
# --------------------------------------------------------------------------- #


def test_build_round_manifest_full_returns_all_external(card_path: Path) -> None:
    m = al.build_round_manifest(card_path, scope="full")
    # 3 external: TAM + 2 comps (SAM/SOM are computed, excluded by build_manifest)
    assert len(m["claims"]) == 3
    types = sorted(c["claim_type"] for c in m["claims"])
    assert types == ["comp_roi", "comp_roi", "market_tam"]


def test_build_round_manifest_worklist_filters(card_path: Path) -> None:
    worklist = {
        "19_irreversible": [
            {"type": "comp_roi", "snippet": "Blade Runner 2049 grossed $277.9M worldwide"},
        ]
    }
    m = al.build_round_manifest(card_path, scope="worklist", worklist=worklist)
    assert len(m["claims"]) == 1
    assert m["claims"][0]["claim_type"] == "comp_roi"
    assert "Blade Runner 2049" in m["claims"][0]["text"]


def test_build_round_manifest_only_ids_restricts(card_path: Path) -> None:
    keep = _claim_id(CARD, "comp_roi", "Blade Runner")
    m = al.build_round_manifest(card_path, scope="full", only_ids={keep})
    assert [c["claim_id"] for c in m["claims"]] == [keep]


def test_build_round_manifest_rejects_unknown_scope(card_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown scope"):
        al.build_round_manifest(card_path, scope="bogus")


# --------------------------------------------------------------------------- #
# Subject-binding — the off-scope deep-link guard (plan §4)
# --------------------------------------------------------------------------- #


def test_subject_bind_keeps_comp_with_title_in_quote() -> None:
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    claims = {c.claim_id: c for c in enumerate_claims(CARD, concept_id=STEM)}
    judgments = {
        cid: {
            "supports": True,
            "url": "https://www.boxofficemojo.com/title/tt1856101/",
            "quote": "Blade Runner 2049 grossed $277,965,733 worldwide",
        }
    }
    res = al.subject_bind(judgments, claims)
    assert cid in res.bound
    assert res.dropped == []


def test_subject_bind_drops_offscope_comp() -> None:
    """A comp number with no co-located film title is the off-scope cheat -> drop."""
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    claims = {c.claim_id: c for c in enumerate_claims(CARD, concept_id=STEM)}
    judgments = {
        cid: {
            "supports": True,
            "url": "https://www.boxofficemojo.com/year/2017/",
            "quote": "the film grossed $277,965,733 worldwide that year",  # no title
        }
    }
    res = al.subject_bind(judgments, claims)
    assert cid not in res.bound
    assert len(res.dropped) == 1
    assert res.dropped[0]["claim_id"] == cid


def test_subject_bind_keeps_comp_on_single_film_url_without_title_in_quote() -> None:
    """A value-verified comp on a single-film deep path binds by URL: keep it even
    when the bare 'Worldwide $X' quote omits the title (off-scope is impossible on
    a one-film page — the BOM /title/, /release/ and The Numbers /movie/ pages)."""
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    claims = {c.claim_id: c for c in enumerate_claims(CARD, concept_id=STEM)}
    for url in (
        "https://www.boxofficemojo.com/title/tt1856101/",
        "https://www.boxofficemojo.com/release/rl1649182209/",
        "https://www.the-numbers.com/movie/Blade-Runner-2049",
    ):
        judgments = {cid: {"supports": True, "url": url, "quote": "Worldwide $277,965,733"}}
        res = al.subject_bind(judgments, claims)
        assert cid in res.bound, url
        assert res.dropped == []


def test_is_single_film_page_excludes_multi_title_pages() -> None:
    assert al.is_single_film_page("https://www.boxofficemojo.com/title/tt0102926/")
    assert al.is_single_film_page("https://www.boxofficemojo.com/release/rl1649182209/")
    assert al.is_single_film_page("https://www.the-numbers.com/movie/Batman")
    # multi-title / non-film pages must STILL require co-location -> not single-film
    assert not al.is_single_film_page("https://www.boxofficemojo.com/year/2017/")
    assert not al.is_single_film_page("https://www.boxofficemojo.com/chart/top_lifetime_gross/")
    assert not al.is_single_film_page("https://news.gallup.com/poll/651881/x.aspx")
    assert not al.is_single_film_page("")


def test_subject_bind_passes_non_comp_claims() -> None:
    cid = _claim_id(CARD, "market_tam", "157")
    claims = {c.claim_id: c for c in enumerate_claims(CARD, concept_id=STEM)}
    judgments = {cid: {"supports": True, "url": "https://example.gov/x", "quote": "no title"}}
    res = al.subject_bind(judgments, claims)
    assert cid in res.bound  # non-comp claims are not subject-bound


def test_subject_bind_flags_low_tier_survivor() -> None:
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    claims = {c.claim_id: c for c in enumerate_claims(CARD, concept_id=STEM)}
    judgments = {
        cid: {
            "supports": True,
            "url": "https://some-random-blog.example/post",  # tier 5
            "quote": "Blade Runner 2049 grossed $277,965,733 worldwide",
        }
    }
    res = al.subject_bind(judgments, claims)
    assert cid in res.bound
    assert len(res.flagged) == 1
    assert res.flagged[0]["claim_id"] == cid


# --------------------------------------------------------------------------- #
# score_card — merge lifts SUPPORTED -> VERIFIED, raising density
# --------------------------------------------------------------------------- #


def test_score_card_structural_has_zero_verified() -> None:
    score = al.score_card(CARD, {}, stem=STEM, title="Irreversible")
    assert score.claim_density_pct == 0.0  # nothing agent-confirmed yet


def test_score_card_merge_lifts_density() -> None:
    """Sourcing every external claim with agent support drives density to 100%."""
    judgments = {}
    for ctype, sub in (
        ("comp_roi", "Blade Runner"),
        ("comp_roi", "Tourist"),
        ("market_tam", "157"),
    ):
        judgments[_claim_id(CARD, ctype, sub)] = {
            "supports": True,
            "url": "https://www.boxofficemojo.com/x/",
            "quote": "grossed worldwide",
        }
    rendered = al.render_inline(CARD, judgments, concept_id=STEM)  # link the unlinked comp
    score = al.score_card(rendered, judgments, stem=STEM, title="Irreversible")
    assert score.claim_density_pct == 100.0
    assert score.grade == "A"
    assert score.fabricated_count == 0
    assert score.mode == "online"


# --------------------------------------------------------------------------- #
# converge — the deterministic stop machine (plan §3 step 6)
# --------------------------------------------------------------------------- #


def test_converge_done_when_dod_met() -> None:
    goal = load_campaign_goal()
    decision, _ = al.converge(
        _score(), deep_links=12, unsourced_history=[3, 1, 0], round_idx=2, goal=goal
    )
    assert decision == al.CONVERGE_DONE


def test_converge_not_done_below_link_floor() -> None:
    goal = load_campaign_goal()
    decision, _ = al.converge(
        _score(), deep_links=11, unsourced_history=[3, 2, 1], round_idx=2, goal=goal
    )
    assert decision == al.CONVERGE_CONTINUE


def test_converge_stop_at_l2_cap() -> None:
    goal = load_campaign_goal()
    low = _score(grade="C", claim_density_pct=40.0)
    decision, reason = al.converge(
        low, deep_links=5, unsourced_history=[2, 2], round_idx=5, goal=goal
    )
    assert decision == al.CONVERGE_STOP_BELOW_GATE
    assert "L2" in reason


def test_converge_stop_on_two_round_stall() -> None:
    goal = load_campaign_goal()
    low = _score(grade="C", claim_density_pct=40.0)
    decision, _ = al.converge(
        low, deep_links=5, unsourced_history=[3, 3, 3], round_idx=2, goal=goal
    )
    assert decision == al.CONVERGE_STOP_BELOW_GATE


def test_converge_continue_when_progressing() -> None:
    goal = load_campaign_goal()
    low = _score(grade="C", claim_density_pct=40.0)
    decision, _ = al.converge(
        low, deep_links=5, unsourced_history=[5, 4, 3], round_idx=2, goal=goal
    )
    assert decision == al.CONVERGE_CONTINUE


# --------------------------------------------------------------------------- #
# apply_round — full integration on a tmp card
# --------------------------------------------------------------------------- #


def test_apply_round_links_comp_and_checkpoints(card_path: Path, tmp_path: Path) -> None:
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    judgments = {
        cid: {
            "supports": True,
            "url": "https://www.boxofficemojo.com/title/tt1856101/",
            "quote": "Blade Runner 2049 grossed $277,965,733 worldwide",
            "date": "2017",
        }
    }
    out_dir = tmp_path / "_loop"
    record = al.apply_round(
        card_path,
        judgments,
        scope="full",
        worklist={},
        round_idx=1,
        prior_unsourced=[],
        out_dir=out_dir,
    )
    # The unlinked comp is now linked in the on-disk card (checkpointed).
    updated = card_path.read_text(encoding="utf-8")
    assert "[Blade Runner 2049](https://www.boxofficemojo.com/title/tt1856101/)" in updated
    assert record["bound_count"] == 1
    assert record["dropped"] == []
    assert (out_dir / "19_irreversible.loop.json").exists()
    # $ figures are frozen — count of $ tokens unchanged after render.
    assert al._LINK_COUNT_RE.findall(updated)  # links present


def test_apply_round_dollar_guard_is_respected(card_path: Path, tmp_path: Path) -> None:
    """render_inline never alters a $ token; apply_round completes without raising."""
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    judgments = {
        cid: {
            "supports": True,
            "url": "https://www.boxofficemojo.com/title/tt1856101/",
            "quote": "Blade Runner 2049 grossed $277,965,733 worldwide",
        }
    }
    before_dollars = CARD.count("$")
    al.apply_round(
        card_path,
        judgments,
        scope="full",
        worklist={},
        round_idx=1,
        prior_unsourced=[],
        out_dir=tmp_path / "_loop",
    )
    assert card_path.read_text(encoding="utf-8").count("$") == before_dollars


# --------------------------------------------------------------------------- #
# below-gate ledger + quota
# --------------------------------------------------------------------------- #


def test_write_below_gate_records_blockers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    led = tmp_path / "_below_gate.json"
    monkeypatch.setattr(al, "BELOW_GATE_PATH", led)
    claims = {c.claim_id: c for c in enumerate_claims(CARD, concept_id=STEM)}
    cid = _claim_id(CARD, "comp_roi", "Blade Runner")
    record = {
        "round": 5,
        "grade": "C",
        "claim_density_pct": 40.0,
        "deep_links": 5,
        "reason": "reached L2 round cap (5)",
        "verdict_counts": {"SUPPORTED": 2},
        "still_unsourced": [cid],
    }
    al.write_below_gate("19_irreversible", record, claims, {})
    data = json.loads(led.read_text(encoding="utf-8"))
    assert data["19_irreversible"]["gate_met"] is False
    assert cid in data["19_irreversible"]["blockers"]


def test_record_round_quota_routes_tiers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qlog = tmp_path / "quota.jsonl"
    monkeypatch.setattr(al.quota, "QUOTA_LOG", qlog)
    al.record_round_quota(
        {"finder_model": "sonnet", "refuter_model": "opus", "find_agents": 3, "verify_agents": 2},
        run_id="testrun",
    )
    rows = [
        json.loads(line) for line in qlog.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    models = sorted(r["model"] for r in rows)
    assert models == ["opus", "sonnet"]
    sonnet_row = next(r for r in rows if r["model"] == "sonnet")
    assert sonnet_row["tokens_in"] == 3 * al._EST_TOKENS_IN_PER_AGENT
