"""tests/test_golden_examples.py — GOLD-01..04, STAB-06 golden fixtures verification.

Verifies:
- examples/golden/ has 3 golden A4 concept files with correct scores, sections, and URLs
- examples/rejected/ has exactly 4 rejected anchor files with ## Why This Failed
- docs/CHANGELOG.md has v3.0 entry

Run: uv run pytest tests/test_golden_examples.py -x
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent
GOLDEN_DIR = ROOT / "examples" / "golden"
REJECTED_DIR = ROOT / "examples" / "rejected"
CHANGELOG = ROOT / "docs" / "CHANGELOG.md"

_SEARCH_DENYLIST_HOSTS = frozenset(
    {
        "google.com",
        "www.google.com",
        "bing.com",
        "www.bing.com",
        "duckduckgo.com",
        "www.duckduckgo.com",
        "search.brave.com",
        "yandex.com",
        "www.yandex.com",
        "yahoo.com",
        "search.yahoo.com",
    }
)

_GOLDEN_FILES = [
    "HC-bukhari.md",
    "HC-ostankino.md",
    "HC-mamontenok.md",
]

_SCORE_FLOORS = {
    "HC-bukhari.md": 96,
    "HC-ostankino.md": 90,
    "HC-mamontenok.md": 85,
}


# ---------------------------------------------------------------------------
# YAML frontmatter parsing helpers (stdlib only — no PyYAML import)
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Parse the first YAML frontmatter block delimited by '---' lines.

    Supports simple key: value pairs and list values like:
      key: ["SA", "ID"]
      key: [SA, ID]
    Returns an empty dict if no frontmatter block is found.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}

    result: dict[str, object] = {}
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()
        # List value detection
        if raw_val.startswith("[") and raw_val.endswith("]"):
            inner = raw_val[1:-1]
            items = [v.strip().strip('"').strip("'") for v in inner.split(",")]
            result[key] = items
        # Bool
        elif raw_val.lower() == "true":
            result[key] = True
        elif raw_val.lower() == "false":
            result[key] = False
        else:
            # Try int
            try:
                result[key] = int(raw_val)
            except ValueError:
                # Try float
                try:
                    result[key] = float(raw_val)
                except ValueError:
                    # String — strip quotes
                    result[key] = raw_val.strip('"').strip("'")
    return result


def _extract_urls(text: str) -> list[str]:
    """Extract all http/https URLs from markdown text."""
    url_pattern = re.compile(r'https?://[^\s\)\]"\'<>]+')
    return url_pattern.findall(text)


def _is_bare_domain(url: str) -> bool:
    """Return True if URL has no meaningful path (just '/' or empty).

    A bare domain is one where path is '' or '/' and there's no query or fragment.
    """
    parsed = urlparse(url)
    path = parsed.path
    return path in ("", "/") and not parsed.query and not parsed.fragment


# ---------------------------------------------------------------------------
# Golden file existence tests
# ---------------------------------------------------------------------------


def test_golden_files_exist() -> None:
    """examples/golden/ must contain the three golden A4 concept files (GOLD-01..03)."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist — run plan 06-01 to create it"
    for filename in _GOLDEN_FILES:
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), (
            f"Missing golden file: {filepath}\n"
            "Create examples/golden/{filename} with full 12-section A4 format."
        )


# ---------------------------------------------------------------------------
# Section count tests
# ---------------------------------------------------------------------------


def test_golden_section_count() -> None:
    """Each golden file must contain exactly 12 '## ' section headings (A4 format)."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist"
    for filename in _GOLDEN_FILES:
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), f"Missing: {filepath}"
        content = filepath.read_text()
        # Count '## ' headings (not ### or ####)
        section_headings = re.findall(r"^## .+", content, re.MULTILINE)
        assert len(section_headings) == 12, (
            f"{filename} has {len(section_headings)} '## ' sections; expected 12.\n"
            f"Found: {section_headings}"
        )


# ---------------------------------------------------------------------------
# Frontmatter tests
# ---------------------------------------------------------------------------


def test_golden_frontmatter_present() -> None:
    """Each golden file must have YAML frontmatter delimited by '---'."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist"
    for filename in _GOLDEN_FILES:
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), f"Missing: {filepath}"
        content = filepath.read_text()
        fm = _parse_frontmatter(content)
        assert fm, (
            f"{filename} has no parseable YAML frontmatter.\n"
            "First block must start and end with '---' lines."
        )
        assert "concept_id" in fm, f"{filename} frontmatter missing 'concept_id'"


def test_golden_score_floors() -> None:
    """Score floors: HC-bukhari==96, HC-ostankino>=90, HC-mamontenok>=85."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist"
    for filename, floor in _SCORE_FLOORS.items():
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), f"Missing: {filepath}"
        fm = _parse_frontmatter(filepath.read_text())
        assert "score" in fm, f"{filename} frontmatter missing 'score' field"
        score = fm["score"]
        assert isinstance(score, (int, float)), f"{filename} score must be numeric; got {score!r}"
        if filename == "HC-bukhari.md":
            assert score == 96, f"{filename} score must be exactly 96; got {score}"
        else:
            assert score >= floor, f"{filename} score {score} is below floor {floor}"


def test_golden_audience_floor() -> None:
    """Each golden file must have audience_size >= 50_000_000 in frontmatter."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist"
    for filename in _GOLDEN_FILES:
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), f"Missing: {filepath}"
        fm = _parse_frontmatter(filepath.read_text())
        assert "audience_size" in fm, f"{filename} frontmatter missing 'audience_size'"
        aud = fm["audience_size"]
        assert isinstance(aud, (int, float)), (
            f"{filename} audience_size must be numeric; got {aud!r}"
        )
        assert aud >= 50_000_000, f"{filename} audience_size {aud} is below 50M floor"


# ---------------------------------------------------------------------------
# URL quality tests
# ---------------------------------------------------------------------------


def test_golden_no_bare_domain_urls() -> None:
    """No URL in any golden file may be a bare domain (path == '' or '/')."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist"
    violations: list[str] = []
    for filename in _GOLDEN_FILES:
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), f"Missing: {filepath}"
        for url in _extract_urls(filepath.read_text()):
            if _is_bare_domain(url):
                violations.append(f"{filename}: {url}")
    assert not violations, (
        f"Bare-domain URLs found in golden files ({len(violations)}):\n" + "\n".join(violations)
    )


def test_golden_no_search_redirect_urls() -> None:
    """No URL in any golden file may point to a search engine."""
    assert GOLDEN_DIR.exists(), f"{GOLDEN_DIR} does not exist"
    violations: list[str] = []
    for filename in _GOLDEN_FILES:
        filepath = GOLDEN_DIR / filename
        assert filepath.exists(), f"Missing: {filepath}"
        for url in _extract_urls(filepath.read_text()):
            host = urlparse(url).hostname or ""
            if host in _SEARCH_DENYLIST_HOSTS:
                violations.append(f"{filename}: {url}")
    assert not violations, (
        f"Search-engine URLs found in golden files ({len(violations)}):\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rejected anchor tests
# ---------------------------------------------------------------------------


def test_rejected_count() -> None:
    """examples/rejected/ must contain exactly 4 .md files (GOLD-04)."""
    assert REJECTED_DIR.exists(), f"{REJECTED_DIR} does not exist"
    md_files = list(REJECTED_DIR.glob("*.md"))
    assert len(md_files) == 4, (
        f"Expected exactly 4 rejected anchor files; found {len(md_files)}: "
        f"{[f.name for f in md_files]}"
    )


def test_rejected_have_why_section() -> None:
    """Each rejected file must contain '## Why This Failed' section."""
    assert REJECTED_DIR.exists(), f"{REJECTED_DIR} does not exist"
    for filepath in sorted(REJECTED_DIR.glob("*.md")):
        content = filepath.read_text()
        assert "## Why This Failed" in content, (
            f"{filepath.name} is missing the '## Why This Failed' section.\n"
            "All rejected anchors must document why they were rejected."
        )


def test_rejected_have_frontmatter() -> None:
    """Each rejected file must have YAML frontmatter with status: rejected and failure_mode."""
    assert REJECTED_DIR.exists(), f"{REJECTED_DIR} does not exist"
    for filepath in sorted(REJECTED_DIR.glob("*.md")):
        fm = _parse_frontmatter(filepath.read_text())
        assert fm, f"{filepath.name} has no parseable YAML frontmatter"
        assert fm.get("status") == "rejected", (
            f"{filepath.name} frontmatter 'status' must be 'rejected'; got {fm.get('status')!r}"
        )
        assert "failure_mode" in fm, f"{filepath.name} frontmatter missing 'failure_mode' field"


# ---------------------------------------------------------------------------
# CHANGELOG tests
# ---------------------------------------------------------------------------


def test_changelog_exists() -> None:
    """docs/CHANGELOG.md must exist (STAB-06)."""
    assert CHANGELOG.exists(), (
        f"{CHANGELOG} not found — create it with the v3.0 build history entry"
    )


def test_changelog_has_v3_entry() -> None:
    """docs/CHANGELOG.md must contain 'v3.0' and '2026'."""
    assert CHANGELOG.exists(), f"{CHANGELOG} missing"
    content = CHANGELOG.read_text()
    assert "v3.0" in content, f"{CHANGELOG} must contain 'v3.0'"
    assert "2026" in content, f"{CHANGELOG} must contain '2026' (year)"
