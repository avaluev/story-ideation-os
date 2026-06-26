"""scripts/top_ideas.py — surface the top-N most powerful ideas from the leaderboard.

Reads data/leaderboard.jsonl, ranks by combined_quality = crystallization_score *
genius_score (pure mechanical aggregation — no operator taste injected), and writes
two paired deliverables:

  data/top_ideas_<YYYY-MM-DD>.md   — scannable in 60 seconds, one row per idea
  data/top_ideas_<YYYY-MM-DD>.csv  — spreadsheet-friendly, identical ordering

For each idea: rank, combined_quality, crystallization, genius, SOM ($M), world,
moral wager, top comp (title + gross), axes triple, run_id, has_narrator flag
(true iff a *-NARRATOR.md file already exists under runs/<slug>/).

Why combined_quality = crystallization * genius:
  - Both are bounded in [0, 1].
  - The product is high only when BOTH are high (no compensating one weakness with
    another strength).
  - It is purely mechanical: neither term depends on operator ratings.

Run:
  uv run python scripts/top_ideas.py             # default top 20
  uv run python scripts/top_ideas.py --top 50    # custom top-N
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

DEFAULT_TOP_N = 20
_LEADERBOARD_JSONL = Path("data/leaderboard.jsonl")
_RUNS_ROOT = Path("runs")
_OUT_DIR = Path("data")
_MAX_WORLD_LEN = 60
_MAX_WAGER_LEN = 120


def _load_leaderboard() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _LEADERBOARD_JSONL.open(encoding="utf-8") as f:
        for raw in f:
            stripped = raw.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows


def _combined_quality(row: dict[str, Any]) -> float:
    crystal = float(row.get("crystallization_score", 0.0) or 0.0)
    genius = float(row.get("genius_score", 0.0) or 0.0)
    return crystal * genius


def _has_narrator(run_id: str) -> tuple[bool, str | None]:
    """Return (exists, relative_path) for any NARRATOR.md under runs/<run_id>/.

    Evolve-style runs (runs/evolve-*/) typically do NOT carry NARRATOR.md.
    Legacy May-11..21 runs DO. Both paths checked.
    """
    candidate_dir = _RUNS_ROOT / run_id
    if candidate_dir.exists():
        for narrator in candidate_dir.glob("*NARRATOR.md"):
            return True, str(narrator)
    return False, None


def _truncate(text: str | None, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _top_comp_title(row: dict[str, Any]) -> str:
    comps = row.get("top_comps") or []
    if not comps:
        return ""
    return str(comps[0].get("title") or "")


def _top_comp_gross_m(row: dict[str, Any]) -> float:
    comps = row.get("top_comps") or []
    if not comps:
        return 0.0
    gross_usd = comps[0].get("ww_gross_usd")
    if gross_usd is None:
        return 0.0
    return round(float(gross_usd) / 1_000_000.0, 1)


def _som_m(row: dict[str, Any]) -> float:
    som_usd = row.get("som_y1_usd")
    if som_usd is None:
        return 0.0
    return round(float(som_usd) / 1_000_000.0, 1)


def _rank(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = [(_combined_quality(row), row) for row in rows]
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for rank, (quality, row) in enumerate(scored[:top_n], start=1):
        run_id = str(row.get("run_id") or "")
        has_narr, narr_path = _has_narrator(run_id)
        axes = row.get("axes_triple") or []
        axes_str = " + ".join(str(a) for a in axes) if isinstance(axes, list) else str(axes)
        out.append(
            {
                "rank": rank,
                "run_id": run_id,
                "combined_quality": round(quality, 4),
                "crystallization_score": round(
                    float(row.get("crystallization_score", 0.0) or 0.0), 4
                ),
                "genius_score": round(float(row.get("genius_score", 0.0) or 0.0), 4),
                "som_y1_m": _som_m(row),
                "world": _truncate(row.get("world"), _MAX_WORLD_LEN),
                "moral_wager": _truncate(row.get("moral_wager"), _MAX_WAGER_LEN),
                "top_comp": _top_comp_title(row),
                "top_comp_gross_m": _top_comp_gross_m(row),
                "axes_triple": axes_str,
                "cluster_label": str(row.get("cluster_label") or ""),
                "has_narrator": has_narr,
                "narrator_path": narr_path or "",
            }
        )
    return out


def _write_csv(ranked: list[dict[str, Any]], out_path: Path) -> None:
    fieldnames = list(ranked[0].keys()) if ranked else []
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in ranked:
            writer.writerow(row)


def _write_md(ranked: list[dict[str, Any]], out_path: Path, today: str) -> None:
    lines: list[str] = []
    lines.append(f"# Top {len(ranked)} Most Powerful Ideas ({today})")
    lines.append("")
    lines.append(
        "Ranked by `combined_quality = crystallization_score * genius_score` — "
        "pure mechanical aggregation, no operator taste."
    )
    lines.append("")
    lines.append(
        f"Source: `{_LEADERBOARD_JSONL}` ({len(_load_leaderboard())} total rows). "
        f"Cross-referenced against `runs/<slug>/*NARRATOR.md`."
    )
    lines.append("")
    has_narr_count = sum(1 for r in ranked if r["has_narrator"])
    lines.append(
        f"**NARRATOR.md status:** {has_narr_count} / {len(ranked)} of the "
        f"top {len(ranked)} have an existing investor doc; "
        f"the remaining {len(ranked) - has_narr_count} are evolve-stage candidates "
        "(operator decision to escalate via `/single-idea` or `/loop-engine`)."
    )
    lines.append("")
    lines.append(
        "| # | Quality | Crystal | Genius | SOM ($M) | World | Top Comp ($M) | Axes | NAR? |"
    )
    lines.append("|---|---:|---:|---:|---:|---|---|---|:---:|")
    for r in ranked:
        narr = "✅" if r["has_narrator"] else "—"
        top_comp = f"{r['top_comp']} (${r['top_comp_gross_m']:.0f}M)" if r["top_comp"] else ""
        lines.append(
            "| {rank} | {quality:.3f} | {crystal:.3f} | {genius:.3f} | "
            "{som:.0f} | {world} | {comp} | `{axes}` | {narr} |".format(
                rank=r["rank"],
                quality=r["combined_quality"],
                crystal=r["crystallization_score"],
                genius=r["genius_score"],
                som=r["som_y1_m"],
                world=r["world"],
                comp=top_comp,
                axes=r["axes_triple"],
                narr=narr,
            )
        )
    lines.append("")
    lines.append("## Detailed entries")
    lines.append("")
    for r in ranked:
        lines.append(f"### {r['rank']}. {r['world']}")
        lines.append("")
        lines.append(f"- **Run:** `{r['run_id']}`")
        lines.append(
            f"- **Quality:** combined `{r['combined_quality']:.4f}` "
            f"(crystallization `{r['crystallization_score']:.4f}` * "
            f"genius `{r['genius_score']:.4f}`)"
        )
        lines.append(
            f"- **Year-1 SOM:** ${r['som_y1_m']:.1f}M  "
            f"· Cluster: *{r['cluster_label']}*  "
            f"· Axes: `{r['axes_triple']}`"
        )
        if r["moral_wager"]:
            lines.append(f"- **Wager:** {r['moral_wager']}")
        if r["top_comp"]:
            lines.append(
                f"- **Top comp:** {r['top_comp']} (${r['top_comp_gross_m']:.1f}M worldwide)"
            )
        if r["has_narrator"]:
            lines.append(f"- **Investor doc:** `{r['narrator_path']}`")
        else:
            lines.append(
                "- **Investor doc:** *not yet rendered* "
                "(operator can promote via `/single-idea` or `/loop-engine`)"
            )
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Number of ideas to surface (default {DEFAULT_TOP_N}).",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=dt.date.today().isoformat(),
        help="Date stamp used in output filenames (default today).",
    )
    args = parser.parse_args()

    rows = _load_leaderboard()
    if not rows:
        msg = f"Leaderboard {_LEADERBOARD_JSONL} is empty"
        raise SystemExit(msg)

    ranked = _rank(rows, args.top)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _OUT_DIR / f"top_ideas_{args.date}.md"
    csv_path = _OUT_DIR / f"top_ideas_{args.date}.csv"

    _write_md(ranked, md_path, args.date)
    _write_csv(ranked, csv_path)

    print(
        f"top_ideas: {len(ranked)} ideas → {md_path} + {csv_path} "
        f"(from {len(rows)} leaderboard rows)"
    )


if __name__ == "__main__":
    main()
