"""URL evidence gate for the v4 single-idea pipeline.

Validates every cited URL in a run's research.json via HTTP HEAD requests.
Writes runs/{run_id}/evidence_gate.json with per-URL verdicts.

Usage (CLI)::

    uv run python -m pipeline.evidence_gate runs/<run_id>/research.json

Exit codes:
    0 — all URLs pass (2xx or allow-listed)
    1 — >50% of URLs are invalid (hard fail)
    2 — some URLs invalid but below 50% threshold (soft warn)
"""

import json
import logging
import sys
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_REQUEST_TIMEOUT: float = 10.0
_USER_AGENT: str = "AnomalyEngine/4.0 evidence-gate"
_HARD_FAIL_THRESHOLD: float = 0.50
_HTTP_2XX_MIN: int = 200
_HTTP_2XX_MAX: int = 300
_HTTP_BOT_BLOCK_1: int = 401
_HTTP_BOT_BLOCK_2: int = 403

# Hosts that legitimately return 401/403 to bots but are real sources.
_ALLOW_LISTED: frozenset[str] = frozenset(
    {
        "variety.com",
        "hollywoodreporter.com",
        "deadline.com",
        "the-numbers.com",
        "boxofficemojo.com",
        "imdb.com",
        "themoviedb.org",
        "letterboxd.com",
        "sec.gov",
        "census.gov",
        "wsj.com",
        "ft.com",
        "nytimes.com",
        "economist.com",
        "bloomberg.com",
    }
)

# ── URL extraction ────────────────────────────────────────────────────────────


def _extract_urls(research: dict[str, object]) -> list[str]:
    """Pull all cited URLs out of a research.json dict."""
    urls: list[str] = []
    for key in ("audience_source_url", "cultural_moment_source_url"):
        val = research.get(key)
        if isinstance(val, str) and val.startswith("http"):
            urls.append(val)

    comps_raw = research.get("comps", [])
    if isinstance(comps_raw, list):
        # cast narrows list[Unknown] → list[dict[str,object]] for pyright
        comp_list = cast(list[dict[str, object]], comps_raw)
        for comp in comp_list:
            src_val = comp.get("source_url", "")
            if isinstance(src_val, str) and src_val.startswith("http"):
                urls.append(src_val)

    return urls


# ── Per-URL check ─────────────────────────────────────────────────────────────


def _check_url(client: httpx.Client, url: str) -> dict[str, object]:
    """HEAD-check a single URL and return a verdict dict."""
    host = urlparse(url).hostname or ""
    # Strip leading "www."
    bare_host = host.removeprefix("www.")

    try:
        resp = client.head(url, follow_redirects=True)
        status = resp.status_code
    except Exception as exc:
        return {"url": url, "status": None, "verdict": "ERROR", "detail": str(exc)}

    if _HTTP_2XX_MIN <= status < _HTTP_2XX_MAX:
        return {"url": url, "status": status, "verdict": "PASS", "detail": "2xx"}

    # Allow-listed bot-block hosts: treat 401/403 as PASS
    if status in (401, 403) and bare_host in _ALLOW_LISTED:
        return {
            "url": url,
            "status": status,
            "verdict": "PASS",
            "detail": f"{status} from allow-listed host {bare_host}",
        }

    return {
        "url": url,
        "status": status,
        "verdict": "FAIL",
        "detail": f"HTTP {status}",
    }


# ── Gate runner ───────────────────────────────────────────────────────────────


def run_gate(research_path: Path) -> dict[str, object]:
    """Validate all URLs in *research_path* and write evidence_gate.json.

    Returns the gate result dict.
    """
    research: dict[str, object] = json.loads(research_path.read_text(encoding="utf-8"))
    urls = _extract_urls(research)

    if not urls:
        result: dict[str, object] = {
            "verdict": "SKIP",
            "detail": "No URLs found in research.json",
            "checked": 0,
            "passed": 0,
            "failed": 0,
            "results": [],
        }
        _write(research_path, result)
        return result

    results: list[dict[str, object]] = []
    with httpx.Client(
        headers={"User-Agent": _USER_AGENT},
        timeout=_REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for url in urls:
            verdict_row = _check_url(client, url)
            results.append(verdict_row)
            symbol = "✓" if verdict_row["verdict"] == "PASS" else "✗"
            logger.info("%s %s — %s", symbol, url[:80], verdict_row["detail"])

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = len(results) - passed
    fail_rate = failed / len(results) if results else 0.0

    if fail_rate > _HARD_FAIL_THRESHOLD:
        gate_verdict = "FAIL"
    elif failed > 0:
        gate_verdict = "WARN"
    else:
        gate_verdict = "PASS"

    result = {
        "verdict": gate_verdict,
        "checked": len(results),
        "passed": passed,
        "failed": failed,
        "fail_rate": round(fail_rate, 3),
        "results": results,
    }
    _write(research_path, result)
    return result


def _write(research_path: Path, result: dict[str, object]) -> None:
    out = research_path.parent / "evidence_gate.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("evidence_gate.json written → %s", out)


# ── CLI ───────────────────────────────────────────────────────────────────────

_MIN_CLI_ARGS: int = 2


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < _MIN_CLI_ARGS:
        print("Usage: python -m pipeline.evidence_gate <path/to/research.json>")
        sys.exit(1)

    research_path = Path(sys.argv[1])
    if not research_path.exists():
        print(f"File not found: {research_path}")
        sys.exit(1)

    result = run_gate(research_path)
    print(json.dumps(result, indent=2))

    if result["verdict"] == "FAIL":
        sys.exit(1)
    if result["verdict"] == "WARN":
        sys.exit(2)


if __name__ == "__main__":
    main()
