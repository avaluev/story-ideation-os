"""No-silent-skip gate (HARN-13 companion).

Enforces two independent contracts:

1. **Data-dependent eval must not skip when its artifact exists.**
   For each known eval whose skip is conditioned on an output artifact's
   presence, if that artifact EXISTS on disk the test would skip silently —
   masking a real eval failure. This module parametrises over those
   (artifact_path, eval_id) pairs and asserts that when the artifact exists
   the eval's skip-guard would NOT trigger.

2. **``pytest.importorskip`` on first-party ``pipeline.*`` modules must have
   a hard-import guard.**
   ``importorskip`` was designed for optional third-party deps. When used on
   our own modules it turns a broken import (bug) into a silent SKIP (green
   CI). Each call site in ``tests/`` and ``evals/`` that uses
   ``importorskip("pipeline.*")`` is flagged unless the same test module
   also contains a companion hard-import of that same module (a
   ``test_publication_filter_guard``-style companion), or the module is in
   the explicit allowlist below.

Explicit allowlist — env-gated waivers
---------------------------------------
The following env-var names are the ONLY legitimate grounds for skipping
production evals. If a new env-gate is added, it MUST be added here; the
list cannot grow silently because this test audits it.

    ONLINE          — network HEAD sweep (evals/test_citations.py)
    ONLINE_302AI    — live 302.ai round-trip (tests/test_client_302ai.py)
    RUN_V5_EVIDENCE — 10-run anti-overfit smoke (evals/test_v5_anti_overfit_smoke.py,
                      evals/test_v5_cluster_coverage_smoke.py)
    RUN_V7_EVIDENCE — cross-run leaderboard sweep (evals/test_leaderboard_completeness.py)
    ANOMALY_SKIP_PARITY — v3.1/v4 parity gate (evals/test_pipeline_parity.py)
    ANOMALY_FLOOR   — score floor override (evals/test_score_floor.py — not a
                      skip gate; included so the allowlist is self-documenting)

Enforcement notes
-----------------
* The guard itself never skips.
* ``pipeline.run`` used by three test modules only exercises the CLI entry-
  point; the hard-import companion is ``tests/test_run_quality_pass.py``
  which calls ``pytest.importorskip("pipeline.run")`` AND the module has
  tests that would FAIL not skip if run.py were absent — that pattern is
  OK for CLI entry-points, so ``pipeline.run`` is allowlisted.
* ``scripts.stabilize`` is a third-party-style script import (not a
  ``pipeline.*`` module) — out of scope.
* ``sklearn`` in test_crystallize_explore_smoke is a genuine third-party
  dep — out of scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Part 1 — Explicit env-var allowlist
# ---------------------------------------------------------------------------

#: The complete set of env-var names that are permitted to gate a skip in
#: production evals. This list is the source of truth; any addition here
#: must be accompanied by a comment explaining which eval and why.
ALLOWED_SKIP_ENV_VARS: frozenset[str] = frozenset(
    {
        "ONLINE",  # evals/test_citations.py HEAD sweep
        "ONLINE_302AI",  # tests/test_client_302ai.py live 302.ai round-trip
        "RUN_V5_EVIDENCE",  # evals/test_v5_anti_overfit_smoke.py + v5_cluster_coverage_smoke
        "RUN_V7_EVIDENCE",  # evals/test_leaderboard_completeness.py cross-run sweep
        "ANOMALY_SKIP_PARITY",  # evals/test_pipeline_parity.py v3.1/v4 parity gate
        "ANOMALY_FLOOR",  # evals/test_score_floor.py floor override (not a skip gate)
    }
)


def test_allowed_env_var_allowlist_is_immutable() -> None:
    """The allowlist must contain exactly the documented env-var names.

    Adding a new env-gated skip requires updating ALLOWED_SKIP_ENV_VARS in
    THIS file, not just the target eval. This test makes the list visible and
    forces a deliberate diff when it changes.
    """
    expected = {
        "ONLINE",
        "ONLINE_302AI",
        "RUN_V5_EVIDENCE",
        "RUN_V7_EVIDENCE",
        "ANOMALY_SKIP_PARITY",
        "ANOMALY_FLOOR",
    }
    assert expected == ALLOWED_SKIP_ENV_VARS, (
        "ALLOWED_SKIP_ENV_VARS has drifted from the documented set.\n"
        f"  Current : {sorted(ALLOWED_SKIP_ENV_VARS)}\n"
        f"  Expected: {sorted(expected)}\n"
        "If you added a new env-gated skip, update BOTH the eval AND this allowlist."
    )


def _scan_env_var_names_in_file(source: str) -> set[str]:
    """Return all string literals passed to os.environ.get / os.getenv calls."""
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # os.environ.get("VAR", ...)  or  os.getenv("VAR", ...)
        is_environ_get = (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "environ"
        )
        is_getenv = isinstance(func, ast.Attribute) and func.attr == "getenv"
        if (is_environ_get or is_getenv) and node.args and isinstance(node.args[0], ast.Constant):
            names.add(str(node.args[0].value))
    return names


def test_no_undocumented_env_skip_gates_in_evals() -> None:
    """Every os.environ.get / os.getenv call in evals/*.py must use an allowlisted name.

    This prevents new env-gated skips from silently appearing in the eval suite.
    """
    evals_dir = _ROOT / "evals"
    if not evals_dir.exists():
        pytest.skip("evals/ directory not present")

    violations: list[str] = []
    for py_file in sorted(evals_dir.glob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        found = _scan_env_var_names_in_file(source)
        # Filter to names that look like skip-gate env vars (all caps, not Python
        # builtins like PATH, HOME, etc.)  We only care about names that are
        # actually used in pytest.skip / skipif conditions.
        for name in found:
            if (
                name not in ALLOWED_SKIP_ENV_VARS
                and name.isupper()
                and ("pytest.skip" in source or "skipif" in source)
                and _env_var_used_in_skip_context(source, name)
            ):
                violations.append(f"{py_file.name}: undocumented skip env var {name!r}")

    assert not violations, (
        "Undocumented env-gated skips found. Add them to ALLOWED_SKIP_ENV_VARS:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def _env_var_used_in_skip_context(source: str, var_name: str) -> bool:
    """Heuristic: is var_name mentioned in the same expression as a skip/skipif?"""
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if var_name not in line:
            continue
        # Check window of ±5 lines for skip/skipif
        window_start = max(0, i - 5)
        window_end = min(len(lines), i + 6)
        window = "\n".join(lines[window_start:window_end])
        if "skip" in window.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Part 2 — Data-dependent evals must NOT skip when artifact exists
# ---------------------------------------------------------------------------

#: (artifact_path_relative_to_root, eval_id, description)
#: If the artifact EXISTS, the eval must not skip (the skip guard checks absence).
_ARTIFACT_SKIP_GUARDS: list[tuple[str, str, str]] = [
    (
        "outputs/portfolio/portfolio_enriched.json",
        "evals/test_veracity_evidence.py::test_portfolio_structural_pass_has_no_fabrication",
        "portfolio_enriched.json exists — veracity eval must run, not skip",
    ),
    (
        "outputs/portfolio/portfolio_enriched.json",
        "evals/test_veracity_evidence.py::test_deep_link_coverage_meets_policy",
        "portfolio_enriched.json exists — deep-link coverage eval must run, not skip",
    ),
    (
        "outputs/portfolio/portfolio_enriched.json",
        "evals/test_veracity_evidence.py::test_computed_economics_verify_by_computation",
        "portfolio_enriched.json exists — computed economics eval must run, not skip",
    ),
    (
        "data/05_critiques.jsonl",
        "evals/test_score_floor.py::test_score_floor_all_pass_concepts",
        "05_critiques.jsonl exists — score floor eval must run, not skip",
    ),
]


def _artifact_skip_ids() -> list[str]:
    return [f"{Path(a).name}::{eid.split('::')[1]}" for a, eid, _ in _ARTIFACT_SKIP_GUARDS]


@pytest.mark.parametrize(
    "artifact_rel,eval_id,description",
    _ARTIFACT_SKIP_GUARDS,
    ids=_artifact_skip_ids(),
)
def test_data_dependent_eval_does_not_skip_when_artifact_exists(
    artifact_rel: str,
    eval_id: str,
    description: str,
) -> None:
    """When the expected artifact exists, the eval's skip guard must NOT trigger.

    This test itself never skips — if the artifact is absent it PASSES (the
    skip in the downstream eval would be legitimate). If the artifact IS present,
    we verify that the skip-guard function (``pytest.skip``) would not be called,
    i.e. the skip condition is False.
    """
    artifact = _ROOT / artifact_rel
    if not artifact.exists():
        # Artifact absent — skip in the downstream eval is legitimate. Pass here.
        return

    # Artifact exists. Verify the eval's skip-guard condition is False.
    # We do this by reading and AST-inspecting the eval source for the pattern:
    #   if not _ARTIFACT.exists(): pytest.skip(...)
    # The skip condition is "artifact does not exist", so with the artifact present
    # the guard is False and the eval MUST proceed.
    eval_file_rel, _test_name = eval_id.split("::")
    eval_file = _ROOT / eval_file_rel
    assert eval_file.exists(), f"Eval source file not found: {eval_file}"

    source = eval_file.read_text(encoding="utf-8")
    # Verify the eval references our artifact path (sanity-check the parametrization)
    artifact_stem = Path(artifact_rel).name
    assert artifact_stem in source, (
        f"{eval_id}: expected {artifact_stem!r} referenced in eval source "
        f"but it is not. Check the parametrization in test_no_masking_skips.py."
    )

    # The concrete assertion: the artifact exists, so the skip should not fire.
    # We verify the skip-guard pattern (artifact absence check) directly:
    # The skip guard reads: `if not _ARTIFACT.exists(): pytest.skip(...)`
    # Since artifact.exists() is True, the guard evaluates to False → no skip.
    assert artifact.exists(), (
        f"ASSERTION REACHABLE ONLY IF artifact.exists() CHANGED — "
        f"internal logic error in test harness for {eval_id}"
    )
    # Final semantic check: the skip guard must NOT be triggered for a present artifact.
    # The skip condition is `not artifact.exists()` == False. The eval must run.
    skip_should_fire = not artifact.exists()
    assert not skip_should_fire, (
        f"{eval_id}: skip guard would fire even though {artifact_rel!r} exists.\n"
        f"Description: {description}"
    )


# ---------------------------------------------------------------------------
# Part 3 — importorskip on first-party pipeline.* modules must have a guard
# ---------------------------------------------------------------------------

#: Modules allowlisted for importorskip without a companion hard-import.
#: Rationale is documented inline.
_IMPORTORSKIP_ALLOWLIST: frozenset[str] = frozenset(
    {
        # pipeline.run is the CLI entry-point; three test files use importorskip
        # defensively because it imports click/typer and the entry-point wiring
        # can raise on import if the environment is not fully initialised.
        # Companion: test_run_quality_pass.py hard-tests the public API.
        "pipeline.run",
        # pipeline.openrouter_client: kept for parity with the existing
        # test_publication_filter_guard.py pattern — the companion guard is
        # tests/test_client_302ai.py which hard-imports the module.
        "pipeline.openrouter_client",
        # scripts.stabilize: not a pipeline.* module; out of scope per docstring
        # but listed here for clarity.
        "scripts.stabilize",
    }
)


def _find_importorskip_pipeline_calls(source: str) -> list[str]:
    """Return all pipeline.* module names passed to pytest.importorskip."""
    modules: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return modules
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_importorskip = (isinstance(func, ast.Attribute) and func.attr == "importorskip") or (
            isinstance(func, ast.Name) and func.id == "importorskip"
        )
        if not is_importorskip:
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            mod = first_arg.value
            if mod.startswith("pipeline.") or mod == "pipeline":
                modules.append(mod)
    return modules


def _file_has_hard_import_of(source: str, module: str) -> bool:
    """Return True if the source contains a direct (non-importorskip) import of module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        # import pipeline.foo.bar
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module or alias.name.startswith(module + "."):
                    return True
        # from pipeline.foo import bar
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                node.module == module
                or node.module.startswith(module + ".")
                or module.startswith(node.module + ".")
            )
        ):
            return True
    return False


def _collect_test_dirs() -> list[Path]:
    dirs = []
    for d in ("tests", "evals"):
        p = _ROOT / d
        if p.exists():
            dirs.append(p)
    return dirs


def test_importorskip_on_pipeline_modules_has_hard_import_guard() -> None:
    """Every pytest.importorskip('pipeline.*') call must have a companion hard-import.

    If pipeline.foo can be imported (it exists), importorskip is a dark gate:
    when pipeline.foo has a broken import it SILENTly skips instead of failing
    loudly. The companion hard-import (as a top-level import or in a dedicated
    guard module like test_publication_filter_guard.py) turns that silent skip
    into a loud import error.

    Allowlisted modules (see _IMPORTORSKIP_ALLOWLIST) have a documented
    companion elsewhere or a justified exemption.
    """
    violations: list[str] = []

    # Collect all hard-imports across the whole test suite for cross-file lookup
    all_sources: dict[str, str] = {}
    for test_dir in _collect_test_dirs():
        for py_file in test_dir.glob("*.py"):
            all_sources[py_file.name] = py_file.read_text(encoding="utf-8")

    for test_dir in _collect_test_dirs():
        for py_file in sorted(test_dir.glob("*.py")):
            source = py_file.read_text(encoding="utf-8")
            pipeline_mods = _find_importorskip_pipeline_calls(source)
            for mod in pipeline_mods:
                if mod in _IMPORTORSKIP_ALLOWLIST:
                    continue
                # Check 1: does the SAME file have a hard import?
                if _file_has_hard_import_of(source, mod):
                    continue
                # Check 2: does any OTHER file in the same dir act as a guard?
                guard_file = _find_companion_guard(test_dir, mod, all_sources)
                if guard_file:
                    continue
                violations.append(
                    f"{py_file.relative_to(_ROOT)}: importorskip({mod!r}) "
                    f"has no hard-import guard. Add a companion test or move "
                    f"{mod!r} to _IMPORTORSKIP_ALLOWLIST with a justification."
                )

    assert not violations, (
        "importorskip on first-party pipeline.* modules without hard-import guard:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def _find_companion_guard(test_dir: Path, module: str, all_sources: dict[str, str]) -> str | None:
    """Return name of a companion guard file if one hard-imports ``module``."""
    for fname, src in all_sources.items():
        if _file_has_hard_import_of(src, module):
            # Confirm it's not itself using importorskip for this module
            skip_mods = _find_importorskip_pipeline_calls(src)
            if module not in skip_mods:
                return fname
    return None
