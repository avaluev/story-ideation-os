"""V4A-004 — v4 isolation CI guard rail.

Mechanical enforcement of the path-partition contract in `docs/v4_isolation.md`:

  1. v4 entry-point Python modules MUST NOT contain string literals
     pointing at v3.1-rooted paths (out/concepts/v3.1- or data/runs/v3.1-).
     A literal v3.1 path inside a v4 module is a write-pollution risk.

  2. `scripts/v4_preflight.py` MUST exist and be invokable from the
     command line (`--help` exits 0).

  3. The v4 partition roots (`data/runs/v4-genius-cc/`,
     `out/concepts/v4-genius-cc/`) MUST NOT contain any v3.1-rooted
     path strings inside committed files (excluding the comparison
     harness, which legitimately reads both pipelines).

  4. Pre-flight script MUST refuse a v3.1-formatted run-id slug.
     This is the behavioral test of the gate itself.

The pre-flight gate (`scripts/v4_preflight.py`) catches violations at
runtime; this test catches them at commit-time.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

V4_ENTRY_MODULES = (
    Path("pipeline/run_cc.py"),
    Path("pipeline/cc_dispatch.py"),
    Path("pipeline/quota.py"),
    Path("pipeline/genius_loop.py"),
    Path("pipeline/mutation.py"),
    Path("pipeline/kb.py"),
    Path("pipeline/bridge.py"),
)
COMPARISON_ALLOW_LIST = (
    Path("scripts/compare_pipelines.py"),
    Path("scripts/extract_v3_audiences.py"),
    Path("evals/test_pipeline_parity.py"),
    Path("docs/v4_isolation.md"),  # documentation legitimately names both
)
# Comparison-harness output filenames (V4A-004 Stage 2 writes v3_audience_pool
# into data/runs/v4-genius-cc/<run_id>/ by design). These are runtime artifacts
# whose JSONL rows reference v3.1 brief paths as evidence — NOT a v4-write into
# v3.1 territory. Any file in the v4 partition with one of these names is
# excluded from the v3.1-path scan.
COMPARISON_OUTPUT_FILENAMES: frozenset[str] = frozenset(
    {
        "v3_audience_pool.jsonl",
    }
)
V3_PATH_RE = re.compile(r"(?:out/concepts/v3\.1-|data/runs/v3\.1-)")
V4_RUNS_ROOT = Path("data/runs/v4-genius-cc")
V4_OUT_ROOT = Path("out/concepts/v4-genius-cc")
V4_PREFLIGHT = Path("scripts/v4_preflight.py")


def test_v4_entry_modules_have_no_v3_path_literals() -> None:
    """No v4 entry module contains a literal v3.1 path string. A hit means a
    v4 component is one slip away from writing into the v3.1 partition."""
    violations: list[str] = []
    for module in V4_ENTRY_MODULES:
        if not module.exists():
            continue
        text = module.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if V3_PATH_RE.search(line):
                violations.append(f"{module}:{line_no} {line.strip()}")
    assert not violations, (
        f"{len(violations)} v3.1-path literals found inside v4 entry modules. "
        f"v4 must never write to v3.1 paths (docs/v4_isolation.md):\n" + "\n".join(violations)
    )


def test_v4_preflight_script_exists_and_help_works() -> None:
    """Pre-flight script must be invokable from the CLI."""
    assert V4_PREFLIGHT.is_file(), f"missing {V4_PREFLIGHT}"
    result = subprocess.run(  # noqa: S603 — invoking own script under sys.executable, all args are constants
        [sys.executable, str(V4_PREFLIGHT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"v4_preflight --help exited {result.returncode}; stderr:\n{result.stderr}"
    )
    assert "--run-id" in result.stdout, (
        f"v4_preflight --help missing --run-id flag; got:\n{result.stdout}"
    )


def test_v4_preflight_rejects_invalid_run_id() -> None:
    """Pre-flight refuses a malformed run-id (exit code 4)."""
    result = subprocess.run(  # noqa: S603 — invoking own script under sys.executable, all args are constants
        [sys.executable, str(V4_PREFLIGHT), "--run-id", "not-a-valid-id"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 4, (
        f"v4_preflight should exit 4 on bad run-id; got {result.returncode}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert "run_id must match" in result.stderr


def test_v4_preflight_accepts_valid_run_id_in_tmp(tmp_path: Path) -> None:
    """Pre-flight on a synthetic v4 run-id exits 0 and creates the dir.

    Uses a synthetic run-id that won't collide with any real run; cleans up
    after itself.
    """
    synthetic_id = "20260101T000000Z"
    expected_dir = V4_RUNS_ROOT / synthetic_id
    try:
        result = subprocess.run(  # noqa: S603 — invoking own script under sys.executable, all args are constants
            [sys.executable, str(V4_PREFLIGHT), "--run-id", synthetic_id, "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"v4_preflight on valid id should exit 0; got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert expected_dir.is_dir(), f"v4_preflight did not create {expected_dir}"
        assert (expected_dir / "preflight.json").is_file(), (
            f"v4_preflight did not write preflight.json under {expected_dir}"
        )
    finally:
        # Best-effort cleanup of the synthetic run dir.
        if expected_dir.exists():
            for child in expected_dir.rglob("*"):
                if child.is_file():
                    child.unlink()
            for child in sorted(expected_dir.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            expected_dir.rmdir()


def test_v4_partition_dirs_have_no_v3_pollution() -> None:
    """Files under v4 partition roots MUST NOT name v3.1 paths.

    Comparison-harness modules are explicitly allow-listed (they read
    both pipelines by design). Everything else is checked.
    """
    violations: list[str] = []
    roots = (V4_RUNS_ROOT, V4_OUT_ROOT)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md", ".json", ".jsonl", ".yaml", ".yml"}:
                continue
            if path.name in COMPARISON_OUTPUT_FILENAMES:
                # V4A-004 Stage 2 comparison-pool artifact — references v3.1
                # paths as evidence, not as a write target. Permitted.
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if V3_PATH_RE.search(text):
                violations.append(str(path))
    # Exclude allow-listed comparison harness paths if any happen to live in v4
    # partition (they shouldn't, but defense-in-depth).
    violations = [v for v in violations if Path(v) not in COMPARISON_ALLOW_LIST]
    assert not violations, (
        "v3.1-rooted paths found inside the v4 partition. The v4 partition "
        "must remain pure (docs/v4_isolation.md):\n" + "\n".join(violations)
    )


def test_isolation_doc_exists_and_lists_path_partition() -> None:
    """docs/v4_isolation.md must exist and document the path partition table."""
    doc = Path("docs/v4_isolation.md")
    assert doc.is_file(), "missing docs/v4_isolation.md"
    text = doc.read_text(encoding="utf-8")
    # Sanity check that the canonical v4 paths are documented:
    for marker in ("data/runs/v4-genius-cc", "out/concepts/v4-genius-cc"):
        assert marker in text, f"docs/v4_isolation.md missing canonical v4 path marker: {marker}"
    # And both pipelines are named:
    for marker in ("v3.1-pathc-a4", "v4-genius-cc"):
        assert marker in text, f"docs/v4_isolation.md missing partition marker: {marker}"
