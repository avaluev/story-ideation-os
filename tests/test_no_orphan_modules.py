"""tests/test_no_orphan_modules.py — ANOMALY-003 dead-code reappearance gate.

Every ``pipeline/**/*.py`` module must be reachable (imported by something,
a CLI entrypoint, or an explicit allowlist root).  Unreferenced modules rot
silently and must be removed or reconnected.

Rule enforcement: ANOMALY-003 in scripts/lint_imports.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable without installing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lint_imports import find_orphan_pipeline_modules  # noqa: E402


def test_no_unreferenced_pipeline_modules() -> None:
    """ANOMALY-003: the cleaned pipeline tree has zero orphaned modules.

    An orphan is any ``pipeline/**/*.py`` that is:
    - not imported by any file under pipeline/, scripts/, tests/, or evals/,
    - not a CLI entrypoint (no ``__main__`` block / ``__main__.py``), and
    - not in the explicit ``_ORPHAN_ALLOWLIST``.

    If this test fails, either delete the dead module, import it from an
    appropriate consumer, or add it to ``_ORPHAN_ALLOWLIST`` in
    ``scripts/lint_imports.py`` with a rationale comment.
    """
    violations = find_orphan_pipeline_modules()
    if violations:
        details = "\n".join(f"  {v['file']}: {v['why']}" for v in violations)
        pytest.fail(
            f"ANOMALY-003: {len(violations)} orphaned pipeline module(s) found:\n{details}\n"
            "FIX: delete, reconnect, or add to _ORPHAN_ALLOWLIST in scripts/lint_imports.py."
        )


# ── Fixture: deliberate-orphan detection ─────────────────────────────────────


def test_anomaly_003_fires_on_deliberate_orphan(tmp_path: Path) -> None:
    """ANOMALY-003 checker fires when a deliberately orphaned module is introduced.

    Creates a minimal ``pipeline/`` tree under *tmp_path* with one module that
    imports nothing and is imported by nothing, then asserts the checker flags
    it.  This proves the gate is not a no-op.
    """
    # Build a minimal pipeline package
    pkg = tmp_path / "pipeline"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""pipeline stub."""\n', encoding="utf-8")

    # A genuine consumer module that imports from pipeline.used
    (pkg / "used.py").write_text(
        '"""pipeline.used — imported by consumer."""\n\ndef helper() -> None: ...\n',
        encoding="utf-8",
    )
    consumer = tmp_path / "scripts"
    consumer.mkdir()
    (consumer / "__init__.py").write_text("", encoding="utf-8")
    (consumer / "run_something.py").write_text(
        "from pipeline.used import helper\n\nif __name__ == '__main__':\n    helper()\n",
        encoding="utf-8",
    )

    # The deliberate orphan: no importer, no __main__
    dead_src = '"""pipeline.dead_module — orphan."""\n\n\ndef unused() -> None: ...\n'
    (pkg / "dead_module.py").write_text(dead_src, encoding="utf-8")

    violations = find_orphan_pipeline_modules(pipeline_root=pkg)

    orphan_files = [v["file"] for v in violations]
    assert any("dead_module" in f for f in orphan_files), (
        f"ANOMALY-003 did not fire on the deliberate orphan 'dead_module.py'.\n"
        f"Violations found: {orphan_files}"
    )
    assert all(v["rule"] == "ANOMALY-003" for v in violations), (
        "All violations from find_orphan_pipeline_modules must carry rule='ANOMALY-003'."
    )
    # The genuinely-used module must NOT be flagged
    assert not any("used" in f for f in orphan_files), (
        f"pipeline/used.py was incorrectly flagged as an orphan: {orphan_files}"
    )
