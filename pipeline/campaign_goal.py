"""pipeline.campaign_goal -- typed loader for config/campaign_goal.json.

Loads the campaign-level definition-of-done thresholds and operational
guards so any module can read them without hard-coding threshold values.

Constraints
===========

- MUST NOT import ``anthropic``, ``httpx``, or ``openrouter_client``
  (ANOMALY-001 in scripts/lint_imports.py).
- MUST NOT import from ``frameworks/`` (ANOMALY-002).
- No LLM calls -- pure data loading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

DEFAULT_CAMPAIGN_GOAL_PATH: Final[Path] = Path("config/campaign_goal.json")


@dataclass(frozen=True)
class DefinitionOfDone:
    """Thresholds that declare the campaign complete."""

    reports: int
    languages: tuple[str, ...]
    packaging: str
    deep_links_per_report_min: int
    quote_bound_pct_min: float
    verified_density_min: float
    http_2xx_pct_min: float
    mean_card_grade: str
    every_dollar_has_inline_arithmetic: bool
    fabricated_count_max: int
    en_ru_parity: tuple[str, ...]


@dataclass(frozen=True)
class BaselineToExceed:
    """Metrics from the previous best run; new run must beat all of them."""

    verified_claims: int
    deep_link_pct: float
    quote_bound_pct: float
    mean_composite: float


@dataclass(frozen=True)
class Guards:
    """Operational safety guards."""

    make_test: str
    make_eval: str
    lint_imports: tuple[str, ...]
    webfetch_primary_forbidden: bool
    openrouter_optional: bool
    no_gemini: bool


@dataclass(frozen=True)
class Budget:
    """Cost / model-routing budget constraints."""

    research_max_concurrency: int
    iso_week_cache: bool
    opus_touch_budget: str
    exec_model: str


@dataclass(frozen=True)
class CampaignGoal:
    """Typed representation of config/campaign_goal.json.

    Frozen so downstream consumers cannot mutate thresholds in place.
    Every field has a helper on the class; callers must not reach into
    ``definition_of_done`` directly when a helper is available.
    """

    campaign: str
    created: str
    description: str
    definition_of_done: DefinitionOfDone
    baseline_to_exceed: BaselineToExceed
    guards: Guards
    budget: Budget
    concepts: tuple[str, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # Definition-of-done helpers
    # ------------------------------------------------------------------

    def deep_link_threshold(self) -> float:
        """Minimum deep-link percentage required for campaign completion."""
        return self.definition_of_done.verified_density_min

    def quote_threshold(self) -> float:
        """Minimum quote-bound percentage required for campaign completion."""
        return self.definition_of_done.quote_bound_pct_min

    def mean_grade_target(self) -> str:
        """Target mean card grade for campaign completion."""
        return self.definition_of_done.mean_card_grade

    def fabrication_allowed(self) -> bool:
        """True iff any fabricated claims are tolerated (always False in v6)."""
        return self.definition_of_done.fabricated_count_max > 0

    # ------------------------------------------------------------------
    # Guard helpers
    # ------------------------------------------------------------------

    def no_gemini_guard(self) -> bool:
        """Return True when the Gemini dispatcher is forbidden by policy."""
        return self.guards.no_gemini

    def exec_model(self) -> str:
        """Return the required execution model slug (e.g. ``'sonnet'``)."""
        return self.budget.exec_model

    # ------------------------------------------------------------------
    # Baseline comparison helpers
    # ------------------------------------------------------------------

    def beats_baseline_deep_link(self, pct: float) -> bool:
        """Return True when *pct* strictly exceeds the baseline deep-link pct."""
        return pct > self.baseline_to_exceed.deep_link_pct

    def beats_baseline_quote(self, pct: float) -> bool:
        """Return True when *pct* strictly exceeds the baseline quote-bound pct."""
        return pct > self.baseline_to_exceed.quote_bound_pct

    def beats_baseline_composite(self, mean: float) -> bool:
        """Return True when *mean* strictly exceeds the baseline mean composite."""
        return mean > self.baseline_to_exceed.mean_composite


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_definition_of_done(raw: dict[str, Any]) -> DefinitionOfDone:
    return DefinitionOfDone(
        reports=int(raw["reports"]),
        languages=tuple(str(x) for x in raw.get("languages", [])),
        packaging=str(raw.get("packaging", "")),
        deep_links_per_report_min=int(raw.get("deep_links_per_report_min", 0)),
        quote_bound_pct_min=float(raw["quote_bound_pct_min"]),
        verified_density_min=float(raw["verified_density_min"]),
        http_2xx_pct_min=float(raw.get("http_2xx_pct_min", 0.0)),
        mean_card_grade=str(raw["mean_card_grade"]),
        every_dollar_has_inline_arithmetic=bool(
            raw.get("every_dollar_has_inline_arithmetic", False)
        ),
        fabricated_count_max=int(raw.get("fabricated_count_max", 0)),
        en_ru_parity=tuple(str(x) for x in raw.get("en_ru_parity", [])),
    )


def _parse_baseline(raw: dict[str, Any]) -> BaselineToExceed:
    return BaselineToExceed(
        verified_claims=int(raw["verified_claims"]),
        deep_link_pct=float(raw["deep_link_pct"]),
        quote_bound_pct=float(raw["quote_bound_pct"]),
        mean_composite=float(raw["mean_composite"]),
    )


def _parse_guards(raw: dict[str, Any]) -> Guards:
    return Guards(
        make_test=str(raw.get("make_test", "")),
        make_eval=str(raw.get("make_eval", "")),
        lint_imports=tuple(str(x) for x in raw.get("lint_imports", [])),
        webfetch_primary_forbidden=bool(raw.get("webfetch_primary_forbidden", False)),
        openrouter_optional=bool(raw.get("openrouter_optional", False)),
        no_gemini=bool(raw.get("no_gemini", False)),
    )


def _parse_budget(raw: dict[str, Any]) -> Budget:
    return Budget(
        research_max_concurrency=int(raw.get("research_max_concurrency", 4)),
        iso_week_cache=bool(raw.get("iso_week_cache", False)),
        opus_touch_budget=str(raw.get("opus_touch_budget", "minimal")),
        exec_model=str(raw["exec_model"]),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_campaign_goal(path: Path | str | None = None) -> CampaignGoal:
    """Load and parse *config/campaign_goal.json* into a :class:`CampaignGoal`.

    Parameters
    ----------
    path:
        Optional override for the JSON file location. Defaults to
        :data:`DEFAULT_CAMPAIGN_GOAL_PATH` (``config/campaign_goal.json``
        relative to the working directory, which matches the project root
        convention used by every other loader in the pipeline).

    Raises
    ------
    FileNotFoundError
        When the resolved path does not exist.
    KeyError
        When a required field is missing from the JSON.
    ValueError
        When a field cannot be coerced to its expected type.
    """
    resolved = Path(path) if path is not None else DEFAULT_CAMPAIGN_GOAL_PATH
    raw: dict[str, Any] = json.loads(resolved.read_text(encoding="utf-8"))

    return CampaignGoal(
        campaign=str(raw["campaign"]),
        created=str(raw.get("created", "")),
        description=str(raw.get("description", "")),
        definition_of_done=_parse_definition_of_done(raw["definition_of_done"]),
        baseline_to_exceed=_parse_baseline(raw["baseline_to_exceed"]),
        guards=_parse_guards(raw["guards"]),
        budget=_parse_budget(raw["budget"]),
        concepts=tuple(str(x) for x in raw.get("concepts", [])),
    )


__all__ = [
    "DEFAULT_CAMPAIGN_GOAL_PATH",
    "BaselineToExceed",
    "Budget",
    "CampaignGoal",
    "DefinitionOfDone",
    "Guards",
    "load_campaign_goal",
]
