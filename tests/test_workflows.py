"""tests/test_workflows.py — OPS-07: Structural validation of GitHub Actions workflows.

Checks that both workflow YAML files exist and contain the required structural
elements (cron schedules, step names, PR creation action).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_NIGHTLY_EVAL_YML = Path(".github/workflows/nightly-eval.yml")
_REFRESH_PRICES_YML = Path(".github/workflows/refresh-prices.yml")


def _load_yaml(path: Path) -> dict:
    """Load a YAML file and return parsed content."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _get_on_block(data: dict) -> dict:
    """Return the workflow trigger block.

    PyYAML 1.1 parses bare 'on' as boolean True, so check both True and 'on'.
    """
    result = data.get(True, data.get("on", {}))
    return result if isinstance(result, dict) else {}


def _get_schedule_crons(data: dict) -> list[str]:
    """Extract all cron strings from a workflow's schedule trigger."""
    on_block = _get_on_block(data)
    schedule = on_block.get("schedule", []) or []
    return [entry.get("cron", "") for entry in schedule if isinstance(entry, dict)]


# ---------------------------------------------------------------------------
# nightly-eval.yml structural tests
# ---------------------------------------------------------------------------


def test_nightly_eval_yml_exists() -> None:
    """nightly-eval.yml must exist under .github/workflows/."""
    assert _NIGHTLY_EVAL_YML.exists(), f"{_NIGHTLY_EVAL_YML} not found — create it (OPS-07)"


def test_nightly_eval_has_cron() -> None:
    """nightly-eval.yml must schedule at 03:00 UTC ('0 3 * * *')."""
    crons = _get_schedule_crons(_load_yaml(_NIGHTLY_EVAL_YML))
    assert "0 3 * * *" in crons, (
        f"Expected cron '0 3 * * *' in nightly-eval.yml schedule, got: {crons}"
    )


def test_nightly_eval_runs_make_eval() -> None:
    """nightly-eval.yml must have a step that runs pytest evals/ or make eval."""
    data = _load_yaml(_NIGHTLY_EVAL_YML)
    jobs = data.get("jobs", {})
    all_run_lines: list[str] = []
    for job in jobs.values():
        for step in job.get("steps", []):
            run_val = step.get("run", "")
            if run_val:
                all_run_lines.append(run_val)
    joined = "\n".join(all_run_lines)
    assert ("pytest evals/" in joined) or ("make eval" in joined), (
        f"No step runs pytest evals/ or make eval in nightly-eval.yml. Found run blocks:\n{joined}"
    )


# ---------------------------------------------------------------------------
# refresh-prices.yml structural tests
# ---------------------------------------------------------------------------


def test_refresh_prices_yml_exists() -> None:
    """refresh-prices.yml must exist under .github/workflows/."""
    assert _REFRESH_PRICES_YML.exists(), f"{_REFRESH_PRICES_YML} not found — create it (OPS-07)"


def test_refresh_prices_weekly_cron() -> None:
    """refresh-prices.yml must run weekly (Monday 06:00 UTC — '0 6 * * 1')."""
    crons = _get_schedule_crons(_load_yaml(_REFRESH_PRICES_YML))
    assert "0 6 * * 1" in crons, (
        f"Expected cron '0 6 * * 1' in refresh-prices.yml schedule, got: {crons}"
    )


def test_refresh_prices_has_pr_step() -> None:
    """refresh-prices.yml must use peter-evans/create-pull-request action."""
    data = _load_yaml(_REFRESH_PRICES_YML)
    jobs = data.get("jobs", {})
    uses_values: list[str] = []
    for job in jobs.values():
        for step in job.get("steps", []):
            uses_val = step.get("uses", "")
            if uses_val:
                uses_values.append(uses_val)
    assert any("peter-evans/create-pull-request" in u for u in uses_values), (
        f"No peter-evans/create-pull-request step found in refresh-prices.yml. Uses: {uses_values}"
    )
