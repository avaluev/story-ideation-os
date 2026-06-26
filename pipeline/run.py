"""Anomaly Engine v3.0 — Pipeline CLI orchestrator.

Entry point for all 6 pipeline phases. Wires schema, openrouter_client,
scoring, state, and GoT operators into a single Typer command.

Usage:
    python -m pipeline.run --phase miner --theme "Urban decay" --n 10 --seed 42

Phase file mapping (PIPE-08):
    miner     → data/01_assets.jsonl
    mapper    → data/02_jtbd.jsonl       (reads 01_assets.jsonl)
    validator → data/03_audience.jsonl   (reads 02_jtbd.jsonl, requires --paid-ok)
    forger    → data/04_concepts.jsonl   (reads 03_audience.jsonl)
    critic    → data/05_critiques.jsonl  (reads 04_concepts.jsonl)
    formatter → out/concepts/{id}.md     (reads 05_critiques.jsonl, filters 85-floor)

ADR references:
    ADR-0001: all output written via pipeline.state (safe_write / append_jsonl)
    ADR-0002: total_score set only by pipeline.scoring — never by LLM
    ADR-0003: key rotation handled by OpenRouterClient
    ADR-0006: Forge defaults to Sonnet K=3; Opus promoted on two-gate pass

MUST NOT import: anthropic (enforced by ANOMALY-001 / scripts/lint_imports.py).
MUST NOT import from frameworks/ (ANOMALY-002).
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import typer
from rich.console import Console

from pipeline.metrics import compute_run_metrics, emit_metrics
from pipeline.openrouter_client import (
    DEFAULT_PHASE4_MODEL,
    BudgetExceeded,
    OpenRouterClient,
)
from pipeline.operators.base import Operator
from pipeline.operators.generate import Generate
from pipeline.operators.improve import Improve
from pipeline.operators.keep_best import KeepBest
from pipeline.operators.score import Score
from pipeline.operators.validate import Validate
from pipeline.schema import (
    Phase1Assets,
    Phase2JTBD,
    Phase3Audience,
    Phase4Concept,
    Phase5Critique,
)
from pipeline.scoring import ajtbd_score, overall_score, sdt_score
from pipeline.state import RUN_LOG, RUNTIME_STATE_DIR, append_jsonl, safe_write

# ---------------------------------------------------------------------------
# Module-level constants and logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_SDT_DEPRIVATION_THRESHOLD: float = 0.7
_FORMAT_FLOOR_DEFAULT: float = 85.0
_SCHOOL_CHECK_PASS_RATIO: float = 0.7  # cap@70 trigger: <70% of self-checks pass


class _ModelCfg:
    """Mutable model selection — attribute mutation avoids PLW0603 global."""

    active: str = DEFAULT_PHASE4_MODEL


_model_cfg = _ModelCfg()

_DATA_DIR = Path("data")
_OUT_DIR = Path("out") / "concepts"

# Stabilization queue (STAB-03)
_STAB_QUEUE = _DATA_DIR / "stabilization_queue.jsonl"

# Phase file map (PIPE-08)
_PHASE_FILES: dict[str, Path] = {
    "miner": _DATA_DIR / "01_assets.jsonl",
    "mapper": _DATA_DIR / "02_jtbd.jsonl",
    "validator": _DATA_DIR / "03_audience.jsonl",
    "forger": _DATA_DIR / "04_concepts.jsonl",
    "critic": _DATA_DIR / "05_critiques.jsonl",
}

_PHASE_PREV: dict[str, Path] = {
    "mapper": _DATA_DIR / "01_assets.jsonl",
    "validator": _DATA_DIR / "02_jtbd.jsonl",
    "forger": _DATA_DIR / "03_audience.jsonl",
    "critic": _DATA_DIR / "04_concepts.jsonl",
    "formatter": _DATA_DIR / "05_critiques.jsonl",
}

# GoT operator pipelines — wired for pyright protocol conformance check.
# Phase 7 fills __call__ bodies (GOT-01..05). Smoke test (--phase miner)
# never invokes these operators.
_got_forge_pipeline: list[Operator] = [
    Generate(k=3),
    KeepBest(),
    Improve(),
    Validate(),
    KeepBest(),
]
_got_critic_pipeline: list[Operator] = [
    Validate(),
    Score(),
    KeepBest(),
]

# ---------------------------------------------------------------------------
# Framework loader (PIPE-14)
# ---------------------------------------------------------------------------

_FRAMEWORK_CACHE: dict[str, str] = {}


def load_framework(names: list[str]) -> str:
    """Load one or more framework/prompt files and wrap each in an XML tag.

    Searches frameworks/{name}.md first, then prompts/{name}.md.
    Results are cached in _FRAMEWORK_CACHE (module-level dict; lists are not
    hashable so lru_cache is not usable here).

    Args:
        names: List of framework name strings (without .md extension).

    Returns:
        Concatenated XML string:
            <framework name="{name}">...content...</framework>

    Raises:
        FileNotFoundError: If a name cannot be resolved in either directory.
    """
    parts: list[str] = []
    for name in names:
        if name not in _FRAMEWORK_CACHE:
            for candidate in [
                Path("frameworks") / f"{name}.md",
                Path("prompts") / f"{name}.md",
            ]:
                if candidate.exists():
                    _FRAMEWORK_CACHE[name] = candidate.read_text()
                    break
            else:
                raise FileNotFoundError(f"Framework not found: {name!r}")
        parts.append(f'<framework name="{name}">{_FRAMEWORK_CACHE[name]}</framework>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# STAB-03: Stabilization queue helper
# ---------------------------------------------------------------------------


def _maybe_queue_stab_pattern(
    scored_critique: Phase5Critique,
    session_id: str,
    stab_queue_path: Path = _STAB_QUEUE,
) -> None:
    """Append stabilization pattern to queue if critic flagged one (STAB-03).

    Called immediately after _run_critic() writes the scored critique row.
    Uses append_jsonl (ADR-0001 compliant) to persist the entry atomically.

    Args:
        scored_critique: The fully-scored Phase5Critique object.
        session_id: Current pipeline session ID for log correlation.
        stab_queue_path: Override path for testing (defaults to _STAB_QUEUE).
    """
    pattern = scored_critique.stabilization_pattern_to_add_to_anti_slop
    if not pattern:
        return
    queue_entry: dict[str, object] = {
        "concept_id": scored_critique.concept_id,
        "pattern": pattern,
        "queued_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    append_jsonl(stab_queue_path, queue_entry)
    _log_event(
        "STABILIZATION_QUEUED",
        "critic",
        concept_id=scored_critique.concept_id,
        pattern_words=len(pattern.split()),
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Phase 6 quality-pass filter helper (PIPE-11)
# ---------------------------------------------------------------------------


def _should_format_concept(score_dict: dict[str, Any], floor: float = 85.0) -> bool:
    """Return True when a concept's overall_score meets the floor.

    Args:
        score_dict: Dict returned by pipeline.scoring.overall_score(), or any
                    dict with a ``passes_85_floor`` bool key.
        floor: Minimum score to pass (default 85). Override via --format-floor.

    Returns:
        True if the concept's final score meets the floor.
    """
    if floor <= _FORMAT_FLOOR_DEFAULT and score_dict.get("passes_85_floor"):  # fast path
        return True
    final = score_dict.get("final", 0)
    return float(str(final or "0")) >= floor


# ---------------------------------------------------------------------------
# Log-event helper
# ---------------------------------------------------------------------------


def _log_event(event: str, phase: str, **extra: object) -> None:
    """Append a structured event to RUN_LOG via pipeline.state.append_jsonl."""
    row: dict[str, object] = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "event": event,
        "phase": phase,
        **extra,
    }
    append_jsonl(RUN_LOG, row)


def _write_stop_checkpoint(session_id: str, reason: str = "CTRL_C") -> None:
    """Write a stop checkpoint JSON to data/state/stop_{reason}_{session_id}.json.

    Uses safe_write for atomic durability (ADR-0001).

    Args:
        session_id: Current pipeline session UUID.
        reason: "CTRL_C" or "BUDGET" — identifies the stop trigger.
    """
    dest = RUNTIME_STATE_DIR / f"stop_{reason}_{session_id}.json"
    payload = json.dumps(
        {
            "session_id": session_id,
            "stopped_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "reason": reason,
        }
    )
    safe_write(dest, payload)
    logger.info("Stop checkpoint written: %s", dest)


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def _run_miner(
    client: OpenRouterClient,
    theme: str,
    n: int,
    seed: int,
    session_id: str,
) -> None:
    """Phase 1 — Asset Miner. Writes data/01_assets.jsonl."""
    rng = np.random.default_rng(seed)
    out_path = _PHASE_FILES["miner"]

    console.print(f"[cyan]Phase 1 miner[/cyan] theme={theme!r} n={n} seed={seed}")
    _log_event("START", "miner", theme=theme, n=n, seed=seed, session_id=session_id)

    prompt_body = load_framework(["01-asset-miner"])
    messages: list[dict[str, str]] = [
        {"role": "system", "content": prompt_body},
        {
            "role": "user",
            "content": (
                f"Theme: {theme}\n"
                f"Generate {n} untapped cultural/historical assets as JSON array. "
                f"Each item must match Phase1Assets schema. "
                f"Random seed context: {int(rng.integers(0, 2**32))}."
            ),
        },
    ]

    try:
        raw: dict[str, object] = client.chat(
            model=_model_cfg.active,
            messages=messages,
            paid_required=False,
        )
    except BudgetExceeded:
        _log_event("BUDGET_EXCEEDED", "miner", session_id=session_id)
        console.print("[red]BudgetExceeded in miner phase — flushing checkpoint.[/red]")
        raise

    # Parse response — wrap single-asset dict in a list; or use "assets" key
    if "assets" in raw:
        assets_raw: list[dict[str, object]] = raw["assets"]  # type: ignore[assignment]
    else:
        assets_raw = [raw]

    written = 0
    for item in assets_raw:
        # Normalize LLM field names → schema field names (prompt and schema diverged)
        if "asset_title" in item and "asset_name" not in item:
            item["asset_name"] = item.pop("asset_title")
        if "primary_source_url" in item and "source_url" not in item:
            item["source_url"] = item.pop("primary_source_url") or ""
        item.setdefault("source_url", "")
        if "source_quote" not in item:
            # Derive ≤14-word quote from emotional_charge or asset_description
            raw_quote: str = str(
                item.get("emotional_charge") or item.get("asset_description") or ""
            )
            item["source_quote"] = " ".join(raw_quote.split()[:14])
        if "untapped_check_passed" not in item:
            uc = item.get("untapped_check")
            raw_verdict = uc.get("verdict", "UNKNOWN") if isinstance(uc, dict) else "UNKNOWN"  # type: ignore[union-attr]
            verdict: str = str(raw_verdict)  # type: ignore[reportUnknownArgumentType]
            item["untapped_check_passed"] = verdict in ("UNTAPPED", "UNKNOWN")
        # Inject required metadata if absent
        item.setdefault("produced_at", datetime.datetime.now(datetime.UTC).isoformat())
        item.setdefault("session_id", session_id)
        try:
            asset = Phase1Assets(**item)  # type: ignore[arg-type]
        except Exception as exc:  # permanent schema failure
            _log_event(
                "FAIL",
                "miner",
                concept_id=str(item.get("asset_id", "unknown")),
                seed=seed,
                error_type="schema_hard_fail",
                error=str(exc),
                session_id=session_id,
            )
            continue
        append_jsonl(out_path, asset.model_dump())
        written += 1

    _log_event("DONE", "miner", written=written, session_id=session_id)
    console.print(f"[green]miner done[/green] wrote {written} assets → {out_path}")


def _run_mapper(
    client: OpenRouterClient,
    n: int,
    session_id: str,
) -> None:
    """Phase 2 — JTBD Mapper. Reads 01_assets.jsonl, writes 02_jtbd.jsonl."""
    in_path = _PHASE_PREV["mapper"]
    out_path = _PHASE_FILES["mapper"]

    console.print(f"[cyan]Phase 2 mapper[/cyan] input={in_path}")
    _log_event("START", "mapper", session_id=session_id)

    if not in_path.exists():
        console.print(f"[red]mapper: input {in_path} not found — run miner first.[/red]")
        sys.exit(1)

    prompt_body = load_framework(["02-jtbd-mapper"])
    written = 0
    for line in in_path.read_text().splitlines():
        if not line.strip():
            continue
        asset_row = json.loads(line)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt_body},
            {"role": "user", "content": f"Asset: {json.dumps(asset_row)}"},
        ]
        try:
            raw = client.chat(model=_model_cfg.active, messages=messages)
        except BudgetExceeded:
            _log_event("BUDGET_EXCEEDED", "mapper", session_id=session_id)
            raise

        raw.setdefault("asset_id", asset_row.get("asset_id", "unknown"))
        # Normalize prompt field names → Phase2JTBD schema
        if "sdt_primary_need" in raw and "primary_need" not in raw:
            raw["primary_need"] = raw.pop("sdt_primary_need")
        if "sdt_primary_strength" in raw and "primary_strength" not in raw:
            raw["primary_strength"] = float(str(raw.pop("sdt_primary_strength") or "0"))
        if "sdt_secondary_need" in raw and "secondary_need" not in raw:
            raw["secondary_need"] = raw.pop("sdt_secondary_need")
        if "sdt_secondary_strength" in raw and "secondary_strength" not in raw:
            raw["secondary_strength"] = float(str(raw.pop("sdt_secondary_strength") or "0"))
        if "job_statement" not in raw:
            raw["job_statement"] = str(
                raw.get("sdt_deprivation_description") or raw.get("asset_description") or ""
            )
        if "deprivation_amplifier_active" not in raw:
            strength = float(str(raw.get("primary_strength") or "0"))
            raw["deprivation_amplifier_active"] = strength >= _SDT_DEPRIVATION_THRESHOLD
        try:
            jtbd = Phase2JTBD(**raw)  # type: ignore[arg-type]
        except Exception as exc:
            _log_event(
                "FAIL",
                "mapper",
                concept_id=str(raw.get("asset_id", "unknown")),
                seed=0,
                error_type="schema_hard_fail",
                error=str(exc),
                session_id=session_id,
            )
            continue
        append_jsonl(out_path, jtbd.model_dump())
        written += 1

    _log_event("DONE", "mapper", written=written, session_id=session_id)
    console.print(f"[green]mapper done[/green] wrote {written} rows → {out_path}")


def _normalize_audience(raw: dict[str, object], jtbd_row: dict[str, object]) -> None:
    """Translate Phase 3 prompt field names to Phase3Audience schema field names."""
    if "audience_size_estimate" in raw and "cited_audience" not in raw:
        raw["cited_audience"] = int(str(raw.pop("audience_size_estimate") or "0"))
    if "target_countries" not in raw:
        breakdown = raw.get("country_breakdown")
        codes: list[str] = []
        if isinstance(breakdown, list):
            for entry in breakdown:  # type: ignore[reportUnknownVariableType]
                if isinstance(entry, dict):
                    codes.append(str(entry.get("country_iso2") or ""))  # type: ignore[union-attr]
        raw["target_countries"] = codes or ["US"]
    if "sources_per_claim" not in raw:
        raw["sources_per_claim"] = 1
    if "primary_jtbd_strength" not in raw:
        raw["primary_jtbd_strength"] = float(
            str(jtbd_row.get("primary_strength") or _SDT_DEPRIVATION_THRESHOLD)
        )
    if "source_quote" not in raw:
        raw_quote = str(raw.get("deprivation_evidence_summary") or raw.get("source_quote_1") or "")
        raw["source_quote"] = " ".join(raw_quote.split()[:14])


def _run_validator(
    client: OpenRouterClient,
    paid_ok: bool,
    session_id: str,
) -> None:
    """Phase 3 — Audience Validator. Reads 02_jtbd.jsonl, writes 03_audience.jsonl."""
    # paid_ok=True → use sonar for web-sourced audience data; False → free model (degraded)
    validator_model = "perplexity/sonar" if paid_ok else _model_cfg.active

    in_path = _PHASE_PREV["validator"]
    out_path = _PHASE_FILES["validator"]

    console.print(f"[cyan]Phase 3 validator[/cyan] input={in_path} model={validator_model}")
    _log_event("START", "validator", session_id=session_id)

    if not in_path.exists():
        console.print(f"[red]validator: input {in_path} not found.[/red]")
        sys.exit(1)

    prompt_body = load_framework(["03-audience-validator"])
    written = 0
    for line in in_path.read_text().splitlines():
        if not line.strip():
            continue
        jtbd_row = json.loads(line)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt_body},
            {"role": "user", "content": f"JTBD mapping: {json.dumps(jtbd_row)}"},
        ]
        try:
            raw = client.chat(
                model=validator_model,
                messages=messages,
                paid_required=paid_ok,
            )
        except BudgetExceeded:
            _log_event("BUDGET_EXCEEDED", "validator", session_id=session_id)
            raise

        raw.setdefault("asset_id", jtbd_row.get("asset_id", "unknown"))
        raw.setdefault("produced_at", datetime.datetime.now(datetime.UTC).isoformat())
        raw.setdefault("session_id", session_id)
        _normalize_audience(raw, jtbd_row)
        try:
            audience = Phase3Audience(**raw)  # type: ignore[arg-type]
        except Exception as exc:
            _log_event(
                "FAIL",
                "validator",
                concept_id=str(raw.get("asset_id", "unknown")),
                seed=0,
                error_type="schema_hard_fail",
                error=str(exc),
                session_id=session_id,
            )
            continue
        append_jsonl(out_path, audience.model_dump())
        written += 1

    _log_event("DONE", "validator", written=written, session_id=session_id)
    console.print(f"[green]validator done[/green] wrote {written} rows → {out_path}")


def _run_forger(
    client: OpenRouterClient,
    seed: int,
    quality_pass_floor: float,
    quality_pass_budget: float,
    session_id: str,
) -> None:
    """Phase 4 — Concept Forger. Reads 03_audience.jsonl, writes 04_concepts.jsonl."""
    in_path = _PHASE_PREV["forger"]
    out_path = _PHASE_FILES["forger"]

    console.print(f"[cyan]Phase 4 forger[/cyan] seed={seed} model={_model_cfg.active}")
    _log_event(
        "START",
        "forger",
        seed=seed,
        model=_model_cfg.active,
        quality_pass_floor=quality_pass_floor,
        quality_pass_budget=quality_pass_budget,
        session_id=session_id,
    )

    if not in_path.exists():
        console.print(f"[red]forger: input {in_path} not found — run validator first.[/red]")
        sys.exit(1)

    rng = np.random.default_rng(seed)
    oblique_framework = load_framework(["04-concept-forger", "anti_slop"])
    written = 0

    for line in in_path.read_text().splitlines():
        if not line.strip():
            continue
        audience_row = json.loads(line)
        # Oblique strategy selection uses numpy RNG (seed=seed per PIPE-09)
        oblique_idx = int(rng.integers(0, 100))

        messages: list[dict[str, str]] = [
            {"role": "system", "content": oblique_framework},
            {
                "role": "user",
                "content": (
                    f"Audience profile: {json.dumps(audience_row)}\n"
                    f"Oblique strategy index: {oblique_idx}\n"
                    f"Generate a high-concept film idea as Phase4Concept JSON."
                ),
            },
        ]
        try:
            raw = client.chat(model=_model_cfg.active, messages=messages)
        except BudgetExceeded:
            _log_event("BUDGET_EXCEEDED", "forger", session_id=session_id)
            raise

        raw.setdefault("seed_used", seed)
        raw.setdefault("session_id", session_id)
        raw.setdefault("produced_at", datetime.datetime.now(datetime.UTC).isoformat())
        # forge_meta must carry seed_used (PIPE-09)
        # Build a fresh typed dict; copy existing keys if the field was present
        _fm_raw = raw.get("forge_meta")
        forge_meta: dict[str, object] = (
            {str(k): v for k, v in _fm_raw.items()}  # type: ignore[union-attr]
            if isinstance(_fm_raw, dict)
            else {}
        )
        forge_meta.setdefault("seed_used", seed)
        forge_meta.setdefault("model", _model_cfg.active)
        forge_meta.setdefault("k", 3)
        forge_meta.setdefault("asset_id", audience_row.get("asset_id", ""))
        raw["forge_meta"] = forge_meta
        # Normalize prompt field names → Phase4Concept schema
        if "polti_situation_id" in raw and "polti_id" not in raw:
            raw["polti_id"] = int(str(raw.pop("polti_situation_id") or "1"))
        if "tobias_plot_id" in raw and "tobias_id" not in raw:
            raw["tobias_id"] = int(str(raw.pop("tobias_plot_id") or "1"))
        raw.setdefault("polti_id", 1)
        raw.setdefault("tobias_id", 1)
        raw.setdefault("seed_used", seed)

        try:
            concept = Phase4Concept(**raw)  # type: ignore[arg-type]
        except Exception as exc:
            _log_event(
                "FAIL",
                "forger",
                concept_id=str(raw.get("concept_id", "unknown")),
                seed=seed,
                error_type="schema_hard_fail",
                error=str(exc),
                session_id=session_id,
            )
            continue
        append_jsonl(out_path, concept.model_dump())
        written += 1

    _log_event("DONE", "forger", written=written, session_id=session_id)
    console.print(f"[green]forger done[/green] wrote {written} concepts → {out_path}")


def _derive_cap_at_70(ten_school_self_check: object) -> bool:
    """Trigger the critic's 70-point cap when self-check pass rate is below threshold.

    Per prompts/05-adversarial-critic.md the rule is "7 or more true values out of 10"
    (70%), but the critic actually emits 5 cross_checks rather than 10. Apply the
    70% ratio to whatever list length the critic returned so the cap fires
    appropriately regardless of how many checks the model emits.
    """
    if not isinstance(ten_school_self_check, list) or not ten_school_self_check:
        return True
    n = len(ten_school_self_check)  # type: ignore[reportUnknownArgumentType]
    true_count = sum(1 for x in ten_school_self_check if bool(x))  # type: ignore[reportUnknownArgumentType]
    return (true_count / n) < _SCHOOL_CHECK_PASS_RATIO


def _run_critic(
    client: OpenRouterClient,
    session_id: str,
) -> None:
    """Phase 5 — Adversarial Critic. Reads 04_concepts.jsonl, writes 05_critiques.jsonl."""
    in_path = _PHASE_PREV["critic"]
    out_path = _PHASE_FILES["critic"]

    console.print(f"[cyan]Phase 5 critic[/cyan] input={in_path}")
    _log_event("START", "critic", session_id=session_id)

    if not in_path.exists():
        console.print(f"[red]critic: input {in_path} not found — run forger first.[/red]")
        sys.exit(1)

    prompt_body = load_framework(["05-adversarial-critic", "anti_slop"])
    written = 0

    # Lookup tables — JTBD by asset_id (Phase 2) and audience by asset_id (Phase 3).
    # The forger's concept row doesn't carry these; we join via forge_meta.asset_id.
    jtbd_by_asset = _load_jsonl_by_key(_PHASE_FILES["mapper"], "asset_id")
    audience_by_asset = _load_jsonl_by_key(_PHASE_FILES["validator"], "asset_id")

    for line in in_path.read_text().splitlines():
        if not line.strip():
            continue
        concept_row = json.loads(line)
        # Resolve asset_id from forge_meta (set by _run_forger) and join upstream rows
        forge_meta_lookup: Any = concept_row.get("forge_meta") or {}
        asset_id = ""
        if isinstance(forge_meta_lookup, dict):
            asset_id = str(forge_meta_lookup.get("asset_id") or "")  # type: ignore[reportUnknownArgumentType]
        jtbd_row: dict[str, Any] = jtbd_by_asset.get(asset_id, {})
        audience_row: dict[str, Any] = audience_by_asset.get(asset_id, {})

        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt_body},
            {
                "role": "user",
                "content": f"Concept to critique: {json.dumps(concept_row)}",
            },
        ]
        try:
            raw = client.chat(model=_model_cfg.active, messages=messages)
        except BudgetExceeded:
            _log_event("BUDGET_EXCEEDED", "critic", session_id=session_id)
            raise

        raw.setdefault("concept_id", concept_row.get("concept_id", "unknown"))
        # Normalize nested verdict objects → flat score fields
        for verdict_key, score_key in (
            ("novelty_verdict", "novelty_score"),
            ("jtbd_verdict", "jtbd_score"),
            ("contradiction_verdict", "contradiction_score"),
            ("specificity_verdict", "specificity_score"),
        ):
            if verdict_key in raw and score_key not in raw:
                v = raw.pop(verdict_key)
                raw[score_key] = int(str(v.get("score", 0))) if isinstance(v, dict) else 0  # type: ignore[union-attr]
        if "ten_school_self_check" not in raw:
            checks = raw.get("cross_checks")
            raw["ten_school_self_check"] = (
                [bool(x) for x in checks.values()]  # type: ignore[union-attr]
                if isinstance(checks, dict)
                else [False] * 10
            )
        if "cap_at_70_triggered" not in raw:
            raw["cap_at_70_triggered"] = _derive_cap_at_70(raw.get("ten_school_self_check"))

        try:
            critique = Phase5Critique(**raw)  # type: ignore[arg-type]
        except Exception as exc:
            _log_event(
                "FAIL",
                "critic",
                concept_id=str(raw.get("concept_id", "unknown")),
                seed=0,
                error_type="schema_hard_fail",
                error=str(exc),
                session_id=session_id,
            )
            continue

        # Score via pipeline.scoring — ADR-0002: scoring.py is sole scorer.
        # Source data joined above: jtbd_row (Phase 2), audience_row (Phase 3).
        score_result = overall_score(
            upstream_sdt=sdt_score(
                primary_need=jtbd_row.get("primary_need", "autonomy"),  # type: ignore[arg-type]
                primary_strength=float(jtbd_row.get("primary_strength", 0.8)),
                secondary_need=jtbd_row.get("secondary_need"),  # type: ignore[arg-type]
                secondary_strength=float(jtbd_row.get("secondary_strength", 0.0)),
                deprivation_amplifier_active=bool(
                    jtbd_row.get("deprivation_amplifier_active", False)
                ),
            ),
            upstream_ajtbd=ajtbd_score(
                cited_audience=int(audience_row.get("cited_audience", 0)),
                country_count=len(audience_row.get("target_countries") or []),
                sources_per_claim=int(audience_row.get("sources_per_claim", 0)),
                trend_direction=audience_row.get("trend_direction", "stable"),  # type: ignore[arg-type]
                primary_jtbd_strength=float(audience_row.get("primary_jtbd_strength", 0.0)),
            ),
            critic_novelty=critique.novelty_score,
            critic_jtbd=critique.jtbd_score,
            critic_contradiction=critique.contradiction_score,
            critic_specificity=critique.specificity_score,
            cap_at_70_triggered=critique.cap_at_70_triggered,
        )
        scored_critique = critique.model_copy(update={"total_score": score_result["final"]})
        row_out = scored_critique.model_dump()
        row_out["overall_score"] = score_result
        append_jsonl(out_path, row_out)
        _maybe_queue_stab_pattern(scored_critique, session_id)  # STAB-03
        written += 1

    _log_event("DONE", "critic", written=written, session_id=session_id)
    console.print(f"[green]critic done[/green] wrote {written} critiques → {out_path}")


def _load_jsonl_by_key(path: Path, key: str) -> dict[str, dict[str, Any]]:
    """Load a JSONL file into a dict keyed by `key` (last write wins)."""
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        k = str(row.get(key) or "")
        if k:
            out[k] = row
    return out


def _render_a4(
    concept_id: str,
    critique_row: dict[str, Any],
    score_dict: dict[str, Any],
    concept_row: dict[str, Any],
    audience_row: dict[str, Any],
) -> str:
    """Render an A4-style concept markdown with frontmatter fields for index.html."""
    title = str(concept_row.get("title") or concept_id)
    logline = str(concept_row.get("logline") or "—")
    final = score_dict.get("final", "N/A")
    upstream = score_dict.get("upstream", "N/A")
    critic_total = score_dict.get("critic", "N/A")
    bonus = score_dict.get("agreement_bonus", 0)
    audience_size = audience_row.get("cited_audience", "—")
    countries_raw: Any = audience_row.get("target_countries") or []
    countries: list[str] = (
        [str(c) for c in countries_raw]  # type: ignore[reportUnknownArgumentType,reportUnknownVariableType]
        if isinstance(countries_raw, list)
        else []
    )
    trend = audience_row.get("trend_direction") or "—"
    quote = audience_row.get("source_quote") or ""
    novelty = critique_row.get("novelty_score", "—")
    jtbd = critique_row.get("jtbd_score", "—")
    contradiction = critique_row.get("contradiction_score", "—")
    specificity = critique_row.get("specificity_score", "—")
    self_check_raw: Any = critique_row.get("ten_school_self_check") or []
    self_check: list[bool] = (
        [bool(x) for x in self_check_raw]  # type: ignore[reportUnknownArgumentType,reportUnknownVariableType]
        if isinstance(self_check_raw, list)
        else []
    )
    self_check_summary = f"{sum(1 for x in self_check if x)}/{len(self_check)}"
    stab_pattern = critique_row.get("stabilization_pattern_to_add_to_anti_slop")

    reach = f"{audience_size:,}" if isinstance(audience_size, int) else str(audience_size)
    geo = ", ".join(countries) if countries else "—"
    stab_section = (
        f"## Stabilization Pattern (queued for anti-slop review)\n\n> {stab_pattern}\n\n"
        if stab_pattern
        else ""
    )
    cap = critique_row.get("cap_at_70_triggered", False)
    return (
        f"# {title}\n\n"
        f"id: {concept_id}\n"
        f"title: {title}\n"
        f"final_score: {final}\n"
        f"sdt_score: {upstream}\n"
        f"ajtbd_score: {critic_total}\n"
        f"audience_size: {audience_size}\n\n"
        f"## Logline\n\n{logline}\n\n"
        f"## Audience\n\n"
        f"- **Reach:** {reach} viewers (estimated)\n"
        f"- **Geography:** {geo}\n"
        f"- **Trend:** {trend}\n"
        f"- **Source quote:** “{quote}”\n\n"
        f"## Score Breakdown\n\n"
        f"| Component | Score |\n|---|---|\n"
        f"| Novelty | {novelty} |\n"
        f"| JTBD fit | {jtbd} |\n"
        f"| Contradiction | {contradiction} |\n"
        f"| Specificity | {specificity} |\n"
        f"| Critic raw | {critic_total} |\n"
        f"| Upstream (SDT+AJTBD) | {upstream} |\n"
        f"| Agreement bonus | +{bonus} |\n"
        f"| **Final** | **{final}** |\n"
        f"| Cinema schools self-check | {self_check_summary} |\n"
        f"| Cap @70 triggered | {cap} |\n\n"
        f"{stab_section}"
        f"---\n*Generated by Anomaly Engine v3.0 — concept_id: {concept_id}*\n"
    )


def _run_formatter(session_id: str, format_floor: float = _FORMAT_FLOOR_DEFAULT) -> None:
    """Phase 6 — Formatter. Reads 05_critiques.jsonl, writes out/concepts/{id}.md."""
    in_path = _PHASE_PREV["formatter"]
    out_dir = _OUT_DIR

    console.print(f"[cyan]Phase 6 formatter[/cyan] input={in_path}")
    _log_event("START", "formatter", session_id=session_id)

    if not in_path.exists():
        console.print(f"[red]formatter: input {in_path} not found — run critic first.[/red]")
        sys.exit(1)

    # Lookup tables for cross-phase data
    concepts_by_id = _load_jsonl_by_key(_PHASE_FILES["forger"], "concept_id")
    audiences_by_asset = _load_jsonl_by_key(_PHASE_FILES["validator"], "asset_id")

    written = 0
    skipped = 0

    for line in in_path.read_text().splitlines():
        if not line.strip():
            continue
        critique_row = json.loads(line)
        score_dict: dict[str, Any] = critique_row.get("overall_score", {})

        if not _should_format_concept(score_dict, floor=format_floor):
            skipped += 1
            _log_event(
                "SKIP",
                "formatter",
                concept_id=critique_row.get("concept_id", "unknown"),
                reason="below_floor",
                score=score_dict.get("final"),
                session_id=session_id,
            )
            continue

        concept_id: str = str(critique_row.get("concept_id", "unknown"))
        concept_row = concepts_by_id.get(concept_id, {})
        # Asset_id is stashed in forge_meta by _run_forger
        forge_meta_lookup: Any = concept_row.get("forge_meta") or {}
        asset_id = ""
        if isinstance(forge_meta_lookup, dict):
            asset_id = str(forge_meta_lookup.get("asset_id") or "")  # type: ignore[reportUnknownArgumentType]
        if not asset_id:
            asset_id = str(critique_row.get("asset_id") or "")
        audience_row = audiences_by_asset.get(asset_id, {})

        md_content = _render_a4(concept_id, critique_row, score_dict, concept_row, audience_row)
        out_path = out_dir / f"{concept_id}.md"
        safe_write(out_path, md_content)
        written += 1

    _log_event("DONE", "formatter", written=written, skipped=skipped, session_id=session_id)
    console.print(
        f"[green]formatter done[/green] wrote {written} files "
        f"(skipped {skipped} below floor) → {out_dir}/"
    )


# ---------------------------------------------------------------------------
# Typer CLI
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="pipeline",
    help="Anomaly Engine v3.0 pipeline orchestrator.",
    add_completion=False,
)

_PHASE_CHOICES = ["miner", "mapper", "validator", "forger", "critic", "formatter", "all"]

# Named constant avoids S107 "hardcoded password" false positive on the string "top-3"
_DEFAULT_QUALITY_MODE = "top-3"


def _dispatch_phase(
    p: str,
    client: OpenRouterClient,
    theme: str,
    n: int,
    seed: int,
    paid_ok: bool,
    quality_pass_floor: float,
    quality_pass_budget: float,
    format_floor: float,
    session_id: str,
) -> None:
    """Dispatch a single phase name to its runner function."""
    if p == "miner":
        if not theme:
            console.print("[red]--theme is required for miner phase.[/red]")
            raise typer.Exit(code=1)
        _run_miner(client, theme, n, seed, session_id)
    elif p == "mapper":
        _run_mapper(client, n, session_id)
    elif p == "validator":
        _run_validator(client, paid_ok, session_id)
    elif p == "forger":
        _run_forger(client, seed, quality_pass_floor, quality_pass_budget, session_id)
    elif p == "critic":
        _run_critic(client, session_id)
    elif p == "formatter":
        _run_formatter(session_id, format_floor=format_floor)


@app.command()
def main(
    phase: Annotated[
        str,
        typer.Option(
            help="Pipeline phase to run. Choices: " + ", ".join(_PHASE_CHOICES),
        ),
    ] = "all",
    theme: Annotated[str, typer.Option(help="Content theme for Phase 1 miner.")] = "",
    n: Annotated[int, typer.Option(help="Number of assets to mine (Phase 1).")] = 10,
    seed: Annotated[int, typer.Option(help="RNG seed for reproducibility.")] = 42,
    paid_ok: Annotated[
        bool,
        typer.Option("--paid-ok/--no-paid-ok", help="Allow paid-key-only calls (Phase 3)."),
    ] = False,
    resume_from_phase: Annotated[
        str, typer.Option(help="Resume from this phase (skips earlier phases).")
    ] = "",
    quality_pass: Annotated[
        str,
        typer.Option(help="Quality pass mode: off|top-3|top-5|all (ADR-0006)."),
    ] = _DEFAULT_QUALITY_MODE,
    quality_pass_floor: Annotated[
        float,
        typer.Option(help="Minimum score floor for Phase 6 formatter (ADR-0006)."),
    ] = 75.0,
    quality_pass_budget: Annotated[
        float,
        typer.Option(help="Daily Opus budget cap in USD (ADR-0006)."),
    ] = 10.0,
    format_floor: Annotated[
        float,
        typer.Option(help="Minimum score for Phase 6 formatter (default 85, lower for testing)."),
    ] = _FORMAT_FLOOR_DEFAULT,
    model: Annotated[
        str,
        typer.Option(help="LLM model override for all phases (default: DEFAULT_PHASE4_MODEL)."),
    ] = "",
) -> None:
    """Run one or all Anomaly Engine pipeline phases."""
    if model:
        _model_cfg.active = model
    if phase not in _PHASE_CHOICES:
        console.print(
            f"[red]Unknown phase {phase!r}. Must be one of: {', '.join(_PHASE_CHOICES)}[/red]"
        )
        raise typer.Exit(code=1)

    session_id = str(uuid.uuid4())

    try:
        client = OpenRouterClient()
    except ValueError as exc:
        console.print(f"[red]Client init error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    # Determine which phases to run
    run_order = ["miner", "mapper", "validator", "forger", "critic", "formatter"]
    if phase != "all":
        run_order = [phase]

    if resume_from_phase and resume_from_phase in run_order:
        start_idx = run_order.index(resume_from_phase)
        run_order = run_order[start_idx:]

    # Sentinel file: lets the Stop hook know --n so it can run make audit if n >= 10.
    _sentinel = RUNTIME_STATE_DIR / "last_run_n.txt"
    safe_write(_sentinel, str(n))

    try:
        for p in run_order:
            _dispatch_phase(
                p,
                client,
                theme,
                n,
                seed,
                paid_ok,
                quality_pass_floor,
                quality_pass_budget,
                format_floor,
                session_id,
            )
        # Emit per-run metrics + append to timeline (Workstream D)
        try:
            snapshot = compute_run_metrics(
                run_id=session_id,
                theme=theme,
                model=_model_cfg.active,
                format_floor=format_floor,
            )
            emit_metrics(snapshot)
            console.print(f"[green]metrics emitted[/green] → data/metrics/{session_id}.json")
        except Exception as exc:  # never let metrics block the run
            console.print(f"[yellow]metrics emit skipped: {exc}[/yellow]")
    except BudgetExceeded as exc:
        _log_event(
            "BUDGET_EXCEEDED",
            phase,
            error=str(exc),
            session_id=session_id,
        )
        n_pass = len(list(_OUT_DIR.glob("*.md")))
        console.print(f"[red]BudgetExceeded: {exc}[/red]")
        console.print(f"[green]{n_pass} PASS concepts written to {_OUT_DIR}/[/green]")
        _write_stop_checkpoint(session_id, reason="BUDGET")
        raise typer.Exit(code=0) from exc
    except KeyboardInterrupt:
        _log_event("CTRL_C_STOP", phase, session_id=session_id)
        n_pass = len(list(_OUT_DIR.glob("*.md")))
        console.print("[yellow]Ctrl-C — writing stop checkpoint and exiting clean.[/yellow]")
        console.print(f"[green]{n_pass} PASS concepts written to {_OUT_DIR}/[/green]")
        _write_stop_checkpoint(session_id, reason="CTRL_C")
        raise typer.Exit(code=0) from None


if __name__ == "__main__":
    app()
