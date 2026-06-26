"""Tests for the plan-compliance loop CLI.

Covers the four CLAUDE.md MUST rules:

1. ``--pre-task`` blocks when prereqs are missing.
2. ``--post-task`` blocks when expected artifacts are absent.
3. ``--audit`` reports a compliance score and respects ``--strict``.
4. ``--stop-gate`` blocks when ``RESUME.md`` is older than the ledger.

Tests run against an isolated tmp_path so they never touch the real
``.planning/state/PLAN_LEDGER.jsonl``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from pipeline import plan_compliance

# A minimal plan fixture exercising every parser branch:
#   T001: no prereq, single artifact
#   T002: depends on T001, single artifact
#   T003: depends on a range "T001<dash>T002"
_DASH = chr(0x2013)  # U+2013 EN DASH (constructed at runtime to avoid RUF001).
_EM_DASH = chr(0x2014)  # U+2014 EM DASH.
PLAN_TEMPLATE = (
    "# Test Plan\n\n"
    "## Ultra TODO List\n\n"
    "| ID | Title | Prereq | Artifact | Verify |\n"
    "|---|---|---|---|---|\n"
    f"| T001 | Build foo.txt | {_EM_DASH} | {{artifact1}} | `wc -l` |\n"
    "| T002 | Build bar.txt | T001 | {artifact2} | `wc -l` |\n"
    f"| T003 | Build baz.txt | T001{_DASH}T002 | {{artifact3}} | `ls` |\n"
)


def _write_plan(tmp_path: Path, artifact1: str, artifact2: str, artifact3: str) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text(
        PLAN_TEMPLATE.format(
            artifact1=artifact1,
            artifact2=artifact2,
            artifact3=artifact3,
        ),
        encoding="utf-8",
    )
    return plan


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect plan-compliance's filesystem hooks to tmp_path."""
    ledger = tmp_path / "PLAN_LEDGER.jsonl"
    resume = tmp_path / "RESUME.md"
    resume.write_text("# resume\n", encoding="utf-8")
    monkeypatch.setattr(plan_compliance, "LEDGER_PATH", ledger)
    monkeypatch.setattr(plan_compliance, "RESUME_PATH", resume)
    monkeypatch.chdir(tmp_path)
    return {"ledger": ledger, "resume": resume, "tmp": tmp_path}


def test_parse_plan_extracts_three_items(tmp_path: Path) -> None:
    """The parser must return one TodoItem per row in the Ultra TODO List."""
    plan = _write_plan(
        tmp_path,
        artifact1="`foo.txt`",
        artifact2="`bar.txt`",
        artifact3="`baz.txt`",
    )
    items = plan_compliance.parse_plan(plan)
    assert set(items.keys()) == {"T001", "T002", "T003"}
    assert items["T002"].prereqs == ("T001",)
    # Range "T001<dash>T002" must expand to both ids.
    assert items["T003"].prereqs == ("T001", "T002")


def test_pretask_blocks_without_prereqs(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """--pre-task must exit non-zero when a prereq is not DONE in the ledger."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    rc = plan_compliance.main(["--pre-task", "T002", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_BLOCKED


def test_pretask_passes_when_prereqs_done(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """--pre-task must exit 0 when all declared prereqs have a DONE row."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    # Fabricate a DONE row for T001.
    foo = tmp_path / "foo.txt"
    foo.write_text("ok", encoding="utf-8")
    rc = plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_OK
    rc = plan_compliance.main(["--pre-task", "T002", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_OK


def test_posttask_blocks_on_missing_artifacts(
    isolated_state: dict[str, Path], tmp_path: Path
) -> None:
    """--post-task must refuse to mark DONE if expected artifacts do not exist."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    rc = plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_BLOCKED
    # The ledger should remain empty.
    ledger = isolated_state["ledger"]
    assert not ledger.exists() or ledger.stat().st_size == 0


def test_posttask_appends_ledger_row(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """--post-task on a satisfied item appends one DONE row to the ledger."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    (tmp_path / "foo.txt").write_text("ok", encoding="utf-8")
    rc = plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_OK
    rows = plan_compliance.read_ledger(isolated_state["ledger"])
    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == "T001"
    assert row["status"] == "DONE"
    assert row["actual_artifacts"] == ["foo.txt"]
    assert row["plan_file_sha"]


def test_audit_reports_score(
    isolated_state: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--audit must print a compliance percentage."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    (tmp_path / "foo.txt").write_text("ok", encoding="utf-8")
    plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    rc = plan_compliance.main(["--audit", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_OK
    out = capsys.readouterr().out
    assert "Compliance score:" in out
    # 1 of 3 done => ~33%.
    assert "33.3%" in out


def test_audit_strict_fails_below_threshold(
    isolated_state: dict[str, Path], tmp_path: Path
) -> None:
    """--audit --strict must exit non-zero when score < AUDIT_OK_THRESHOLD."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    rc = plan_compliance.main(["--audit", "--strict", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_GENERIC_ERROR


def test_stop_gate_blocks_on_stale_resume(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """--stop-gate must fail if RESUME.md mtime < ledger mtime."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    (tmp_path / "foo.txt").write_text("ok", encoding="utf-8")
    plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    # Force RESUME.md older than ledger.
    resume = isolated_state["resume"]
    ledger = isolated_state["ledger"]
    old = ledger.stat().st_mtime - 100
    os.utime(resume, (old, old))
    rc = plan_compliance.main(["--stop-gate"])
    assert rc == plan_compliance.EXIT_GENERIC_ERROR


def test_stop_gate_passes_when_resume_fresh(
    isolated_state: dict[str, Path], tmp_path: Path
) -> None:
    """--stop-gate must exit 0 when RESUME.md is newer than the ledger."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    (tmp_path / "foo.txt").write_text("ok", encoding="utf-8")
    plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    # Touch RESUME.md to bump its mtime.
    resume = isolated_state["resume"]
    time.sleep(0.01)
    resume.write_text("# updated\n", encoding="utf-8")
    rc = plan_compliance.main(["--stop-gate"])
    assert rc == plan_compliance.EXIT_OK


def test_pretask_detects_plan_drift(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """--pre-task must refuse when the plan file SHA has changed since the last ledger row."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    (tmp_path / "foo.txt").write_text("ok", encoding="utf-8")
    plan_compliance.main(["--post-task", "T001", "--plan", str(plan)])
    # Mutate the plan to change its SHA.
    plan.write_text(plan.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    rc = plan_compliance.main(["--pre-task", "T002", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_PLAN_DRIFT
    # --allow-drift permits the call.
    rc = plan_compliance.main(["--pre-task", "T002", "--plan", str(plan), "--allow-drift"])
    assert rc == plan_compliance.EXIT_OK


def test_unknown_item_id(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """--pre-task and --post-task return EXIT_UNKNOWN_ITEM for unknown IDs."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    rc = plan_compliance.main(["--pre-task", "T999", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_UNKNOWN_ITEM
    rc = plan_compliance.main(["--post-task", "T999", "--plan", str(plan)])
    assert rc == plan_compliance.EXIT_UNKNOWN_ITEM


def test_ledger_row_shape(isolated_state: dict[str, Path], tmp_path: Path) -> None:
    """Every ledger row must carry the documented fields for downstream auditing."""
    plan = _write_plan(tmp_path, "`foo.txt`", "`bar.txt`", "`baz.txt`")
    (tmp_path / "foo.txt").write_text("ok", encoding="utf-8")
    plan_compliance.main(
        [
            "--post-task",
            "T001",
            "--plan",
            str(plan),
            "--tests",
            "tests/test_plan_compliance.py::test_ledger_row_shape",
            "--tests-status",
            "PASS",
        ]
    )
    raw = isolated_state["ledger"].read_text(encoding="utf-8").splitlines()[0]
    row = json.loads(raw)
    for key in (
        "ts",
        "item_id",
        "title",
        "plan_file_sha",
        "expected_artifacts",
        "actual_artifacts",
        "tests_run",
        "tests_status",
        "deviations",
        "status",
    ):
        assert key in row, f"missing required ledger field: {key}"
