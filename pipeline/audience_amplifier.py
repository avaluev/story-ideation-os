"""Audience Amplification Loop — compound multiplier engine for commercial scale.

Mental model: a 'periodic table' of audience vectors where certain combinations
produce non-linear (synergistic) multipliers. Like chemistry: mixing element 1 + 3
can yield 10x, not just 1x + 3x = 4x additive.

The loop applies vectors in order of highest leverage, detects synergy bonuses,
and produces a decision trail showing exactly what was done and why.

Usage:
    from pipeline.audience_amplifier import amplification_loop, render_trail
    result = amplification_loop("the-sleeper", base_audience_M=45.0)
    print(render_trail(result))

    # CLI: uv run python -m pipeline.audience_amplifier --concept the-sleeper --base 45
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_DEFAULT_VECTORS: Final[Path] = _REPO_ROOT / "pipeline" / "data" / "amplification_vectors.json"

# Revenue bands (rough comp-based guide, not financial advice)
_REVENUE_BANDS: Final[list[tuple[float, str]]] = [
    (500.0, "$250M-$500M+ theatrical / $100M+ streaming acquisition"),
    (200.0, "$100M-$250M theatrical / $40M-$80M streaming acquisition"),
    (100.0, "$50M-$120M theatrical / $25M-$45M streaming acquisition"),
    (50.0, "$20M-$55M theatrical / $15M-$30M streaming acquisition"),
    (0.0, "Under $50M addressable - concept needs more amplification"),
]


@dataclass
class AmplificationVector:
    id: str
    name: str
    category: str
    base_multiplier: float
    conditions: list[str]
    evidence: str
    synergy_with: dict[str, float] = field(default_factory=lambda: cast(dict[str, float], {}))


@dataclass
class IterationDecision:
    iteration: int
    vector_id: str
    vector_name: str
    synergy_activated: str | None
    audience_before_M: float
    audience_after_M: float
    multiplier_used: float
    reasoning: str


@dataclass
class AmplificationResult:
    concept_slug: str
    base_audience_M: float
    final_audience_M: float
    total_multiplier: float
    iterations: list[IterationDecision]
    vectors_applied: list[str]
    vectors_remaining: list[str]
    revenue_implication: str


def load_vectors(path: Path = _DEFAULT_VECTORS) -> dict[str, AmplificationVector]:
    raw: list[Any] = cast(list[Any], json.loads(path.read_text(encoding="utf-8")))
    result: dict[str, AmplificationVector] = {}
    for entry in raw:
        e: dict[str, Any] = cast(dict[str, Any], entry)
        vid: str = str(e["id"])
        raw_syn: dict[str, Any] = cast(dict[str, Any], e.get("synergy_with", {}))
        result[vid] = AmplificationVector(
            id=vid,
            name=str(e["name"]),
            category=str(e["category"]),
            base_multiplier=float(e["base_multiplier"]),
            conditions=list(e.get("conditions", [])),
            evidence=str(e.get("evidence", "")),
            synergy_with={str(k): float(v) for k, v in raw_syn.items()},
        )
    return result


def _best_move(
    applied: set[str],
    vectors: dict[str, AmplificationVector],
) -> tuple[str | None, float, str | None]:
    """Return (vector_id, effective_multiplier, synergy_label) for the highest-leverage
    unapplied vector. Synergy bonuses activate when the partner vector is already applied."""
    best_id: str | None = None
    best_mult = 1.0
    best_synergy: str | None = None

    for vid, v in vectors.items():
        if vid in applied:
            continue
        # Start with base multiplier
        mult = v.base_multiplier
        activated_synergy: str | None = None

        # Check if any synergy partner is already applied → upgrade multiplier
        for partner_id, synergy_mult in v.synergy_with.items():
            if partner_id in applied and synergy_mult > mult:
                mult = synergy_mult
                activated_synergy = f"{vid}⊕{partner_id}"

        if mult > best_mult:
            best_mult = mult
            best_id = vid
            best_synergy = activated_synergy

    return best_id, best_mult, best_synergy


def _revenue_band(audience_M: float) -> str:
    for threshold, label in _REVENUE_BANDS:
        if audience_M >= threshold:
            return label
    return _REVENUE_BANDS[-1][1]


def amplification_loop(
    concept_slug: str,
    base_audience_M: float,
    vectors: dict[str, AmplificationVector] | None = None,
    already_applied: list[str] | None = None,
    max_iterations: int = 8,
    target_M: float = 100.0,
    min_delta: float = 1.05,
) -> AmplificationResult:
    """Run the recursive compound amplification loop.

    Args:
        concept_slug: Identifier for the concept being amplified.
        base_audience_M: Starting addressable audience in millions.
        vectors: Pre-loaded vector registry; loads from JSON if None.
        already_applied: Vector IDs already baked into the concept.
        max_iterations: Hard cap on loop iterations.
        target_M: Loop terminates early when audience reaches this.
        min_delta: Stop iterating when best move is below this multiplier.

    Returns:
        AmplificationResult with full decision trail.
    """
    if vectors is None:
        vectors = load_vectors()

    applied: set[str] = set(already_applied or [])
    current = base_audience_M
    decisions: list[IterationDecision] = []

    for i in range(1, max_iterations + 1):
        if current >= target_M:
            break

        vid, mult, synergy = _best_move(applied, vectors)
        if vid is None or mult < min_delta:
            break

        before = current
        current = round(current * mult, 1)
        applied.add(vid)

        v = vectors[vid]
        reasoning = v.evidence[:120]
        if synergy:
            reasoning = f"⚡SYNERGY {synergy}: " + reasoning

        decisions.append(
            IterationDecision(
                iteration=i,
                vector_id=vid,
                vector_name=v.name,
                synergy_activated=synergy,
                audience_before_M=before,
                audience_after_M=current,
                multiplier_used=round(mult, 2),
                reasoning=reasoning,
            )
        )

    remaining = [vid for vid in vectors if vid not in applied]
    total_mult = round(current / base_audience_M, 2) if base_audience_M > 0 else 1.0

    return AmplificationResult(
        concept_slug=concept_slug,
        base_audience_M=base_audience_M,
        final_audience_M=current,
        total_multiplier=total_mult,
        iterations=decisions,
        vectors_applied=sorted(applied),
        vectors_remaining=remaining,
        revenue_implication=_revenue_band(current),
    )


def render_trail(result: AmplificationResult) -> str:
    """Render the amplification decision trail as markdown."""
    lines = [
        f"# Audience Amplification Trail — {result.concept_slug}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Base audience | **{result.base_audience_M}M** |",
        f"| Final audience | **{result.final_audience_M}M** |",
        f"| Total compound multiplier | **{result.total_multiplier}x** |",
        f"| Revenue implication | {result.revenue_implication} |",
        "",
        "---",
        "",
        "## Decision Trail",
        "",
        "```",
        f"{result.concept_slug}",
        f"│  Base: {result.base_audience_M}M addressable",
    ]

    for d in result.iterations:
        lines.append("│")
        row = (
            f"├─ Iter {d.iteration}: "
            f"{d.audience_before_M}M -> {d.audience_after_M}M  "
            f"(x{d.multiplier_used})"
        )
        lines.append(row)
        lines.append(f"│   Vector: [{d.vector_id}] {d.vector_name}")
        if d.synergy_activated:
            lines.append(f"│   ⚡ SYNERGY ACTIVATED: {d.synergy_activated}")
        lines.append(f"│   Evidence: {d.reasoning[:100]}")

    lines += [
        "│",
        (
            f"└─ FINAL: {result.final_audience_M}M  "
            f"(x{result.total_multiplier} compound from {result.base_audience_M}M base)"
        ),
        "```",
        "",
        "---",
        "",
        f"## Vectors Applied ({len(result.vectors_applied)})",
        "",
    ]
    for vid in result.vectors_applied:
        lines.append(f"- `{vid}`")

    lines += [
        "",
        f"## Vectors Remaining — Untapped Upside ({len(result.vectors_remaining)})",
        "",
    ]
    for vid in result.vectors_remaining:
        lines.append(f"- `{vid}`")

    return "\n".join(lines)


def write_trail(result: AmplificationResult, output_dir: Path) -> Path:
    """Write the trail as [slug]-AMPLIFIED.md in output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{result.concept_slug}-AMPLIFIED.md"
    out_path.write_text(render_trail(result), encoding="utf-8")
    return out_path


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Run audience amplification loop on a concept.")
    parser.add_argument("--concept", required=True, help="Concept slug (e.g. the-sleeper)")
    parser.add_argument(
        "--base", type=float, required=True, help="Base addressable audience in millions"
    )
    parser.add_argument(
        "--target", type=float, default=100.0, help="Target audience in millions (default 100)"
    )
    parser.add_argument(
        "--applied", nargs="*", default=[], help="Vector IDs already applied to this concept"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="Write trail to this directory"
    )
    parser.add_argument(
        "--vectors", type=Path, default=_DEFAULT_VECTORS, help="Path to amplification_vectors.json"
    )
    args = parser.parse_args()

    vecs = load_vectors(args.vectors)
    result = amplification_loop(
        concept_slug=args.concept,
        base_audience_M=args.base,
        vectors=vecs,
        already_applied=args.applied,
        target_M=args.target,
    )

    trail = render_trail(result)
    print(trail)

    if args.output_dir:
        out = write_trail(result, args.output_dir)
        print(f"\nTrail written to: {out}")


if __name__ == "__main__":
    _cli()
