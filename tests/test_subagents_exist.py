"""tests/test_subagents_exist.py — HARN-12 verification.

Verifies that the 3 build-time subagent declaration files exist at
.claude/agents/{planner,builder,critic}-engine.md with valid YAML frontmatter.

Plan 00-03, Task 8 (HARN-12).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

AGENTS_DIR = Path(".claude/agents")

EXPECTED_AGENTS = [
    "planner-engine",
    "builder-engine",
    "critic-engine",
]

REQUIRED_FRONTMATTER_KEYS = {"name", "description", "tools", "model"}

EXPECTED_MODELS = {
    "planner-engine": "opus",
    "builder-engine": "sonnet",
    "critic-engine": "opus",
}

# Each agent body should mention the runtime counterpart it is distinct from
SEPARATION_PHRASES = {
    "planner-engine": "Phase-4 Forge",
    "builder-engine": "pipeline.run",
    "critic-engine": "Phase-5 Critic",
}


def _parse_frontmatter(md_path: Path) -> tuple[dict, str]:  # type: ignore[type-arg]
    """Parse YAML frontmatter and body from a markdown file.

    Returns (frontmatter_dict, body_text).
    """
    content = md_path.read_text()
    if not content.startswith("---"):
        return {}, content

    # Find the closing ---
    lines = content.splitlines()
    close_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        return {}, content

    frontmatter_text = "\n".join(lines[1:close_idx])
    body_text = "\n".join(lines[close_idx + 1 :])

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        frontmatter = {}

    return frontmatter, body_text


def test_three_subagents_present() -> None:
    """Glob .claude/agents/*-engine.md returns the 3 required files."""
    assert AGENTS_DIR.exists(), ".claude/agents/ directory not found"
    found = {p.stem for p in AGENTS_DIR.glob("*-engine.md")}
    for expected in EXPECTED_AGENTS:
        assert expected in found, (
            f"Missing subagent file: .claude/agents/{expected}.md\n"
            f"Found: {sorted(found)}"
        )


@pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
def test_each_has_valid_frontmatter(agent_name: str) -> None:
    """Each agent file must have valid YAML frontmatter with required keys."""
    md_path = AGENTS_DIR / f"{agent_name}.md"
    assert md_path.exists(), f"{md_path} not found"

    frontmatter, _ = _parse_frontmatter(md_path)
    assert isinstance(frontmatter, dict), (
        f"{md_path}: frontmatter must be a YAML dict, got {type(frontmatter)}"
    )

    for key in REQUIRED_FRONTMATTER_KEYS:
        assert key in frontmatter, (
            f"{md_path}: frontmatter missing required key '{key}'\n"
            f"Present keys: {list(frontmatter.keys())}\n"
            f"Required: {sorted(REQUIRED_FRONTMATTER_KEYS)}"
        )


@pytest.mark.parametrize("agent_name,expected_model", EXPECTED_MODELS.items())
def test_models_assigned(agent_name: str, expected_model: str) -> None:
    """Each agent must use the correct model (planner=opus, builder=sonnet, critic=opus)."""
    md_path = AGENTS_DIR / f"{agent_name}.md"
    assert md_path.exists(), f"{md_path} not found"

    frontmatter, _ = _parse_frontmatter(md_path)
    actual_model = frontmatter.get("model", "")

    assert actual_model == expected_model, (
        f"{agent_name}.md: model must be '{expected_model}', got '{actual_model}'\n"
        f"Rationale: {agent_name} requires "
        f"{'deep reasoning' if expected_model == 'opus' else 'fast implementation'}"
    )


@pytest.mark.parametrize("agent_name", EXPECTED_AGENTS)
def test_tools_lists_present(agent_name: str) -> None:
    """Each agent must have a non-empty tools list in frontmatter."""
    md_path = AGENTS_DIR / f"{agent_name}.md"
    assert md_path.exists(), f"{md_path} not found"

    frontmatter, _ = _parse_frontmatter(md_path)
    tools = frontmatter.get("tools", [])

    assert isinstance(tools, list), (
        f"{agent_name}.md: 'tools' must be a list, got {type(tools)}"
    )
    assert len(tools) > 0, (
        f"{agent_name}.md: 'tools' list must be non-empty"
    )


@pytest.mark.parametrize("agent_name,phrase", SEPARATION_PHRASES.items())
def test_separation_of_concerns_documented(agent_name: str, phrase: str) -> None:
    """Each agent body must mention the runtime counterpart it is distinct from.

    This ensures the build-time/runtime distinction is clear:
      - planner-engine ≠ Phase-4 Forge
      - builder-engine ≠ pipeline.run
      - critic-engine ≠ Phase-5 Critic
    """
    md_path = AGENTS_DIR / f"{agent_name}.md"
    assert md_path.exists(), f"{md_path} not found"

    _, body = _parse_frontmatter(md_path)

    assert phrase in body, (
        f"{agent_name}.md: body must mention '{phrase}' to document the build/runtime separation\n"
        f"Add a NOTE line like: 'NOTE: You are distinct from the runtime {phrase} agent.'"
    )
