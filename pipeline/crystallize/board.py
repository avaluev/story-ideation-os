"""pipeline.crystallize.board — CrystalBoard schema + serialization.

Holds the persistent sidecar that captures one ``--problem + --themes``
exploration run: N candidate seeds, their score vectors, comp matches,
greatness sub-scores, cluster assignments, and a cluster summary.

Schema is documented in the user-approved plan
(``~/.claude/plans/i-need-to-see-graceful-moler.md``) under
"crystal_board.json — Schema".

All disk I/O routes through ``pipeline.state.safe_write`` (atomic rename).

MUST NOT import LLM clients. MUST NOT import from frameworks/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pipeline.state import safe_write


def _empty_dict_list() -> list[dict[str, Any]]:
    return []


def _empty_str_list() -> list[str]:
    return []


def _empty_str_any_dict() -> dict[str, Any]:
    return {}


def _empty_candidate_list() -> list[Candidate]:
    return []


def _empty_cluster_summary_list() -> list[ClusterSummary]:
    return []


_SLUG_MAX_LEN: int = 40
_TS_FMT: str = "%Y-%m-%dT%H%M"


def _slugify(text: str, max_len: int = _SLUG_MAX_LEN) -> str:
    """ASCII-lowercase + hyphen slug, capped at ``max_len`` chars.

    Empty / whitespace-only input → "untitled" so the board_id is never
    just a timestamp.
    """
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not base:
        return "untitled"
    return base[:max_len].rstrip("-") or "untitled"


def make_board_id(problem: str, *, ts: datetime | None = None) -> str:
    """Generate a deterministic board id like ``2026-05-22-T1700-ai-trust``."""
    timestamp = (ts or datetime.now(UTC)).strftime(_TS_FMT)
    return f"{timestamp}-{_slugify(problem)}"


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One scored compound seed inside a crystal board."""

    candidate_id: str
    rng_seed: int
    compound_seed: dict[str, Any]
    score_vector: dict[str, Any]
    crystallization_score: float
    cluster_id: int
    cluster_name: str
    comps: list[dict[str, Any]] = field(default_factory=_empty_dict_list)
    derivative_distance: float = 1.0
    corpus_grounded_audience_overlap_M: float | None = None
    query_genres: list[str] = field(default_factory=_empty_str_list)
    greatness: dict[str, Any] = field(default_factory=_empty_str_any_dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rng_seed": self.rng_seed,
            "compound_seed": self.compound_seed,
            "score_vector": self.score_vector,
            "crystallization_score": self.crystallization_score,
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "comps": self.comps,
            "derivative_distance": self.derivative_distance,
            "corpus_grounded_audience_overlap_M": self.corpus_grounded_audience_overlap_M,
            "query_genres": self.query_genres,
            "greatness": self.greatness,
        }


# ---------------------------------------------------------------------------
# ClusterSummary
# ---------------------------------------------------------------------------


@dataclass
class ClusterSummary:
    cluster_id: int
    cluster_name: str
    n_members: int
    avg_crystallization_score: float
    avg_corpus_roi: float | None
    top_candidate_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "n_members": self.n_members,
            "avg_crystallization_score": self.avg_crystallization_score,
            "avg_corpus_roi": self.avg_corpus_roi,
            "top_candidate_id": self.top_candidate_id,
        }


# ---------------------------------------------------------------------------
# CrystalBoard
# ---------------------------------------------------------------------------


@dataclass
class CrystalBoard:
    board_id: str
    problem: str
    themes: list[str]
    n_requested: int
    n_generated: int
    generated_at: str  # ISO-8601 UTC
    runtime_seconds: float
    candidates: list[Candidate] = field(default_factory=_empty_candidate_list)
    clusters: list[ClusterSummary] = field(default_factory=_empty_cluster_summary_list)
    cluster_collapse: bool = False
    corpus_size: int = 0
    checklist_version: str = "0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "problem": self.problem,
            "themes": self.themes,
            "n_requested": self.n_requested,
            "n_generated": self.n_generated,
            "generated_at": self.generated_at,
            "runtime_seconds": self.runtime_seconds,
            "candidates": [c.to_dict() for c in self.candidates],
            "clusters": [s.to_dict() for s in self.clusters],
            "cluster_collapse": self.cluster_collapse,
            "corpus_size": self.corpus_size,
            "checklist_version": self.checklist_version,
        }

    def write(self, path: Path) -> None:
        """Atomically write the board as JSON to ``path``."""
        safe_write(path, json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CrystalBoard:
        """Round-trip a previously persisted board (for tests + future tooling)."""
        raw_candidates = cast("list[dict[str, Any]]", d.get("candidates") or [])
        raw_clusters = cast("list[dict[str, Any]]", d.get("clusters") or [])
        return cls(
            board_id=str(d.get("board_id", "")),
            problem=str(d.get("problem", "")),
            themes=[str(t) for t in cast("list[Any]", d.get("themes") or [])],
            n_requested=int(d.get("n_requested", 0)),
            n_generated=int(d.get("n_generated", 0)),
            generated_at=str(d.get("generated_at", "")),
            runtime_seconds=float(d.get("runtime_seconds", 0.0)),
            candidates=[_candidate_from_dict(c) for c in raw_candidates],
            clusters=[_cluster_summary_from_dict(c) for c in raw_clusters],
            cluster_collapse=bool(d.get("cluster_collapse", False)),
            corpus_size=int(d.get("corpus_size", 0)),
            checklist_version=str(d.get("checklist_version", "0.0")),
        )


def _candidate_from_dict(d: dict[str, Any]) -> Candidate:
    return Candidate(
        candidate_id=str(d.get("candidate_id", "")),
        rng_seed=int(d.get("rng_seed", 0)),
        compound_seed=dict(d.get("compound_seed") or {}),
        score_vector=dict(d.get("score_vector") or {}),
        crystallization_score=float(d.get("crystallization_score", 0.0)),
        cluster_id=int(d.get("cluster_id", 0)),
        cluster_name=str(d.get("cluster_name", "")),
        comps=list(d.get("comps") or []),
        derivative_distance=float(d.get("derivative_distance", 1.0)),
        corpus_grounded_audience_overlap_M=(
            float(d["corpus_grounded_audience_overlap_M"])
            if d.get("corpus_grounded_audience_overlap_M") is not None
            else None
        ),
        query_genres=list(d.get("query_genres") or []),
        greatness=dict(d.get("greatness") or {}),
    )


def _cluster_summary_from_dict(d: dict[str, Any]) -> ClusterSummary:
    roi_val = d.get("avg_corpus_roi")
    return ClusterSummary(
        cluster_id=int(d.get("cluster_id", 0)),
        cluster_name=str(d.get("cluster_name", "")),
        n_members=int(d.get("n_members", 0)),
        avg_crystallization_score=float(d.get("avg_crystallization_score", 0.0)),
        avg_corpus_roi=float(roi_val) if roi_val is not None else None,
        top_candidate_id=(
            str(d["top_candidate_id"]) if d.get("top_candidate_id") is not None else None
        ),
    )


# ---------------------------------------------------------------------------
# Cluster-summary builder
# ---------------------------------------------------------------------------


def build_cluster_summaries(
    candidates: list[Candidate],
    cluster_sizes: list[int],
    cluster_id_to_name: dict[int, str],
) -> list[ClusterSummary]:
    """Aggregate per-cluster stats from candidate list + size vector."""
    summaries: list[ClusterSummary] = []
    by_cluster: dict[int, list[Candidate]] = {i: [] for i in range(len(cluster_sizes))}
    for c in candidates:
        by_cluster.setdefault(c.cluster_id, []).append(c)

    for cid, size in enumerate(cluster_sizes):
        members = by_cluster.get(cid, [])
        if members:
            avg_cryst = sum(m.crystallization_score for m in members) / len(members)
            roi_vals: list[float] = []
            for m in members:
                for film in m.comps:
                    r = film.get("roi")
                    if isinstance(r, (int, float)):
                        roi_vals.append(float(r))
            avg_roi: float | None = sum(roi_vals) / len(roi_vals) if roi_vals else None
            top = max(members, key=lambda m: m.crystallization_score)
            top_id: str | None = top.candidate_id
        else:
            avg_cryst = 0.0
            avg_roi = None
            top_id = None
        summaries.append(
            ClusterSummary(
                cluster_id=cid,
                cluster_name=cluster_id_to_name.get(cid, f"cluster_{cid}"),
                n_members=size,
                avg_crystallization_score=avg_cryst,
                avg_corpus_roi=avg_roi,
                top_candidate_id=top_id,
            )
        )
    return summaries


__all__ = [
    "Candidate",
    "ClusterSummary",
    "CrystalBoard",
    "build_cluster_summaries",
    "make_board_id",
]
