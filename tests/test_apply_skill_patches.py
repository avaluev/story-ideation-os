"""tests/test_apply_skill_patches.py — contract for scripts/apply_skill_patches.py.

The script automates four SKILL.md patches that the Claude Code
self-modification classifier blocks at the agent layer. The operator
invokes it via the ``!`` prefix (``! uv run python scripts/apply_skill_patches.py
--all``). Because the file under modification is a load-bearing skill
config, these tests pin the patch contract byte-for-byte against an
in-memory fixture:

  * every patch is idempotent (applied → no-op on second invocation)
  * a missing anchor aborts cleanly with ``status == "missing_anchor"``
  * applying NB.10 then NB-EVAL-L5 (or vice versa) leaves both sentinels
    in the output (the two patches are independent and order-agnostic)
  * the live SKILL.md file is never written by tests (--skill-path is
    redirected at fixture-built copies)

The fixture mirrors the canonical Session-7 SKILL.md shape: the anchors
each patch keys on are present. The fixture is small (under 200 lines)
so the tests stay readable.
"""
# The SKILL.md fixture below carries a verbatim long-line anchor that must
# match the live SKILL.md byte-for-byte. Suppressing E501 file-wide rather
# than per-line (inline noqa would land inside the string literal and break
# the match).
# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import apply_skill_patches as patcher

# ── Minimal SKILL.md fixture ────────────────────────────────────────────────

_FIXTURE_SKILL_MD = (
    """\
---
name: single-idea
description: |
  Single-Idea Pipeline v4.0 — 10-phase orchestrator.
---

# /single-idea — Single-Idea Pipeline v4.0

### STEP 3 — PHASE 1: research (concept-researcher)

If `current_phase > 1`: skip.

Run the researcher Task.

### STEP 4 — PHASE 2: draft_v0 (concept-drafter, initial mode)

If `current_phase > 2`: skip. Read `{run_dir}/draft_v0.json` and extract `slug` for later steps.

```
Task(subagent_type="concept-drafter", ...)
```

Wait for Task. Read `{run_dir}/draft_v0.json`. Extract `slug` (use it as `{title_slug}` for all subsequent steps).

### STEP 5 — PHASE 3: challenge + L1 patch loop

If `current_phase > 3`: skip.

Run the challenge Task.

### STEP 6 — PHASE 4: amplify + L2 plateau verification

If `current_phase > 4`: skip.

Run the amplify Task.

### STEP 7 — PHASE 5: genius_audit + L3 patch loop

If `current_phase > 5`: skip.

Run the genius_audit Task.

### STEP 8 — PHASE 6: consistency_check + L4 patch loop

If `current_phase > 6`: skip.

Run the consistency_check Task.

### STEP 9 — PHASE 7: investor_narrator (concept-narrator)

If `current_phase > 7`: skip.

Run the investor_narrator Task.

### STEP 10 — PHASE 8: eval_gate + L5 narrator-redo loop

If `current_phase > 8`: skip.

"""
    + patcher.NB10_OLD_BLOCK
    + """\

Read `{run_dir}/eval.json`.

"""
    + patcher.NB_EVAL_L5_OLD_BLOCK
    + """\

### STEP 11 — PHASE 9: lessons_capture

Write `{run_dir}/lessons.json` from the sidecar data.

### STEP 12 — COMPLETE

Print deliverables summary.

## Resume Protocol

If the pipeline is interrupted mid-run, run `--resume`.
"""
)


@pytest.fixture
def skill_path(tmp_path: Path) -> Path:
    """Write the fixture SKILL.md into a temp dir and return its path."""
    p = tmp_path / "SKILL.md"
    p.write_text(_FIXTURE_SKILL_MD, encoding="utf-8")
    return p


# ── Unit: pure-function patch contracts ─────────────────────────────────────


def test_apply_nb9_inserts_nine_brackets() -> None:
    out, result = patcher.apply_nb9(_FIXTURE_SKILL_MD)
    assert result.status == "applied"
    assert result.name == "NB9"
    # All 9 (phase_index, phase_name) start lines present.
    for _step, phase_index, phase_name, _next in patcher.NB9_STEPS:
        assert (
            f"pipeline.phase_timing start --run-dir {{run_dir}} "
            f"--phase-index {phase_index} --phase-name {phase_name}"
        ) in out
        assert (
            f"pipeline.phase_timing end --run-dir {{run_dir}} "
            f"--phase-index {phase_index} --phase-name {phase_name}"
        ) in out


def test_apply_nb9_idempotent() -> None:
    once, _ = patcher.apply_nb9(_FIXTURE_SKILL_MD)
    twice, result = patcher.apply_nb9(once)
    assert result.status == "already_applied"
    assert twice == once


def test_apply_nb11_wires_both_steps() -> None:
    out, result = patcher.apply_nb11(_FIXTURE_SKILL_MD)
    assert result.status == "applied"
    assert patcher.NB11_DRAFT_SENTINEL in out
    assert patcher.NB11_REPORT_SENTINEL in out


def test_apply_nb11_idempotent() -> None:
    once, _ = patcher.apply_nb11(_FIXTURE_SKILL_MD)
    twice, result = patcher.apply_nb11(once)
    assert result.status == "already_applied"
    assert twice == once


def test_apply_nb10_replaces_inline_block() -> None:
    out, result = patcher.apply_nb10(_FIXTURE_SKILL_MD)
    assert result.status == "applied"
    assert patcher.NB10_SENTINEL in out
    # The bulky inline python -c block is gone.
    assert "scan_for_internal_ids, parse_som, check_template_compliance" not in out
    # The new one-liner is present.
    assert "uv run python -m pipeline.eval_gate --run-dir {run_dir}" in out


def test_apply_nb10_idempotent() -> None:
    once, _ = patcher.apply_nb10(_FIXTURE_SKILL_MD)
    twice, result = patcher.apply_nb10(once)
    assert result.status == "already_applied"
    assert twice == once


def test_apply_nb_eval_l5_replaces_narrator_redo_block() -> None:
    out, result = patcher.apply_nb_eval_l5(_FIXTURE_SKILL_MD)
    assert result.status == "applied"
    assert patcher.NB_EVAL_L5_SENTINEL in out
    # Old marker gone.
    assert '**L5 narrator-redo loop (verdict == "FAIL"):**' not in out
    # Split-dispatch artefacts present.
    assert "patcher_routing.drafter" in out
    assert "concept-drafter" in out
    assert "concept-narrator" in out


def test_apply_nb_eval_l5_idempotent() -> None:
    once, _ = patcher.apply_nb_eval_l5(_FIXTURE_SKILL_MD)
    twice, result = patcher.apply_nb_eval_l5(once)
    assert result.status == "already_applied"
    assert twice == once


# ── Order independence: NB.10 then NB-EVAL-L5, and reverse ──────────────────


def test_nb10_then_nb_eval_l5_leaves_both_sentinels() -> None:
    after10, r10 = patcher.apply_nb10(_FIXTURE_SKILL_MD)
    after5, r5 = patcher.apply_nb_eval_l5(after10)
    assert r10.status == r5.status == "applied"
    assert patcher.NB10_SENTINEL in after5
    assert patcher.NB_EVAL_L5_SENTINEL in after5


def test_nb_eval_l5_then_nb10_leaves_both_sentinels() -> None:
    after5, r5 = patcher.apply_nb_eval_l5(_FIXTURE_SKILL_MD)
    after10, r10 = patcher.apply_nb10(after5)
    assert r5.status == r10.status == "applied"
    assert patcher.NB10_SENTINEL in after10
    assert patcher.NB_EVAL_L5_SENTINEL in after10


# ── Anchor drift detection ──────────────────────────────────────────────────


def test_nb10_missing_anchor_aborts() -> None:
    """If the inline python -c block has drifted, apply_nb10 reports
    missing_anchor and leaves the text untouched."""
    drifted = _FIXTURE_SKILL_MD.replace(patcher.NB10_OLD_BLOCK, "<<DRIFTED>>")
    out, result = patcher.apply_nb10(drifted)
    assert result.status == "missing_anchor"
    assert out == drifted  # no mutation


def test_nb_eval_l5_missing_anchor_aborts() -> None:
    drifted = _FIXTURE_SKILL_MD.replace(patcher.NB_EVAL_L5_OLD_BLOCK, "<<DRIFTED>>")
    out, result = patcher.apply_nb_eval_l5(drifted)
    assert result.status == "missing_anchor"
    assert out == drifted


def test_nb9_missing_anchor_aborts() -> None:
    """Removing the STEP 5 skip line should break the NB9 patch
    cleanly (no partial mutation of earlier STEPs that already succeeded
    in the loop — the function returns the ORIGINAL text on failure)."""
    drifted = _FIXTURE_SKILL_MD.replace("If `current_phase > 3`: skip.", "")
    out, result = patcher.apply_nb9(drifted)
    assert result.status == "missing_anchor"
    assert out == drifted
    # No phase_timing tokens leaked in despite STEPS 3/4 having succeeded
    # before STEP 5 failed.
    assert "pipeline.phase_timing start" not in out


def test_nb11_missing_step4_anchor_aborts() -> None:
    """If STEP 4's `Wait for Task` line is missing, abort cleanly with no
    partial mutation. STEP 12 is also untouched."""
    drifted = _FIXTURE_SKILL_MD.replace(
        "Wait for Task. Read `{run_dir}/draft_v0.json`. "
        "Extract `slug` (use it as `{title_slug}` for all subsequent steps).",
        "",
    )
    out, result = patcher.apply_nb11(drifted)
    assert result.status == "missing_anchor"
    assert out == drifted
    assert patcher.NB11_DRAFT_SENTINEL not in out
    assert patcher.NB11_REPORT_SENTINEL not in out


# ── CLI surface ─────────────────────────────────────────────────────────────


def test_cli_verify_reports_pending_for_clean_fixture(
    skill_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = patcher.main(["--verify", "--skill-path", str(skill_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "pending" in captured.out
    # Live file untouched.
    assert skill_path.read_text(encoding="utf-8") == _FIXTURE_SKILL_MD


def test_cli_dry_run_does_not_write(skill_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = patcher.main(["--all", "--dry-run", "--skill-path", str(skill_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "dry-run: no changes written" in captured.out
    assert skill_path.read_text(encoding="utf-8") == _FIXTURE_SKILL_MD


def test_cli_all_writes_and_is_idempotent(
    skill_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # First run: applies every patch.
    rc1 = patcher.main(["--all", "--no-backup", "--skill-path", str(skill_path)])
    assert rc1 == 0
    after_first = skill_path.read_text(encoding="utf-8")
    assert patcher.NB9_SENTINEL in after_first
    assert patcher.NB11_DRAFT_SENTINEL in after_first
    assert patcher.NB11_REPORT_SENTINEL in after_first
    assert patcher.NB10_SENTINEL in after_first
    assert patcher.NB_EVAL_L5_SENTINEL in after_first

    # Second run: every patch already applied, file unchanged.
    rc2 = patcher.main(["--all", "--no-backup", "--skill-path", str(skill_path)])
    assert rc2 == 0
    captured = capsys.readouterr()
    assert "already applied" in captured.out
    assert skill_path.read_text(encoding="utf-8") == after_first


def test_cli_creates_backup_by_default(skill_path: Path) -> None:
    rc = patcher.main(["--all", "--skill-path", str(skill_path)])
    assert rc == 0
    backups = list(skill_path.parent.glob("SKILL.md.bak.*"))
    assert len(backups) == 1
    # Backup contains the pre-patch contents.
    assert backups[0].read_text(encoding="utf-8") == _FIXTURE_SKILL_MD


def test_cli_aborts_on_missing_anchor(skill_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drifted = _FIXTURE_SKILL_MD.replace(patcher.NB10_OLD_BLOCK, "<<DRIFTED>>")
    skill_path.write_text(drifted, encoding="utf-8")
    rc = patcher.main(["--nb10", "--no-backup", "--skill-path", str(skill_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "missing_anchor" in captured.out
    # File untouched on abort.
    assert skill_path.read_text(encoding="utf-8") == drifted


def test_cli_per_patch_flag_isolates_changes(skill_path: Path) -> None:
    """``--nb9`` applies ONLY NB9; other sentinels stay absent."""
    rc = patcher.main(["--nb9", "--no-backup", "--skill-path", str(skill_path)])
    assert rc == 0
    after = skill_path.read_text(encoding="utf-8")
    assert patcher.NB9_SENTINEL in after
    assert patcher.NB10_SENTINEL not in after
    assert patcher.NB_EVAL_L5_SENTINEL not in after
    assert patcher.NB11_DRAFT_SENTINEL not in after
    assert patcher.NB11_REPORT_SENTINEL not in after


def test_cli_argparse_rejects_empty_invocation(
    skill_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        patcher.main(["--skill-path", str(skill_path)])
