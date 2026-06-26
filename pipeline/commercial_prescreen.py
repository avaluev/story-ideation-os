"""Commercial Viability Pre-Screen — Karpathy Fix #1.

Rule-based gate that evaluates a SeedPackage's commercial potential
BEFORE any LLM agent runs. Eliminates prestige-indie seeds that cannot
plausibly reach $50M+ revenue, saving the full 4-agent pipeline cost.

Logic:
- High-weight binary tensions with proven $100M+ track record -> PASS
- Unusual spaces that are universally relatable -> PASS bonus
- Overdone or hyper-niche combinations -> FAIL
- Borderline cases -> MAYBE (proceed with caution flag)

Usage:
    from pipeline.commercial_prescreen import prescreen
    result = prescreen(seed_package)
    if result.verdict == "FAIL":
        # discard and pick a new seed
    elif result.verdict == "MAYBE":
        # proceed but note the commercial ceiling risk
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Binary tensions with documented $100M+ track records
_HIGH_COMMERCIAL_BT: Final[frozenset[str]] = frozenset(
    {
        "BT-001",  # Love vs Duty (Titanic, The Notebook)
        "BT-003",  # Justice vs Revenge (John Wick, Gladiator, Kill Bill)
        "BT-005",  # Memory vs Sanity (Memento, Eternal Sunshine, Oldboy)
        "BT-007",  # Faith vs Evidence (A Few Good Men, First Reformed)
        "BT-009",  # Healing vs Truth (Ordinary People, Spotlight)
        "BT-013",  # Control vs Surrender (Black Swan, Whiplash, Misery)
        "BT-017",  # Visibility vs Invisibility (Get Out, Us, Parasite)
        "BT-021",  # Rage vs Forgiveness (Manchester by the Sea, Prisoners)
        "BT-025",  # Purpose vs Pleasure (The Social Network, Whiplash)
        "BT-033",  # Love vs Obsession (Fatal Attraction, Single White Female)
        "BT-043",  # Authority vs Conscience (A Few Good Men, Erin Brockovich)
        "BT-044",  # Transparency vs Privacy (The Social Network, Snowden)
    }
)

# Universal unusual spaces (any audience can project into them)
_UNIVERSAL_US_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "corporation",
        "hospital",
        "courtroom",
        "school",
        "family",
        "workplace",
        "city",
        "community",
        "government",
        "military",
        "48 hours",
        "last day",
        "first year",
        "final",
        "last",
        "ai",
        "algorithm",
        "memory",
        "identity",
        "trial",
    }
)

# Overdone binary tensions that saturate the market
_OVERDONE_BT: Final[frozenset[str]] = frozenset(
    {
        "BT-029",  # Tradition vs Survival (Western, historical drama - saturated)
        "BT-027",  # Nature vs Nurture (prestige drama - low commercial ceiling)
    }
)

# Minimum resonance score to pass without additional bonuses
_MIN_RESONANCE_PASS: Final[float] = 0.70
_MIN_RESONANCE_MAYBE: Final[float] = 0.55
_MIN_CEILING_PASS_M: Final[float] = 60.0


@dataclass(frozen=True)
class PrescreenResult:
    """Result of commercial viability pre-screen."""

    verdict: str  # "PASS" | "MAYBE" | "FAIL"
    commercial_score: float  # 0.0 - 1.0
    ceiling_estimate_M: float  # rough revenue ceiling in millions
    reasons: list[str]
    recommendation: str


def prescreen(seed: object) -> PrescreenResult:
    """Evaluate a SeedPackage for commercial viability.

    Args:
        seed: A SeedPackage from pipeline.seed_picker (duck-typed to avoid
              circular imports; must have bt_id, us_space, resonance_score,
              novelty_band attributes).

    Returns:
        PrescreenResult with verdict and reasoning.
    """
    bt_id: str = str(getattr(seed, "bt_id", ""))
    us_space: str = str(getattr(seed, "us_space", "")).lower()
    resonance: float = float(getattr(seed, "resonance_score", 0.5))
    novelty_band: str = str(getattr(seed, "novelty_band", "neutral"))

    score = resonance
    reasons: list[str] = []
    ceiling = 30.0  # default prestige indie ceiling

    # Hard fail: overdone binary tension
    if bt_id in _OVERDONE_BT:
        reasons.append(f"{bt_id} is a market-saturated binary tension (prestige indie ceiling)")
        return PrescreenResult(
            verdict="FAIL",
            commercial_score=0.2,
            ceiling_estimate_M=15.0,
            reasons=reasons,
            recommendation="Discard. Pick a new seed.",
        )

    # Strong positive: high-commercial BT
    if bt_id in _HIGH_COMMERCIAL_BT:
        score = min(1.0, score + 0.15)
        ceiling = max(ceiling, 80.0)
        reasons.append(f"{bt_id} has documented $100M+ track record")

    # Universal space bonus
    us_words = set(us_space.split())
    matched = _UNIVERSAL_US_KEYWORDS & us_words
    if len(matched) >= 2:  # noqa: PLR2004
        score = min(1.0, score + 0.10)
        ceiling = max(ceiling, 120.0)
        reasons.append(f"Universal setting keywords: {', '.join(sorted(matched))}")
    elif len(matched) == 1:
        ceiling = max(ceiling, 60.0)
        reasons.append(f"Partially universal setting: {next(iter(matched))}")

    # Underexplored novelty band: white space = commercial opportunity
    if novelty_band == "underexplored":
        score = min(1.0, score + 0.10)
        ceiling = max(ceiling, 100.0)
        reasons.append("Underexplored cell: white space in the market")
    elif novelty_band == "overdone":
        score = max(0.0, score - 0.15)
        ceiling = min(ceiling, 40.0)
        reasons.append("Overdone cell: saturated market territory")

    # Verdict
    if not reasons:
        reasons.append("No strong commercial signals; evaluate manually")

    if score >= _MIN_RESONANCE_PASS and ceiling >= _MIN_CEILING_PASS_M:
        verdict = "PASS"
        recommendation = "Proceed with full 4-agent pipeline."
    elif score >= _MIN_RESONANCE_MAYBE:
        verdict = "MAYBE"
        recommendation = (
            "Proceed with caution. Apply audience amplification vectors "
            "before investor pitch to close the revenue gap."
        )
    else:
        verdict = "FAIL"
        recommendation = "Discard. Revenue ceiling too low. Pick a new seed."

    return PrescreenResult(
        verdict=verdict,
        commercial_score=round(score, 3),
        ceiling_estimate_M=ceiling,
        reasons=reasons,
        recommendation=recommendation,
    )
