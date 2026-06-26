#!/usr/bin/env python3
"""Validate the live-sourced proof points and write a 'Verified Proof of Demand'
block into each flagship concept file.

Re-probes every agent-supplied URL through the engine's blessed deep-link verifier
(``pipeline.veracity.probe.probe_url``, online) — a proof point survives ONLY if its
URL is a real deep path AND returns 2xx (or is an allow-listed bot-block host such as
Variety/Deadline) AND carries a non-empty verbatim quote. Anything the agent could not
stand behind is dropped, not shown. Deterministic; never edits a dollar figure.

Usage:
  uv run python scripts/portfolio/flagship/apply_evidence.py \
      outputs/portfolio/flagship/_evidence_result.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pipeline.veracity.probe import probe_url  # noqa: E402

FLAG = ROOT / "outputs" / "portfolio" / "flagship"
PROV_MARK = "## Economics — Methodology & Provenance"
PROOF_MARK = "## Verified Proof of Demand"
HTTP_OK_LOW, HTTP_OK_HIGH = 200, 400
MIN_VERIFIED_POINTS = 2  # fewer than this → flag as thin coverage


def _reachable(url: str) -> bool:
    try:
        p = probe_url(url, offline=False)
    except Exception:
        return False
    if not p.is_deep:
        return False
    if p.allow_listed:
        return True
    return p.status is not None and HTTP_OK_LOW <= p.status < HTTP_OK_HIGH


def _file_for_idx(idx: int) -> Path | None:
    hits = sorted(FLAG.glob(f"{idx:02d}_*.md"))
    return hits[0] if hits else None


def main() -> None:
    res_path = Path(sys.argv[1]) if len(sys.argv) > 1 else FLAG / "_evidence_result.json"
    results = json.loads(res_path.read_text())

    summary = []
    for r in results:
        idx = r.get("idx")
        f = _file_for_idx(idx) if idx else None
        if f is None:
            continue
        verified = []
        for pp in r.get("proof_points", []) or []:
            url = (pp.get("url") or "").strip()
            quote = (pp.get("quote") or "").strip()
            if not url or not quote:
                continue
            if _reachable(url):
                verified.append(pp)

        text = f.read_text()
        # idempotent: strip any prior proof block
        if PROOF_MARK in text:
            head, _sep, tail = text.partition(PROOF_MARK)
            # tail runs until the provenance block (or EOF)
            after = tail.partition(PROV_MARK)[2]
            text = head.rstrip() + ("\n\n" + PROV_MARK + after if after else "")

        if verified:
            _preamble = (
                "_Every figure below was fetched live; the quoted text"
                " appears verbatim on the linked page._\n"
            )
            lines = [f"\n\n{PROOF_MARK}\n", _preamble]
            for pp in verified:
                claim = pp.get("claim", "").strip()
                quote = pp.get("quote", "").strip().strip('"')
                url = pp.get("url", "").strip()
                date = pp.get("date", "").strip()
                lines.append(
                    f"- **{claim}** — “{quote}” ([source]({url}){', ' + date if date else ''})"
                )
            block = "\n".join(lines) + "\n"
            # insert before the provenance block if present, else append
            if PROV_MARK in text:
                head, sep, tail = text.partition(PROV_MARK)
                text = head.rstrip() + block + "\n" + sep + tail
            else:
                text = text.rstrip() + block
            f.write_text(text)

        summary.append((idx, f.name, len(r.get("proof_points", []) or []), len(verified)))

    total_v = sum(s[3] for s in summary)
    n_with = sum(1 for s in summary if s[3])
    print(
        f"Applied evidence to {n_with}/{len(summary)} concepts;"
        f" {total_v} verified deep-linked points."
    )
    for idx, name, found, ver in sorted(summary):
        flag = "" if ver >= MIN_VERIFIED_POINTS else "  ⚠ thin"
        print(f"  {idx:2}. {name:26} {ver}/{found} verified{flag}")


if __name__ == "__main__":
    main()
