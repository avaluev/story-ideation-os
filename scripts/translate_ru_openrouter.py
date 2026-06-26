"""scripts/translate_ru_openrouter.py — RU translation of the amplified EN cards via OpenRouter.

Operator-requested OpenRouter path (distinct from the AIML `build_translation_client`
Run-D design). Translates every ``outputs/portfolio/amplified/EN/NN_slug_EN.md`` into
professional investor-register Russian and writes ``.../RU/NN_slug_RU.md``.

ADR-0011 / ru_parity integrity is GUARANTEED, not hoped for: before translation every
markdown link URL and every ``$`` token (the exact spans ``scripts.ru_parity`` counts) is
swapped for an inert sentinel (``@@U#@@`` / ``@@D#@@``) the model is told to copy verbatim,
then restored after. So the url-multiset and ``$``-multiset cannot drift. Each card is then
checked with ``ru_parity.check_parity`` and only kept when the 3 hard gates pass.

Key: read from ``OPENROUTER_API_KEY`` in ``.env`` (never logged in full). No Gemini
(campaign guard ``config/campaign_goal.json: no_gemini``); default model is the operator's
``openrouter/fusion`` router.

Usage:
    uv run python scripts/translate_ru_openrouter.py            # all 20, skip done
    uv run python scripts/translate_ru_openrouter.py --only 04_tremor --force
    uv run python scripts/translate_ru_openrouter.py --model deepseek/deepseek-chat-v3-0324
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from pipeline.veracity.render_inline import _MONEY_RE  # noqa: E402  exact $-token def (ADR-0011)
from scripts.ru_parity import _LINK_RE, check_parity  # noqa: E402  exact url def + the gate

load_dotenv()

EN_DIR = ROOT / "outputs" / "portfolio" / "amplified" / "EN"
RU_DIR = ROOT / "outputs" / "portfolio" / "amplified" / "RU"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
# Pinned, predictable, cheap, strong-for-Russian. NOT a router. Earlier a
# router default (openrouter/fusion) silently routed to premium models (Opus) and
# burned real money — never default to a router for bulk work.
DEFAULT_MODEL = "deepseek/deepseek-chat-v3-0324"

_NO_GEMINI = ("gemini", "gemma")  # campaign guard
#: OpenRouter meta-models that route to an UNCONTROLLED (often premium) backend.
#: Refused unless --allow-router is passed, because cost is unpredictable.
_ROUTER_PREFIXES = ("openrouter/",)
_MASK_LEN = 8

SYSTEM = (
    "You are a senior financial translator producing an investor-grade Russian "
    "(профессиональный инвестиционный регистр, третье лицо) version of a film/series "
    "investment memo written in Markdown.\n\n"
    "RULES:\n"
    "1. Translate ALL natural-language prose, heading text, table cells and markdown link "
    "anchor text into fluent professional Russian.\n"
    "2. Preserve the Markdown structure EXACTLY: same tables (same rows/columns), same '>' "
    "blockquotes, same bullet/number lists, same number of lines that begin with a heading token.\n"
    "3. Tokens of the form @@H<n>@@, @@U<n>@@ and @@D<n>@@ are PROTECTED placeholders "
    "(@@H@@ = heading markers, @@U@@ = URLs, @@D@@ = dollar figures). Copy every one VERBATIM, "
    "unchanged, in the SAME place — each @@H<n>@@ MUST stay at the very start of its own line. "
    "Never translate, reorder, merge, drop, space-out or invent these tokens. The FIRST line is "
    "the document title (a @@H0@@ heading) — you MUST keep it.\n"
    "4. Keep film and company proper names in their original Latin spelling (a short Russian "
    "gloss in parentheses is fine on first mention). Do NOT alter numbers, years or percentages.\n"
    "5. Output ONLY the translated Markdown — no preamble, no code fence, no commentary."
)


def _mask(key: str) -> str:
    return key[:_MASK_LEN] + "..." if len(key) > _MASK_LEN else "***"


_HEADING_LINE_RE = re.compile(r"^(#{1,6})([ \t])", re.MULTILINE)


def protect(md: str) -> tuple[str, dict[str, str]]:
    """Swap every ru_parity-counted heading marker, URL and $-token for an inert sentinel."""
    store: dict[str, str] = {}
    counter = [0]

    def _head(m: re.Match[str]) -> str:
        key = f"@@H{counter[0]}@@"
        counter[0] += 1
        store[key] = m.group(1)  # the #..###### marker, restored verbatim -> level+count preserved
        return f"{key}{m.group(2)}"

    out = _HEADING_LINE_RE.sub(_head, md)

    def _url(m: re.Match[str]) -> str:
        url = m.group(1)
        key = f"@@U{counter[0]}@@"
        counter[0] += 1
        store[key] = url
        return m.group(0).replace(url, key, 1)

    out = _LINK_RE.sub(_url, out)

    def _money(m: re.Match[str]) -> str:
        key = f"@@D{counter[0]}@@"
        counter[0] += 1
        store[key] = m.group(0)
        return key

    out = _MONEY_RE.sub(_money, out)
    return out, store


def restore(md: str, store: dict[str, str]) -> str:
    for key, val in store.items():
        md = md.replace(key, val)
    return md


def _call(
    model: str, system: str, user: str, key: str, max_tokens: int = 20000
) -> tuple[str, str, int]:
    """Return (content, model_actually_used, total_tokens). ``allow_fallbacks: False``
    pins the request to *model* so OpenRouter cannot silently substitute another."""
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "provider": {"allow_fallbacks": False},
        }
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 (https endpoint, fixed host)
        ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://filmintel.local",
            "X-Title": "FilmIntel RU translation",
        },
    )
    with urllib.request.urlopen(req, timeout=240) as r:  # noqa: S310
        data = json.load(r)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"no choices in response: {str(data)[:300]}")
    content = choices[0]["message"]["content"]
    used = str(data.get("model", model))
    total = int((data.get("usage") or {}).get("total_tokens", 0) or 0)
    return content.strip(), used, total


def translate_card(en_path: Path, model: str, key: str, attempts: int = 3) -> dict[str, object]:
    slug_stem = en_path.stem.replace("_EN", "")
    ru_path = RU_DIR / f"{slug_stem}_RU.md"
    en_md = en_path.read_text(encoding="utf-8")
    protected, store = protect(en_md)
    last_err = ""
    last_ru: str | None = None
    used = ""
    tokens = 0
    for _ in range(attempts):
        try:
            raw, used, tok = _call(model, SYSTEM, protected, key)
            tokens += tok
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, KeyError) as e:
            last_err = str(e)[:200]
            continue
        # strip any accidental code fence
        raw = re.sub(r"^```(?:markdown)?\s*\n|\n```\s*$", "", raw.strip())
        last_ru = restore(raw, store)
        parity = check_parity(en_md, last_ru)
        if parity.passed:
            RU_DIR.mkdir(parents=True, exist_ok=True)
            ru_path.write_text(last_ru, encoding="utf-8")
            (RU_DIR / f"{slug_stem}_RU.FAILED.md").unlink(missing_ok=True)
            return {
                "slug": slug_stem,
                "ok": True,
                "path": str(ru_path),
                "warnings": len(parity.readability_warnings),
                "model_used": used,
                "tokens": tokens,
            }
        last_err = "; ".join(parity.mismatches[:4]) or "parity failed"
    # keep the last attempt for inspection even on failure
    if last_ru is not None:
        RU_DIR.mkdir(parents=True, exist_ok=True)
        (RU_DIR / f"{slug_stem}_RU.FAILED.md").write_text(last_ru, encoding="utf-8")
    return {"slug": slug_stem, "ok": False, "error": last_err, "model_used": used, "tokens": tokens}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="translate_ru_openrouter")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--only", default="", help="comma-separated slug stems (e.g. 04_tremor)")
    p.add_argument("--force", action="store_true", help="re-translate even if RU exists")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument(
        "--allow-router",
        action="store_true",
        help="permit an openrouter/* router (UNPREDICTABLE premium cost) — off by default",
    )
    args = p.parse_args(argv)

    if any(b in args.model.lower() for b in _NO_GEMINI):
        print(
            f"REFUSED: {args.model} is Gemini-family — banned by campaign guard.", file=sys.stderr
        )
        return 2

    if args.model.startswith(_ROUTER_PREFIXES) and not args.allow_router:
        print(
            f"REFUSED: {args.model!r} is a ROUTER — it routes to an uncontrolled (often premium, "
            f"e.g. Opus) backend and can burn real money fast. Pin a specific cheap model "
            f"(default {DEFAULT_MODEL}) or pass --allow-router to override deliberately.",
            file=sys.stderr,
        )
        return 2

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print(
            "OPENROUTER_API_KEY not set in .env — run scripts/set_env_key.py first.",
            file=sys.stderr,
        )
        return 2
    print(f"model={args.model}  key={_mask(key)}")

    cards = sorted(EN_DIR.glob("[0-9]*_EN.md"))
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        cards = [c for c in cards if c.stem.replace("_EN", "") in want]
    if not args.force:
        cards = [c for c in cards if not (RU_DIR / f"{c.stem.replace('_EN', '')}_RU.md").exists()]
    if not cards:
        print("nothing to translate (all RU files exist; use --force to redo)")
        return 0

    print(f"translating {len(cards)} cards -> {RU_DIR}/")
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(lambda c: translate_card(c, args.model, key), cards):
            tag = "OK " if r["ok"] else "FAIL"
            extra = f"(warnings {r.get('warnings')})" if r["ok"] else f"-> {r.get('error')}"
            mu = r.get("model_used") or "?"
            print(f"  [{tag}] {r['slug']:18s} via {mu} {r.get('tokens', 0)} tok {extra}")
            results.append(r)
    ok = sum(1 for r in results if r["ok"])
    total_tok = sum(t for r in results if isinstance(t := r.get("tokens"), int))
    models_seen = sorted({str(r.get("model_used")) for r in results if r.get("model_used")})
    print(f"\n{ok}/{len(results)} cards passed ru_parity (url + $ + heading).")
    print(f"total tokens this run: {total_tok:,}  | models actually used: {models_seen}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
