"""Source every enumerated claim via EvidenceRouter — multi-gateway find + deterministic verify.

Re-implemented on top of :class:`~pipeline.research.evidence_router.EvidenceRouter` so
every pipeline component is reused from the canonical research layer:

  1. FIND   — ``router.discover(query, claim_type=...)`` fans out to configured search
              gateways (Serper → Exa → GW302-serp) and returns credible deep-link hits.
  2. GROUND — ``router.fetch(url)`` walks the fetch cascade (Jina → 302/firecrawl →
              httpx-GET) and returns the page text.
  3. VERIFY — ``value_on_page.value_on_page(value, page.text)`` does refute-by-default
              deterministic substring matching. No LLM verdict decides support.

Emits ``{claim_id: {"supports", "quote", "url", "date"}}`` keyed by the EXACT
extractor claim_id, ready for ``pipeline.veracity.merge_agent_judgments``.
Resumable: judgments are checkpointed after every claim.

Usage:
    uv run python -m scripts.source_claims_302 \
        --manifest runs/veracity/claims_manifest.json \
        --out runs/veracity/judgments_302.json [--limit N] [--cards 01,04] [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from pipeline.research.client_302ai import BudgetExceeded
from pipeline.research.evidence_router import EvidenceRouter, Judgment
from pipeline.state import safe_write

logger = logging.getLogger("source_claims_302")

#: per-claim failures that must not crater a 200-claim run
_EXPECTED = (
    httpx.HTTPError,
    BudgetExceeded,
    json.JSONDecodeError,
    KeyError,
    ValueError,
    TypeError,
    IndexError,
)


def source_one(router: EvidenceRouter, claim: dict[str, Any]) -> dict[str, Any] | None:
    """Find + verify ONE claim via EvidenceRouter. Returns a judgment dict or None (unsourced).

    Delegates to :meth:`~pipeline.research.evidence_router.EvidenceRouter.source_claim`
    after adapting the manifest claim dict to the router's expected shape.

    The manifest uses ``text`` for the full assertion sentence; the router expects
    ``claim_text``.  All other fields (``claim_id``, ``value``, ``claim_type``) are
    forwarded verbatim.

    Args:
        router: A configured :class:`~pipeline.research.evidence_router.EvidenceRouter`.
        claim:  Manifest claim dict with keys: ``claim_id``, ``value``, ``text``,
                ``claim_type`` (and optionally ``title``, ``card``, ``tier_hint``).

    Returns:
        ``{"supports": True, "quote": str, "url": str, "date": str}`` on success,
        or ``None`` when no supporting evidence is found.
    """
    router_claim: dict[str, Any] = {
        "claim_id": claim.get("claim_id", ""),
        "value": claim.get("value", ""),
        # manifest key is "text"; router key is "claim_text"
        "claim_text": claim.get("text", "") or claim.get("claim_text", ""),
        "claim_type": claim.get("claim_type", ""),
    }

    try:
        judgment: Judgment | None = router.source_claim(router_claim)
    except _EXPECTED as exc:
        logger.debug("source_one: router failed for %s: %s", claim.get("claim_id"), exc)
        return None

    if judgment is None or not judgment.supports:
        return None

    return {
        "supports": True,
        "quote": judgment.quote,
        "url": judgment.url,
        "date": judgment.date,
    }


def _load_checkpoint(out_path: Path) -> dict[str, dict[str, Any]]:
    if not out_path.exists():
        return {}
    try:
        raw = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    inner = raw.get("judgments", raw) if isinstance(raw, dict) else {}
    return inner if isinstance(inner, dict) else {}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(
        description="Source claims via EvidenceRouter (search gateways + Firecrawl)."
    )
    ap.add_argument("--manifest", default="runs/veracity/claims_manifest.json")
    ap.add_argument("--out", default="runs/veracity/judgments_302.json")
    ap.add_argument("--limit", type=int, default=0, help="cap claims (0 = all)")
    ap.add_argument("--cards", default="", help="comma-separated card-id prefixes to include")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    claims: list[dict[str, Any]] = list(manifest.get("claims", []))
    if args.cards:
        keep = tuple(c.strip() for c in args.cards.split(",") if c.strip())
        claims = [c for c in claims if str(c.get("card", "")).startswith(keep)]
    if args.limit:
        claims = claims[: args.limit]

    out_path = Path(args.out)
    judgments = _load_checkpoint(out_path)
    todo = [c for c in claims if c["claim_id"] not in judgments]
    print(
        f"302.ai sourcing: {len(todo)} to source ({len(judgments)} cached), {args.workers} workers"
    )

    router = EvidenceRouter.from_defaults()
    lock = threading.Lock()
    done = 0

    def _flush() -> None:
        safe_write(out_path, json.dumps({"judgments": judgments}, indent=2, ensure_ascii=False))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(source_one, router, c): c for c in todo}
        for fut in as_completed(futs):
            claim = futs[fut]
            try:
                judgment = fut.result()
            except Exception as exc:
                judgment = None
                logger.warning("claim %s crashed: %s", claim.get("claim_id"), exc)
            done += 1
            with lock:
                if judgment:
                    judgments[claim["claim_id"]] = judgment
                if done % 5 == 0 or judgment:
                    _flush()
            mark = "OK " if judgment else "-- "
            print(f"  [{done}/{len(todo)}] {mark}{claim['claim_id']} {claim.get('card', '')}")

    _flush()
    print(f"\nDONE — {len(judgments)}/{len(claims)} claims verified -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
