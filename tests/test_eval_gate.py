"""tests/test_eval_gate.py — NB.5-EVAL-CONSULT contract (Cycle 1 Session 6).

The eval gate previously lived as an inline ``python -c`` block inside
``.claude/skills/single-idea/SKILL.md`` STEP 10. NB.5-EVAL-CONSULT extracts
that logic to ``pipeline.eval_gate`` so:

1. The skill's eval step can be a one-liner
   (``uv run python -m pipeline.eval_gate --run-dir {run_dir}``), and
2. The 5-vector quality gate (``runs/{id}/quality.json``) finally has a
   downstream consumer.

Cycle-1 contract enforced here:

- Tier-1 gates (INTERNAL_IDS, SOM_BELOW_100M, TEMPLATE_NONCOMPLIANT)
  match the previous inline-Python behaviour exactly. No regression.
- quality.json is consulted when present and added under
  ``per_file[<md>].quality_overall_pass``.
- Cycle-1 default: a failed 5-vector gate surfaces as a *warning*
  (``warnings`` field), NOT a failure. Phase 3 challenger remains the
  canonical L1 patch trigger; quality.json is informational.
- ``--strict-quality`` flag (Cycle 2 toggle): when set, a 5-vector
  failure becomes ``QUALITY_GATE_FAIL`` in ``failures`` and flips the
  verdict to FAIL.
- Soft-fail: missing concept md → FAIL with ``CONCEPT_MD_MISSING``,
  never a Python exception.
- Atomic write: ``eval.json`` written via
  :func:`pipeline.state.safe_write` (ADR-0001).

Anti-pattern guards:

- Tests assert shape + verdict semantics; no LLM calls, no I/O beyond
  ``tmp_path``.
- Backward-compat assertions duplicate the previous inline-Python
  behaviour on the same fixture shape — every existing run dir keeps
  producing the same verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline import eval_gate

# ── Fixture helpers ─────────────────────────────────────────────────────────


def _make_run(
    tmp_path: Path,
    *,
    slug: str = "the-quota",
    md_body: str | None = None,
    quality: dict[str, Any] | None = None,
) -> Path:
    """Build a fake run dir with draft_v0.json, {slug}.md, and optionally
    quality.json. Returns the run directory path."""
    run_dir = tmp_path
    draft = {
        "slug": slug,
        "logline": "A protagonist confronts an institution.",
        "som_usd_millions": 1540.0,
    }
    (run_dir / "draft_v0.json").write_text(json.dumps(draft), encoding="utf-8")
    if md_body is not None:
        (run_dir / f"{slug}.md").write_text(md_body, encoding="utf-8")
    if quality is not None:
        (run_dir / "quality.json").write_text(json.dumps(quality), encoding="utf-8")
    return run_dir


_PASSING_MD = """\
# The Quota

A public defender discovers her own office is rigging her son's trial.

# 1. Market & Audience

## Audience Sizing

Market prose without any internal framework labels.

**SOM (Year 1):** $1540M

## Revenue Thesis

Revenue prose.

## Why Now

Cultural moment.

# 2. The Concept

## Mass-Appeal Theme

Theme prose.

## Format & Genre

Format prose.

## Tonal Contract

Tone prose.

# 3. Story

## Synopsis

Synopsis prose.

## Comparables

| Title | Year |
|---|---|
| Just Mercy | 2019 |

# 4. Characters

## Protagonist

Protagonist prose.

## Antagonist

Antagonist prose.

## Key Characters

Key character prose.
"""


# ── Tier-1: backward-compatibility shape ────────────────────────────────────


def test_eval_gate_passes_on_canonical_md(tmp_path: Path) -> None:
    """Concept md with canonical SOM line, no internal IDs, full V2 template
    sections → verdict PASS."""
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    result = eval_gate.run_eval_gate(run_dir)
    assert result["verdict"] == "PASS", f"failures={result['failures']}"
    assert result["failures"] == []


def test_eval_gate_fails_when_concept_md_missing(tmp_path: Path) -> None:
    """draft_v0 says slug=foo but foo.md is absent → CONCEPT_MD_MISSING."""
    (tmp_path / "draft_v0.json").write_text(json.dumps({"slug": "foo"}), encoding="utf-8")
    result = eval_gate.run_eval_gate(tmp_path)
    assert result["verdict"] == "FAIL"
    assert eval_gate.F_CONCEPT_MD_MISSING in result["failures"]


def test_eval_gate_fails_on_internal_id_leak(tmp_path: Path) -> None:
    """An internal framework ID in the concept prose trips INTERNAL_IDS."""
    md = _PASSING_MD + "\nReferences TRIZ kill-switch C001.\n"
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    assert result["verdict"] == "FAIL"
    assert eval_gate.F_INTERNAL_IDS in result["failures"]


def test_eval_gate_fails_on_low_som(tmp_path: Path) -> None:
    """SOM < $100M trips SOM_BELOW_100M."""
    md = _PASSING_MD.replace("**SOM (Year 1):** $1540M", "**SOM (Year 1):** $50M")
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    assert result["verdict"] == "FAIL"
    assert eval_gate.F_SOM_BELOW_100M in result["failures"]


def test_eval_gate_fails_on_missing_som(tmp_path: Path) -> None:
    """No SOM line at all trips SOM_BELOW_100M (the gate treats absent as
    insufficient — investors need a number)."""
    md = _PASSING_MD.replace("**SOM (Year 1):** $1540M", "")
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    assert result["verdict"] == "FAIL"
    assert eval_gate.F_SOM_BELOW_100M in result["failures"]


def test_eval_gate_accepts_widened_som_variants(tmp_path: Path) -> None:
    """NB-PARSE-SOM-WIDEN follow-through: the eval gate accepts the
    investor-readable variants (comma + colon-inside-bold)."""
    md = _PASSING_MD.replace("**SOM (Year 1):** $1540M", "**SOM: $1,540M**")
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    assert eval_gate.F_SOM_BELOW_100M not in result["failures"]
    # Non-canonical form surfaces as a soft warning, not a failure.
    assert eval_gate.W_SOM_LINE_NON_CANONICAL in result["warnings"]


def test_eval_gate_no_warning_when_som_canonical(tmp_path: Path) -> None:
    """The canonical SOM shape does NOT emit the SOM_LINE_NON_CANONICAL warning."""
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    result = eval_gate.run_eval_gate(run_dir)
    assert eval_gate.W_SOM_LINE_NON_CANONICAL not in result["warnings"]


def test_eval_gate_writes_eval_json_atomically(tmp_path: Path) -> None:
    """eval.json is written via pipeline.state.safe_write — must be present
    on disk after run_eval_gate returns."""
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    eval_gate.run_eval_gate(run_dir)
    path = run_dir / eval_gate.EVAL_FILENAME
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"


# ── Tier-2: NB.5-EVAL-CONSULT quality.json consultation ─────────────────────


def test_quality_pass_propagates_to_eval(tmp_path: Path) -> None:
    """When quality.json.overall_pass=True, eval.json records that and
    keeps the verdict PASS."""
    quality = {"overall_pass": True, "vector_pass": {"Q2": True}}
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD, quality=quality)
    result = eval_gate.run_eval_gate(run_dir)
    assert result["verdict"] == "PASS"
    assert result["quality_consulted"] is True
    md_name = next(iter(result["per_file"]))
    assert result["per_file"][md_name]["quality_overall_pass"] is True


def test_quality_fail_in_default_mode_is_warning_only(tmp_path: Path) -> None:
    """Cycle-1 default: quality.overall_pass=False surfaces as a warning,
    not a failure. Verdict stays PASS if Tier-1 gates pass."""
    quality = {"overall_pass": False, "vector_pass": {"Q2": False}}
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD, quality=quality)
    result = eval_gate.run_eval_gate(run_dir, strict_quality=False)
    assert result["verdict"] == "PASS"
    assert eval_gate.F_QUALITY_GATE_FAIL in result["warnings"]
    assert eval_gate.F_QUALITY_GATE_FAIL not in result["failures"]


def test_quality_fail_in_strict_mode_is_a_failure(tmp_path: Path) -> None:
    """Cycle-2 toggle: --strict-quality flips QUALITY_GATE_FAIL to a hard
    failure and flips the verdict."""
    quality = {"overall_pass": False, "vector_pass": {"Q2": False}}
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD, quality=quality)
    result = eval_gate.run_eval_gate(run_dir, strict_quality=True)
    assert result["verdict"] == "FAIL"
    assert eval_gate.F_QUALITY_GATE_FAIL in result["failures"]


def test_quality_absent_is_neither_pass_nor_fail(tmp_path: Path) -> None:
    """Missing quality.json → quality_consulted=False; verdict reflects
    only Tier-1 gates."""
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    result = eval_gate.run_eval_gate(run_dir, strict_quality=True)
    assert result["quality_consulted"] is False
    # Strict mode does NOT fail when the sidecar is simply absent —
    # only an explicit False triggers QUALITY_GATE_FAIL.
    assert eval_gate.F_QUALITY_GATE_FAIL not in result["failures"]
    assert result["verdict"] == "PASS"


def test_quality_malformed_json_is_treated_as_absent(tmp_path: Path) -> None:
    """A corrupt quality.json should not raise — soft-fail back to absent."""
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    (run_dir / "quality.json").write_text("{not valid json", encoding="utf-8")
    result = eval_gate.run_eval_gate(run_dir, strict_quality=True)
    assert result["quality_consulted"] is False
    assert result["verdict"] == "PASS"


def test_strict_quality_persisted_in_eval_json(tmp_path: Path) -> None:
    """The strict_quality flag must appear in eval.json so operators can
    audit which mode the gate ran in."""
    quality = {"overall_pass": True}
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD, quality=quality)
    result = eval_gate.run_eval_gate(run_dir, strict_quality=True)
    assert result["strict_quality"] is True
    result2 = eval_gate.run_eval_gate(run_dir, strict_quality=False)
    assert result2["strict_quality"] is False


# ── NB-EVAL-L5-RECONNECT: patcher routing (B1'' closure) ────────────────────
#
# Failure codes carry an implicit owner: the agent that wrote the failing
# artifact. The eval gate surfaces ``patcher_routing`` so the L5 SKILL.md
# branch can dispatch concept-md-rooted failures to the concept-drafter
# (previously the L5 loop only ever invoked the narrator, leaving these
# failures auto-unfixable). Pure-Python classification; no LLM side effects.


def test_classify_failures_routes_concept_md_codes_to_drafter() -> None:
    """All Tier-1/Tier-2 codes today route to the drafter — the concept md
    is the canonical artifact and the drafter owns it."""
    result = {
        "failures": [
            eval_gate.F_INTERNAL_IDS,
            eval_gate.F_SOM_BELOW_100M,
            eval_gate.F_TEMPLATE_NONCOMPLIANT,
            eval_gate.F_QUALITY_GATE_FAIL,
            eval_gate.F_CONCEPT_MD_MISSING,
        ]
    }
    routing = eval_gate.classify_failures(result)
    assert set(routing[eval_gate.PATCHER_DRAFTER]) == {
        eval_gate.F_INTERNAL_IDS,
        eval_gate.F_SOM_BELOW_100M,
        eval_gate.F_TEMPLATE_NONCOMPLIANT,
        eval_gate.F_QUALITY_GATE_FAIL,
        eval_gate.F_CONCEPT_MD_MISSING,
    }
    assert routing[eval_gate.PATCHER_NARRATOR] == []


def test_classify_failures_empty_on_pass() -> None:
    """A passing eval produces both buckets empty — symmetric for the
    SKILL.md dispatch (no nil-checks needed)."""
    routing = eval_gate.classify_failures({"failures": []})
    assert routing == {
        eval_gate.PATCHER_DRAFTER: [],
        eval_gate.PATCHER_NARRATOR: [],
    }


def test_classify_failures_defaults_unknown_to_drafter() -> None:
    """Forward-compat: an unknown code routes to the drafter (concept md
    is the canonical artifact; safe fallback)."""
    routing = eval_gate.classify_failures({"failures": ["FUTURE_UNKNOWN_CODE"]})
    assert routing[eval_gate.PATCHER_DRAFTER] == ["FUTURE_UNKNOWN_CODE"]
    assert routing[eval_gate.PATCHER_NARRATOR] == []


def test_classify_failures_skips_non_string_entries() -> None:
    """Defensive: malformed failure entries (None, int, dict) are ignored
    rather than raised — eval.json never blocks the pipeline."""
    routing = eval_gate.classify_failures({"failures": [eval_gate.F_INTERNAL_IDS, None, 42, {}]})
    assert routing[eval_gate.PATCHER_DRAFTER] == [eval_gate.F_INTERNAL_IDS]


def test_classify_failures_handles_missing_failures_key() -> None:
    """An eval_result without a failures key returns empty buckets."""
    routing = eval_gate.classify_failures({})
    assert routing == {
        eval_gate.PATCHER_DRAFTER: [],
        eval_gate.PATCHER_NARRATOR: [],
    }


def test_classify_failures_handles_non_list_failures() -> None:
    """A malformed eval_result with failures: <not a list> returns empty
    buckets rather than raising."""
    routing = eval_gate.classify_failures({"failures": "INTERNAL_IDS"})  # str, not list
    assert routing == {
        eval_gate.PATCHER_DRAFTER: [],
        eval_gate.PATCHER_NARRATOR: [],
    }


def test_preferred_patcher_table_covers_every_failure_constant() -> None:
    """Every ``F_*`` constant exported from :mod:`pipeline.eval_gate` must
    appear in PREFERRED_PATCHER_BY_CODE. Guards against a future code
    being added without a routing decision.
    """
    failure_constants = {
        getattr(eval_gate, name)
        for name in dir(eval_gate)
        if name.startswith("F_") and isinstance(getattr(eval_gate, name), str)
    }
    table_codes = set(eval_gate.PREFERRED_PATCHER_BY_CODE.keys())
    missing = failure_constants - table_codes
    assert not missing, (
        f"Failure codes missing from PREFERRED_PATCHER_BY_CODE: {sorted(missing)}. "
        "Add each to the routing table with an explicit patcher hint."
    )


def test_preferred_patcher_values_are_known_patchers() -> None:
    """The routing table only maps to PATCHER_DRAFTER or PATCHER_NARRATOR.
    A typo'd value would silently route to a non-existent agent."""
    known = {eval_gate.PATCHER_DRAFTER, eval_gate.PATCHER_NARRATOR}
    for code, patcher in eval_gate.PREFERRED_PATCHER_BY_CODE.items():
        assert patcher in known, (
            f"PREFERRED_PATCHER_BY_CODE[{code!r}] = {patcher!r}; must be one of {sorted(known)}"
        )


def test_eval_json_includes_patcher_routing_on_pass(tmp_path: Path) -> None:
    """A passing eval still surfaces patcher_routing (both buckets empty).

    The skill's L5 dispatch needs the key to be present regardless of
    verdict so it can branch without ``.get(..., {})`` boilerplate.
    """
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    result = eval_gate.run_eval_gate(run_dir)
    assert "patcher_routing" in result
    assert result["patcher_routing"] == {
        eval_gate.PATCHER_DRAFTER: [],
        eval_gate.PATCHER_NARRATOR: [],
    }
    # Persisted to disk.
    persisted = json.loads((run_dir / eval_gate.EVAL_FILENAME).read_text(encoding="utf-8"))
    assert persisted["patcher_routing"] == result["patcher_routing"]


def test_eval_json_routes_internal_ids_to_drafter(tmp_path: Path) -> None:
    """A real concept-md-rooted failure (INTERNAL_IDS) lands in the drafter
    bucket of the persisted eval.json, never the narrator bucket."""
    md = _PASSING_MD + "\nReferences TRIZ kill-switch C001.\n"
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    assert eval_gate.F_INTERNAL_IDS in result["patcher_routing"][eval_gate.PATCHER_DRAFTER]
    assert result["patcher_routing"][eval_gate.PATCHER_NARRATOR] == []


def test_eval_json_routes_low_som_to_drafter(tmp_path: Path) -> None:
    """SOM_BELOW_100M routes to drafter — the SOM line lives in {slug}.md
    under "Market & Audience", written by the concept-drafter, not the
    narrator companion."""
    md = _PASSING_MD.replace("**SOM (Year 1):** $1540M", "**SOM (Year 1):** $50M")
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    assert eval_gate.F_SOM_BELOW_100M in result["patcher_routing"][eval_gate.PATCHER_DRAFTER]


def test_eval_json_routes_concept_md_missing_to_drafter(tmp_path: Path) -> None:
    """CONCEPT_MD_MISSING reaches the persisted eval.json even on the
    early-exit branch (no draft, no md), and routes to drafter."""
    (tmp_path / "draft_v0.json").write_text(json.dumps({"slug": "foo"}), encoding="utf-8")
    result = eval_gate.run_eval_gate(tmp_path)
    assert eval_gate.F_CONCEPT_MD_MISSING in result["patcher_routing"][eval_gate.PATCHER_DRAFTER]
    persisted = json.loads((tmp_path / eval_gate.EVAL_FILENAME).read_text(encoding="utf-8"))
    assert eval_gate.F_CONCEPT_MD_MISSING in persisted["patcher_routing"][eval_gate.PATCHER_DRAFTER]


def test_eval_json_routes_strict_quality_fail_to_drafter(tmp_path: Path) -> None:
    """Under --strict-quality the QUALITY_GATE_FAIL routes to drafter — the
    5-vector axes read from the draft_v0 sections, and remediation revises
    the draft."""
    quality = {"overall_pass": False, "vector_pass": {"Q2": False}}
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD, quality=quality)
    result = eval_gate.run_eval_gate(run_dir, strict_quality=True)
    assert result["verdict"] == "FAIL"
    assert eval_gate.F_QUALITY_GATE_FAIL in result["patcher_routing"][eval_gate.PATCHER_DRAFTER]


def test_eval_json_mixed_batch_routing(tmp_path: Path) -> None:
    """A concept with multiple concurrent failures (internal ID + low SOM)
    accumulates both codes in the drafter bucket; narrator bucket stays empty."""
    md = _PASSING_MD.replace("**SOM (Year 1):** $1540M", "**SOM (Year 1):** $25M")
    md += "\nReferences TRIZ kill-switch C001.\n"
    run_dir = _make_run(tmp_path, md_body=md)
    result = eval_gate.run_eval_gate(run_dir)
    drafter_codes = set(result["patcher_routing"][eval_gate.PATCHER_DRAFTER])
    assert {eval_gate.F_INTERNAL_IDS, eval_gate.F_SOM_BELOW_100M}.issubset(drafter_codes)
    assert result["patcher_routing"][eval_gate.PATCHER_NARRATOR] == []


def test_patcher_routing_keys_stable_for_skill_md_dispatch(tmp_path: Path) -> None:
    """The SKILL.md L5 branch reads eval.patcher_routing.drafter and
    eval.patcher_routing.narrator. Locking the key names so a rename
    here is forced through a test failure (and a coordinated SKILL.md
    patch)."""
    run_dir = _make_run(tmp_path, md_body=_PASSING_MD)
    result = eval_gate.run_eval_gate(run_dir)
    assert set(result["patcher_routing"].keys()) == {"drafter", "narrator"}, (
        "Renaming a patcher key requires a coordinated SKILL.md patch — "
        "see .planning/state/NB_EVAL_L5_PATCH.md."
    )


# ── Regression: the actual NB.10 Quota run ──────────────────────────────────


def test_quota_run_eval_gate_passes(tmp_path: Path) -> None:
    """The literal Quota run must continue to verdict PASS after this atom.

    This is the canonical regression test: if a future change to the gate,
    template_filter, or quality.json schema breaks the NB.10 reference run,
    this test catches it.

    The run is copied to ``tmp_path`` before invocation so the eval gate's
    atomic write to ``eval.json`` lands in the copy, not the committed
    artifact — otherwise every test run would mutate the canonical
    ``runs/2026-05-19-133938-the-quota/eval.json`` timestamp.
    """
    import shutil  # noqa: PLC0415

    quota_src = Path("runs/2026-05-19-133938-the-quota")
    if not quota_src.exists():
        pytest.skip("NB.10 reference run not present (runs/ may have been cleaned)")
    quota_copy = tmp_path / quota_src.name
    shutil.copytree(quota_src, quota_copy)

    result = eval_gate.run_eval_gate(quota_copy)
    assert result["verdict"] == "PASS", (
        f"NB.10 regression: Quota run failed eval gate. failures={result['failures']}"
    )
    assert result["quality_consulted"] is True, (
        "Quota run's quality.json should be consulted (it exists after NB.5-AXIS-PROSE)"
    )
