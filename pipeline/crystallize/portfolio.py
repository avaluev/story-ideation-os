"""pipeline.crystallize.portfolio — diversified MULTI-CONCEPT portfolio selection.

The v5.2 superset of the single-best-per-format slate
(:mod:`scripts.build_format_slate`). Where the slate keeps the top-1 concept
per format, the portfolio keeps the top-K *distinct* concepts per format and
assigns *distinct* comps across the whole slate — fixing the two visible
weaknesses a sophisticated investor catches in the prior pack:

  1. duplicate worlds / wounds across cards (here: rejected at selection time);
  2. the same four comps reused on every card (here: greedily de-duplicated).

Pure ranking + de-dup logic only. No LLM, no network, no engine calls — the
orchestration script (:mod:`scripts.build_portfolio`) supplies already-scored
candidate dicts whose every number is produced upstream by python_executed
economics (ADR-0002 / ADR-0011). Subject to the ANOMALY-001 LLM-client import
ban (scripts/lint_imports.py).
"""

from __future__ import annotations

import copy
import re
from typing import Any, cast

#: The four narrative axes that define a concept's identity. Two concepts that
#: share all four are the *same* idea; two that share a world OR a wound read as
#: duplicates on the page even when the other axes differ.
DEDUP_AXES: tuple[str, ...] = (
    "world_texture",
    "sdt_wound",
    "structural_inversion",
    "moral_fault_line",
)

#: Default axes a portfolio must not visibly repeat within a single format.
DEFAULT_DISTINCT_ON: tuple[str, ...] = ("world_texture", "sdt_wound")

#: Hosts that are never acceptable as an evidence source (search redirects).
_BANNED_HOSTS: frozenset[str] = frozenset(
    {
        "google.com",
        "bing.com",
        "duckduckgo.com",
        "search.brave.com",
        "yandex.com",
        "yahoo.com",
    }
)

#: An https URL needs more than this many slashes to have a path beyond the host.
_MIN_DEEP_PATH_SLASHES = 2


def _axis_id(concept: dict[str, Any], axis: str) -> str:
    """Read an axis value-id from ``concept['seed_axes'][axis]`` or, failing
    that, the top-level ``concept[axis]`` (a raw ``CompoundSeedResult`` dict)."""
    src_raw: Any = concept.get("seed_axes")
    src: dict[str, Any] = cast("dict[str, Any]", src_raw) if isinstance(src_raw, dict) else concept
    node_raw: Any = src.get(axis)
    if not isinstance(node_raw, dict):
        return ""
    node = cast("dict[str, Any]", node_raw)
    return str(node.get("id", ""))


def dedup_axis_key(concept: dict[str, Any]) -> tuple[str, ...]:
    """Stable identity tuple ``(world, wound, inversion, fault)`` for a concept."""
    return tuple(_axis_id(concept, a) for a in DEDUP_AXES)


def is_deep_path(url: str) -> bool:
    """True only for an https URL with a real path beyond the host and a host
    that is not a search engine (deep-link evidence policy)."""
    if not url.startswith("https://"):
        return False
    rest = url[len("https://") :]
    # Measure path depth on the PATH ONLY — a query string or fragment must never
    # count as a path segment. A bare domain like https://example.com/?utm=x is not
    # a deep link, even though the trailing-slash-before-"?" would inflate the count.
    path_only = rest.split("?", 1)[0].split("#", 1)[0]
    host = path_only.split("/", 1)[0].lower()
    bare = host[4:] if host.startswith("www.") else host
    if bare in _BANNED_HOSTS:
        return False
    return ("https://" + path_only).rstrip("/").count("/") > _MIN_DEEP_PATH_SLASHES


def select_topk_distinct(
    candidates: list[dict[str, Any]],
    k: int,
    *,
    distinct_on: tuple[str, ...] = DEFAULT_DISTINCT_ON,
    seen: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Return the top-``k`` candidates by ``crystallization_score`` (descending),
    skipping any candidate whose value on ANY axis in ``distinct_on`` already
    appears in a kept candidate — or in the pre-claimed ``seen`` set.

    Guarantees no two selected concepts share a world or a wound (the visible-
    duplication failure modes), so a same-format trio reads as three ideas, not
    one idea three times.

    ``seen`` pre-populates the claimed axis-values (e.g. world_textures already
    used by earlier formats) so distinctness holds ACROSS the whole slate, not
    only within one call. The caller's ``seen`` is never mutated; thread it by
    unioning the returned winners' axis-ids after each call.
    """
    initial = seen or {}
    claimed: dict[str, set[str]] = {a: set(initial.get(a, ())) for a in distinct_on}
    out: list[dict[str, Any]] = []
    ordered = sorted(
        candidates,
        key=lambda c: float(c.get("crystallization_score", 0.0)),
        reverse=True,
    )
    for c in ordered:
        ids = {a: _axis_id(c, a) for a in distinct_on}
        if any(ids[a] and ids[a] in claimed[a] for a in distinct_on):
            continue
        out.append(c)
        for a in distinct_on:
            if ids[a]:
                claimed[a].add(ids[a])
        if len(out) >= k:
            break
    return out


def select_top_by_som(
    candidates: list[dict[str, Any]],
    n: int,
    *,
    distinct_on: tuple[str, ...] = DEFAULT_DISTINCT_ON,
    max_per_format: int | None = None,
    seen: dict[str, set[str]] | None = None,
    format_key: str = "economics_key",
) -> list[dict[str, Any]]:
    """Top-``n`` candidates by python-executed ``som_y1_usd`` (descending),
    enforcing the same world/wound distinctness as :func:`select_topk_distinct`
    plus an optional per-format cap.

    This is the *max-credible-economics* selection mode. ``select_topk_distinct``
    keeps a fixed quota per format (breadth-first); this ranks every candidate
    across all formats at once on the actual Year-1 SOM, so the slate's headline
    numbers are as large as the engine can defensibly support — while
    ``max_per_format`` stops it collapsing into a single format and ``distinct_on``
    still guarantees no two cards share a world or a wound. Every SOM is
    python_executed (ADR-0011), so ranking on it never trusts an LLM number.

    The caller's ``seen`` is never mutated.
    """
    initial = seen or {}
    claimed: dict[str, set[str]] = {a: set(initial.get(a, ())) for a in distinct_on}
    fmt_count: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    ordered = sorted(
        candidates,
        key=lambda c: float(c.get("som_y1_usd", 0.0) or 0.0),
        reverse=True,
    )
    for c in ordered:
        ids = {a: _axis_id(c, a) for a in distinct_on}
        if any(ids[a] and ids[a] in claimed[a] for a in distinct_on):
            continue
        fmt = str(c.get(format_key, ""))
        if max_per_format is not None and fmt_count.get(fmt, 0) >= max_per_format:
            continue
        out.append(c)
        for a in distinct_on:
            if ids[a]:
                claimed[a].add(ids[a])
        fmt_count[fmt] = fmt_count.get(fmt, 0) + 1
        if len(out) >= n:
            break
    return out


def assign_distinct_comps(
    concepts: list[dict[str, Any]],
    *,
    k: int = 4,
    max_reuse: int = 2,
) -> list[dict[str, Any]]:
    """Return *new* concept dicts whose ``comps`` are de-duplicated across the
    whole portfolio.

    Two passes over each concept's similarity-ordered comp pool:

      * **Pass 1 (exclusive):** claim a comp only if no other concept has it yet
        (``usage == 0``), up to ``k``. This gives every card a unique lead set.
      * **Pass 2 (fill):** for concepts still short of ``k``, claim comps with
        ``usage < max_reuse`` — limited reuse only when the matched pool is too
        thin to fill ``k`` distinct slots.

    Similarity order is preserved within each card. Input dicts are never
    mutated (immutability: deep-copied output).
    """
    usage: dict[str, int] = {}
    work = [copy.deepcopy(c) for c in concepts]
    chosen: list[list[dict[str, Any]]] = [[] for _ in work]

    def _title(comp: dict[str, Any]) -> str:
        return str(comp.get("title", "")).strip()

    def _claim_pass(reuse_ceiling: int) -> None:
        """One pass: each short card claims pool comps whose global usage is
        below ``reuse_ceiling`` (use a huge ceiling for the guaranteed fill)."""
        for i, c in enumerate(work):
            if len(chosen[i]) >= k:
                continue
            already = {_title(x) for x in chosen[i]}
            for comp in list(c.get("comps") or []):
                if len(chosen[i]) >= k:
                    break
                t = _title(comp)
                if not t or t in already or usage.get(t, 0) >= reuse_ceiling:
                    continue
                chosen[i].append(comp)
                usage[t] = usage.get(t, 0) + 1
                already.add(t)

    _claim_pass(1)  # Pass 1 — exclusive: a unique lead set per card.
    _claim_pass(max_reuse)  # Pass 2 — limited reuse when the matched pool is thin.
    _claim_pass(len(work) + 1)  # Pass 3 — guarantee k; never empty/short cards.

    for i, c in enumerate(work):
        c["comps"] = chosen[i]
    return work


def validate_demand_evidence(row: dict[str, Any]) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a single demand-evidence row.

    A row is investor-grade only when it carries a non-empty ``claim`` and
    ``stat`` and a deep-path ``source_url`` (the "direct link of demand" the
    operator requires). Bare domains, search redirects and missing URLs fail.
    """
    if not str(row.get("claim", "")).strip():
        return (False, "missing claim")
    if not str(row.get("stat", "")).strip():
        return (False, "missing stat")
    url = str(row.get("source_url", "")).strip()
    if not url:
        return (False, "missing source_url")
    if not is_deep_path(url):
        return (False, f"source_url not a deep path: {url}")
    return (True, "ok")


# --------------------------------------------------------------------------- #
# Cross-slate title distinctiveness + review-fix application (v5.2 P5)
# --------------------------------------------------------------------------- #

#: Tokens too generic to carry a title's identity, so "The Quiet Wing" and
#: "The Quiet Archive" collide on "quiet", not on the shared "the".
_TITLE_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "into",
        "over",
        "under",
        "this",
        "that",
    }
)

#: A salient title token must be at least this long (drops "of", initials, "&").
_MIN_TITLE_TOKEN_LEN = 3


def _singularize(word: str) -> str:
    """Crudely fold a trailing plural ``s`` so 'Hours' and 'Hour' collide."""
    if len(word) > _MIN_TITLE_TOKEN_LEN and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _concept_title(concept: dict[str, Any]) -> str:
    """The shipped title: the enrichment title if present, else the raw title."""
    enr_raw: Any = concept.get("enrichment")
    if isinstance(enr_raw, dict):
        t = str(cast("dict[str, Any]", enr_raw).get("title", "")).strip()
        if t:
            return t
    return str(concept.get("title", "") or concept.get("working_title", "")).strip()


def _title_tokens(title: str, stopwords: frozenset[str] = _TITLE_STOPWORDS) -> set[str]:
    """Salient, singularised, lowercased tokens that define a title's identity."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {_singularize(w) for w in words if w not in stopwords and len(w) >= _MIN_TITLE_TOKEN_LEN}


def title_overlap_clusters(
    concepts: list[dict[str, Any]],
    *,
    stopwords: frozenset[str] = _TITLE_STOPWORDS,
) -> list[list[str]]:
    """Return one cluster of concept ids per salient token shared by >1 title.

    Two titles collide when they share any salient token (singularised, so
    'Hour' and 'Hours' collide; stop-words like 'the' are ignored). The slate
    reads as distinct exactly when this returns ``[]`` — the mechanical truth
    the cross-slate distinctiveness eval enforces. Clusters are ordered by the
    colliding token for determinism; ids within a cluster keep input order.
    """
    token_to_ids: dict[str, list[str]] = {}
    for c in concepts:
        cid = str(c.get("id", ""))
        for tok in _title_tokens(_concept_title(c), stopwords):
            token_to_ids.setdefault(tok, []).append(cid)
    return [ids for _tok, ids in sorted(token_to_ids.items()) if len(ids) > 1]


def select_titles_to_rename(
    concepts: list[dict[str, Any]],
    *,
    strength_key: str = "crystallization_score",
    stopwords: frozenset[str] = _TITLE_STOPWORDS,
) -> list[str]:
    """Greedily keep the strongest token-distinct set of titles; return the ids
    whose titles must be renamed so the slate becomes token-distinct.

    Concepts are considered strongest-first (by ``strength_key`` descending). A
    title is KEPT when none of its salient tokens are already claimed by a kept
    title; otherwise its id is returned for renaming. This minimises churn — only
    the weaker member of each collision is renamed, never the strongest.
    """
    ordered = sorted(
        concepts,
        key=lambda c: float(c.get(strength_key, 0.0) or 0.0),
        reverse=True,
    )
    claimed: set[str] = set()
    to_rename: list[str] = []
    for c in ordered:
        toks = _title_tokens(_concept_title(c), stopwords)
        if toks & claimed:
            to_rename.append(str(c.get("id", "")))
        else:
            claimed |= toks
    return to_rename


def apply_review_fixes(
    enriched: dict[str, Any],
    *,
    renames: dict[str, str] | None = None,
    dropped_urls: dict[str, list[str]] | None = None,
    dropped_ids: list[str] | None = None,
    min_demand_rows: int = 3,
) -> dict[str, Any]:
    """Return a NEW enriched-portfolio dict with adversarial-review fixes applied.

    * ``renames``      — concept id -> new title (written to BOTH
      ``concept['title']`` and ``concept['enrichment']['title']``).
    * ``dropped_urls`` — concept id -> ``source_url`` strings to remove from that
      concept's ``demand_evidence`` (the dead / shallow links the review flagged).
    * ``dropped_ids``  — concepts to drop from the slate entirely.

    Never mutates the input (deep-copied). Raises :class:`ValueError` if dropping
    URLs would leave a kept concept with fewer than ``min_demand_rows`` rows — the
    caller must re-enrich that concept to restore deep-path evidence first.
    """
    renames = renames or {}
    dropped_urls = dropped_urls or {}
    drop_ids = set(dropped_ids or [])
    out = copy.deepcopy(enriched)
    concepts_in = cast("list[dict[str, Any]]", out.get("concepts") or [])
    kept: list[dict[str, Any]] = []
    for c in concepts_in:
        cid = str(c.get("id", ""))
        if cid in drop_ids:
            continue
        new_title = renames.get(cid, "").strip()
        if new_title:
            c["title"] = new_title
            enr_raw: Any = c.get("enrichment")
            if isinstance(enr_raw, dict):
                cast("dict[str, Any]", enr_raw)["title"] = new_title
        urls_to_drop = {u.strip() for u in dropped_urls.get(cid, []) if u.strip()}
        if urls_to_drop:
            rows_in = cast("list[dict[str, Any]]", c.get("demand_evidence") or [])
            rows = [r for r in rows_in if str(r.get("source_url", "")).strip() not in urls_to_drop]
            if len(rows) < min_demand_rows:
                raise ValueError(
                    f"{cid}: dropping {len(urls_to_drop)} url(s) leaves {len(rows)} "
                    f"demand rows (< {min_demand_rows}); re-enrich before dropping."
                )
            c["demand_evidence"] = rows
        kept.append(c)
    out["concepts"] = kept
    out["concept_count"] = len(kept)
    return out


__all__ = [
    "DEDUP_AXES",
    "DEFAULT_DISTINCT_ON",
    "apply_review_fixes",
    "assign_distinct_comps",
    "dedup_axis_key",
    "is_deep_path",
    "select_titles_to_rename",
    "select_topk_distinct",
    "title_overlap_clusters",
    "validate_demand_evidence",
]
