"""scripts/ru_pipeline.py — deterministic referee for the Claude-native RU translation pipeline.

The LLM work (mine terms / translate / judge) is done by Workflow subagents
(Haiku / Sonnet / Opus); this module is the **deterministic spine** they hang on
(ADR-0001 file-state, ADR-0002 no-LLM-verdicts, ADR-0011 $-frozen). It NEVER calls
a model and NEVER needs an API key.

It owns four things, all file-backed so work is resumable and every task is a file:

  1. PROTECT / RESTORE — swap every ru_parity-counted heading marker, URL and $-token
     for an inert ``@@H#@@`` / ``@@U#@@`` / ``@@D#@@`` sentinel the translator copies
     verbatim, so url + $ + heading parity is GUARANTEED, not hoped for.
  2. GLOSSARY — a shared, growing EN->RU termbase every stream reads (for consistency)
     and Opus updates (canonical decisions only). ``render_glossary_block`` emits the
     "use these exact RU renderings" block injected into every translator prompt.
  3. TASKS — one ``_ru_tasks/NN_slug.task.json`` per card tracking each stage's status,
     model, parity result and judge verdict; ``status`` aggregates remaining work.
  4. APPLY — restore a translator's output, run ``ru_parity.check_parity`` (the gate),
     write the RU card only on pass, and stamp the task file either way.

CLI (run by the orchestrator between Workflow phases):
    uv run python -m scripts.ru_pipeline init
    uv run python -m scripts.ru_pipeline status
    uv run python -m scripts.ru_pipeline prompt   --card 04_tremor      # -> payload + store
    uv run python -m scripts.ru_pipeline apply     --card 04_tremor --ru agent_out.md
    uv run python -m scripts.ru_pipeline glossary-merge --decisions opus_canonical.json
    uv run python -m scripts.ru_pipeline glossary-block                  # -> the prompt block
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.veracity.render_inline import _MONEY_RE  # noqa: E402  exact $-token def (ADR-0011)
from scripts.ru_parity import _LINK_RE, check_parity  # noqa: E402  exact url def + the gate

AMP = ROOT / "outputs" / "portfolio" / "amplified"
EN_DIR = AMP / "EN"
RU_DIR = AMP / "RU"
TASKS_DIR = AMP / "_ru_tasks"
GLOSSARY_DIR = AMP / "_glossary"
GLOSSARY_PATH = GLOSSARY_DIR / "terms_en_ru.json"
PROPOSALS_DIR = GLOSSARY_DIR / "proposals"

_HEADING_LINE_RE = re.compile(r"^(#{1,6})([ \t])", re.MULTILINE)
_STAGES = ("mine", "translate", "parity", "judge")

#: Bootstrap canonical terms so the very first card is already consistent. Opus +
#: the Haiku miners grow this; merge_canonical only ever upserts canonical decisions.
SEED_TERMS: dict[str, dict[str, str]] = {
    "logline": {"ru": "логлайн", "domain": "format"},
    "tagline": {"ru": "слоган", "domain": "format"},
    "worldwide gross": {"ru": "мировые сборы", "domain": "boxoffice"},
    "box office": {"ru": "кассовые сборы", "domain": "boxoffice"},
    "production budget": {"ru": "производственный бюджет", "domain": "finance"},
    "limited series": {"ru": "мини-сериал", "domain": "format"},
    "animated feature": {"ru": "полнометражный анимационный фильм", "domain": "format"},
    "feature film": {"ru": "полнометражный фильм", "domain": "format"},
    "addressable market": {"ru": "адресный рынок", "domain": "finance"},
    "revenue thesis": {"ru": "обоснование доходности", "domain": "finance"},
    "investor multiple": {"ru": "инвестиционный мультипликатор", "domain": "finance"},
    "theatrical window": {"ru": "кинотеатральное окно", "domain": "finance"},
    "comparable": {"ru": "сопоставимый проект", "domain": "finance"},
    "obtainable revenue": {"ru": "достижимая выручка", "domain": "finance"},
    "breakeven": {"ru": "точка безубыточности", "domain": "finance"},
    "lifetime value": {"ru": "совокупная выручка за весь срок", "domain": "finance"},
    "four-quadrant": {"ru": "для всех четырёх зрительских квадрантов", "domain": "marketing"},
}


# --------------------------------------------------------------------------- #
# Protect / restore (validated this session) — guarantees url + $ + heading parity
# --------------------------------------------------------------------------- #


def protect(md: str) -> tuple[str, dict[str, str]]:
    """Swap every ru_parity-counted heading marker, URL and $-token for a sentinel."""
    store: dict[str, str] = {}
    n = [0]

    def _head(m: re.Match[str]) -> str:
        key = f"@@H{n[0]}@@"
        n[0] += 1
        store[key] = m.group(1)  # the #..###### marker -> restored verbatim
        return f"{key}{m.group(2)}"

    out = _HEADING_LINE_RE.sub(_head, md)

    def _url(m: re.Match[str]) -> str:
        url = m.group(1)
        key = f"@@U{n[0]}@@"
        n[0] += 1
        store[key] = url
        return m.group(0).replace(url, key, 1)

    out = _LINK_RE.sub(_url, out)

    def _money(m: re.Match[str]) -> str:
        key = f"@@D{n[0]}@@"
        n[0] += 1
        store[key] = m.group(0)
        return key

    out = _MONEY_RE.sub(_money, out)
    return out, store


def restore(md: str, store: dict[str, str]) -> str:
    for key, val in store.items():
        md = md.replace(key, val)
    return md


# --------------------------------------------------------------------------- #
# Glossary — the shared, growing EN->RU termbase
# --------------------------------------------------------------------------- #


def load_glossary() -> dict[str, Any]:
    if GLOSSARY_PATH.exists():
        return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return {"version": 0, "updated_at": None, "terms": {}}


def save_glossary(g: dict[str, Any]) -> None:
    GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    GLOSSARY_PATH.write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")


def seed_glossary() -> dict[str, Any]:
    g = load_glossary()
    for en, meta in SEED_TERMS.items():
        g["terms"].setdefault(
            en.lower(), {"en": en, "ru": meta["ru"], "domain": meta["domain"], "status": "seed"}
        )
    g["version"] = max(1, int(g.get("version", 0)))
    save_glossary(g)
    return g


def save_proposals(slug: str, proposals: list[dict[str, str]]) -> None:
    """Persist a card's RAW mined proposals (pre-canonicalization, Haiku output)."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    (PROPOSALS_DIR / f"{slug}.json").write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def merge_canonical(decisions: list[dict[str, str]]) -> dict[str, Any]:
    """Upsert Opus-canonicalized EN->RU decisions into the termbase; bump version."""
    g = load_glossary()
    changed = 0
    for d in decisions:
        en = str(d.get("en", "")).strip()
        ru = str(d.get("ru", "")).strip()
        if not en or not ru:
            continue
        key = en.lower()
        cur = g["terms"].get(key)
        if not cur or cur.get("ru") != ru:
            g["terms"][key] = {
                "en": en,
                "ru": ru,
                "domain": str(d.get("domain", "")),
                "status": "canonical",
            }
            changed += 1
    if changed:
        g["version"] = int(g.get("version", 0)) + 1
    save_glossary(g)
    return g


def render_glossary_block(g: dict[str, Any] | None = None, limit: int = 400) -> str:
    """Emit the mandatory-terminology block injected into every translator prompt."""
    g = g or load_glossary()
    rows = sorted(g.get("terms", {}).values(), key=lambda t: t["en"].lower())[:limit]
    lines = [
        f"ОБЯЗАТЕЛЬНАЯ ТЕРМИНОЛОГИЯ (glossary v{g.get('version', 0)} — "
        "используйте эти переводы дословно, согласованно во всех отчётах):"
    ]
    lines += [f"  - {t['en']} → {t['ru']}" for t in rows]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Tasks — one file per card
# --------------------------------------------------------------------------- #


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _new_task(slug: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "en_path": _rel(EN_DIR / f"{slug}_EN.md"),
        "ru_path": _rel(RU_DIR / f"{slug}_RU.md"),
        "status": "pending",
        "stages": {
            "mine": {"status": "pending", "model": "haiku", "terms_proposed": 0},
            "translate": {"status": "pending", "model": "sonnet", "attempts": 0},
            "parity": {"status": "pending", "url_ok": None, "money_ok": None, "heading_ok": None},
            "judge": {"status": "pending", "model": "opus", "verdict": None, "score": None},
        },
        "glossary_version_used": None,
        "tokens": {"haiku": 0, "sonnet": 0, "opus": 0},
        "updated_at": None,
    }


def task_path(slug: str) -> Path:
    return TASKS_DIR / f"{slug}.task.json"


def load_task(slug: str) -> dict[str, Any]:
    return json.loads(task_path(slug).read_text(encoding="utf-8"))


def save_task(task: dict[str, Any]) -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_path(task["slug"]).write_text(
        json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def all_slugs() -> list[str]:
    return [c.stem.replace("_EN", "") for c in sorted(EN_DIR.glob("[0-9]*_EN.md"))]


def init_tasks() -> int:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for slug in all_slugs():
        if not task_path(slug).exists():
            save_task(_new_task(slug))
            n += 1
    write_index()
    return n


def write_index() -> None:
    rows = []
    for slug in all_slugs():
        if not task_path(slug).exists():
            continue
        t = load_task(slug)
        st = {k: v["status"] for k, v in t["stages"].items()}
        rows.append(
            f"| {slug} | {t['status']} | {st['mine']} | {st['translate']} | "
            f"{st['parity']} | {st['judge']} |"
        )
    body = [
        "# RU translation — task board",
        "",
        "One file per card under `_ru_tasks/`. Statuses: pending → in_progress → done/blocked.",
        "",
        "| card | overall | mine(haiku) | translate(sonnet) | parity | judge(opus) |",
        "|---|---|---|---|---|---|",
        *rows,
    ]
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    (TASKS_DIR / "INDEX.md").write_text("\n".join(body) + "\n", encoding="utf-8")


def status_board() -> dict[str, int]:
    counts: dict[str, int] = {"pending": 0, "done": 0, "blocked": 0, "in_progress": 0}
    for slug in all_slugs():
        if task_path(slug).exists():
            counts[load_task(slug).get("status", "pending")] = (
                counts.get(load_task(slug).get("status", "pending"), 0) + 1
            )
    return counts


# --------------------------------------------------------------------------- #
# Per-card prompt + apply
# --------------------------------------------------------------------------- #


def card_prompt(slug: str) -> Path:
    """Protect the EN card + attach the glossary block -> the translator payload.

    Writes ``_ru_tasks/<slug>.payload.md`` (what the Sonnet agent translates) and
    ``_ru_tasks/<slug>.store.json`` (the sentinel map ``apply`` restores from).
    """
    en = (EN_DIR / f"{slug}_EN.md").read_text(encoding="utf-8")
    protected, store = protect(en)
    g = load_glossary()
    payload = f"{render_glossary_block(g)}\n\n----- BEGIN MARKDOWN TO TRANSLATE -----\n{protected}"
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    (TASKS_DIR / f"{slug}.payload.md").write_text(payload, encoding="utf-8")
    (TASKS_DIR / f"{slug}.store.json").write_text(
        json.dumps(store, ensure_ascii=False), encoding="utf-8"
    )
    t = load_task(slug)
    t["glossary_version_used"] = g.get("version", 0)
    t["stages"]["mine"]["status"] = "done" if g.get("version", 0) else "pending"
    save_task(t)
    return TASKS_DIR / f"{slug}.payload.md"


def apply_translation(slug: str, ru_text: str) -> dict[str, Any]:
    """Restore sentinels, run the parity gate, write RU on pass, stamp the task."""
    store = json.loads((TASKS_DIR / f"{slug}.store.json").read_text(encoding="utf-8"))
    ru_text = re.sub(r"^```(?:markdown)?\s*\n|\n```\s*$", "", ru_text.strip())
    ru_md = restore(ru_text, store)
    en = (EN_DIR / f"{slug}_EN.md").read_text(encoding="utf-8")
    parity = check_parity(en, ru_md)
    t = load_task(slug)
    t["stages"]["translate"]["attempts"] += 1
    t["stages"]["parity"].update(
        {
            "status": "pass" if parity.passed else "fail",
            "url_ok": parity.url_ok,
            "money_ok": parity.money_ok,
            "heading_ok": parity.heading_ok,
            "mismatches": parity.mismatches[:8],
        }
    )
    if parity.passed:
        RU_DIR.mkdir(parents=True, exist_ok=True)
        (RU_DIR / f"{slug}_RU.md").write_text(ru_md, encoding="utf-8")
        (RU_DIR / f"{slug}_RU.FAILED.md").unlink(missing_ok=True)
        t["stages"]["translate"]["status"] = "done"
        t["status"] = "in_progress"  # awaits judge
    else:
        RU_DIR.mkdir(parents=True, exist_ok=True)
        (RU_DIR / f"{slug}_RU.FAILED.md").write_text(ru_md, encoding="utf-8")
    save_task(t)
    write_index()
    return {"slug": slug, "passed": parity.passed, "mismatches": parity.mismatches[:8]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _resolve(card: str) -> str:
    slugs = all_slugs()
    if card.isdigit():
        i = int(card) - 1
        if not 0 <= i < len(slugs):
            raise SystemExit(f"--card {card} out of range (1..{len(slugs)})")
        return slugs[i]
    want = card.replace("_EN", "").replace(".md", "")
    for s in slugs:
        if s == want:
            return s
    raise SystemExit(f"no card matches {card!r}")


def _cmd_init(_: argparse.Namespace) -> int:
    seed_glossary()
    n = init_tasks()
    print(
        f"seeded glossary v{load_glossary()['version']} ({len(SEED_TERMS)} terms); "
        f"created {n} task files in {TASKS_DIR.relative_to(ROOT)}/"
    )
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    print("remaining-work board:", status_board())
    write_index()
    print(f"see {(TASKS_DIR / 'INDEX.md').relative_to(ROOT)}")
    return 0


def _cmd_prompt(args: argparse.Namespace) -> int:
    out = card_prompt(_resolve(args.card))
    print(f"payload -> {out.relative_to(ROOT)} (+ store.json)")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    ru = Path(args.ru).read_text(encoding="utf-8")
    r = apply_translation(_resolve(args.card), ru)
    print(f"{r['slug']}: parity {'PASS' if r['passed'] else 'FAIL'} {r['mismatches']}")
    return 0 if r["passed"] else 1


def _cmd_glossary_merge(args: argparse.Namespace) -> int:
    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
    g = merge_canonical(decisions if isinstance(decisions, list) else [])
    print(f"glossary now v{g['version']} ({len(g['terms'])} terms)")
    return 0


def _cmd_glossary_block(_: argparse.Namespace) -> int:
    print(render_glossary_block())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.ru_pipeline", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="scaffold task files + seed glossary + INDEX").set_defaults(
        func=_cmd_init
    )
    sub.add_parser("status", help="print the remaining-work board").set_defaults(func=_cmd_status)
    sp = sub.add_parser("prompt", help="protect EN + glossary -> translator payload")
    sp.add_argument("--card", required=True)
    sp.set_defaults(func=_cmd_prompt)
    sa = sub.add_parser("apply", help="restore + parity gate -> write RU + stamp task")
    sa.add_argument("--card", required=True)
    sa.add_argument("--ru", required=True, help="file with the agent's RU markdown")
    sa.set_defaults(func=_cmd_apply)
    sm = sub.add_parser("glossary-merge", help="upsert Opus canonical EN->RU decisions")
    sm.add_argument("--decisions", required=True, help="JSON list of {en,ru,domain}")
    sm.set_defaults(func=_cmd_glossary_merge)
    sub.add_parser("glossary-block", help="emit the current glossary prompt block").set_defaults(
        func=_cmd_glossary_block
    )
    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
