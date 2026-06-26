"""EVAL -- SOM >= $100M quality gate.

Parses the SOM line from investor-facing .md and asserts >= $100M.

SKIP until Wave C creates pipeline/template_filter.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_tf = pytest.importorskip("pipeline.template_filter", reason="defensive import guard")
parse_som = _tf.parse_som

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SOM_120M = """\
## Audience Sizing
### TAM
**TAM:** $4.8B
### SAM
**SAM:** $800M
### SOM -- Serviceable Obtainable Market (Year 1 realistic capture)
**SOM (Year 1):** $120M
"""

_SOM_50M = """\
### SOM -- Serviceable Obtainable Market (Year 1 realistic capture)
**SOM (Year 1):** $50M
"""

_SOM_1_2B = """\
### SOM -- Serviceable Obtainable Market (Year 1 realistic capture)
**SOM (Year 1):** $1.2B
"""

_SOM_200_5M = """\
### SOM -- Serviceable Obtainable Market (Year 1 realistic capture)
**SOM (Year 1):** $200.5M
"""

_NO_SOM = """\
## Audience Sizing
Nothing here.
"""


class TestParseSom:
    def test_120m_parsed(self) -> None:
        result = parse_som(_SOM_120M)
        assert result is not None
        value, _ = result
        assert abs(value - 120.0) < 0.01

    def test_50m_parsed(self) -> None:
        result = parse_som(_SOM_50M)
        assert result is not None
        value, _ = result
        assert abs(value - 50.0) < 0.01

    def test_billion_converted_to_millions(self) -> None:
        result = parse_som(_SOM_1_2B)
        assert result is not None
        value, _ = result
        assert abs(value - 1200.0) < 1.0

    def test_decimal_millions_parsed(self) -> None:
        result = parse_som(_SOM_200_5M)
        assert result is not None
        value, _ = result
        assert abs(value - 200.5) < 0.01

    def test_missing_som_returns_none(self) -> None:
        assert parse_som(_NO_SOM) is None

    def test_empty_doc_returns_none(self) -> None:
        assert parse_som("") is None

    def test_line_number_is_positive_int(self) -> None:
        result = parse_som(_SOM_120M)
        assert result is not None
        _, line_no = result
        assert isinstance(line_no, int)
        assert line_no > 0

    def test_returns_tuple(self) -> None:
        result = parse_som(_SOM_120M)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestSomGate:
    def test_120m_passes_gate(self) -> None:
        result = parse_som(_SOM_120M)
        assert result is not None
        assert result[0] >= 100.0

    def test_50m_is_below_gate(self) -> None:
        result = parse_som(_SOM_50M)
        assert result is not None
        assert result[0] < 100.0

    def test_billion_passes_gate(self) -> None:
        result = parse_som(_SOM_1_2B)
        assert result is not None
        assert result[0] >= 100.0


# ── Output scan (v4 runs only — identified by eval.json sidecar) ─────────────

_RUNS_DIR = Path("runs")
_V4_RUN_DIRS = (
    [d for d in _RUNS_DIR.glob("*/") if (d / "eval.json").exists()] if _RUNS_DIR.exists() else []
)


@pytest.mark.skipif(
    not _V4_RUN_DIRS,
    reason="No v4 runs (eval.json) in runs/ yet — SOM gate applies to v4 output only",
)
class TestOutputSomGate:
    def test_all_investor_mds_have_som_above_100m(self) -> None:
        non_md = {"draft.v0.md", "eval.md"}
        for run_dir in _V4_RUN_DIRS:
            for md_path in run_dir.glob("*.md"):
                if md_path.name in non_md:
                    continue
                # Non-concept docs: internal audit, narrative companion, amplification report
                _sidecars = ("-NARRATOR", "-CHALLENGE", "-RESEARCH", "-AMPLIFIED")
                if any(m in md_path.name for m in _sidecars):
                    continue
                text = md_path.read_text()
                result = parse_som(text)
                assert result is not None, f"{md_path}: SOM line not found"
                value, line_no = result
                assert value >= 100.0, f"{md_path}:{line_no}: SOM ${value}M is below the $100M gate"
