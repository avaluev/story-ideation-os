"""Custom architectural lint for Anomaly Engine v3.0.

Enforces import-direction rules derived from ADRs.

Usage:
    uv run python scripts/lint_imports.py

Exit codes:
    0 — no violations (clean tree)
    1 — one or more violations found

Current rules (more added as pipeline/* lands in P3, PIPE-04, etc.):
    ANOMALY-001 (ADR-0002): pipeline/scoring.py MUST NOT import LLM clients
    ANOMALY-002 (ADR-0005): no pipeline/**/*.py may import from frameworks/
    ANOMALY-003: no pipeline/**/*.py may be unreachable (imported by nothing,
                 not a CLI entrypoint, and not in the explicit allowlist)

Error message format (WHY/FIX/EXAMPLE per §13.3 of 00-RESEARCH.md):
    <file>:<line>: <rule_code>
      WHY: <one-line ADR or doctrine reference>
      FIX: <concrete steps>
      EXAMPLE: <bad → good code snippet, ≤4 lines>
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

VIOLATIONS: list[dict] = []

# ── ANOMALY-001 ──────────────────────────────────────────────────────────────

_LLM_MODULES = frozenset(
    {
        "openrouter_client",
        "pipeline.openrouter_client",
        "anthropic",
        "httpx",
        "pipeline.run",
    }
)


def check_scoring_no_llm_imports() -> None:
    """ANOMALY-001 (ADR-0002 + ADR-0007): files in this list MUST NOT import
    LLM clients (anthropic, httpx, openrouter_client) or pipeline.run.

    Targets:
      - pipeline/scoring.py     (ADR-0002 — scoring is pure Python)
      - pipeline/cc_dispatch.py (ADR-0007 — gateway shim never directly calls models)
      - pipeline/gemini_dispatch.py (ADR-0007/0008 — optional/forward-compat; skipped if absent)
      - pipeline/quota.py       (ADR-0008 — quota tracker reads JSONL only)
      - pipeline/crystallize/format_economics.py (ADR-0002 + ADR-0011 — per-format
        revenue constants are pure Python; SOM/SAM/TAM must stay python_executed)

    A target that does not exist on disk is silently skipped (forward-compat).
    """
    targets = [
        Path("pipeline/scoring.py"),
        Path("pipeline/cc_dispatch.py"),
        Path("pipeline/gemini_dispatch.py"),
        Path("pipeline/quota.py"),
        Path("pipeline/crystallize/format_economics.py"),
        Path("pipeline/crystallize/score.py"),
        Path("pipeline/empirical_genius.py"),
    ]
    for target in targets:
        if not target.exists():
            continue
        _check_one_no_llm_imports(target)


def _check_one_no_llm_imports(target: Path) -> None:
    """Walk AST of `target` and append violations for any LLM-client import."""
    source = target.read_text()
    try:
        tree = ast.parse(source, filename=str(target))
    except SyntaxError as exc:
        VIOLATIONS.append(
            {
                "file": str(target),
                "line": exc.lineno or 0,
                "rule": "ANOMALY-001",
                "why": f"{target.name} contains a SyntaxError; cannot validate imports.",
                "fix": f"Fix the SyntaxError in {target}.",
                "example": f"SyntaxError: {exc.msg}",
            }
        )
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _LLM_MODULES:
                    VIOLATIONS.append(
                        {
                            "file": str(target),
                            "line": node.lineno,
                            "rule": "ANOMALY-001",
                            "why": (
                                f"{target} imports {alias.name!r} — "
                                "forbidden by ADR-0002 / ADR-0007 / ADR-0008."
                            ),
                            "fix": (
                                "Move LLM-dependent logic to a different module.\n"
                                "  scoring.py / cc_dispatch.py / gemini_dispatch.py / "
                                "quota.py must stay LLM-free."
                            ),
                            "example": (
                                "# BAD:\n"
                                "  from pipeline.openrouter_client import chat\n"
                                "# GOOD:\n"
                                "  # the orchestrator (skill body) calls Task; "
                                "this module plans manifests"
                            ),
                        }
                    )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in _LLM_MODULES or any(module.startswith(m) for m in _LLM_MODULES):
                VIOLATIONS.append(
                    {
                        "file": str(target),
                        "line": node.lineno,
                        "rule": "ANOMALY-001",
                        "why": (
                            f"{target} imports from {module!r} — "
                            "forbidden by ADR-0002 / ADR-0007 / ADR-0008."
                        ),
                        "fix": (
                            "Move LLM call to the orchestrator (skill body); "
                            "this module plans manifests / records quota only."
                        ),
                        "example": (
                            "# BAD:\n"
                            "  from anthropic import Anthropic\n"
                            "# GOOD:\n"
                            "  # this module receives pre-computed token counts via "
                            "record_task_completion"
                        ),
                    }
                )


# ── ANOMALY-002 ──────────────────────────────────────────────────────────────

_FRAMEWORKS_IMPORT_PATTERN = re.compile(
    r"^\s*(from\s+frameworks|import\s+frameworks)", re.MULTILINE
)


def check_frameworks_not_imported() -> None:
    """ANOMALY-002 (ADR-0005): no pipeline/**/*.py may import from frameworks/.

    frameworks/*.md are read-only doctrine; never imported programmatically.
    P0 has no pipeline/*.py with imports; forward-compatible no-op.
    """
    pipeline_dir = Path("pipeline")
    if not pipeline_dir.exists():
        return

    for py_file in pipeline_dir.rglob("*.py"):
        source = py_file.read_text()
        match = _FRAMEWORKS_IMPORT_PATTERN.search(source)
        if match:
            # Find line number
            line_num = source[: match.start()].count("\n") + 1
            VIOLATIONS.append(
                {
                    "file": str(py_file),
                    "line": line_num,
                    "rule": "ANOMALY-002",
                    "why": (
                        "frameworks/*.md is read-only doctrine — never import from it "
                        "(ADR-0005: doctrine drift would silently desync scoring.py)."
                    ),
                    "fix": (
                        "Load the markdown via `pipeline.run.load_framework(path)` "
                        "and inject as system context string."
                    ),
                    "example": (
                        "# BAD:\n"
                        "  from frameworks import narrative_master_grid\n"
                        "# GOOD:\n"
                        "  context = pipeline.run.load_framework("
                        "'frameworks/narrative-master-grid.md')"
                    ),
                }
            )


# ── ANOMALY-003 ──────────────────────────────────────────────────────────────

# Allowlist of pipeline/**/*.py that are intentional roots (never imported by
# anything) and are NOT CLI entrypoints.  Add to this list only when a module
# is a genuine operator-facing stub or an unambiguous pipeline root.
_ORPHAN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "pipeline/run.py",  # primary CLI root (also has __main__)
        "pipeline/loop_wedge.py",  # operator loop stub (also has __main__)
        "pipeline/veracity/__main__.py",  # veracity CLI entrypoint
    }
)


def _path_to_dotted(p: Path) -> str:
    """Convert a path like ``pipeline/foo/bar.py`` to ``pipeline.foo.bar``."""
    return ".".join(p.with_suffix("").parts)


def _collect_pipeline_refs_from_node(
    node: ast.AST,
    reached_modules: set[str],
    reached_from_parent: set[tuple[str, str]],
    reached_string_refs: set[str],
) -> None:
    """Extract pipeline-scoped import references from a single AST node (in-place)."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.startswith("pipeline"):
                reached_modules.add(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.module and node.module.startswith("pipeline"):
            reached_modules.add(node.module)
            for alias in node.names:
                reached_from_parent.add((node.module, alias.name))
    elif isinstance(node, ast.Call):
        for arg in node.args:
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.startswith("pipeline.")
            ):
                reached_string_refs.add(arg.value)


def _build_reached_set(source_dirs: list[Path]) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """Walk all Python source files under *source_dirs* and return three sets.

    Returns
    -------
    reached_modules:
        Dotted module paths seen in ``import X`` or ``from X import ...``
        statements (where X starts with ``pipeline``).
    reached_from_parent:
        ``(parent_module, name)`` pairs from ``from parent import name``
        statements (where parent starts with ``pipeline``).
    reached_string_refs:
        ``pipeline.X`` strings found as literal Call arguments (covers
        ``pytest.importorskip("pipeline.X")`` and similar dynamic references).
    """
    reached_modules: set[str] = set()
    reached_from_parent: set[tuple[str, str]] = set()
    reached_string_refs: set[str] = set()

    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        for py_file in source_dir.rglob("*.py"):
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                _collect_pipeline_refs_from_node(
                    node, reached_modules, reached_from_parent, reached_string_refs
                )

    return reached_modules, reached_from_parent, reached_string_refs


def _is_module_reached(
    mod_dotted: str,
    reached_modules: set[str],
    reached_from_parent: set[tuple[str, str]],
    reached_string_refs: set[str],
) -> bool:
    """Return True if *mod_dotted* is referenced by at least one import statement."""
    if mod_dotted in reached_modules:
        return True
    if mod_dotted in reached_string_refs:
        return True
    # Handle ``from pipeline.x import y`` where ``pipeline.x.y`` == mod_dotted.
    parts = mod_dotted.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        name = parts[i]
        if (parent, name) in reached_from_parent:
            return True
    return False


def _is_cli_entrypoint(source: str) -> bool:
    """Return True if the module has a ``__main__`` block or is a ``__main__`` module."""
    return "__main__" in source or "if __name__" in source


def find_orphan_pipeline_modules(pipeline_root: Path | None = None) -> list[dict]:
    """ANOMALY-003: find pipeline/**/*.py modules imported by nothing.

    A module is an *orphan* when ALL of the following hold:
    - It is not imported (directly or via ``from pkg import name``) by any
      Python file under ``pipeline/``, ``scripts/``, ``tests/``, or ``evals/``.
    - It is not a CLI entrypoint (no ``if __name__ == '__main__'`` block and
      the filename is not ``__main__.py``).
    - It is a ``__init__.py`` whose package has NO reachable submodule.
    - It is not in ``_ORPHAN_ALLOWLIST``.

    Parameters
    ----------
    pipeline_root:
        Path to the ``pipeline/`` directory.  Defaults to ``Path("pipeline")``.
        Pass an absolute tmp path in tests; source_dirs are resolved relative
        to its parent so the fixture's sibling ``scripts/`` is also scanned.

    Returns a list of violation dicts (same schema as VIOLATIONS entries).
    """
    root = (pipeline_root or Path("pipeline")).resolve()
    if not root.exists():
        return []

    repo_root = root.parent  # parent of pipeline/ — may be tmp or real repo root

    all_pipeline_files = list(root.rglob("*.py"))
    # Build dotted names relative to repo_root so they always start with "pipeline."
    all_pipeline_mods: dict[str, Path] = {
        _path_to_dotted(f.relative_to(repo_root)): f for f in all_pipeline_files
    }

    source_dirs = [
        repo_root / "pipeline",
        repo_root / "scripts",
        repo_root / "tests",
        repo_root / "evals",
    ]
    reached_modules, reached_from_parent, reached_string_refs = _build_reached_set(source_dirs)

    def is_reached(mod_dotted: str) -> bool:
        return _is_module_reached(
            mod_dotted, reached_modules, reached_from_parent, reached_string_refs
        )

    def pkg_name_for_init(mod_dotted: str, fpath: Path) -> str | None:
        if fpath.name == "__init__.py":
            if "." in mod_dotted:
                return mod_dotted.rsplit(".", 1)[0]
            return mod_dotted
        return None

    def pkg_itself_reached(pkg_dotted: str) -> bool:
        if pkg_dotted in reached_modules:
            return True
        parts = pkg_dotted.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            name = parts[i]
            if (parent, name) in reached_from_parent:
                return True
        return False

    def any_submod_reached(pkg_dotted: str) -> bool:
        prefix = pkg_dotted + "."
        return any(
            m.startswith(prefix) and not m.endswith(".__init__") and is_reached(m)
            for m in all_pipeline_mods
        )

    orphan_violations: list[dict] = []
    for mod_dotted, fpath in sorted(all_pipeline_mods.items()):
        # Normalize to repo-root-relative path string for allowlist comparison.
        try:
            rel_path = str(fpath.relative_to(repo_root))
        except ValueError:
            rel_path = str(fpath)

        # Allowlist: intentional roots that are never imported.
        if rel_path in _ORPHAN_ALLOWLIST:
            continue

        # CLI entrypoints: modules with __main__ blocks are roots by design.
        try:
            source = fpath.read_text(encoding="utf-8")
        except OSError:
            continue
        if _is_cli_entrypoint(source):
            continue

        # __init__.py: reachable if the package itself or any non-__init__ submod is reached.
        pkg = pkg_name_for_init(mod_dotted, fpath)
        if pkg is not None:
            if pkg_itself_reached(pkg) or any_submod_reached(pkg):
                continue
        elif is_reached(mod_dotted):
            continue

        # Still here → orphan.
        orphan_violations.append(
            {
                "file": rel_path,
                "line": 1,
                "rule": "ANOMALY-003",
                "why": (
                    f"{rel_path} is not imported by anything and is not a CLI entrypoint. "
                    "Dead-code reappearance gate (ANOMALY-003): unreferenced pipeline modules "
                    "rot silently and must be removed or re-connected."
                ),
                "fix": (
                    "Either (a) delete the module if it is truly dead, "
                    "(b) import it from the appropriate consumer, or "
                    "(c) add it to _ORPHAN_ALLOWLIST in scripts/lint_imports.py "
                    "if it is a genuine pipeline root that is never imported."
                ),
                "example": (
                    "# BAD: pipeline/dead_helper.py with no importer\n"
                    "# GOOD: imported from pipeline/run.py:\n"
                    "  from pipeline.dead_helper import util_fn\n"
                    "# OR: deleted / moved to scripts/ if it is a CLI tool"
                ),
            }
        )

    return orphan_violations


def check_no_orphan_pipeline_modules() -> None:
    """ANOMALY-003: add any orphan violations to the global VIOLATIONS list."""
    VIOLATIONS.extend(find_orphan_pipeline_modules())


# ── Reporter ─────────────────────────────────────────────────────────────────


def _report_violations() -> None:
    """Print violations in WHY/FIX/EXAMPLE format and exit 1."""
    for v in VIOLATIONS:
        print(f"{v['file']}:{v['line']}: {v['rule']}")
        print(f"  WHY: {v['why']}")
        print(f"  FIX: {v['fix']}")
        print(f"  EXAMPLE: {v['example']}")
        print()


if __name__ == "__main__":
    check_scoring_no_llm_imports()
    check_frameworks_not_imported()
    check_no_orphan_pipeline_modules()

    if VIOLATIONS:
        _report_violations()
        sys.exit(1)

    sys.exit(0)
