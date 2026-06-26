"""pipeline/zeitgeist_probe.py — Pre-seed cultural zeitgeist probe (Change 2).

Queries Perplexity sonar-pro once per calendar day for the top 20 cultural
fears/anxieties in English-speaking media. Results are cached under
runs/_cache/zeitgeist_{YYYYMMDD}.json for 24 hours.

The cache is read by pipeline/compound_seed.py._pick_cultural_moment() to bias
sampling toward today's hottest cultural moments.

ADR-0007: calls are routed through openrouter_client (not direct httpx).
ADR-0001: cache write uses pipeline.state.safe_write.
MUST NOT import from frameworks/ (ADR-0005, ANOMALY-002).
MUST NOT import anthropic, httpx directly (ADR-0007).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Final, cast

_log = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_CACHE_DIR: Final[Path] = _REPO_ROOT / "runs" / "_cache"
_CACHE_TTL_DAYS: Final[int] = 1

_SONAR_MODEL: Final[str] = "perplexity/sonar-pro"

# Minimum word length for zeitgeist overlap matching (suppress PLR2004).
_MIN_WORD_LEN: Final[int] = 3
# Floor weight assigned to cultural moments with no zeitgeist overlap.
_WEIGHT_FLOOR: Final[float] = 0.1

_ZEITGEIST_QUERY: Final[str] = (
    "List the 20 most discussed cultural fears, scientific anxieties, and "
    "conspiracy beliefs in English-speaking media in the last 90 days. "
    "For each item return: a short id slug (snake_case, max 30 chars), "
    "a 1-line description (max 80 chars), an estimated audience size in millions "
    "(integer), and one citation URL. "
    "Return a JSON array of objects with keys: id, description, audience_M, citation_url. "
    "No prose, no markdown fences — raw JSON array only."
)


def _cache_path() -> Path:
    today = date.today().isoformat().replace("-", "")
    return _CACHE_DIR / f"zeitgeist_{today}.json"


def load_cached() -> list[dict[str, Any]] | None:
    """Return today's cached zeitgeist list, or None if stale/absent."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data: list[dict[str, Any]] = cast("list[dict[str, Any]]", raw)
        if isinstance(raw, list) and len(data) > 0:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def probe(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Return today's zeitgeist list, fetching from sonar-pro if cache is stale.

    Args:
        force_refresh: Skip cache and always query sonar-pro.

    Returns:
        List of dicts with keys: id, description, audience_M, citation_url.
        Returns [] on API failure (caller degrades gracefully).
    """
    if not force_refresh:
        cached = load_cached()
        if cached is not None:
            _log.info("zeitgeist_probe: cache hit %s", _cache_path())
            return cached

    try:
        from pipeline.llm_client import build_chat_client  # noqa: PLC0415

        client = build_chat_client()
        # chat() returns the already-parsed inner JSON content (see
        # pipeline.openrouter_client._call_once, which extracts
        # choices[0].message.content, strips fences, and json.loads it).
        # Walking .choices[0].message.content here is the silent-empty-list
        # defect fixed in micro_amplify.py on 2026-05-22 — do not reintroduce.
        # For this prompt the LLM is asked for a JSON array, so the expected
        # return is list[dict]. _parse_possibly_multiple_json wraps stacked
        # objects as {"assets": [...]} — handle both shapes defensively.
        raw_response: Any = client.chat(
            model=_SONAR_MODEL,
            messages=[{"role": "user", "content": _ZEITGEIST_QUERY}],
            paid_required=True,
            json_mode=False,
        )
        items: list[Any]
        if isinstance(raw_response, list):
            items = cast("list[Any]", raw_response)
        elif isinstance(raw_response, dict):
            response_dict: dict[str, Any] = cast("dict[str, Any]", raw_response)
            assets: Any = response_dict.get("assets")
            if not isinstance(assets, list):
                _log.warning(
                    "zeitgeist_probe: dict response missing 'assets' list, keys=%s",
                    sorted(response_dict.keys()),
                )
                return []
            items = cast("list[Any]", assets)
        else:
            _log.warning(
                "zeitgeist_probe: unexpected response shape, got %s",
                type(raw_response).__name__,
            )
            return []

        result: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                result.append(cast("dict[str, Any]", item))
        if not result:
            _log.warning("zeitgeist_probe: response contained no dict items")
            return []

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        from pipeline.state import safe_write  # noqa: PLC0415

        safe_write(_cache_path(), json.dumps(result, indent=2, ensure_ascii=False))
        _log.info("zeitgeist_probe: fetched %d items, cached to %s", len(result), _cache_path())
        return result

    except Exception as exc:
        _log.warning("zeitgeist_probe: API call failed (%s), returning []", exc)
        return []


def boost_weights(
    cultural_moments: list[dict[str, Any]],
    zeitgeist: list[dict[str, Any]],
) -> list[float]:
    """Return a weight list for cultural_moments based on zeitgeist overlap * urgency.

    Issue #24: weights are now the product of two independent signals:
    1. Zeitgeist overlap (1.0 if label/id matches live zeitgeist text, else floor)
    2. ``urgency_score_2026`` field (float 0.5-2.0 baked into each entry).
       This makes hot 2026 topics (urgency=1.9) outrank cooled ones (urgency=0.8)
       even when the live zeitgeist API is unavailable or returns no match.

    Returned weights are normalized so the maximum is 1.0, minimum is _WEIGHT_FLOOR.
    """
    weights: list[float] = []
    zeitgeist_text = " ".join(
        f"{z.get('id', '')} {z.get('description', '')}".lower() for z in zeitgeist
    )
    for cm in cultural_moments:
        cm_label = str(cm.get("label", cm.get("id", ""))).lower().replace("_", " ")
        overlap = (
            1.0
            if any(word in zeitgeist_text for word in cm_label.split() if len(word) > _MIN_WORD_LEN)
            else _WEIGHT_FLOOR
        )
        urgency: float = float(cm.get("urgency_score_2026", 1.0))
        weights.append(overlap * urgency)
    if not weights:
        return weights
    max_w = max(weights)
    if max_w <= _WEIGHT_FLOOR:
        return weights
    return [w / max_w for w in weights]


__all__ = ["boost_weights", "load_cached", "probe"]
