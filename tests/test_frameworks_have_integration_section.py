"""KNOW-11 enforcer: every frameworks/*.md file ends with §Operational Integration.

This is a cross-plan structure-lint:
- Plans 01-01 + 01-03 produce the 6 framework files.
- Plan 01-05 (this file) lints them as the integration backstop.
- Per-task `python3 -c` verifiers in 01-01 + 01-03 sample the lint at write-time
  (no Nyquist gap; revision-2 BLOCKER B3); this pytest test consolidates them
  into a single cross-plan integration backstop.

Operator decision (RESEARCH §Open Questions item 5): the §Operational Integration
heading must appear in the last 30% of the file (allowing a brief footer/citation
block to follow). Regex: `^## Operational Integration\\s*$` with re.MULTILINE.

References:
- frameworks/*.md (the 6 files under audit)
- .planning/phases/01-knowledge-layer/01-VALIDATION.md per-task verification map
- .planning/phases/01-knowledge-layer/01-RESEARCH.md §Per-REQ-ID Enforcer Map
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRAMEWORK_DIR = Path("frameworks")
ALL_FRAMEWORKS = [
    "narrative-master-grid.md",  # plan 01-01 task 1
    "sdt-spine.md",  # plan 01-01 task 2
    "ajtbd-segmentation.md",  # plan 01-01 task 3
    "forced-collision.md",  # plan 01-03 task 1
    "character-arcs.md",  # plan 01-03 task 2
    "cinema-school-doctrines.md",  # plan 01-03 task 3
]
OP_INTEGRATION_RE = re.compile(r"^## Operational Integration\s*$", re.MULTILINE)


def _content(filename: str) -> str:
    path = FRAMEWORK_DIR / filename
    assert path.exists(), f"{path} missing -- check plan 01-01 / 01-03 execution status"
    return path.read_text(encoding="utf-8")


def _has_op_integration_in_last_30pct(content: str) -> bool:
    """Operator decision: §Operational Integration must appear in last 30% of file."""
    matches = list(OP_INTEGRATION_RE.finditer(content))
    if not matches:
        return False
    last_match_pos = matches[-1].start()
    threshold = int(len(content) * 0.7)  # last 30% starts at 70%
    return last_match_pos >= threshold


@pytest.mark.parametrize("filename", ALL_FRAMEWORKS)
def test_every_framework_has_op_integration_in_last_30pct(filename: str) -> None:
    """KNOW-11: every framework/*.md must end with §Operational Integration."""
    content = _content(filename)
    assert _has_op_integration_in_last_30pct(content), (
        f"{filename}: §Operational Integration missing from last 30% of file. "
        f"Add `## Operational Integration` heading near the end of the file. "
        f"(Operator decision per RESEARCH §Open Questions item 5.)"
    )


def test_narrative_master_grid_structure() -> None:
    """KNOW-01: narrative-master-grid.md has all 5 grid sections + 15+ cited URLs."""
    content = _content("narrative-master-grid.md")
    for token in ("Polti", "Booker", "Tobias", "Save the Cat", "Truby"):
        assert token in content, f"narrative-master-grid.md missing grid: {token}"
    urls = re.findall(r"https?://[^\s)]+", content)
    distinct_hosts = {url.split("/")[2] for url in urls if "//" in url}
    assert len(distinct_hosts) >= 15, (
        f"narrative-master-grid.md has only {len(distinct_hosts)} distinct cited domains;"
        " KNOW-01 requires >=15"
    )


def test_sdt_spine_structure() -> None:
    """KNOW-02: sdt-spine.md has formula + Al-Bukhari = 70."""
    content = _content("sdt-spine.md")
    for token in (
        "Autonomy",
        "Competence",
        "Relatedness",
        "## The sdt_score Formula",
        "## The Worked Al-Bukhari Example",
    ):
        assert token in content, f"sdt-spine.md missing: {token}"
    assert re.search(r"sdt_score\s*=\s*70", content), (
        "sdt-spine.md missing explicit `sdt_score = 70` in worked example"
    )


def test_ajtbd_structure() -> None:
    """KNOW-03: ajtbd-segmentation.md has 8 JTBDs + 12 segments + ajtbd_score formula."""
    content = _content("ajtbd-segmentation.md")
    for token in (
        "## The 8 Universal Cinema JTBDs",
        "## The 12 Macro-Segments",
        "## The ajtbd_score Formula",
    ):
        assert token in content, f"ajtbd-segmentation.md missing: {token}"


def test_forced_collision_structure() -> None:
    """KNOW-04: forced-collision.md >=500 lines + 3 worked examples + 90-min clock + Eno hook."""
    content = _content("forced-collision.md")
    line_count = content.count("\n") + 1
    assert line_count >= 500, f"forced-collision.md has {line_count} lines; KNOW-04 requires >=500"
    for token in ("COLLISION OPERATOR", "Al-Bukhari", "Ostankino", "Mamontenok"):
        assert token in content, f"forced-collision.md missing: {token}"
    assert re.search(r"90-Minute Clock|90-minute clock", content), (
        "forced-collision.md missing 90-Minute Clock reference (revision-2 H6)"
    )
    assert "oblique_strategies.json" in content, (
        "forced-collision.md missing pipeline/data/oblique_strategies.json reference"
        " (revision-2 H6)"
    )


def test_character_arcs_structure() -> None:
    """KNOW-07: character-arcs.md has Truby/McKee/Egri/Jung-Pearson + >=9 worked moral args."""
    content = _content("character-arcs.md")
    for token in ("Truby", "McKee", "Egri", "Jung-Pearson"):
        assert token in content, f"character-arcs.md missing: {token}"
    premise_count = len(re.findall(r"premise:", content))
    assert premise_count >= 9, (
        f"character-arcs.md has only {premise_count} `premise:` entries;"
        " KNOW-07 requires >=9 worked moral arguments"
    )


def test_cinema_school_structure() -> None:
    """KNOW-08: cinema-school-doctrines.md has 10 schools + 10 boolean check fns."""
    content = _content("cinema-school-doctrines.md")
    schools = [
        "USC",
        "UCLA",
        "AFI",
        "NYU",
        "Columbia",
        "NFTS",
        "FAMU",
        "Lodz",
        "VGIK",
        "Beijing",
    ]
    for school in schools:
        assert school in content, f"cinema-school-doctrines.md missing school: {school}"
    fns = [
        "usc_check",
        "ucla_check",
        "afi_check",
        "nyu_check",
        "columbia_check",
        "nfts_check",
        "famu_check",
        "lodz_check",
        "vgik_check",
        "beijing_check",
    ]
    for fn in fns:
        assert fn in content, f"cinema-school-doctrines.md missing boolean fn: {fn}"
    # Revision-2 M12: FAMU must appear exactly once as a distinct school heading.
    famu_heading_count = len(re.findall(r"^### FAMU", content, flags=re.MULTILINE))
    assert famu_heading_count == 1, (
        f"cinema-school-doctrines.md has {famu_heading_count} `### FAMU` headings;"
        " revision-2 M12 requires exactly 1"
    )
