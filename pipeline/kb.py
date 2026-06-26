"""Long-term knowledge base for the Genius Engine v4.0 (V4A-003b, Track B.6).

Append-only JSONL of every asset that has ever passed Phase-3 audience
validation. INTRUSION operator (`pipeline.mutation.intrusion`) queries here to
pull underused validated assets (`use_count < threshold`) from distant domains.

Schema (one row per asset):
    {
        "asset_id": str,
        "domain": str,                          # K..R or A..J
        "asset_title": str,
        "ferocious_specific_summary": str,      # ≤140 words
        "audience_size": int,
        "used_in_concepts": list[str],          # concept_ids that pulled this asset
        "retired_at": str | None,               # ISO-8601 if archived
        "created_at": str                       # ISO-8601
    }

ADR-0001: persistence via `pipeline.state.append_jsonl` + `safe_write`.
ADR-0005: no `frameworks/` imports.
ADR-0007: no anthropic / httpx / openrouter_client (lint-imports enforces).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pipeline.state import append_jsonl, safe_write

DEFAULT_KB_PATH: Path = Path("data/knowledge_kb.jsonl")
DEFAULT_USE_THRESHOLD: int = 5  # archive after >threshold uses (Track B.6)
DEFAULT_TOP_K: int = 10
SUMMARY_MAX_WORDS: int = 140
_TOKEN_MIN_LEN: int = 3  # tokens shorter than this are skipped during search


@dataclass(frozen=True)
class KbAsset:
    """One asset row in the knowledge KB."""

    asset_id: str
    domain: str
    asset_title: str
    ferocious_specific_summary: str
    audience_size: int
    created_at: str
    used_in_concepts: tuple[str, ...] = field(default_factory=lambda: ())
    retired_at: str | None = None

    def __post_init__(self) -> None:
        wc = len(self.ferocious_specific_summary.split())
        if wc > SUMMARY_MAX_WORDS:
            raise ValueError(
                f"ferocious_specific_summary must be ≤{SUMMARY_MAX_WORDS} words; got {wc}"
            )


# ── Read / write ──────────────────────────────────────────────────────────────


def load_kb(path: Path = DEFAULT_KB_PATH) -> list[KbAsset]:
    """Read every row from the KB JSONL into KbAsset instances."""
    if not path.exists():
        return []
    rows: list[KbAsset] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        data = json.loads(line)
        rows.append(
            KbAsset(
                asset_id=data["asset_id"],
                domain=data["domain"],
                asset_title=data["asset_title"],
                ferocious_specific_summary=data["ferocious_specific_summary"],
                audience_size=int(data["audience_size"]),
                created_at=data["created_at"],
                used_in_concepts=tuple(data.get("used_in_concepts", ())),
                retired_at=data.get("retired_at"),
            )
        )
    return rows


def record_asset(
    asset: KbAsset,
    used_in: str | None = None,
    *,
    path: Path = DEFAULT_KB_PATH,
) -> None:
    """Append one asset row. If `used_in` is given, the row's used_in_concepts
    starts with [used_in]; otherwise the caller is registering a fresh asset.
    """
    row_dict = asdict(asset)
    if used_in:
        row_dict["used_in_concepts"] = list(set([*row_dict["used_in_concepts"], used_in]))
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(path, row_dict)


# ── Search (lightweight TF-style overlap; no sentence-transformers needed) ──


def _tokenize(text: str) -> set[str]:
    """Lowercase split → set of word tokens (>= _TOKEN_MIN_LEN chars)."""
    return {tok.lower() for tok in text.split() if len(tok) >= _TOKEN_MIN_LEN}


def search(
    query: str, top_k: int = DEFAULT_TOP_K, *, path: Path = DEFAULT_KB_PATH
) -> list[KbAsset]:
    """Rank KB rows by token-overlap with query; return top_k non-retired rows.

    Uses a simple Jaccard-style token overlap rather than embeddings to keep
    this module dependency-free. `pipeline.bridge` provides the
    sentence-transformers semantic retrieval when richer ranking is needed.
    """
    rows = load_kb(path)
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    scored: list[tuple[float, KbAsset]] = []
    for row in rows:
        if row.retired_at is not None:
            continue
        haystack = f"{row.asset_title} {row.ferocious_specific_summary} {row.domain}"
        h_tokens = _tokenize(haystack)
        if not h_tokens:
            continue
        intersection = q_tokens & h_tokens
        union = q_tokens | h_tokens
        score = len(intersection) / len(union)
        if score > 0.0:
            scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1].asset_id))
    return [row for _score, row in scored[:top_k]]


# ── Retire ────────────────────────────────────────────────────────────────────


def retire_overused(
    threshold: int = DEFAULT_USE_THRESHOLD,
    *,
    path: Path = DEFAULT_KB_PATH,
) -> int:
    """Mark all rows with use_count > threshold as retired (in-place rewrite).

    Returns the number of rows newly retired. Rewrites the JSONL atomically
    via `pipeline.state.safe_write` so a kill -9 mid-rewrite leaves the
    original intact (ADR-0001).
    """
    rows = load_kb(path)
    if not rows:
        return 0
    now = datetime.now(UTC).isoformat()
    newly_retired = 0
    rewritten: list[dict[str, object]] = []
    for row in rows:
        if row.retired_at is None and len(row.used_in_concepts) > threshold:
            row_dict = asdict(row)
            row_dict["retired_at"] = now
            rewritten.append(row_dict)
            newly_retired += 1
        else:
            rewritten.append(asdict(row))
    if newly_retired > 0:
        body = "\n".join(json.dumps(d, ensure_ascii=False) for d in rewritten) + "\n"
        safe_write(path, body)
    return newly_retired


# ── CLI ───────────────────────────────────────────────────────────────────────


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Knowledge KB CLI")
    parser.add_argument("--search", type=str, default=None, help="Token-overlap query")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--retire-overused",
        action="store_true",
        help=f"Retire assets used >threshold (default {DEFAULT_USE_THRESHOLD})",
    )
    parser.add_argument("--threshold", type=int, default=DEFAULT_USE_THRESHOLD)
    parser.add_argument("--kb-path", type=Path, default=DEFAULT_KB_PATH)
    args = parser.parse_args(argv)

    if args.search:
        hits = search(args.search, top_k=args.top_k, path=args.kb_path)
        for h in hits:
            print(f"{h.asset_id}\t{h.domain}\t{h.asset_title}")
        return 0
    if args.retire_overused:
        n = retire_overused(threshold=args.threshold, path=args.kb_path)
        print(f"retired {n} asset(s)")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
