"""EVAL: Veracity mode-honesty gate — closes the offline-cert loophole.

Two independent safeguards:

(a) SYNTHETIC — always runs, no skip.
    Proves that the grade gate (_enforce_grade_gate) and the density gate
    (_enforce_density_gate) both refuse an OFFLINE CredibilityScore, even
    when the scorecard composite/density figures look perfect.

(b) ARTIFACT SCAN — parameterised over every *.veracity.json under
    outputs/ and runs/.
    FAIL if ``scorecard.mode`` is not "online" (absent key is treated as
    "offline") AND the scorecard claims either grade A or any assessment
    carries a VERIFIED verdict.  An offline/legacy artifact must not
    misrepresent itself as agent-confirmed evidence.

Run::

    uv run pytest evals/test_veracity_mode_honesty.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.veracity.__main__ import (
    _GATE_EXIT_FAIL,
    _enforce_density_gate,
    _enforce_grade_gate,
)
from pipeline.veracity.claims import Claim
from pipeline.veracity.provenance import Provenance
from pipeline.veracity.scorecard import (
    MODE_OFFLINE,
    ClaimAssessment,
    CredibilityScore,
)
from pipeline.veracity.verdict import Verdict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
_GRADE_A_COMPOSITE: float = 91.0
_DENSITY_ABOVE_FLOOR: float = 80.0
_DENSITY_FLOOR: float = 0.70


def _make_offline_grade_a_score() -> CredibilityScore:
    """A plausible-looking A-grade scorecard stamped as OFFLINE."""
    return CredibilityScore(
        composite=_GRADE_A_COMPOSITE,
        grade="A",
        n_total=10,
        n_external=10,
        n_computed=0,
        fabricated_count=0,
        mode=MODE_OFFLINE,
        claim_density_pct=_DENSITY_ABOVE_FLOOR,
    )


def _make_dummy_assessments() -> list[ClaimAssessment]:
    """One SUPPORTED claim — enough for the gate to compute per-concept scores."""
    claim = Claim(
        claim_id="test_offline_001",
        concept_id="concept_offline",
        concept_title="Offline Film",
        claim_type="demand",
        text="Global streaming audience 1.2B",
        value="$1.2B",
        cited_url="https://example.com/deep/stats/2024",
    )
    prov = Provenance(
        url="https://example.com/deep/stats/2024",
        http_status=None,
        fetched_at="2026-01-01T00:00:00Z",
        content_sha256=None,
        quote="",
        supports_claim=False,
    )
    return [ClaimAssessment(claim, Verdict.SUPPORTED, prov)]


# ---------------------------------------------------------------------------
# (a) SYNTHETIC GATE TESTS — no skip, always execute
# ---------------------------------------------------------------------------


def test_grade_gate_rejects_offline_scorecard() -> None:
    """_enforce_grade_gate MUST return _GATE_EXIT_FAIL for an OFFLINE score.

    An offline structural pass confirms citation *form*, not network
    reachability.  Certifying it as grade A would allow unverified slates
    to ship as investor-grade.
    """
    score = _make_offline_grade_a_score()
    assessments = _make_dummy_assessments()

    rc = _enforce_grade_gate(assessments, score, minimum="A")

    assert rc == _GATE_EXIT_FAIL, (
        f"_enforce_grade_gate returned {rc!r} for an OFFLINE score; "
        f"expected {_GATE_EXIT_FAIL!r} (_GATE_EXIT_FAIL).  "
        f"An offline scorecard MUST NOT pass the grade gate."
    )


def test_density_gate_rejects_offline_scorecard() -> None:
    """_enforce_density_gate MUST return _GATE_EXIT_FAIL for an OFFLINE score.

    Even when claim_density_pct is well above the floor, an offline run has
    not fetched any URLs — density is structurally zero, not agent-confirmed.
    """
    score = _make_offline_grade_a_score()

    rc = _enforce_density_gate(score, floor=_DENSITY_FLOOR)

    assert rc == _GATE_EXIT_FAIL, (
        f"_enforce_density_gate returned {rc!r} for an OFFLINE score with "
        f"claim_density_pct={score.claim_density_pct}%; "
        f"expected {_GATE_EXIT_FAIL!r}.  "
        f"Offline density figures are unconfirmed and MUST NOT pass the density gate."
    )


def test_grade_gate_rejects_offline_regardless_of_density() -> None:
    """_enforce_grade_gate blocks even if density_pct is 100 and fabricated=0."""
    score = CredibilityScore(
        composite=95.0,
        grade="A",
        n_total=5,
        n_external=5,
        n_computed=0,
        fabricated_count=0,
        mode=MODE_OFFLINE,
        claim_density_pct=100.0,
    )
    assessments = _make_dummy_assessments()

    rc = _enforce_grade_gate(assessments, score, minimum="A")

    assert rc == _GATE_EXIT_FAIL, (
        "Grade gate must refuse OFFLINE even with perfect density figures."
    )


def test_density_gate_rejects_offline_regardless_of_density_pct() -> None:
    """_enforce_density_gate blocks OFFLINE even when claim_density_pct == 100."""
    score = CredibilityScore(
        composite=95.0,
        grade="A",
        n_total=5,
        n_external=5,
        n_computed=0,
        fabricated_count=0,
        mode=MODE_OFFLINE,
        claim_density_pct=100.0,
    )

    rc = _enforce_density_gate(score, floor=0.50)

    assert rc == _GATE_EXIT_FAIL, (
        "Density gate must refuse OFFLINE regardless of the density figure."
    )


# ---------------------------------------------------------------------------
# (b) ARTIFACT SCAN — parameterised over on-disk *.veracity.json files
# ---------------------------------------------------------------------------


def _collect_veracity_artifacts() -> list[Path]:
    """Return all *.veracity.json files under outputs/ and runs/."""
    artifacts: list[Path] = []
    for base in ("outputs", "runs"):
        base_dir = REPO_ROOT / base
        if base_dir.is_dir():
            artifacts.extend(base_dir.rglob("*.veracity.json"))
    return sorted(artifacts)


_ALL_ARTIFACTS = _collect_veracity_artifacts()


@pytest.mark.parametrize(
    "artifact_path",
    _ALL_ARTIFACTS,
    ids=[p.name for p in _ALL_ARTIFACTS],
)
def test_no_offline_artifact_claims_grade_a_or_verified(artifact_path: Path) -> None:
    """An offline (or mode-absent) artifact MUST NOT present grade A or VERIFIED verdicts.

    The offline structural pass only confirms URL *form*; it never fetches
    content.  Presenting an offline artifact as grade A or as having VERIFIED
    claims misrepresents structural compliance as agent-confirmed evidence —
    the loophole this eval closes.

    A missing ``mode`` key is treated as offline: any pre-mode-field artifact
    cannot prove it was online.
    """
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    scorecard: dict = raw.get("scorecard", {})
    assessments: list[dict] = raw.get("assessments", [])

    mode: str = scorecard.get("mode", "offline")  # absent key → treat as offline
    grade: str = scorecard.get("grade", "F")
    verdicts: list[str] = [a.get("verdict", "") for a in assessments]

    if mode == "online":
        # Online artifacts are agent-confirmed — no restriction.
        return

    # mode is "offline" or absent (legacy): neither grade A nor VERIFIED is allowed.
    violations: list[str] = []

    if grade == "A":
        composite = scorecard.get("composite", 0.0)
        violations.append(
            f"grade=A (composite={composite}) on an offline/legacy artifact — "
            f"offline grades reflect citation form, not confirmed reachability"
        )

    verified_indices = [i for i, v in enumerate(verdicts) if v == "VERIFIED"]
    if verified_indices:
        sample = verified_indices[:5]
        violations.append(
            f"{len(verified_indices)} assessment(s) carry verdict=VERIFIED "
            f"in an offline/legacy artifact (indices {sample}…) — "
            f"VERIFIED requires an agent-confirmed online fetch"
        )

    assert not violations, (
        f"{artifact_path.name}: offline-cert loophole detected:\n"
        + "\n".join(f"  • {v}" for v in violations)
        + f"\n  scorecard.mode={mode!r}  "
        + "Fix: re-run with --online to produce a legitimate online artifact, "
        + "or remove the stale file."
    )
