"""EVAL -- Run 3 (en-assemble) output: the amplified EN report skeletons.

Scans ``outputs/portfolio/amplified/EN/*_EN.md`` (produced by
``scripts/build_amplified_reports.py``) and enforces the Run-3 gate stated in
the campaign plan: *template / ID / SOM evals pass*. Specifically, every report:

  * passes ``check_template_compliance`` (the 4 V2 H1 + 5 H2 anchors);
  * leaks zero internal IDs / framework labels (``scan_for_internal_ids``);
  * carries a canonical ``**SOM (Year 1):** $NNNM`` line whose value equals the
    frozen DNA SOM, and holds the SOM < SAM < TAM invariant;
  * declares a TAM deep-link (the Economics provenance row).

The render-numeric "every external $ carries a source/arithmetic" rule is the
Run-4 (online) target, NOT a Run-3 gate -- the treatments cite richer comps
than the frozen DNA holds, so those claims cannot be sourced offline. Run 3
records them in ``_run4_worklist.json``; this eval does not fail on them.

Skips gracefully when the directory is absent (fresh checkout / pre-Run-3).
Offline / pure-parsing -- no network, no LLM (ADR-0002).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.template_filter import (
    check_template_compliance,
    is_som_line_canonical,
    parse_som,
    scan_for_internal_ids,
)
from scripts.build_amplified_reports import USD_M, _load_concept, validate_report

_AMP_DIR = Path("outputs/portfolio/amplified/EN")
_FILES = sorted(_AMP_DIR.glob("*_EN.md")) if _AMP_DIR.exists() else []
_EXPECTED_REPORTS = 20
_SOM_PARSE_TOL_M = 1.0

pytestmark = pytest.mark.skipif(
    not _FILES, reason="no amplified EN reports yet -- Run 3 (build_amplified_reports) not run"
)


def _idx_of(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def test_twenty_reports_present() -> None:
    """The campaign declares 20 per-concept reports."""
    assert len(_FILES) == _EXPECTED_REPORTS, (
        f"expected {_EXPECTED_REPORTS} EN reports, found {len(_FILES)}: "
        + ", ".join(p.name for p in _FILES)
    )


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_run3_hard_gates(path: Path) -> None:
    """The on-disk report passes every Run-3 hard gate (template/ID/SOM/invariant)."""
    concept = _load_concept(_idx_of(path))
    md = path.read_text(encoding="utf-8")
    problems, _worklist = validate_report(md, concept, label=path.stem)
    assert problems == [], f"{path.name} failed Run-3 gates: " + "; ".join(problems)


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_template_compliance(path: Path) -> None:
    result = check_template_compliance(path.read_text(encoding="utf-8"))
    assert result["passed"], f"{path.name}: " + "; ".join(result["failures"])  # type: ignore[arg-type]


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_no_internal_ids(path: Path) -> None:
    findings = scan_for_internal_ids(path.read_text(encoding="utf-8"))
    assert not findings, f"{path.name}: " + ", ".join(
        f"{d['match']!r}@{d['line']}" for d in findings
    )


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_som_canonical_and_matches_frozen(path: Path) -> None:
    md = path.read_text(encoding="utf-8")
    assert is_som_line_canonical(md), f"{path.name}: SOM not in canonical **SOM (Year 1):** form"
    parsed = parse_som(md)
    assert parsed is not None, f"{path.name}: SOM line not parseable"
    frozen_m = _load_concept(_idx_of(path)).econ["som_y1_usd"] / USD_M
    assert abs(parsed[0] - round(frozen_m)) <= _SOM_PARSE_TOL_M, (
        f"{path.name}: rendered SOM {parsed[0]} != frozen {round(frozen_m)}"
    )


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_som_sam_tam_invariant(path: Path) -> None:
    econ = _load_concept(_idx_of(path)).econ
    assert econ["som_y1_usd"] < econ["sam_usd"] < econ["tam_usd"], (
        f"{path.name}: SOM<SAM<TAM violated "
        f"({econ['som_y1_usd']} < {econ['sam_usd']} < {econ['tam_usd']})"
    )


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_has_tam_deep_link(path: Path) -> None:
    """The Economics TAM row must carry a non-empty deep-link (no `[](url)`)."""
    econ = _load_concept(_idx_of(path)).econ
    url = econ.get("tam_source_url", "")
    assert url and url in path.read_text(encoding="utf-8"), (
        f"{path.name}: frozen TAM source URL absent from the rendered report"
    )
