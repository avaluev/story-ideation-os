"""API key manager for the Anomaly Engine.

Provides a single resolution path for all external API keys used by the pipeline.
Accepts both the internal key names (OPENROUTER_KEY_PAID) and the common
developer names (OPENROUTER_API_KEY) so that either naming convention works.

OpenRouter resolution order (first non-empty value wins):
    OPENROUTER_KEY_PAID   → internal name (legacy)
    OPENROUTER_API_KEY    → common name (standard)
    OPENROUTER_KEY_FREE_1 → free-tier fallback 1
    OPENROUTER_KEY_FREE_2 → free-tier fallback 2

TMDB resolution (all configured keys returned for client-side rotation):
    TMDB_API_KEY         → v3 primary key
    TMDB_KEY_1..N        → v3 rotation slots (round-robin in client)
    TMDB_READ_TOKEN      → v4 Bearer token (preferred when present)

Usage (CLI)::

    uv run python -m pipeline.key_manager diagnose

Usage (Python)::

    from pipeline.key_manager import resolve_openrouter_key, diagnose
    key = resolve_openrouter_key()   # raises KeyError if not found
    diagnose()                        # prints masked status to stdout
"""

from __future__ import annotations

import os
import pathlib
import sys

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:
    pass

# ── Key name registry ─────────────────────────────────────────────────────────

# Each entry: (primary_env_var, fallback_env_var, description, required)
_KEY_SPECS: list[tuple[str, str | None, str, bool]] = [
    (
        "OPENROUTER_KEY_PAID",
        "OPENROUTER_API_KEY",
        "OpenRouter paid key (1000 calls/day) — optional fallback since 302.ai is primary",
        False,
    ),
    (
        "OPENROUTER_KEY_FREE_1",
        None,
        "OpenRouter free key slot 1 (50 calls/day)",
        False,
    ),
    (
        "OPENROUTER_KEY_FREE_2",
        None,
        "OpenRouter free key slot 2 (50 calls/day)",
        False,
    ),
    (
        "TMDB_API_KEY",
        None,
        "TMDB v3 API key (primary)",
        False,
    ),
    (
        "TMDB_KEY_1",
        None,
        "TMDB v3 rotation slot 1",
        False,
    ),
    (
        "TMDB_KEY_2",
        None,
        "TMDB v3 rotation slot 2",
        False,
    ),
    (
        "TMDB_READ_TOKEN",
        None,
        "TMDB v4 Read Access Token (Bearer)",
        False,
    ),
    (
        "TAO_AI_API_KEY",
        None,
        "302.ai unified key — PRIMARY provider (Perplexity/Firecrawl/Jina/Exa/SerpApi)",
        False,
    ),
    # ── Evidence Router providers (direct keys — used when 302.ai is absent) ──
    (
        "EXA_API_KEY",
        None,
        "Exa direct key (search + fetch) — evidence router fallback",
        False,
    ),
    (
        "SERPER_API_KEY",
        None,
        "Serper.dev key (Google search) — evidence router fallback",
        False,
    ),
    (
        "JINA_API_KEY",
        None,
        "Jina Reader/Search key — evidence router fallback (optional; works without key)",
        False,
    ),
    (
        "AIML_API_KEY",
        None,
        "AIML API key (chat completions via api.aimlapi.com) — evidence router provider",
        False,
    ),
]

# Slot prefix scanned for additional TMDB v3 keys (TMDB_KEY_3, TMDB_KEY_4, ...).
_TMDB_KEY_PREFIX: str = "TMDB_KEY_"
_TMDB_PRIMARY: str = "TMDB_API_KEY"
_TMDB_BEARER: str = "TMDB_READ_TOKEN"
_TMDB_MAX_SLOTS: int = 16  # safety ceiling on the rotation scan

_MASK_LEN: int = 9  # expose prefix only: 'sk-or-v1-'


# ── Key resolution ────────────────────────────────────────────────────────────


def _mask(key: str) -> str:
    if len(key) > _MASK_LEN:
        return key[:_MASK_LEN] + "..." + f"({len(key)} chars)"
    return key


def resolve_openrouter_key() -> str:
    """Return the paid OpenRouter key, checking both env var names.

    Raises:
        KeyError: if neither OPENROUTER_KEY_PAID nor OPENROUTER_API_KEY is set.
    """
    primary, fallback, _, _ = _KEY_SPECS[0]
    value = os.environ.get(primary) or os.environ.get(fallback or "", "")
    if not value:
        raise KeyError(
            "No OpenRouter API key found.\n"
            "Set one of these in your .env file:\n"
            "  OPENROUTER_KEY_PAID=sk-or-v1-...\n"
            "  OPENROUTER_API_KEY=sk-or-v1-...\n"
            "Get your key at: https://openrouter.ai/settings/keys"
        )
    return value


def resolve_302ai_key() -> str:
    """Return the 302.ai API key from TAO_AI_API_KEY env var.

    302.ai exposes Perplexity, Firecrawl, Jina, Exa, and SerpApi behind a
    single Bearer key.  The env var is named TAO_AI_API_KEY (302 ≈ "tao").

    Raises:
        KeyError: if TAO_AI_API_KEY is not set or is empty after stripping.
    """
    value = os.environ.get("TAO_AI_API_KEY", "").strip()
    if not value:
        raise KeyError(
            "TAO_AI_API_KEY not set\n"
            "Set it in your .env file:\n"
            "  TAO_AI_API_KEY=<your-302.ai-api-key>\n"
            "Get your key at: https://302.ai"
        )
    return value


def resolve_exa_key() -> str:
    """Return the Exa direct API key from EXA_API_KEY env var.

    Used by the evidence router when 302.ai is absent or over-budget.

    Raises:
        KeyError: if EXA_API_KEY is not set or is empty after stripping.
    """
    value = os.environ.get("EXA_API_KEY", "").strip()
    if not value:
        raise KeyError(
            "EXA_API_KEY not set\n"
            "Set it in your .env file:\n"
            "  EXA_API_KEY=<your-exa-api-key>\n"
            "Get your key at: https://exa.ai"
        )
    return value


def resolve_serper_key() -> str:
    """Return the Serper.dev API key from SERPER_API_KEY env var.

    Used by the evidence router for Google search results.

    Raises:
        KeyError: if SERPER_API_KEY is not set or is empty after stripping.
    """
    value = os.environ.get("SERPER_API_KEY", "").strip()
    if not value:
        raise KeyError(
            "SERPER_API_KEY not set\n"
            "Set it in your .env file:\n"
            "  SERPER_API_KEY=<your-serper-key>\n"
            "Get your key at: https://serper.dev"
        )
    return value


def resolve_jina_key() -> str:
    """Return the Jina Reader/Search key from JINA_API_KEY env var.

    Jina works without a key (rate-limited); the key unlocks higher quotas.
    Returns an empty string (tolerant) when the env var is absent, so callers
    can omit the Authorization header gracefully.

    Returns:
        The configured Jina API key, or ``""`` if not set.
    """
    return os.environ.get("JINA_API_KEY", "").strip()


def resolve_aiml_key() -> str:
    """Return the AIML API key from AIML_API_KEY env var.

    Used by the evidence router for chat completions via api.aimlapi.com.

    Raises:
        KeyError: if AIML_API_KEY is not set or is empty after stripping.
    """
    value = os.environ.get("AIML_API_KEY", "").strip()
    if not value:
        raise KeyError(
            "AIML_API_KEY not set\n"
            "Set it in your .env file:\n"
            "  AIML_API_KEY=<your-aiml-api-key>\n"
            "Get your key at: https://aimlapi.com"
        )
    return value


def get_free_keys() -> list[str]:
    """Return any configured OpenRouter free-tier keys (may be empty list)."""
    result: list[str] = []
    for slot in ("OPENROUTER_KEY_FREE_1", "OPENROUTER_KEY_FREE_2"):
        val = os.environ.get(slot, "")
        if val:
            result.append(val)
    return result


# ── TMDB resolution ───────────────────────────────────────────────────────────


def resolve_tmdb_keys() -> list[str]:
    """Return every configured TMDB v3 API key, in rotation order.

    Order: ``TMDB_API_KEY`` (primary), then ``TMDB_KEY_1``, ``TMDB_KEY_2``, …
    up to ``_TMDB_MAX_SLOTS``. Empty values are skipped. Duplicates are
    de-duplicated while preserving first occurrence so a single key declared
    under two aliases does not skew rotation.
    """
    seen: set[str] = set()
    ordered: list[str] = []

    primary = os.environ.get(_TMDB_PRIMARY, "").strip()
    if primary and primary not in seen:
        ordered.append(primary)
        seen.add(primary)

    for i in range(1, _TMDB_MAX_SLOTS + 1):
        val = os.environ.get(f"{_TMDB_KEY_PREFIX}{i}", "").strip()
        if val and val not in seen:
            ordered.append(val)
            seen.add(val)
    return ordered


def resolve_tmdb_bearer() -> str | None:
    """Return the configured TMDB v4 Read Access Token, or ``None``."""
    val = os.environ.get(_TMDB_BEARER, "").strip()
    return val or None


# ── Diagnostics ───────────────────────────────────────────────────────────────


def diagnose() -> dict[str, object]:
    """Check key availability and print a masked status report.

    Returns a dict with key_name → status pairs suitable for logging.
    """
    report: dict[str, object] = {}
    all_ok = True

    print("\n── API Key Diagnostics ───────────────────────────────────────")
    for primary, fallback, description, required in _KEY_SPECS:
        value = os.environ.get(primary) or os.environ.get(fallback or "", "")
        found_via = ""
        if os.environ.get(primary):
            found_via = primary
        elif fallback and os.environ.get(fallback):
            found_via = fallback

        if value:
            status = f"✓ FOUND via {found_via}: {_mask(value)}"
        elif required:
            label = f"{primary} or {fallback}" if fallback else primary
            status = f"✗ MISSING  (set {label} in .env)"
            all_ok = False
        else:
            status = "- not set  (optional)"

        print(f"  {description}")
        print(f"    {status}")
        report[primary] = {"found": bool(value), "via": found_via, "required": required}

    tmdb_keys = resolve_tmdb_keys()
    bearer = resolve_tmdb_bearer()
    print("  TMDB rotation pool (auto-scanned: TMDB_KEY_3…16)")
    if tmdb_keys or bearer:
        print(f"    ✓ {len(tmdb_keys)} v3 key(s), v4 bearer {'present' if bearer else 'absent'}")
    else:
        print("    - not set  (only blocks TMDB corpus expansion script)")
    report["TMDB_ROTATION_POOL_SIZE"] = {"found": bool(tmdb_keys), "count": len(tmdb_keys)}
    report["TMDB_V4_BEARER"] = {"found": bool(bearer)}

    # At least one chat provider must be present. 302.ai is PRIMARY; OpenRouter
    # is an optional fallback. PASS requires either.
    or_present = bool(os.environ.get("OPENROUTER_KEY_PAID") or os.environ.get("OPENROUTER_API_KEY"))
    tao_present = bool(os.environ.get("TAO_AI_API_KEY", "").strip())
    chat_ok = or_present or tao_present
    all_ok = all_ok and chat_ok
    report["CHAT_PROVIDER"] = {
        "found": chat_ok,
        "primary": "302.ai" if tao_present else ("openrouter" if or_present else None),
    }

    print()
    if all_ok:
        provider = "302.ai" if tao_present else "OpenRouter"
        print(f"  Result: PASS — chat provider present ({provider} primary)")
    else:
        print("  Result: FAIL — no chat provider key found")
        print()
        print("  Set the 302.ai key (the primary provider) in .env:")
        print("    TAO_AI_API_KEY=sk-...        # get it at https://302.ai")
        print("  OpenRouter is an optional fallback: OPENROUTER_API_KEY=sk-or-v1-...")
        print("  Then re-run: uv run python -m pipeline.key_manager diagnose")
    print("────────────────────────────────────────────────────────────\n")

    report["overall"] = "PASS" if all_ok else "FAIL"
    return report


def diagnose_302() -> bool:
    """Live one-call smoke test of the 302.ai chat endpoint (Perplexity sonar-pro).

    Builds a TaoAIClient from ``TAO_AI_API_KEY`` and sends a tiny JSON-only chat
    request through the model-id map (``perplexity/sonar-pro`` -> ``sonar-pro``).
    Prints an OK/FAIL line. Returns True on a parseable response.

    The operator's proof that the 302.ai key + endpoint + model id all work before
    the pipeline depends on them. Costs one sonar call (~5-15s).
    """
    print("\n── 302.ai chat smoke (perplexity/sonar-pro) ──────────────────")
    try:
        from pipeline.research.client_302ai import TaoAIClient  # noqa: PLC0415

        client = TaoAIClient.from_env()
    except KeyError as exc:
        print(f"  ✗ FAIL — {exc}")
        print("────────────────────────────────────────────────────────────\n")
        return False

    try:
        result = client.chat(
            model="perplexity/sonar-pro",
            messages=[{"role": "user", "content": 'Reply with JSON {"ok": true}. No prose.'}],
            json_mode=True,
            max_tokens=128,
        )
    except Exception as exc:
        print(f"  ✗ FAIL — 302.ai chat error: {exc!s:.160}")
        print("  If this is a model-id error, set TAO_AI_MODEL_OVERRIDES in .env, e.g.")
        print('       TAO_AI_MODEL_OVERRIDES={"perplexity/sonar-pro": "sonar-pro"}')
        print("────────────────────────────────────────────────────────────\n")
        return False

    print(f"  ✓ OK — 302.ai chat returned: {str(result)[:120]}")
    print("────────────────────────────────────────────────────────────\n")
    return True


# ── .env.example generator ────────────────────────────────────────────────────


def generate_env_example(path: str = ".env.example") -> None:
    """Write a .env.example template documenting all key names.

    Safe to run: never overwrites an existing .env file.
    """
    lines = [
        "# Anomaly Engine — environment variables",
        "# Copy this file to .env and fill in real values.",
        "# NEVER commit .env to git.",
        "",
        "# ── OpenRouter API keys ─────────────────────────────────",
        "# Get your key at: https://openrouter.ai/settings/keys",
        "#",
        "# Use EITHER name — the pipeline accepts both:",
        "OPENROUTER_API_KEY=sk-or-v1-your-key-here",
        "# OPENROUTER_KEY_PAID=sk-or-v1-your-key-here  # alternative name",
        "",
        "# Optional free-tier keys (50 calls/day each)",
        "# OPENROUTER_KEY_FREE_1=",
        "# OPENROUTER_KEY_FREE_2=",
        "",
        "# ── 302.ai unified key (PRIMARY provider) ───────────────",
        "# One Bearer key exposes Perplexity, Firecrawl, Jina, Exa, SerpApi.",
        "# Get your key at: https://302.ai  — this is the primary evidence provider.",
        "TAO_AI_API_KEY=sk-...",
        "# Force 302.ai-first routing even if an OpenRouter key is still present:",
        "TAO_AI_PRIMARY=1",
        "# Optional: correct a model id if 302.ai's catalog differs from defaults:",
        '# TAO_AI_MODEL_OVERRIDES={"perplexity/sonar-pro": "sonar-pro"}',
        "",
        "# ── Evidence Router providers ───────────────────────────",
        "# Direct API keys for search/fetch gateways used when 302.ai is absent",
        "# or over-budget.  All four are optional — the router falls back gracefully.",
        "#",
        "# Exa (search + full-text fetch):",
        "# EXA_API_KEY=",
        "#",
        "# Serper.dev (Google search results):",
        "# SERPER_API_KEY=",
        "#",
        "# Jina Reader/Search (free without key; key unlocks higher quota):",
        "# JINA_API_KEY=",
        "#",
        "# AIML API (chat completions via api.aimlapi.com):",
        "# AIML_API_KEY=",
        "# Force AIML as the primary chat provider:",
        "# AIML_PRIMARY=1",
        "# Optional: limit concurrent evidence-router requests:",
        "# RESEARCH_MAX_CONCURRENCY=4",
        "# Optional: remap a model id if AIML's catalog differs from defaults:",
        '# AIML_MODEL_OVERRIDES={"perplexity/sonar-pro": "sonar-pro"}',
        "",
        "# ── TMDB API keys ───────────────────────────────────────",
        "# Get a v3 key or v4 Read Access Token at: https://www.themoviedb.org/settings/api",
        "# Only needed for scripts/corpus/expand_from_tmdb.py.",
        "#",
        "# v3 primary key (round-robin pool):",
        "# TMDB_API_KEY=",
        "# TMDB_KEY_1=",
        "# TMDB_KEY_2=",
        "#",
        "# v4 Read Access Token (preferred when set):",
        "# TMDB_READ_TOKEN=",
        "",
    ]

    target = pathlib.Path(path)
    if target.name == ".env":
        print(f"Refusing to overwrite {path} — use a .example file instead.")
        return
    target.write_text("\n".join(lines))
    print(f"Written: {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "diagnose"
    if command == "diagnose":
        result = diagnose()
        if result.get("overall") != "PASS":
            sys.exit(1)
    elif command == "diagnose-302":
        ok = diagnose_302()
        sys.exit(0 if ok else 1)
    elif command == "gen-example":
        generate_env_example(".env.example")
    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m pipeline.key_manager [diagnose|diagnose-302|gen-example]")
        sys.exit(1)


if __name__ == "__main__":
    main()
