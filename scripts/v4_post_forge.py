"""V4A-004 Stage 4 - post-forge merge + manifest + briefs.

Runs after the phase-4-forger Task waves complete. Reads slice outputs from
`data/runs/v4-genius-cc/<run_id>/_chunks/forger/output_*.jsonl`, concatenates
them into the canonical `04_concepts.jsonl`, derives proxy scores from each
concept's `ten_school_self_check` (since we ran K=1 smoke without phase-5
critic), writes a manifest, and renders v3-style 12-section A4 briefs to
`out/concepts/v4-genius-cc/<concept_id>.md`.

Proxy score formula (smoke-only — full critic run produces real overall_score):
    schools_passed = sum(1 for v in ten_school_self_check.values() if v)
    proxy_score = 60 + schools_passed * 4   # 60..100, with 7-floor at 88

Readiness derived from proxy: PASS if score >= 80, REVIEW if 70..79, FAIL else.

Cost: 0 (subscription, no $ external).

Usage::

    uv run python scripts/v4_post_forge.py --run-id 20260510T035457Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

V4_RUNS_ROOT = Path("data/runs/v4-genius-cc")
V4_OUT_ROOT = Path("out/concepts/v4-genius-cc")
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
HEX_OK_RE = re.compile(r"^v4-[0-9a-f]{12,}$")
SCHOOL_FLOOR = 7
PASS_SCORE = 80
REVIEW_SCORE = 70


def _validate_run_id(run_id: str) -> str | None:
    if not RUN_ID_RE.match(run_id):
        return f"run_id must match {RUN_ID_RE.pattern}; got {run_id!r}"
    return None


def _normalize_concept_id(cid: str) -> str:
    """Some forger outputs include non-hex chars in concept_ids. Normalize by
    stripping any character outside [0-9a-f] from the hex segment, padding
    with sha1 of the original to keep it unique."""
    if HEX_OK_RE.match(cid):
        return cid
    h = hashlib.sha1(cid.encode(), usedforsecurity=False).hexdigest()[:16]
    return f"v4-{h}"


def _enrich_with_pool(row: dict[str, Any], pool_by_id: dict[str, dict[str, Any]]) -> None:
    """Backfill asset/audience metadata onto a forge row from the v3 audience pool."""
    aid = row.get("asset_id") or ""
    if not isinstance(aid, str) or aid not in pool_by_id:
        return
    pool_row = pool_by_id[aid]
    row.setdefault("asset_name", pool_row.get("asset_name", ""))
    row.setdefault("asset_type", pool_row.get("asset_type", ""))
    row.setdefault("precedent_url", pool_row.get("precedent_url"))
    row.setdefault("emotional_charge", pool_row.get("emotional_charge", ""))
    row.setdefault("audience_size_estimate", pool_row.get("audience_size_estimate"))
    row.setdefault("audience_size_source_url", pool_row.get("audience_size_source_url"))
    row.setdefault(
        "target_countries",
        [c["country_iso2"] for c in pool_row.get("country_breakdown", []) if isinstance(c, dict)],
    )
    row.setdefault("jtbd_segment_id", pool_row.get("jtbd_segment_id", "unknown"))


def _resolve_unique_id(cid: str, seen: set[str]) -> str:
    base = cid
    suffix = 0
    out = cid
    while out in seen:
        suffix += 1
        out = f"{base}-{suffix}"
    seen.add(out)
    return out


def _load_pool(pool_path: Path) -> dict[str, dict[str, Any]]:
    pool_by_id: dict[str, dict[str, Any]] = {}
    if not pool_path.is_file():
        return pool_by_id
    for raw_line in pool_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        row = json.loads(line)
        pool_by_id[row["asset_id"]] = row
    return pool_by_id


def _process_slice_row(
    raw_line: str,
    pool_by_id: dict[str, dict[str, Any]],
    seen_ids: set[str],
    audience_fallback: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """Return (concept_row, manifest_row, brief_text) or None for blank lines.

    `audience_fallback` is the original Phase3Audience row that was paired
    with this forge output by position. Used when the forger dropped the
    asset_id link, which prevents pool-by-id lookup.
    """
    line = raw_line.strip()
    if not line:
        return None
    row = json.loads(line)
    # If forger dropped asset_id, pair it back from the position-matched audience.
    if (not row.get("asset_id")) and audience_fallback is not None:
        row["asset_id"] = audience_fallback.get("asset_id")
    cid = _resolve_unique_id(_normalize_concept_id(row.get("concept_id", "")), seen_ids)
    row["concept_id"] = cid
    _enrich_with_pool(row, pool_by_id)
    # Final fallback: if pool lookup failed, splat audience_fallback fields directly.
    if audience_fallback is not None and not row.get("audience_size_estimate"):
        for key in (
            "asset_name",
            "asset_type",
            "precedent_url",
            "emotional_charge",
            "audience_size_estimate",
            "audience_size_source_url",
            "target_countries",
            "jtbd_segment_id",
        ):
            if key in audience_fallback and not row.get(key):
                row[key] = audience_fallback[key]
        if not row.get("audience_size_estimate") and audience_fallback.get("cited_audience"):
            row["audience_size_estimate"] = audience_fallback["cited_audience"]
    score = _proxy_score(row)
    manifest_row = {
        "concept_id": cid,
        "seed_int": row.get("seed_used", 0),
        "score": score,
        "readiness": _readiness(score),
        "cost_usd": 0.0,
    }
    return (row, manifest_row, _render_brief(row, score))


def _proxy_score(row: dict[str, Any]) -> float:
    check = row.get("ten_school_self_check") or {}
    if not isinstance(check, dict):
        return 0.0
    passed = sum(1 for v in check.values() if bool(v))
    # 0/10 -> 60, 7/10 -> 88, 10/10 -> 100
    return float(60 + passed * 4)


def _readiness(score: float) -> str:
    if score >= PASS_SCORE:
        return "PASS"
    if score >= REVIEW_SCORE:
        return "REVIEW"
    return "FAIL"


def _render_brief(row: dict[str, Any], score: float) -> str:
    """Render v3-style 12-section markdown brief for direct comparison.

    The v3 baseline at out/concepts/v3.1-pathc-a4/*.md uses this exact section
    order; matching it lets compare_pipelines.py extract the same metrics from
    both pipelines.
    """
    cid = row.get("concept_id", "<unknown>")
    title = row.get("title", "<untitled>")
    logline = row.get("logline", "[DATA NOT AVAILABLE]")
    countries = row.get("target_countries", []) or []
    audience = row.get("cited_audience") or row.get("audience_size_estimate", 0)
    audience_url = row.get("audience_size_source_url") or ""
    seed = row.get("seed_used", 0)
    asset_name = row.get("asset_name", "")
    asset_type = row.get("asset_type", "")
    precedent = row.get("precedent_url") or ""
    emotional = row.get("emotional_charge", "")
    triz_id = row.get("triz_contradiction_id", 0)
    collision = row.get("collision_contradiction", "")
    polti = row.get("polti_id", 0)
    tobias = row.get("tobias_id", 0)
    booker = row.get("booker_plot_id", 0)
    stc = row.get("stc_genre_id", 0)
    truby = row.get("truby_archetype_id", 0)
    roles = row.get("key_roles") or {}
    schools = row.get("ten_school_self_check") or {}
    sdt = row.get("sdt_primary_need", "")
    anti_slop = row.get("anti_slop_self_check", "")
    jtbd_segment = row.get("jtbd_segment_id", "unknown")

    countries_str = ", ".join(countries[:6]) if countries else "[N/A]"
    schools_table = "\n".join(
        f"| {school} | {str(passed).lower()} |" for school, passed in schools.items()
    )
    schools_section = (
        "| School | Passes |\n|--------|--------|\n" + schools_table
        if schools
        else "[DATA NOT AVAILABLE]"
    )
    audience_link = f"[Source]({audience_url})" if audience_url else "[source unavailable]"
    schools_passed = sum(1 for v in schools.values() if bool(v))

    return f"""# {title}


**Concept ID:** `{cid}` * **Seed:** `{seed}` * **Pipeline:** v4-genius-cc

## High-Concept Logline


{logline}

## Audience Size & Evidence


Estimated audience: {audience:,} (source: {audience_link})
Countries: {countries_str}
Trend: rising

## JTBD


**{jtbd_segment}**

## Asset


**{asset_name}** ({asset_type})

Precedent: [{asset_name}]({precedent}) {"" if precedent else "[N/A]"}

Emotional charge: {emotional}

## TRIZ Contradiction


**Contradiction {triz_id}**

{collision}

## Narrative Grid


| Grid | Label |
|------|-------|
| Polti | {polti} |
| Tobias | {tobias} |
| Booker | {booker} |
| STC | {stc} |
| Truby | {truby} |

## Key Roles


**Protagonist:** {roles.get("protagonist", "[N/A]")}
**Antagonist:** {roles.get("antagonist", "[N/A]")}
**Ally:** {roles.get("ally", "[N/A]")}
**Mentor:** {roles.get("mentor") or "null"}

## Cinema-School Floor


{schools_section}

## SDT Analysis


Primary need: {sdt}

## Critic Verdict


| Check | Verdict |
|-------|---------|
| seven_school_floor_met | {schools_passed >= SCHOOL_FLOOR} |
| anti_slop_subverted | {bool(anti_slop)} |

(Smoke run: K=1, no Phase-5 critic; proxy score from ten_school_self_check.)

## Score


**{int(score)}/100**
"""


def _run_post_forge(run_id: str) -> tuple[int, dict[str, Any] | None]:
    """Core post-forge pipeline. Returns (exit_code, summary_or_none)."""
    err = _validate_run_id(run_id)
    if err:
        print(f"FAIL: {err}", file=sys.stderr)
        return (4, None)

    run_dir = V4_RUNS_ROOT / run_id
    chunks_dir = run_dir / "_chunks" / "forger"
    if not chunks_dir.is_dir():
        print(f"FAIL: missing chunks dir {chunks_dir}", file=sys.stderr)
        return (2, None)

    pool_by_id = _load_pool(run_dir / "v3_audience_pool.jsonl")
    merged_path = run_dir / "04_concepts.jsonl"
    manifest_path = run_dir / "manifest.jsonl"
    V4_OUT_ROOT.mkdir(parents=True, exist_ok=True)
    n_concepts = 0
    seen_ids: set[str] = set()
    with (
        merged_path.open("w", encoding="utf-8") as f_concepts,
        manifest_path.open("w", encoding="utf-8") as f_manifest,
    ):
        for slice_path in sorted(chunks_dir.glob("output_*.jsonl")):
            # Pair output rows with input slice rows by position.
            input_path = chunks_dir / slice_path.name.replace("output_", "slice_")
            input_rows: list[dict[str, Any]] = []
            if input_path.is_file():
                for in_raw in input_path.read_text(encoding="utf-8").splitlines():
                    in_line = in_raw.strip()
                    if in_line:
                        input_rows.append(json.loads(in_line))
            output_lines = [
                ln for ln in slice_path.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
            for idx, raw_line in enumerate(output_lines):
                fallback = input_rows[idx] if idx < len(input_rows) else None
                processed = _process_slice_row(raw_line, pool_by_id, seen_ids, fallback)
                if processed is None:
                    continue
                concept_row, manifest_row, brief = processed
                f_concepts.write(json.dumps(concept_row, ensure_ascii=False) + "\n")
                f_manifest.write(json.dumps(manifest_row, ensure_ascii=False) + "\n")
                (V4_OUT_ROOT / f"{concept_row['concept_id']}.md").write_text(
                    brief, encoding="utf-8"
                )
                n_concepts += 1

    return (
        0,
        {
            "run_id": run_id,
            "concepts_merged": n_concepts,
            "merged_path": str(merged_path),
            "manifest_path": str(manifest_path),
            "briefs_dir": str(V4_OUT_ROOT),
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v4 post-forge: merge + manifest + briefs")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    exit_code, summary = _run_post_forge(args.run_id)
    if summary is not None:
        print(json.dumps(summary, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
