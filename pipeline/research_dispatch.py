"""pipeline/research_dispatch.py — Cycle 1 Option A.

Moves sonar / sonar-deep-research calls OUT of agent Bash invocations and INTO
the Python orchestrator so pipeline.sonar_cache.cached_chat can intercept them.

Two reasons this matters:
1. The agent prompts reference `python -m pipeline.openrouter_client ...` but
   that module has no CLI entry point — the Bash invocations silently fail and
   agents fall back to WebSearch. Quality regresses to web-search level.
2. Even when sonar succeeded, every run paid full latency. With cached_chat,
   re-runs within the same ISO week are free.

This module exposes:
- fetch_research_evidence(...) — Phase 1 concept-researcher Steps A+B+C
- fetch_market_sizing(...)      — Phase 7 concept-narrator Step 0

Both write a JSON sidecar into the run directory. Agents read those sidecars
instead of making their own LLM calls.

ADR-0001: sidecars written via pipeline.state.safe_write.
ADR-0007: sonar calls routed through the research gateway chain.
  MUST NOT import httpx / anthropic directly here.
ADR-0005: MUST NOT import from frameworks/.
ADR-0010: sidecar JSON stays in run_dir; never leaks into the concept's
  user-facing markdown.

Chat fallback chain (default — AIML_PRIMARY=1):
  Primary: AimlClient  (AIML_API_KEY)
  Second:  TaoAIClient (TAO_AI_API_KEY)  — on AimlClient BudgetExceeded
  Third:   OpenRouterClient              — on TaoAIClient BudgetExceeded

When AIML_PRIMARY is unset/falsy the chain collapses to the legacy
  OpenRouter -> 302 two-tier chain.

TAO_AI_PRIMARY still overrides everything: when set, the shared
  llm_client factory is used (302.ai-first) and the AIML tier is skipped.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Final, Protocol

from pipeline import sonar_cache
from pipeline.state import safe_write

_log = logging.getLogger(__name__)

_SONAR_PRO: Final[str] = "perplexity/sonar-pro"
_SONAR_DEEP: Final[str] = "perplexity/sonar-deep-research"

# Sidecar filenames — written into run_dir, read by agents.
RESEARCH_EVIDENCE_FILENAME: Final[str] = "research_raw.json"
MARKET_SIZING_FILENAME: Final[str] = "market_raw.json"

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


class _ChatClient(Protocol):
    """Structural type accepted by both real OpenRouterClient and test fakes."""

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = ...,
        json_mode: bool = ...,
    ) -> dict[str, object]: ...


def _aiml_primary() -> bool:
    """Return True when AIML should be the first link in the chat fallback chain.

    Reads ``AIML_PRIMARY`` env var.  Default is ``"1"`` (AIML first), mirroring
    ``pipeline.research.routes.aiml_primary``.

    M-2: parse symmetrically against :data:`_TRUTHY` (case-insensitive) instead
    of an ad-hoc deny list. The old ``raw not in ("", "0", "false", "False",
    "no")`` form treated ``"off"`` / ``"No"`` / ``"NO"`` as truthy, disagreeing
    with every other truthy check in the codebase.
    """
    return os.environ.get("AIML_PRIMARY", "1").strip().lower() in _TRUTHY


def _aiml_client_or_none() -> _ChatClient | None:
    """Return an AimlClient if AIML_API_KEY is set, else None (never raises)."""
    try:
        from pipeline.research.gateways.aiml import AimlClient  # noqa: PLC0415

        return AimlClient.from_env()  # type: ignore[return-value]
    except (KeyError, ImportError):
        return None


# ── RU translation client (Run D dependency; M-2) ─────────────────────────────
#
# The RU stage translates EN → RU on the AIML allowlist ONLY. OpenRouter has no
# credits for this campaign (config/campaign_goal.json: openrouter_optional=true)
# and Gemini is forbidden outright (no_gemini=true). The two helpers below make
# that policy a mechanical guard rather than a convention the Run-D driver has to
# remember: there is deliberately NO OpenRouter last resort here (unlike
# _build_client), so an exhausted/absent AIML fails loudly instead of silently
# translating through the wrong provider. The allowlist mirrors the TRANSLATE
# route order in pipeline.research.routes (aiml gpt-5-chat-latest → gpt-4.1).

_TRANSLATION_MODELS: Final[frozenset[str]] = frozenset(
    {"openai/gpt-5-chat-latest", "openai/gpt-4.1"}
)


def assert_translation_model(model: str) -> str:
    """Validate *model* for the RU translation path; return it stripped.

    Raises:
        ValueError: when *model* names a Gemini model (forbidden) or any id
            outside the AIML translation allowlist
            (``openai/gpt-5-chat-latest``, fallback ``openai/gpt-4.1``).
    """
    candidate = model.strip()
    if "gemini" in candidate.lower():
        raise ValueError(
            f"Gemini is forbidden for RU translation (got {model!r}); "
            "use openai/gpt-5-chat-latest or openai/gpt-4.1"
        )
    if candidate not in _TRANSLATION_MODELS:
        raise ValueError(
            f"RU translation model {model!r} not in allowlist {sorted(_TRANSLATION_MODELS)}"
        )
    return candidate


def build_translation_client() -> _ChatClient:
    """Return an AIML-only chat client for the RU translation stage (Run D).

    Unlike :func:`_build_client`, there is NO OpenRouter last resort: the RU
    stage must fail loudly when AIML is unavailable rather than translate
    through a provider with no credits for this campaign.

    Raises:
        RuntimeError: when ``AIML_API_KEY`` is not configured.
    """
    aiml = _aiml_client_or_none()
    if aiml is None:
        raise RuntimeError(
            "RU translation requires AIML_API_KEY (no OpenRouter fallback — "
            "OpenRouter has no credits for this campaign)"
        )
    return aiml


def _build_client() -> _ChatClient:
    """Return a ready _ChatClient implementing the AIML -> 302 -> OpenRouter chain.

    Resolution order when ``AIML_PRIMARY`` is set (default ``"1"``):
      1. AimlClient      (AIML_API_KEY) — primary
      2. TaoAIClient     (TAO_AI_API_KEY) — on AimlClient BudgetExceeded
      3. OpenRouterClient                — on TaoAIClient BudgetExceeded

    When ``AIML_PRIMARY`` is unset/falsy the legacy two-tier chain is used:
      OpenRouterClient (primary) -> TaoAIClient (fallback on 402).

    When ``TAO_AI_PRIMARY`` is set the shared llm_client factory takes over
    (302.ai-first) and the AIML tier is skipped entirely — existing behaviour
    for operators who explicitly set TAO_AI_PRIMARY.
    """
    from pipeline.llm_client import build_chat_client, tao_primary_requested  # noqa: PLC0415

    if tao_primary_requested():
        return build_chat_client()

    if _aiml_primary():
        aiml = _aiml_client_or_none()
        if aiml is not None:
            return _FallbackClient(primary=aiml)
        # AIML key absent — fall through to the legacy chain.
        _log.debug(
            "research_dispatch: AIML_PRIMARY=1 but AIML_API_KEY absent, "
            "falling back to OpenRouter -> 302 chain"
        )

    from pipeline.openrouter_client import OpenRouterClient  # noqa: PLC0415

    try:
        primary = OpenRouterClient()
    except ValueError:
        # OpenRouter key not set at all — skip straight to 302 fallback.
        _log.warning("research_dispatch: OpenRouter key absent, using TaoAIClient fallback")
        return _tao_client_or_raise()

    return _FallbackClient(primary=primary)


def _tao_client_or_raise() -> _ChatClient:
    """Return a TaoAIClient or raise KeyError if TAO_AI_API_KEY is also missing."""
    from pipeline.research.client_302ai import TaoAIClient  # noqa: PLC0415

    client: _ChatClient = TaoAIClient.from_env()  # type: ignore[assignment]
    return client


def _openrouter_client_or_none() -> _ChatClient | None:
    """Return an OpenRouterClient if OPENROUTER_* key is set, else None (never raises)."""
    try:
        from pipeline.openrouter_client import OpenRouterClient  # noqa: PLC0415

        return OpenRouterClient()  # type: ignore[return-value]
    except (ValueError, ImportError):
        return None


def _all_budget_exceptions() -> tuple[type[Exception], ...]:
    """Return a tuple containing every provider's BudgetExceeded exception class.

    Collected lazily so missing optional dependencies never crash the import.
    Each import is individually guarded; the result is cached by the caller.
    """
    excs: list[type[Exception]] = []
    try:
        from pipeline.openrouter_client import BudgetExceeded as _ORBudget  # noqa: PLC0415

        excs.append(_ORBudget)
    except ImportError:  # pragma: no cover
        pass
    try:
        from pipeline.research.gateways.aiml import BudgetExceeded as _AimlBudget  # noqa: PLC0415

        excs.append(_AimlBudget)
    except ImportError:  # pragma: no cover
        pass
    try:
        from pipeline.research.client_302ai import BudgetExceeded as _TaoBudget  # noqa: PLC0415

        excs.append(_TaoBudget)
    except ImportError:  # pragma: no cover
        pass
    return tuple(excs) or (Exception,)


class _FallbackClient:
    """Multi-tier fallback chat client: primary -> 302 -> OpenRouter on BudgetExceeded.

    When the primary client raises ``BudgetExceeded`` the call is retried on
    TaoAIClient (302.ai).  If 302 also raises ``BudgetExceeded``, OpenRouter
    is tried as a last resort.

    When constructed with an AimlClient as primary the hot path is:
      AimlClient -> TaoAIClient -> OpenRouterClient

    When constructed with an OpenRouterClient (legacy mode) the chain is:
      OpenRouterClient -> TaoAIClient

    All transitions are lazy: secondary clients are built only on first need so
    absent keys never block the primary path.
    """

    def __init__(self, primary: _ChatClient) -> None:
        self._primary: _ChatClient = primary
        self._tao: _ChatClient | None = None
        self._openrouter: _ChatClient | None = None

    def _get_tao(self) -> _ChatClient:
        if self._tao is None:
            self._tao = _tao_client_or_raise()
        return self._tao

    def _get_openrouter(self) -> _ChatClient | None:
        if self._openrouter is None:
            self._openrouter = _openrouter_client_or_none()
        return self._openrouter

    def _budget_exceptions(self) -> tuple[type[Exception], ...]:
        """Return tuple of all providers' BudgetExceeded exception types."""
        return _all_budget_exceptions()

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        paid_required: bool = False,
        json_mode: bool = False,
    ) -> dict[str, object]:
        budget_excs = self._budget_exceptions()

        # --- primary attempt ---
        try:
            return self._primary.chat(
                model,
                messages,
                paid_required=paid_required,
                json_mode=json_mode,
            )
        except budget_excs as exc:
            _log.warning(
                "research_dispatch: primary BudgetExceeded (%s) — trying TaoAIClient",
                exc,
            )

        # --- 302 tier ---
        try:
            return self._get_tao().chat(
                model,
                messages,
                paid_required=paid_required,
                json_mode=json_mode,
            )
        except budget_excs as exc:
            _log.warning(
                "research_dispatch: TaoAIClient BudgetExceeded (%s) — trying OpenRouter",
                exc,
            )

        # --- OpenRouter last resort ---
        or_client = self._get_openrouter()
        if or_client is None:
            raise RuntimeError(
                "research_dispatch: all providers exhausted (BudgetExceeded) "
                "and no OpenRouter key is configured"
            )
        return or_client.chat(
            model,
            messages,
            paid_required=paid_required,
            json_mode=json_mode,
        )


def _slug(text: str, max_len: int = 60) -> str:
    """Lowercase fingerprint-safe slug; never empty."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:max_len] or "anon"


def _build_research_prompt(
    *,
    primary_genre: str,
    premise_type: str,
    cultural_claim: str,
    audience_demographic: str,
) -> str:
    """One consolidated prompt covering Steps A, B, C of the researcher.

    Returns JSON because chat() always JSON-parses the LLM content. The
    instruction to respond in JSON is mandatory — sonar must comply.
    """
    return (
        "You are a media-research analyst. Respond in valid JSON only — no prose "
        "wrappers, no markdown fences.\n\n"
        f"Task A (genre saturation): How many films in the '{primary_genre}' genre "
        f"explored '{premise_type}' between 2022 and 2026? Return up to 3 examples "
        "with worldwide box office (USD millions) or streaming engagement and a critical "
        "score. Prefer 2025-2026 releases.\n\n"
        f"Task B (cultural moment): Provide the most recent 2025-2026 statistical "
        f"evidence for: '{cultural_claim}'. Cite primary source, year, exact figure, "
        "and a deep-path URL (no bare domains, no search-engine URLs).\n\n"
        f"Task C (audience sizing): What is the global audience size in 2025-2026 "
        f"for content targeted at '{audience_demographic}'? Provide: total streaming "
        "subscribers across major platforms, percentage who actively consume the genre, "
        "demographic breakdown by age and income, three-year trend if available.\n\n"
        "Output schema (JSON object):\n"
        "{\n"
        '  "genre_saturation": {\n'
        '    "status": "VERIFIED|PARTIAL|FAILED",\n'
        '    "examples": [{"title": str, "year": int, "ww_revenue_usd_m": float|null,\n'
        '                  "critic_score_pct": int|null, "source_url": str}]\n'
        "  },\n"
        '  "cultural_moment": {\n'
        '    "status": "VERIFIED|PARTIAL|FAILED",\n'
        '    "source": str, "year": int, "statistic": str, "source_url": str\n'
        "  },\n"
        '  "audience_evidence": {\n'
        '    "status": "VERIFIED|PARTIAL|FAILED",\n'
        '    "us_addressable_m": float|null, "global_en_addressable_m": float|null,\n'
        '    "streaming_total_m": float|null, "cagr_pct": float|null,\n'
        '    "demographic_notes": str, "source_url": str\n'
        "  }\n"
        "}\n"
    )


def _build_research_prompt_from_theme(theme_text: str) -> str:
    """Theme-only variant of the research prompt for use by the orchestrator skill.

    The skill has only the seed's narrative theme text, not pre-parsed genre /
    premise / cultural-claim / audience-demographic fields. Sonar reads the
    theme and produces the structured output itself.
    """
    return (
        "You are a media-research analyst. Respond in valid JSON only — no prose "
        "wrappers, no markdown fences.\n\n"
        f"Concept theme:\n```\n{theme_text}\n```\n\n"
        "From the theme above, infer the primary genre, premise type, the cultural "
        "claim the concept makes, and the implied target demographic.\n\n"
        "Then provide:\n"
        "  (A) Genre saturation: how many films in this genre explored this "
        "premise type 2022-2026? List up to 3 examples with worldwide box-office "
        "(USD millions) or streaming engagement and a critic score. Prefer 2025-2026.\n"
        "  (B) Cultural moment: the most recent 2025-2026 statistical evidence "
        "for the implied claim. Primary source, year, exact figure, deep-path URL.\n"
        "  (C) Audience sizing: global audience size in 2025-2026 for the implied "
        "demographic. Total streaming subscribers across major platforms, percentage "
        "consuming the genre, demographic breakdown, three-year trend if available.\n\n"
        "Output schema (JSON object):\n"
        "{\n"
        '  "inferred": {\n'
        '    "primary_genre": str, "premise_type": str, "cultural_claim": str,\n'
        '    "audience_demographic": str\n'
        "  },\n"
        '  "genre_saturation": {\n'
        '    "status": "VERIFIED|PARTIAL|FAILED",\n'
        '    "examples": [{"title": str, "year": int, "ww_revenue_usd_m": float|null,\n'
        '                  "critic_score_pct": int|null, "source_url": str}]\n'
        "  },\n"
        '  "cultural_moment": {\n'
        '    "status": "VERIFIED|PARTIAL|FAILED",\n'
        '    "source": str, "year": int, "statistic": str, "source_url": str\n'
        "  },\n"
        '  "audience_evidence": {\n'
        '    "status": "VERIFIED|PARTIAL|FAILED",\n'
        '    "us_addressable_m": float|null, "global_en_addressable_m": float|null,\n'
        '    "streaming_total_m": float|null, "cagr_pct": float|null,\n'
        '    "demographic_notes": str, "source_url": str\n'
        "  }\n"
        "}\n"
    )


def _build_market_prompt(*, primary_genre: str) -> str:
    """Phase-7 narrator market-sizing prompt; JSON-only response."""
    return (
        "You are a media-finance analyst. Respond in valid JSON only — no prose, "
        "no markdown fences.\n\n"
        f"Task: Estimate the 2026 global market for '{primary_genre}' content on "
        "streaming platforms. Provide: (1) total global streaming subscribers across "
        "Netflix/HBO/Amazon/Apple TV+/Disney+, (2) percentage actively watching this "
        "genre with primary source, (3) one comparable title's first-week streaming "
        "viewership OR theatrical opening-weekend revenue from 2022-2026, "
        "(4) year-over-year audience growth for the genre.\n\n"
        "Cite primary sources only (Nielsen, MPA, Parrot Analytics, platform earnings).\n\n"
        "Output schema (JSON object):\n"
        "{\n"
        '  "total_subscribers_m": float, "subscribers_source_url": str,\n'
        '  "genre_share_pct": float, "genre_share_source_url": str,\n'
        '  "comp_title": str, "comp_metric_value": str, "comp_source_url": str,\n'
        '  "yoy_growth_pct": float|null, "growth_source_url": str|null\n'
        "}\n"
    )


def fetch_research_evidence(
    *,
    run_dir: Path,
    theme_slug: str,
    primary_genre: str,
    premise_type: str,
    cultural_claim: str,
    audience_demographic: str,
    client: _ChatClient | None = None,
) -> dict[str, Any]:
    """Fetch genre+cultural+audience evidence for the concept-researcher.

    On cache hit (same fingerprint + same week) returns the prior result instantly
    and skips the HTTP call entirely. Always writes to research_raw.json so the
    concept-researcher agent reads from disk, not from the LLM.

    Returns the structured result dict.
    """
    if client is None:
        client = _build_client()

    prompt = _build_research_prompt(
        primary_genre=primary_genre,
        premise_type=premise_type,
        cultural_claim=cultural_claim,
        audience_demographic=audience_demographic,
    )
    messages = [{"role": "user", "content": prompt}]
    fingerprint = f"research:{_slug(theme_slug)}:{_slug(primary_genre)}"

    result: dict[str, Any] = sonar_cache.cached_chat(
        client,
        model=_SONAR_PRO,
        messages=messages,
        fingerprint=fingerprint,
        paid_required=True,
        json_mode=True,
    )

    out_path = Path(run_dir) / RESEARCH_EVIDENCE_FILENAME
    safe_write(out_path, json.dumps(result, indent=2, ensure_ascii=False))
    _log.info("research_dispatch: wrote %s", out_path)
    return result


def fetch_research_for_theme(
    *,
    run_dir: Path,
    theme_slug: str,
    theme_text: str,
    client: _ChatClient | None = None,
) -> dict[str, Any]:
    """Theme-only entry point for the single-idea skill.

    Called BEFORE Task(concept-researcher) so the agent reads a pre-fetched,
    cached evidence sidecar instead of running a Bash sonar command that today
    silently fails (no CLI exists for `python -m pipeline.openrouter_client`).

    Sonar reads the narrative theme directly and produces structured JSON
    covering genre saturation / cultural moment / audience evidence in one call.
    Cache key fingerprint: research-theme:<theme_slug>.

    Writes runs/{slug}/research_raw.json. Returns the structured dict.
    """
    if client is None:
        client = _build_client()

    prompt = _build_research_prompt_from_theme(theme_text)
    messages = [{"role": "user", "content": prompt}]
    fingerprint = f"research-theme:{_slug(theme_slug)}"

    result: dict[str, Any] = sonar_cache.cached_chat(
        client,
        model=_SONAR_PRO,
        messages=messages,
        fingerprint=fingerprint,
        paid_required=True,
        json_mode=True,
    )

    out_path = Path(run_dir) / RESEARCH_EVIDENCE_FILENAME
    safe_write(out_path, json.dumps(result, indent=2, ensure_ascii=False))
    _log.info("research_dispatch: wrote %s (theme-only path)", out_path)
    return result


def fetch_market_sizing(
    *,
    run_dir: Path,
    theme_slug: str,
    primary_genre: str,
    client: _ChatClient | None = None,
) -> dict[str, Any]:
    """Fetch live market sizing for the concept-narrator (Phase 7).

    Mirrors fetch_research_evidence but targets sonar-deep-research with the
    market-sizing prompt. Writes market_raw.json into run_dir.
    """
    if client is None:
        client = _build_client()

    prompt = _build_market_prompt(primary_genre=primary_genre)
    messages = [{"role": "user", "content": prompt}]
    fingerprint = f"market:{_slug(theme_slug)}:{_slug(primary_genre)}"

    result: dict[str, Any] = sonar_cache.cached_chat(
        client,
        model=_SONAR_DEEP,
        messages=messages,
        fingerprint=fingerprint,
        paid_required=True,
        json_mode=True,
    )

    out_path = Path(run_dir) / MARKET_SIZING_FILENAME
    safe_write(out_path, json.dumps(result, indent=2, ensure_ascii=False))
    _log.info("research_dispatch: wrote %s", out_path)
    return result


def fetch_market_for_concept(
    *,
    run_dir: Path,
    theme_slug: str,
    client: _ChatClient | None = None,
) -> dict[str, Any]:
    """Concept-aware entry point for the single-idea Phase-7 narrator (NB.2).

    Reads ``run_dir/draft_v0.json`` to extract the concept's ``primary_genre``,
    then dispatches :func:`fetch_market_sizing`. Mirrors the Phase-1 pattern
    (:func:`fetch_research_for_theme`) so the skill can prefetch market evidence
    before invoking the narrator agent.

    Raises:
        FileNotFoundError: ``draft_v0.json`` does not exist under ``run_dir``.

    If ``primary_genre`` is absent from the sidecar, defaults to ``"drama"`` so
    the dispatcher degrades gracefully rather than aborting the pipeline.
    """
    draft_path = Path(run_dir) / "draft_v0.json"
    if not draft_path.exists():
        raise FileNotFoundError(f"draft_v0.json not found in {run_dir}")
    draft: dict[str, Any] = json.loads(draft_path.read_text(encoding="utf-8"))
    primary_genre = str(draft.get("primary_genre") or "drama")
    return fetch_market_sizing(
        run_dir=Path(run_dir),
        theme_slug=theme_slug,
        primary_genre=primary_genre,
        client=client,
    )


__all__ = [
    "MARKET_SIZING_FILENAME",
    "RESEARCH_EVIDENCE_FILENAME",
    "assert_translation_model",
    "build_translation_client",
    "fetch_market_for_concept",
    "fetch_market_sizing",
    "fetch_research_evidence",
    "fetch_research_for_theme",
]
