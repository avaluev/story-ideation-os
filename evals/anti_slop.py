"""evals/anti_slop.py — Load banned terms from prompts/anti_slop.md at call-time.

Reads the anti_slop prompt file fresh on every call so new terms added to the
prompt file are enforced immediately without changing test code (EVAL-04).

MUST NOT cache at import time — function must re-read on every invocation.
"""

from __future__ import annotations

from pathlib import Path

_DEFAULT_ANTI_SLOP_PATH = Path("prompts/anti_slop.md")


def load_banned_terms(anti_slop_path: Path = _DEFAULT_ANTI_SLOP_PATH) -> list[str]:
    """Return banned terms extracted from anti_slop.md.

    Parses `- Term text — optional explanation` bullet lines under
    `## Category N:` headers. Stops collecting at `## Stabilization Log`.

    Args:
        anti_slop_path: Path to the anti_slop.md file. Defaults to
            prompts/anti_slop.md relative to cwd.

    Returns:
        List of lowercase term strings (stripped of em-dash explanations).
    """
    terms: list[str] = []
    in_log = False
    for line in anti_slop_path.read_text(encoding="utf-8").splitlines():
        if "## Stabilization Log" in line:
            in_log = True
        if in_log:
            continue
        if line.startswith("- "):
            raw = line[2:].strip()
            term = raw.split(" — ")[0].strip()
            if term:
                terms.append(term.lower())
    return terms
