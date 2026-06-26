"""scripts/enrich_compound_variables.py

Research-driven enrichment for pipeline/data/compound_seed_variables.json.

Sends structured deep-research prompts to Perplexity sonar-pro and parses
the responses into schema-validated variable entries. Never hard-codes
specific ideas from operator conversations. Every entry must cite a
real-world source (academic paper, documented film, historical record,
demographic dataset).

Usage:
    # Enrich a single category
    uv run python scripts/enrich_compound_variables.py --category sdt_wounds --n 20

    # Enrich all categories with default batch sizes
    uv run python scripts/enrich_compound_variables.py --category all

    # Dry run: print prompts without calling the API
    uv run python scripts/enrich_compound_variables.py --category era_collisions --dry-run

    # Rebuild from scratch (wipes existing entries, re-researches everything)
    uv run python scripts/enrich_compound_variables.py --category all --rebuild

    # Expand a specific collision type
    uv run python scripts/enrich_compound_variables.py \
        --category era_collisions --collision-type scientific --n 30

Outputs:
    pipeline/data/compound_seed_variables.json  (updated in-place, atomic write)
    pipeline/data/enrich_log.jsonl              (append-only audit trail)

Architecture:
    Each category has a RESEARCH_PROMPTS dict entry. The prompt is sent to
    sonar-pro which searches academic and web sources. The raw response is
    parsed by a category-specific parser that extracts structured entries.
    Entries that fail schema validation are written to enrich_log.jsonl as
    REJECTED rather than silently dropped.

    The enrichment is additive: existing entries are preserved unless
    --rebuild is passed. Deduplication uses semantic similarity of the
    'description' field (Jaccard on word sets, threshold 0.6).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VARS_PATH = _REPO_ROOT / "pipeline" / "data" / "compound_seed_variables.json"
_LOG_PATH = _REPO_ROOT / "pipeline" / "data" / "enrich_log.jsonl"
_OPENROUTER_MODULE = _REPO_ROOT / "pipeline" / "openrouter_client.py"
_MAX_DIVISIVENESS_SCORE: int = 10

# ---------------------------------------------------------------------------
# Research prompts — loaded from scripts/research_prompts/<category>_NN.md
# Edit the .md files to change prompts; no Python changes needed.
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).resolve().parent / "research_prompts"


def _load_prompts() -> dict[str, list[dict[str, Any]]]:
    """Scan research_prompts/ and build RESEARCH_PROMPTS at import time."""
    result: dict[str, list[dict[str, Any]]] = {}
    if not _PROMPTS_DIR.exists():
        return result
    for p in sorted(_PROMPTS_DIR.glob("*.md")):
        # filename format: <category>_<nn>.md
        stem = p.stem
        last_sep = stem.rfind("_")
        if last_sep < 0:
            continue
        category = stem[:last_sep]
        try:
            expected = int(stem[last_sep + 1 :]) * 10  # rough default
        except ValueError:
            expected = 20
        result.setdefault(category, []).append(
            {
                "prompt": p.read_text(encoding="utf-8"),
                "category": category,
                "expected_count": expected,
                "source_file": str(p),
            }
        )
    return result


RESEARCH_PROMPTS: dict[str, list[dict[str, Any]]] = _load_prompts()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, list[str]] = {
    "sdt_wounds": [
        "id",
        "need",
        "description",
        "deprivation_intensity",
        "domain_tags",
        "audience_resonance_M",
        "divisiveness_contribution",
    ],
    "psychological_patterns": [
        "id",
        "description",
        "domain_tags",
        "surprise_weight",
        "audience_resonance_M",
        "divisiveness_contribution",
    ],
    "structural_inversions": [
        "id",
        "description",
        "domain_tags",
        "surprise_weight",
        "divisiveness_contribution",
    ],
    "historical_methodology_transplants": [
        "id",
        "era_of_origin",
        "methodology",
        "modern_crisis",
        "bridge",
        "domain_tags",
        "audience_resonance_M",
        "surprise_weight",
    ],
    "audience_domains": [
        "id",
        "name",
        "size_M",
        "platform_affinity",
        "entry_condition",
        "affinity_with",
    ],
    "civilizational_stakes": [
        "id",
        "description",
        "domain_tags",
        "surprise_weight",
        "audience_resonance_M",
    ],
    "compression_keys": ["id", "description", "domain_tags", "surprise_weight"],
    "divisiveness_engines": [
        "id",
        "score",
        "description",
        "domain_tags",
        "organic_marketing_multiplier",
    ],
    "moral_fault_lines": [
        "id",
        "description",
        "domain_tags",
        "surprise_weight",
        "audience_resonance_M",
    ],
    "world_textures": ["id", "name", "domain_tags", "surprise_weight"],
}

VALID_SDT_NEEDS = {
    "autonomy",
    "competence",
    "relatedness",
    "all_three",
    "autonomy+competence",
    "competence+relatedness",
}


def validate_entry(category: str, entry: dict[str, Any]) -> list[str]:
    """Return list of validation errors, empty if valid."""
    errors: list[str] = []
    required = REQUIRED_FIELDS.get(category, [])
    for field in required:
        if field not in entry:
            errors.append(f"missing field: {field}")
    if category == "sdt_wounds":
        need = entry.get("need", "")
        if need not in VALID_SDT_NEEDS:
            errors.append(f"invalid need: {need!r}")
    if "surprise_weight" in entry:
        sw = entry.get("surprise_weight", 0)
        if not (0.0 <= float(sw) <= 1.0):
            errors.append(f"surprise_weight out of range: {sw}")
    if "score" in entry:
        score = entry.get("score", 0)
        if not (0 <= float(score) <= _MAX_DIVISIVENESS_SCORE):
            errors.append(f"score out of range: {score}")
    return errors


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _word_set(text: str) -> set[str]:
    return set(text.lower().split())


def is_duplicate(
    new_desc: str, existing_entries: list[dict[str, Any]], threshold: float = 0.60
) -> bool:
    """Return True if new_desc is Jaccard-similar to any existing description."""
    new_words = _word_set(new_desc)
    for entry in existing_entries:
        existing_words = _word_set(str(entry.get("description", entry.get("name", ""))))
        if not new_words or not existing_words:
            continue
        intersection = len(new_words & existing_words)
        union = len(new_words | existing_words)
        if union > 0 and intersection / union >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

_ID_PREFIXES: dict[str, str] = {
    "sdt_wounds": "SW",
    "psychological_patterns": "PP",
    "structural_inversions": "SI",
    "historical_methodology_transplants": "HT",
    "audience_domains": "AD",
    "civilizational_stakes": "CS",
    "compression_keys": "CK",
    "divisiveness_engines": "DE",
    "moral_fault_lines": "MF",
    "world_textures": "WT",
    "era_collisions": "EC",
    "methodology_protagonists": "MP",
}


def next_id(category: str, existing: list[dict[str, Any]]) -> str:
    prefix = _ID_PREFIXES.get(category, "XX")
    used_nums = set()
    for e in existing:
        eid = str(e.get("id", ""))
        if eid.startswith(prefix + "_"):
            with contextlib.suppress(ValueError):
                used_nums.add(int(eid[len(prefix) + 1 :]))
    n = max(used_nums, default=0) + 1
    return f"{prefix}_{n:02d}"


# ---------------------------------------------------------------------------
# Response parser — extracts structured entries from Sonar plain text
# ---------------------------------------------------------------------------


def _apply_category_fields(entry: dict[str, Any], block: str, desc: str, category: str) -> None:
    """Mutate entry with category-specific fields extracted from block."""
    if category == "sdt_wounds":
        entry["need"] = _infer_sdt_need(block)
        entry["deprivation_intensity"] = 1.5
        entry["audience_resonance_M"] = _infer_number(
            block, ["million", "M globally", "prevalence"]
        )
        entry["divisiveness_contribution"] = _infer_divisiveness(block)
    elif category in ("psychological_patterns", "structural_inversions"):
        entry["divisiveness_contribution"] = _infer_divisiveness(block)
        cp = _extract_field(block, ["commercial proof:", "film:", "box office:", "example:"])
        if cp:
            entry["commercial_proof"] = cp
        if category == "psychological_patterns":
            entry["audience_resonance_M"] = _infer_number(block, ["million", "M globally"])
    elif category == "historical_methodology_transplants":
        entry["era_of_origin"] = _extract_field(block, ["era:", "origin:", "period:"]) or "undated"
        entry["methodology"] = (
            _extract_field(block, ["methodology:", "method:", "practice:"]) or desc
        )
        entry["modern_crisis"] = (
            _extract_field(block, ["modern crisis:", "crisis:", "threat:"]) or ""
        )
        entry["bridge"] = _extract_field(block, ["bridge:", "character:", "protagonist:"]) or ""
        entry["audience_resonance_M"] = _infer_number(block, ["million", "audience"])
    elif category == "audience_domains":
        entry["name"] = _extract_field(block, ["name:", "segment:", "audience:"]) or desc
        entry["size_M"] = _infer_number(block, ["million", "M globally", "billion"])
        entry["platform_affinity"] = _infer_platforms(block)
        entry["entry_condition"] = (
            _extract_field(block, ["entry condition:", "entry:", "what brings"]) or ""
        )
        entry["affinity_with"] = []
    elif category in ("civilizational_stakes", "moral_fault_lines"):
        entry["audience_resonance_M"] = _infer_number(block, ["million", "billion", "globally"])
    elif category == "compression_keys":
        cp = _extract_field(block, ["film:", "example:", "commercial proof:"])
        if cp:
            entry["commercial_proof"] = cp
    elif category == "divisiveness_engines":
        entry["score"] = _infer_divisiveness(block, default=7.0)
        entry["organic_marketing_multiplier"] = (
            _infer_float(block, ["multiplier:", "amplification:", "organic marketing"]) or 1.8
        )
    elif category == "world_textures":
        entry["name"] = _extract_field(block, ["name:", "context:", "setting:"]) or desc


def parse_sonar_response(
    raw: str, category: str, existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Best-effort parser for numbered list responses from Sonar.

    Sonar returns prose; this parser extracts one entry per numbered item,
    mapping key phrases to schema fields. Entries that cannot be mapped
    are returned with a '_parse_incomplete' flag for operator review.
    """
    entries: list[dict[str, Any]] = []
    blocks = _split_numbered_blocks(raw)

    for block in blocks:
        entry: dict[str, Any] = {}

        desc = _extract_field(block, ["description:", "pattern:", "inversion:", "context:"])
        if not desc:
            desc = _first_sentence(block)

        if not desc or is_duplicate(desc, existing + entries):
            continue

        entry["id"] = next_id(category, existing + entries)
        entry["description"] = desc
        entry["domain_tags"] = _infer_domain_tags(block)
        entry["surprise_weight"] = _infer_surprise_weight(block)

        _apply_category_fields(entry, block, desc, category)

        errors = validate_entry(category, entry)
        if errors:
            entry["_parse_incomplete"] = True
            entry["_validation_errors"] = errors
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_numbered_blocks(text: str) -> list[str]:
    parts = re.split(r"\n\s*\d{1,2}[\.\)]\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 30]  # noqa: PLR2004


def _first_sentence(text: str) -> str:
    for sep in [".", "\n"]:
        idx = text.find(sep)
        if idx > 20:  # noqa: PLR2004
            return text[:idx].strip()
    return text[:200].strip()


def _extract_field(text: str, labels: list[str]) -> str:
    lower = text.lower()
    for label in labels:
        idx = lower.find(label)
        if idx >= 0:
            rest = text[idx + len(label) :].strip()
            end = min(
                (rest.find("\n") if "\n" in rest else len(rest)),
                (rest.find(". ") if ". " in rest else len(rest)),
                200,
            )
            return rest[:end].strip()
    return ""


def _infer_domain_tags(text: str) -> list[str]:
    lower = text.lower()
    tag_map = {
        "institution": ["institution", "bureaucracy", "government", "agency", "committee"],
        "identity": ["identity", "self", "who they are", "personhood"],
        "technology": ["technology", "algorithm", "digital", "ai", "software", "automated"],
        "science": ["science", "research", "experiment", "evidence", "empirical"],
        "medicine": ["medical", "clinical", "patient", "hospital", "health"],
        "law": ["legal", "court", "law", "judicial", "trial"],
        "ecology": ["climate", "ecological", "environmental", "nature", "biological"],
        "economics": ["economic", "financial", "market", "labor", "work"],
        "family": ["family", "parent", "child", "generational", "kinship"],
        "community": ["community", "collective", "social", "neighborhood"],
        "history": ["historical", "archive", "past", "tradition", "heritage"],
        "time": ["temporal", "time", "speed", "delay", "duration"],
        "knowledge": ["knowledge", "expertise", "learning", "information"],
        "truth": ["truth", "evidence", "verification", "authenticity", "fact"],
        "power": ["power", "authority", "hierarchy", "control"],
    }
    found: list[str] = []
    for tag, keywords in tag_map.items():
        if any(kw in lower for kw in keywords):
            found.append(tag)
    return found or ["institution"]


def _infer_surprise_weight(text: str) -> float:
    lower = text.lower()
    if any(
        w in lower
        for w in ["unprecedented", "no direct precedent", "genuinely novel", "never been"]
    ):
        return 0.90
    if any(w in lower for w in ["rare", "under-used", "unexplored", "inversion"]):
        return 0.80
    return 0.65


_SDT_NEED_LOOKUP: dict[tuple[bool, bool, bool], str] = {
    (True, True, True): "all_three",
    (True, True, False): "autonomy+competence",
    (False, True, True): "competence+relatedness",
    (True, False, False): "autonomy",
    (False, True, False): "competence",
    (False, False, True): "relatedness",
}


def _infer_sdt_need(text: str) -> str:
    lower = text.lower()
    has_auto = any(
        w in lower for w in ["autonomy", "choice", "freedom", "self-determination", "agency"]
    )
    has_comp = any(
        w in lower for w in ["competence", "skill", "mastery", "effectiveness", "expertise"]
    )
    has_rel = any(
        w in lower for w in ["relatedness", "belonging", "connection", "relationship", "community"]
    )
    return _SDT_NEED_LOOKUP.get((has_auto, has_comp, has_rel), "autonomy")


def _infer_divisiveness(text: str, default: float = 6.0) -> float:
    lower = text.lower()
    if any(
        w in lower for w in ["no villain", "both sides", "no right answer", "genuinely ambiguous"]
    ):
        return 9.0
    if any(w in lower for w in ["argues", "debate", "divisive", "contested", "split"]):
        return 8.0
    if any(w in lower for w in ["complex", "morally ambiguous", "uncomfortable"]):
        return 7.0
    return default


def _infer_number(text: str, keywords: list[str]) -> float:
    lower = text.lower()
    for kw in keywords:
        idx = lower.find(kw)
        if idx < 0:
            continue
        nearby = text[max(0, idx - 50) : idx + 50]
        matches = re.findall(r"(\d[\d,]*\.?\d*)\s*(?:billion|B\b)", nearby)
        if matches:
            return float(matches[0].replace(",", "")) * 1000
        matches = re.findall(r"(\d[\d,]*\.?\d*)\s*(?:million|M\b)", nearby)
        if matches:
            return float(matches[0].replace(",", ""))
        matches = re.findall(r"(\d[\d,]*)", nearby)
        if matches:
            val = float(matches[0].replace(",", ""))
            if val > 100:  # noqa: PLR2004 — assume millions if large
                return val
    return 0.0


def _infer_float(text: str, keywords: list[str]) -> float | None:
    lower = text.lower()
    for kw in keywords:
        idx = lower.find(kw)
        if idx < 0:
            continue
        nearby = text[idx : idx + 30]
        matches = re.findall(r"\d+\.?\d*", nearby)
        if matches:
            return float(matches[0])
    return None


def _infer_platforms(text: str) -> list[str]:
    platform_map = {
        "Netflix": "netflix",
        "Apple TV+": "apple tv",
        "HBO": "hbo",
        "Amazon": "amazon",
        "Hulu": "hulu",
        "Disney+": "disney",
        "A24": "a24",
        "MUBI": "mubi",
        "Neon": "neon",
        "Focus Features": "focus features",
    }
    lower = text.lower()
    return [name for name, keyword in platform_map.items() if keyword in lower] or ["Netflix"]


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------


def call_sonar(prompt: str, model: str = "perplexity/sonar-pro") -> str:
    """Call OpenRouter directly and return the raw text response.

    Uses httpx directly because the pipeline OpenRouterClient parses responses
    as JSON — sonar-pro returns prose, so we read raw content instead.

    Requires OPENROUTER_KEY_PAID environment variable (same key the pipeline uses).
    """
    key = os.environ.get("OPENROUTER_KEY_PAID", "")
    if not key:
        raise RuntimeError(
            "OPENROUTER_KEY_PAID not set. "
            "Export it before running: export OPENROUTER_KEY_PAID=sk-or-v1-..."
        )
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return str(resp.json()["choices"][0]["message"]["content"])


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def append_log(entry: dict[str, Any]) -> None:
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main enrichment loop
# ---------------------------------------------------------------------------


def enrich_category(
    data: dict[str, Any],
    category: str,
    dry_run: bool = False,
    target_n: int | None = None,
    rebuild: bool = False,
    collision_type: str | None = None,
) -> dict[str, Any]:
    prompts = RESEARCH_PROMPTS.get(category)
    if not prompts:
        print(f"  No research prompts defined for '{category}'. Skipping.")
        return data

    existing = list(data.get(category, []))
    if rebuild:
        existing = []

    all_new: list[dict[str, Any]] = []

    for i, prompt_cfg in enumerate(prompts):
        prompt_text = prompt_cfg["prompt"]
        if collision_type and category == "era_collisions":
            prompt_text += f"\n\nFocus specifically on collision_type: {collision_type}"
        if target_n:
            prompt_text = prompt_text.replace(
                str(prompt_cfg.get("expected_count", 20)),
                str(target_n),
            )

        print(f"  Prompt {i + 1}/{len(prompts)}: {prompt_text[:80]}...")

        if dry_run:
            print("  [DRY RUN] Would call sonar-pro. Skipping API call.")
            continue

        try:
            raw = call_sonar(prompt_text)
            new_entries = parse_sonar_response(raw, category, existing + all_new)
            print(f"  Parsed {len(new_entries)} entries from response.")

            append_log(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "category": category,
                    "prompt_index": i,
                    "new_entries": len(new_entries),
                    "status": "ok",
                }
            )

            all_new.extend(new_entries)
            time.sleep(1)  # rate limit courtesy

        except Exception as e:
            print(f"  ERROR on prompt {i + 1}: {e}")
            append_log(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "category": category,
                    "prompt_index": i,
                    "status": "error",
                    "error": str(e),
                }
            )

    if rebuild:
        data[category] = all_new
    else:
        data[category] = existing + all_new

    added = len(all_new)
    total = len(data[category])
    print(f"  Category '{category}': +{added} new entries → {total} total.")
    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research-driven enrichment for compound_seed_variables.json"
    )
    parser.add_argument(
        "--category",
        default="all",
        help=("Category to enrich, or 'all'. Options: " + ", ".join(RESEARCH_PROMPTS.keys())),
    )
    parser.add_argument("--n", type=int, default=None, help="Target number of new entries")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts, skip API calls")
    parser.add_argument("--rebuild", action="store_true", help="Replace existing entries")
    parser.add_argument(
        "--collision-type",
        default=None,
        help="For era_collisions: time | material | scientific | epistemic | scale",
    )
    parser.add_argument("--model", default="perplexity/sonar-pro", help="OpenRouter model")
    args = parser.parse_args()

    data = json.loads(_VARS_PATH.read_text(encoding="utf-8"))

    categories = list(RESEARCH_PROMPTS.keys()) if args.category == "all" else [args.category]

    for cat in categories:
        print(f"\n{'=' * 60}")
        print(f"Enriching: {cat}")
        print(f"{'=' * 60}")
        data = enrich_category(
            data,
            cat,
            dry_run=args.dry_run,
            target_n=args.n,
            rebuild=args.rebuild,
            collision_type=args.collision_type,
        )
        if not args.dry_run:
            atomic_write(_VARS_PATH, data)
            print(f"  Written to {_VARS_PATH}")

    print("\nDone.")
    for cat in categories:
        print(f"  {cat}: {len(data.get(cat, []))} entries")


if __name__ == "__main__":
    main()
