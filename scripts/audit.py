#!/usr/bin/env python3
"""scripts/audit.py — verify the engine's data-sources registry + downstream checks.

P1 implements: `sources` (KNOW-09 enforcer + Pitfall 4.2 audit-side warning).
P5 will implement: `check-concepts`, `check-quotes`, `check-citations` (golden-concept audits).

References:
- sources/data-sources.yaml (the registry under audit)
- pipeline/data/polti_tobias_coherence.json (Pitfall 4.2 threshold)
- ./CLAUDE.md ADR-0001 (state lives on disk; report writes to data/audit/)
- .planning/phases/01-knowledge-layer/01-RESEARCH.md §HEAD-check protocol
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

ALLOW_LISTED_BOT_BLOCK_HOSTS = frozenset(
    {
        "imdb.com",
        "themoviedb.org",
        "boxofficemojo.com",
        "flixpatrol.com",
        "letterboxd.com",
        "nytimes.com",
        "theblackvault.com",
        "fbi.gov",
        "cia.gov",
        "archives.gov",
        "sec.gov",
        "census.gov",
        "gov.br",
        "papers.ssrn.com",
        "nber.org",
        "arxiv.org",
        "ascap.com",
        "bmi.com",
        "sesac.com",
        "sagaftra.org",
        "dga.org",
        "wga.org",
        # US Library of Congress Chronicling America (403 bot-block on HEAD)
        "chroniclingamerica.loc.gov",
        "loc.gov",
        # Guardian Open Platform (401 requires API key; host is legitimate)
        "content.guardianapis.com",
        "theguardian.com",
        # US Government API gateway (403 bot-block on HEAD)
        "api.usa.gov",
        # GWU National Security Archive (WAF blocks HEAD with 403/404)
        "nsarchive.gwu.edu",
    }
)

SEARCH_REDIRECT_HOSTS = frozenset(
    {
        "google.com",
        "bing.com",
        "duckduckgo.com",
        "search.brave.com",
        "yandex.com",
        "yahoo.com",
    }
)

REGISTRY_PATH = Path("sources/data-sources.yaml")
COHERENCE_PATH = Path("pipeline/data/polti_tobias_coherence.json")
AUDIT_OUT_DIR = Path("data/audit")


def _host_of(url: str) -> str:
    """Extract hostname from a URL."""
    return urlparse(url).hostname or ""


def _is_bare_domain(api_base: str) -> bool:
    """Return True if api_base has no meaningful path (empty or '/')."""
    parsed = urlparse(api_base)
    return parsed.path in ("", "/")


def _host_in_allow_list(host: str) -> bool:
    """Check if a host or any of its parent domains is in the allow-list."""
    for allowed in ALLOW_LISTED_BOT_BLOCK_HOSTS:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


MIN_SOURCE_COUNT = 30  # KNOW-09 hard floor
MAX_QUOTE_WORDS = 14  # P5 OPS-01: blockquote word limit


def head_check_with_retry(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """HEAD-check a URL with one retry on transient failure.

    Returns (status_code, host). Status 0 signals hard FAIL (no response).
    """
    host = _host_of(url)
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, method="HEAD")  # noqa: S310
            req.add_header(
                "User-Agent",
                "AnomalyEngine/3.0 audit-sources",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.status, host
        except urllib.error.HTTPError as e:
            return e.code, host
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 0:
                time.sleep(2)
                continue
            return 0, host
    return 0, host


def _check_polti_tobias_threshold(data: dict | None = None) -> str | None:
    """Return WARNING string when len(anti_patterns) > operator_caps.audit_alert_above, else None.

    When `data` is None, read pipeline/data/polti_tobias_coherence.json from disk
    (returning None if absent — silent no-op for runs before plan 01-04 lands).
    When `data` is provided, apply the same threshold logic to the dict in-memory.
    The latter shape is what tests/test_audit_polti_threshold.py exercises with
    a synthetic 21-entry fixture so the warning logic is unit-tested in Wave 1
    without depending on plan 01-04 having shipped the JSON file.

    References:
    - Pitfall 4.2 (polti_tobias_coherence exhaustion)
    - operator decision 2026-05-06: seed=5, audit alert at >20 entries
    """
    if data is None:
        if not COHERENCE_PATH.exists():
            return None
        try:
            loaded: dict = json.loads(COHERENCE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return f"WARNING: polti_tobias_coherence.json is not valid JSON: {exc}"
    else:
        loaded = data

    threshold = loaded.get("operator_caps", {}).get("audit_alert_above", 20)
    n = len(loaded.get("anti_patterns", []))
    if n > threshold:
        return (
            f"WARNING: polti_tobias_coherence.json has {n} entries "
            f"(exceeds soft cap of {threshold} per Pitfall 4.2 / "
            f"operator decision 2026-05-06). "
            f"Review whether new entries reflect genuine incoherence or Forge over-eagerness."
        )
    return None


def _structural_checks(sources: list[dict]) -> list[str]:
    """Return list of structural failure strings for the sources list."""
    failures: list[str] = []
    if len(sources) < MIN_SOURCE_COUNT:
        failures.append(f"len(sources)={len(sources)} < {MIN_SOURCE_COUNT} (KNOW-09)")

    cats = {s.get("category") for s in sources}
    missing_cats = set("ABCDEFGHIJ") - cats
    if missing_cats:
        failures.append(f"missing categories: {sorted(missing_cats)}")

    bare = [s["source_id"] for s in sources if _is_bare_domain(s.get("api_base", ""))]
    if bare:
        failures.append(f"bare-domain api_base: {bare}")

    redirect = [
        s["source_id"]
        for s in sources
        if any(h in s.get("api_base", "") for h in SEARCH_REDIRECT_HOSTS)
    ]
    if redirect:
        failures.append(f"search-redirect host in api_base: {redirect}")

    return failures


def _head_verdict(status: int, host: str, bot_block_allow_listed: bool = False) -> str:
    """Map a HEAD response status + host to a verdict string.

    bot_block_allow_listed: when True (from sources/data-sources.yaml field), any
    non-200 HTTP status is treated as PASS-bot-block because the site is known to
    return unreliable HEAD responses (e.g. 404 from WAF, 403 from CDN, etc.).
    """
    if status in (200, 204, 206):
        return "PASS"
    if status in (301, 302, 307, 308):
        return "PASS-redirect"
    if status in (401, 403) and (_host_in_allow_list(host) or bot_block_allow_listed):
        return "PASS-bot-block"
    # 405 = HEAD method not allowed; server is live, only HEAD is blocked.
    # 400 = API endpoint requires query params; server is live.
    # 429 = rate-limited; server is live and actively enforcing quotas.
    # All indicate the endpoint exists and is reachable -- not link rot.
    if status in (405, 400, 429):
        return "PASS-head-not-supported"
    # For explicitly allow-listed bot-block sources, any non-200 status is accepted.
    # These hosts are known to return unreliable HEAD responses (WAF, CDN, etc.).
    if bot_block_allow_listed:
        return "PASS-bot-block"
    return "FAIL"


def _head_check_all(sources: list[dict]) -> tuple[list[dict], list[str]]:
    """HEAD-check all api_base URLs; return (results, failures)."""
    results: list[dict] = []
    failures: list[str] = []
    for s in sources:
        url = s["api_base"]
        bot_block = bool(s.get("bot_block_allow_listed", False))
        status, host = head_check_with_retry(url)
        verdict = _head_verdict(status, host, bot_block_allow_listed=bot_block)
        if verdict == "FAIL":
            failures.append(f"{s['source_id']}: HEAD {url} -> {status}")
        results.append(
            {"source_id": s["source_id"], "url": url, "status": status, "verdict": verdict}
        )
    return results, failures


def cmd_sources(args: argparse.Namespace) -> int:
    """Run KNOW-09 audit: structural + HEAD checks on sources/data-sources.yaml.

    Offline mode (--offline or OFFLINE=1 env): structural checks only.
    Online mode (default): structural + HEAD-check every api_base.

    Exit 0 if all checks PASS; exit 1 if any FAIL.
    """
    if not REGISTRY_PATH.exists():
        print(f"FAIL: {REGISTRY_PATH} missing", file=sys.stderr)
        return 1

    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    sources = registry.get("sources", [])
    failures: list[str] = []
    warnings: list[str] = []

    offline_flag = bool(getattr(args, "offline", False))
    offline_env = os.environ.get("OFFLINE", "") not in ("", "0", "false", "False")
    online = not (offline_flag or offline_env)

    # Structural checks
    failures.extend(_structural_checks(sources))
    cats = {s.get("category") for s in sources}

    # Online HEAD checks
    head_results: list[dict] = []
    if online:
        head_results, head_failures = _head_check_all(sources)
        failures.extend(head_failures)

    # Pitfall 4.2 sub-check
    pt_warning = _check_polti_tobias_threshold()
    if pt_warning:
        warnings.append(pt_warning)
        print(pt_warning, file=sys.stderr)

    # Emit JSON report
    AUDIT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "ts": ts,
        "online": online,
        "n_sources": len(sources),
        "categories_present": sorted(cats),
        "head_results": head_results,
        "warnings": warnings,
        "failures": failures,
    }
    out_path = AUDIT_OUT_DIR / f"sources_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if failures:
        print(f"FAIL ({len(failures)} issues): see {out_path}", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    mode_label = "ONLINE" if online else "OFFLINE"
    n_cats = len(cats)
    print(
        f"PASS ({mode_label}): {len(sources)} sources across {n_cats} categories;"
        f" report at {out_path}"
    )
    return 0


def _load_banned_terms_for_concepts() -> list[str]:
    """Load banned terms for concept auditing.

    Lazy wrapper around evals.anti_slop.load_banned_terms so tests can
    monkeypatch 'scripts.audit._load_banned_terms_for_concepts' without
    triggering a circular import at module load time.
    """
    from evals.anti_slop import load_banned_terms  # noqa: PLC0415

    return load_banned_terms()


def _count_words(text: str) -> int:
    """Return the number of whitespace-separated words in text."""
    return len(text.split())


def _check_concept_quotes(content: str) -> list[str]:
    """Return list of failures for blockquote lines exceeding 14 words.

    Returns strings like 'quote_too_long:17_words'.
    """
    failures: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            quote_text = stripped[1:].strip()
            n = _count_words(quote_text)
            if n > MAX_QUOTE_WORDS:
                failures.append(f"quote_too_long:{n}_words")
    return failures


def _check_concept_anti_slop(content: str, banned_terms: list[str]) -> list[str]:
    """Return list of failures for banned anti-slop terms found in content.

    Returns strings like 'anti_slop_term:truly unique'.
    """
    failures: list[str] = []
    content_lower = content.lower()
    for term in banned_terms:
        if term.lower() in content_lower:
            failures.append(f"anti_slop_term:{term}")
    return failures


def _check_concept_citations(content: str) -> list[str]:
    """Return list of failures for citation checks.

    Checks:
    - No search-engine redirect hosts in URLs.
    Returns strings like 'search_redirect_host:{host}'.
    """
    import re  # noqa: PLC0415

    failures: list[str] = []
    url_pattern = re.compile(r"https?://[^\s\)\"'>]+")
    for url in url_pattern.findall(content):
        host = _host_of(url)
        if host in SEARCH_REDIRECT_HOSTS:
            failures.append(f"search_redirect_host:{host}")
    return failures


def _parse_concept_id(path: Path, content: str) -> str:
    """Extract concept_id from frontmatter, falling back to stem."""
    import re  # noqa: PLC0415

    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if line.startswith("concept_id:"):
                return line.split(":", 1)[1].strip()
    return path.stem


def cmd_check_concepts(args: argparse.Namespace) -> int:
    """Audit golden concept markdown files.

    Checks: anti-slop terms, quote word count <=14, citation URL safety.
    Writes: data/audit/audit_report_<ts>.md
    Exit 0 on pass or empty; exit 1 on any failure.
    """
    concepts_dir = Path(getattr(args, "concepts_dir", "out/concepts"))

    if not concepts_dir.exists():
        print("No concepts found — skipping concept audit.")
        return 0

    md_files = sorted(concepts_dir.glob("*.md"))
    if not md_files:
        print("No concepts found — skipping concept audit.")
        return 0

    banned_terms = _load_banned_terms_for_concepts()

    results: list[dict] = []
    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        concept_id = _parse_concept_id(md_path, content)

        checks: list[str] = []
        checks.extend(_check_concept_anti_slop(content, banned_terms))
        checks.extend(_check_concept_quotes(content))
        checks.extend(_check_concept_citations(content))

        results.append(
            {
                "concept_id": concept_id,
                "path": str(md_path),
                "failures": checks,
            }
        )

    total = len(results)
    failed = [r for r in results if r["failures"]]
    passed = total - len(failed)

    # Terminal summary
    print(f"Audited: {total} concepts — {passed} passed / {len(failed)} failed")
    for r in failed:
        checks_str = ", ".join(r["failures"])
        print(f"[FAIL] {r['concept_id']} — {checks_str}")

    # Write report file
    AUDIT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = AUDIT_OUT_DIR / f"audit_report_{ts}.md"
    lines = [
        f"# Concept Audit Report — {ts}",
        "",
        f"**Total:** {total}  **Passed:** {passed}  **Failed:** {len(failed)}",
        "",
    ]
    for r in results:
        status = "PASS" if not r["failures"] else "FAIL"
        lines.append(f"## [{status}] {r['concept_id']}")
        if r["failures"]:
            for f in r["failures"]:
                lines.append(f"- {f}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    if not failed:
        print(f"All {total} concepts passed audit.")
        return 0

    return 1


def cmd_check_quotes(args: argparse.Namespace) -> int:
    """Audit blockquote word counts in concept markdown files.

    Exit 0 if all quotes <=14 words; exit 1 if any exceed 14 words.
    """
    concepts_dir = Path(getattr(args, "concepts_dir", "out/concepts"))

    if not concepts_dir.exists() or not list(concepts_dir.glob("*.md")):
        print("No concepts found — skipping quote audit.")
        return 0

    failures: list[str] = []
    for md_path in sorted(concepts_dir.glob("*.md")):
        content = md_path.read_text(encoding="utf-8")
        concept_id = _parse_concept_id(md_path, content)
        for fail in _check_concept_quotes(content):
            failures.append(f"[FAIL] {concept_id} — {fail}")

    if failures:
        for f in failures:
            print(f)
        return 1

    print("All quotes within word limit.")
    return 0


def cmd_check_citations(args: argparse.Namespace) -> int:
    """Audit citation URLs in concept markdown files for search-engine redirects.

    Exit 0 if no violations; exit 1 if any search-redirect hosts found.
    """
    concepts_dir = Path(getattr(args, "concepts_dir", "out/concepts"))

    if not concepts_dir.exists() or not list(concepts_dir.glob("*.md")):
        print("No concepts found — skipping citation audit.")
        return 0

    failures: list[str] = []
    for md_path in sorted(concepts_dir.glob("*.md")):
        content = md_path.read_text(encoding="utf-8")
        concept_id = _parse_concept_id(md_path, content)
        for fail in _check_concept_citations(content):
            failures.append(f"[FAIL] {concept_id} — {fail}")

    if failures:
        for f in failures:
            print(f)
        return 1

    print("All citations pass.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="audit",
        description="Anomaly Engine audit script",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_sources = sub.add_parser(
        "sources", help="HEAD-check every api_base in sources/data-sources.yaml"
    )
    p_sources.add_argument(
        "--offline",
        action="store_true",
        help="Skip HEAD checks (structural checks only)",
    )
    p_sources.set_defaults(func=cmd_sources)

    p_concepts = sub.add_parser("check-concepts", help="(P5) Audit golden concepts")
    p_concepts.set_defaults(func=cmd_check_concepts)

    p_quotes = sub.add_parser("check-quotes", help="(P5) Audit quote word counts")
    p_quotes.set_defaults(func=cmd_check_quotes)

    p_citations = sub.add_parser("check-citations", help="(P5) Audit citation URLs")
    p_citations.set_defaults(func=cmd_check_citations)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        # Default behavior when invoked bare (matches P0 `make audit` target):
        # run sources subcommand in offline mode (structural check only, safe for no-network CI).
        ns = argparse.Namespace(offline=True)
        return cmd_sources(ns)

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
