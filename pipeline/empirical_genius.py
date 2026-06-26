"""pipeline/empirical_genius.py — 5th axis scoring (Empirical Genius Index).

Consumes `.planning/research/cinema_idea_genius/GREATNESS_CHECKLIST.json` produced
by the Cinema Idea Genius Synthesizer (Agent 8). Implements the v1 MVP of the
two-stage hierarchical aggregation specified in `scoring_aggregation`:

  Stage 1 — Kill switch gate (C006, C007). Failure -> REJECT, EGI=0.
  Stage 2 — Empirical Genius Index sub-composite:
            EGI = a*embedding_novelty + b*emotional_shape + g*premortem_survival
            with a=0.40, b=0.40, g=0.20 (per Synthesizer's checklist;
            named ALPHA_NOVELTY / BETA_SHAPE / GAMMA_SURVIVAL in code).
            Output scaled to [0, EGI_AXIS_MAX=25].

ADR-0002 compliance: this module performs ALL arithmetic in pure Python. It reads
phase outputs (Phase4Concept, Phase5Critique, Phase3Audience, Phase2JTBD,
Phase1Assets) and the immutable GREATNESS_CHECKLIST.json. LLMs never compute
EGI — they emit phase outputs that this module evaluates.

v1 MVP scope:
  • C006 (Want / Need / Flaw / Transformation slot-fill on logline) — heuristic rule_check
    using regex patterns for goal-verbs / obstacle-words / transformation-words.
  • C007 (≥3 protagonist-causal beats) — STUBBED to pass; full LLM-CoT
    implementation deferred (would call a Task subagent which Python can't).
  • C002 (embedding novelty) — sentence-transformers lazy import; if not installed,
    `degraded=True` and novelty defaults to 0.5 (mid-Goldilocks).
  • C001 (emotional shape) — heuristic keyword match against 6 Reagan shapes;
    refined when emotion-classifier model is added.
  • Premortem survival — fraction of 20 PM-D conditions whose criterion_id passes.

Graceful degradation:
  When `sentence-transformers` is not installed (operator hasn't run
  `uv add sentence-transformers` yet), embedding_novelty returns 0.5 with
  `degraded=True`. EGI still computes but the operator sees the flag.
"""

from __future__ import annotations

import json
import re
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pipeline.crystallize.embeddings import CorpusIndex

CHECKLIST_PATH = Path(".planning/research/cinema_idea_genius/GREATNESS_CHECKLIST.json")

EGI_AXIS_MAX: int = 25
ALPHA_NOVELTY: float = 0.40
BETA_SHAPE: float = 0.40
GAMMA_SURVIVAL: float = 0.20

# Premortem-survival threshold constants (PLR2004 — named, not magic)
AUDIENCE_FLOOR: int = 50_000_000  # PM-D13 minimum audience
COUNTRY_FLOOR: int = 3  # PM-D03 minimum distinct ISO2 countries
LOGLINE_MIN_WORDS: int = 25  # PM-D11 posterable logline lower bound
LOGLINE_MAX_WORDS: int = 35  # PM-D11 posterable logline upper bound
TEN_SCHOOL_LIST_LEN: int = 10
SEVEN_SCHOOL_FLOOR: int = 7  # PM-D06 cinema-school floor
CROSS_CHECK_DICT_LEN: int = 5

# Kill switch criteria — fail = REJECT regardless of other scores
KILL_SWITCHES: tuple[str, ...] = ("C006", "C007", "C008")
SOM_HARD_FLOOR_M: float = 1000.0  # C008 hard floor ($M USD)
_SOM_TARGET_M: float = (
    2000.0  # upper SOM band threshold ($M); distinct from compound_seed._TARGET_SOM_M (150)
)

# Probe for sentence-transformers at module load. find_spec checks the
# importability without actually importing the package, so we avoid PLC0415
# (in-function imports) and the cost of loading the model. Downstream callers
# read the flag and degrade gracefully when the dep is absent.
_HAVE_SENTENCE_TRANSFORMERS: bool = find_spec("sentence_transformers") is not None

# Heuristic word lists for C006 (Want / Need / Flaw / Transformation).
# v1 lenient mode: passes if (WANT or TRANSFORM) AND (OBSTACLE or TIME).
# This is a CATCH-OBVIOUSLY-BROKEN check, not a quality gate. Borderline
# loglines should reach the critic for nuanced evaluation, not be killed here.
_WANT_VERBS = re.compile(
    r"\b(want|wants|seek|seeks|must|tries to|trying to|sets out|determined to|"
    r"obsessed with|hunt|hunts|chase|chases|pursue|pursues|attempt|attempts|"
    r"fight|fights|struggle|struggles|need to|needs to|hopes to|aims to|races to|"
    r"investigate|investigates|defend|defends|expose|exposes|prevent|prevents|"
    r"rebuild|rebuilds|read|reads|testify|testifies|negotiate|negotiates|"
    r"build|builds|protect|protects|escape|escapes|return|returns|"
    r"refuse|refuses|infiltrate|infiltrates|hide|hides|recover|recovers)\b",
    re.IGNORECASE,
)
_OBSTACLE_WORDS = re.compile(
    r"\b(but|while|against|before|despite|though|although|unless|until|"
    r"blocked by|opposed by|threatened by|trapped|hunted by|pursued by|"
    r"caught between|forced to|risking|risks losing|risk losing|or lose|"
    r"as the|when the|if the|forced into|even as|even though|"
    r"only to|even when|even after|knowing|aware that|whose|whom)\b",
    re.IGNORECASE,
)
_TRANSFORMATION_WORDS = re.compile(
    r"\b(becomes|becoming|discovers|discover|learns|realizes|realises|"
    r"transforms|emerges|confronts|reveals|reckons|reckoning|"
    r"choose between|forced to choose|simultaneously|"
    r"to save|to stop|to expose|to protect|to redeem|to prevent|"
    r"to escape|to defeat|to overcome|to recover|to find|to return|"
    r"to defend|to rebuild|to restore|to claim)\b",
    re.IGNORECASE,
)
# Franchise / pre-existing-IP dependency cues (v5.1.0 de-franchise detector).
# A hit means the concept's cash flow leans on existing IP rather than a
# standalone original -- the operator's mandate is the opposite.
_FRANCHISE_KEYWORDS = re.compile(
    r"\b(sequel|prequel|spin[- ]?off|franchise|cinematic universe|shared universe|"
    r"based on the (?:video game|game|toy|comic|novel series|book series|bestselling)|"
    # qualify 'adaptation of' with a real IP noun so original true-event/docu
    # framing ('an adaptation of the true story behind NASA') is NOT flagged.
    r"adaptation of (?:the |a )?(?:video game|novel|comic|book|manga|anime|"
    r"tv series|stage show|musical|podcast|toy line)|"
    r"reboot|remake|chapter \d|part \d|"
    # multi-character Roman numerals (Episode IV) + arabic episode markers.
    r"episode (?:[ivxlcdm]+|\d+)|"
    r"expanded universe|extended universe|live[- ]action remake)\b",
    re.IGNORECASE,
)
# Time / deadline / irreversibility cues (counts as obstacle for C006).
_TIME_DEADLINE = re.compile(
    r"\b(\d+\s*(?:hour|hours|day|days|week|weeks|minute|minutes|month|months)|"
    r"deadline|countdown|by midnight|by dawn|tonight|tomorrow|"
    r"final hour|last chance|final|last|before it|before the|until the|"
    r"24-hour|48-hour|72-hour|72|48|24)\b",
    re.IGNORECASE,
)


def _check_C008_commercial_scale(audience_row: dict[str, Any]) -> bool | None:
    """C008 kill switch: projected SOM must be >= $1B.

    Returns:
        True   — SOM data present and at or above the $1B hard floor (passes).
        False  — SOM data present but below the $1B hard floor (kill switch fires).
        None   — SOM data absent; check is unchecked (no kill, but not confirmed pass).
                 Callers must distinguish None from True when deciding whether the
                 criterion was actually verified (use criteria_checked["C008"]).
    """
    som = audience_row.get("projected_som_usd_m")
    if som is None:
        return None  # unchecked — no SOM data yet; do NOT kill, but do NOT mark as passed
    return float(som) >= SOM_HARD_FLOOR_M


def _som_band(audience_row: dict[str, Any]) -> str:
    """Return 'below_1b' | '1b_to_2b' | 'above_2b' | 'unknown' for the concept SOM."""
    som = audience_row.get("projected_som_usd_m")
    if som is None:
        return "unknown"
    v = float(som)
    if v >= _SOM_TARGET_M:
        return "above_2b"
    if v >= SOM_HARD_FLOOR_M:
        return "1b_to_2b"
    return "below_1b"


# 6 Reagan emotional-shape keyword hints (heuristic; replace with classifier post-MVP)
_SHAPE_KEYWORDS: dict[str, list[str]] = {
    "rags_to_riches": ["overcomes", "rises", "ascends", "transforms", "wins"],
    "tragedy": ["loses", "destroyed", "falls", "betrayed", "killed", "consumed"],
    "man_in_hole": ["caught", "trapped", "rescued", "escapes", "redeemed", "survives"],
    "icarus": ["soars", "ambition", "hubris", "falls from grace", "consumed by"],
    "cinderella": ["transformed", "discovered", "elevated", "chosen", "anointed"],
    "oedipus": ["fated", "tragic flaw", "brought down by", "destined", "unwitting"],
}


def _load_checklist(path: Path = CHECKLIST_PATH) -> dict[str, Any] | None:
    """Load GREATNESS_CHECKLIST.json. Returns None on missing/malformed."""
    if not path.exists():
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data  # type: ignore[no-any-return]


def detect_standalone_ip(logline: str, synopsis: str = "") -> bool | None:
    """v5.1.0 de-franchise signal. Returns ``False`` when the concept depends on
    pre-existing IP (sequel / franchise / adaptation / remake), ``True`` for a
    clearly original standalone concept, and ``None`` when there is no text to
    judge (ambiguous). A binary signal — no numeric/market claim, so the
    deep-link evidence policy does not apply."""
    text = f"{logline or ''} {synopsis or ''}".strip()
    if not text:
        return None
    return not _FRANCHISE_KEYWORDS.search(text)


def _check_C006_want_need_flaw_transformation(concept_row: dict[str, Any]) -> bool:
    """C006 kill switch: logline must encode Want / Block / Transformation.

    v1 heuristic (regex over logline text). Replace with LLM-CoT slot-fill in v2.
    Per the prompt, Phase 4 forger emits 25-35-word loglines in WHO does WHAT
    against WHAT TRIZ contradiction with WHAT irreversibility clock format —
    so most well-formed loglines should pass.
    """
    logline = str(concept_row.get("logline", "") or "")
    if not logline.strip():
        return False
    has_want = bool(_WANT_VERBS.search(logline))
    has_obstacle = bool(_OBSTACLE_WORDS.search(logline))
    has_transformation = bool(_TRANSFORMATION_WORDS.search(logline))
    has_time = bool(_TIME_DEADLINE.search(logline))
    # Lenient: (active driving verb) AND (some opposition/clock/transformation).
    # Catches obvious "this is just a sentence" failures; passes well-formed loglines.
    return (has_want or has_transformation) and (has_obstacle or has_time or has_transformation)


#: C007 floor: a logline shorter than this cannot plausibly encode >=3
#: protagonist-causal beats, regardless of which verbs appear. Set well below
#: the 25-35-word Phase-4 logline contract (:data:`LOGLINE_MIN_WORDS` = 25) so
#: no well-formed concept is ever false-rejected -- only genuine fragments.
_C007_MIN_LOGLINE_WORDS: int = 12


def _check_C007_active_protagonist(concept_row: dict[str, Any]) -> bool:
    """C007 kill switch: the protagonist must visibly DRIVE the story (a proxy
    for the checklist's ">=3 protagonist-causal beats"), not merely have events
    happen to them.

    v1 heuristic (regex over logline + synopsis), deliberately lenient: it
    rejects only degenerate input and never a well-formed concept. It FAILS when
    the logline is

      * empty / whitespace, or
      * a fragment (< :data:`_C007_MIN_LOGLINE_WORDS` words -- too thin to hold
        three beats), or
      * motion-less (no narrative-motion marker at all -- the protagonist
        neither acts, changes, faces opposition, nor races a clock, e.g. a
        purely atmospheric or stative premise),

    and PASSES otherwise.

    This is independent of C006: C006 checks Want/Block/Transformation *form*;
    C007 adds a *substance* floor, so a 5-word fragment that happens to satisfy
    C006's marker conjunction ("She must fight on") still fails C007. It replaces
    the previous no-op stub (unconditional ``return True``) so the kill switch
    can actually fire -- optimising ideas against a dead gate silently games the
    score (NEXT_SESSION_PLAYBOOK Risk: "Goodhart at industrial scale").

    Deliberately lenient on the marker set (drive / change / oppose / clock)
    rather than driving-verb-only: an empirical sweep of the golden anchors
    showed a Grade-A concept (Ostankino) that conveys agency through
    opposition+clock ("trapped ... while the coup collapses ... ninety minutes")
    rather than a goal verb. False-rejecting a golden concept is worse than
    passing a borderline one, so the floor catches only genuine fragments /
    stative premises. A v2 upgrade can still escalate to LLM-CoT beat
    extraction; this heuristic is the deterministic, ADR-0002-clean floor.
    """
    logline = str(concept_row.get("logline", "") or "")
    if not logline.strip():
        return False
    if len(logline.split()) < _C007_MIN_LOGLINE_WORDS:
        return False
    # Narrative motion: the protagonist DRIVES (wants/acts), CHANGES
    # (transforms), faces OPPOSITION, or runs against a CLOCK. Their total
    # absence in a non-fragment logline means the premise has no protagonist
    # engine. Search logline + synopsis so a terse logline backed by a richer
    # synopsis still passes.
    synopsis = str(concept_row.get("synopsis", "") or "")
    text = f"{logline}\n{synopsis}"
    return bool(
        _WANT_VERBS.search(text)
        or _TRANSFORMATION_WORDS.search(text)
        or _OBSTACLE_WORDS.search(text)
        or _TIME_DEADLINE.search(text)
    )


_NOVELTY_NEUTRAL: float = 0.5
"""Default returned when corpus index is unavailable -- mid-Goldilocks."""

_NOVELTY_INDEX_CACHE: list[CorpusIndex | None] = []  # populated on first call


def _get_corpus_index() -> CorpusIndex | None:
    """Lazy singleton: load CorpusIndex once per process. Returns None when
    the index file is absent so the caller can degrade gracefully."""
    if _NOVELTY_INDEX_CACHE:
        return _NOVELTY_INDEX_CACHE[0]
    # Lazy import: keep the empirical_genius cold-import path free of
    # the (1.2 MB on disk, ~3s on first model load) embedding stack.
    from pipeline.crystallize.embeddings import CorpusIndex  # noqa: PLC0415

    idx = CorpusIndex.load()
    _NOVELTY_INDEX_CACHE.append(idx)  # store even when None to avoid retry loops
    return idx


def _embedding_novelty(concept_row: dict[str, Any]) -> tuple[float, bool]:
    """C002 embedding novelty: 1 - max_cosine_sim against existing-films corpus.

    Goldilocks zone is novelty in [0.05, 0.50] = pass; outside = soft-fail.
    Returns (novelty_score in [0, 1], degraded_flag).

    Wired to pipeline.crystallize.embeddings.CorpusIndex (commit 8427546).
    Degrades to (_NOVELTY_NEUTRAL, True) when:
      - sentence-transformers is not installed (dev sandbox without ML deps)
      - the .npz index file is absent (operator hasn't run
        scripts/build_corpus_embeddings.py yet)
      - the concept_row has no logline AND no synopsis (degenerate input)
    """
    if not _HAVE_SENTENCE_TRANSFORMERS:
        return _NOVELTY_NEUTRAL, True
    idx = _get_corpus_index()
    if idx is None:
        return _NOVELTY_NEUTRAL, True

    logline = str(concept_row.get("logline", "") or "").strip()
    synopsis = str(concept_row.get("synopsis", "") or "").strip()
    text = " ".join(p for p in (logline, synopsis) if p)
    if not text:
        return _NOVELTY_NEUTRAL, True

    max_sim = idx.max_cosine(text)
    # Cosine of normalised natural-language embeddings is in [0, 1] in practice.
    # novelty = 1 - max_sim, clamped defensively.
    novelty = max(0.0, min(1.0, 1.0 - max_sim))
    return novelty, False


def _emotional_shape_match(concept_row: dict[str, Any]) -> float:
    """C001 emotional shape match. Returns score in [0, 1].

    v1 heuristic: keyword overlap with 6 Reagan shape templates.
    Bonus for "Man in Hole" (highest empirical commercial signal per Agent 3).
    """
    logline = str(concept_row.get("logline", "") or "").lower()
    if not logline:
        return 0.0

    matches: dict[str, int] = {}
    for shape, kws in _SHAPE_KEYWORDS.items():
        matches[shape] = sum(1 for kw in kws if kw in logline)

    best_shape = max(matches, key=lambda s: matches[s]) if matches else None
    best_count = matches.get(best_shape, 0) if best_shape else 0
    if best_count == 0:
        return 0.20  # No shape keyword detected; neutral score (don't fail outright)

    base_score = min(0.85, 0.30 + 0.20 * best_count)  # 1 hit = 0.50; 3+ hits = 0.85
    if best_shape == "man_in_hole":
        base_score = min(1.0, base_score + 0.15)  # Man-in-Hole bonus per checklist
    return base_score


def _seven_school_floor_met(critique_row: dict[str, Any]) -> bool:
    """True iff Phase5Critique.ten_school_self_check has >=SEVEN_SCHOOL_FLOOR Trues.

    Accepts both list[bool] (canonical schema) and dict[str, bool] (LLM variant
    with named schools as keys) — tolerates upstream agent drift.
    """
    raw: object = critique_row.get("ten_school_self_check") or []
    values: list[Any]
    if isinstance(raw, list):
        values = cast("list[Any]", raw)
    elif isinstance(raw, dict):
        values = list(cast("dict[str, Any]", raw).values())
    else:
        return False
    if len(values) != TEN_SCHOOL_LIST_LEN:
        return False
    return sum(1 for x in values if bool(x)) >= SEVEN_SCHOOL_FLOOR


def _all_cross_checks_true(critique_row: dict[str, Any]) -> bool:
    """True iff Phase5Critique.cross_checks is the canonical 5-dict and all True."""
    raw: object = critique_row.get("cross_checks") or {}
    if not isinstance(raw, dict):
        return False
    items = cast("dict[str, Any]", raw)
    if len(items) != CROSS_CHECK_DICT_LEN:
        return False
    return all(bool(v) for v in items.values())


def _premortem_survival_rate(
    concept_row: dict[str, Any],
    critique_row: dict[str, Any],
    audience_row: dict[str, Any],
) -> float:
    """Fraction of 20 PM-D conditions whose corresponding criterion passes.

    v1: count of upstream-checkable conditions. PM conditions tied to:
      - protagonist named (key_roles.protagonist non-null)
      - antagonist named (key_roles.antagonist non-null)
      - audience ≥50M (audience_row.cited_audience ≥50_000_000)
      - ≥3 countries (len(target_countries) ≥3)
      - logline word count in [25, 35]
      - 7+/10 cinema schools pass (sum(ten_school_self_check) ≥7)
      - cap_at_70 not triggered
      - cross_checks all true (when present)
    """
    checks: list[bool] = []

    # Named protagonist + antagonist (PM-D04 / PM-D08).
    key_roles_raw: object = concept_row.get("key_roles") or {}
    if isinstance(key_roles_raw, dict):
        kr_dict = cast("dict[str, Any]", key_roles_raw)
        checks.append(bool(kr_dict.get("protagonist")))
        checks.append(bool(kr_dict.get("antagonist")))
    else:
        checks.extend([False, False])

    # Audience floor (PM-D13).
    cited = int(audience_row.get("cited_audience", 0) or 0)
    checks.append(cited >= AUDIENCE_FLOOR)

    # >=COUNTRY_FLOOR distinct countries (PM-D03).
    countries_raw: object = audience_row.get("target_countries") or []
    if isinstance(countries_raw, list):
        countries_list = cast("list[Any]", countries_raw)
        checks.append(len(countries_list) >= COUNTRY_FLOOR)
    else:
        checks.append(False)

    # Logline word count in [LOGLINE_MIN_WORDS, LOGLINE_MAX_WORDS] (PM-D11).
    logline = str(concept_row.get("logline", "") or "")
    word_count = len(logline.split())
    checks.append(LOGLINE_MIN_WORDS <= word_count <= LOGLINE_MAX_WORDS)

    # >=SEVEN_SCHOOL_FLOOR of TEN_SCHOOL_LIST_LEN cinema schools pass (PM-D06).
    checks.append(_seven_school_floor_met(critique_row))

    # cap_at_70 not triggered (PM-D09).
    checks.append(not bool(critique_row.get("cap_at_70_triggered", False)))

    # All CROSS_CHECK_DICT_LEN cross_checks true (PM-D07/D10/D14).
    checks.append(_all_cross_checks_true(critique_row))

    if not checks:
        return 0.0
    return sum(1 for x in checks if x) / len(checks)


def score_concept(
    concept_row: dict[str, Any],
    critique_row: dict[str, Any],
    audience_row: dict[str, Any],
    jtbd_row: dict[str, Any],
    asset_row: dict[str, Any],
    *,
    checklist_path: Path = CHECKLIST_PATH,
) -> dict[str, Any]:
    """Compute the Empirical Genius Index for one concept.

    Returns:
        {
          "final": float in [0, EGI_AXIS_MAX],
          "novelty": float in [0, 1],
          "shape": float in [0, 1],
          "survival": float in [0, 1],
          "kill_switches_triggered": list[str],   # e.g. ["C006"]
          "criteria_pass": dict[str, bool | None],
              # C006, C007 are strict bool.
              # C008 is tri-state: True (SOM present + passes), False (SOM present + fails),
              #   None (SOM absent — criterion unchecked; kill switch does NOT fire).
          "criteria_checked": dict[str, bool],
              # True when the criterion was actually evaluated against data.
              # C008 is False when projected_som_usd_m was absent from audience_row.
          "degraded": bool,                        # True if checklist
                                                   # or sentence-transformers missing
          "message": str,
        }
    """
    _ = jtbd_row  # joined upstream; reserved for v2 (deprivation amplifier signal)
    _ = asset_row  # joined upstream; reserved for v2 (real-world anchor signal)
    checklist = _load_checklist(checklist_path)
    checklist_present = checklist is not None
    standalone_flag = detect_standalone_ip(
        str(concept_row.get("logline", "") or ""),
        str(concept_row.get("synopsis", "") or ""),
    )

    # Stage 1: Kill switches
    # c006_pass / c007_pass are strict bool (True|False).
    # c008_pass is tri-state: True (checked+passes), False (checked+fails), None (unchecked).
    # Only a hard False fires the kill switch; None means "no SOM data yet" and passes through.
    c006_pass = _check_C006_want_need_flaw_transformation(concept_row)
    c007_pass = _check_C007_active_protagonist(concept_row)
    c008_pass = _check_C008_commercial_scale(audience_row)
    triggered: list[str] = []
    if not c006_pass:
        triggered.append("C006")
    if not c007_pass:
        triggered.append("C007")
    if c008_pass is False:  # None (unchecked) must NOT trigger the kill switch
        triggered.append("C008")

    if triggered:
        return {
            "final": 0.0,
            "novelty": 0.0,
            "shape": 0.0,
            "survival": 0.0,
            "kill_switches_triggered": triggered,
            "criteria_pass": {"C006": c006_pass, "C007": c007_pass, "C008": c008_pass},
            "criteria_checked": {
                "C006": True,
                "C007": True,
                "C008": c008_pass is not None,
            },
            "degraded": not checklist_present,
            "message": f"REJECTED — kill switch(es) failed: {', '.join(triggered)}",
            "som_band": _som_band(audience_row),
            "standalone_ip_flag": standalone_flag,
        }

    # Stage 2: EGI sub-composite
    novelty, novelty_degraded = _embedding_novelty(concept_row)
    shape = _emotional_shape_match(concept_row)
    survival = _premortem_survival_rate(concept_row, critique_row, audience_row)

    egi_normalized = ALPHA_NOVELTY * novelty + BETA_SHAPE * shape + GAMMA_SURVIVAL * survival
    egi_final = round(egi_normalized * EGI_AXIS_MAX, 1)

    return {
        "final": egi_final,
        "novelty": round(novelty, 3),
        "shape": round(shape, 3),
        "survival": round(survival, 3),
        "kill_switches_triggered": [],
        # Use the actual computed booleans, not hardcoded True values.
        # c008_pass may be None when SOM data is absent (unchecked criterion).
        "criteria_pass": {"C006": c006_pass, "C007": c007_pass, "C008": c008_pass},
        "criteria_checked": {
            "C006": True,
            "C007": True,
            "C008": c008_pass is not None,
        },
        "degraded": (not checklist_present) or novelty_degraded,
        "message": (
            f"EGI={egi_final}/25 (a*novelty={ALPHA_NOVELTY * novelty:.3f}, "
            f"b*shape={BETA_SHAPE * shape:.3f}, g*survival={GAMMA_SURVIVAL * survival:.3f})"
        ),
        "som_band": _som_band(audience_row),
        "standalone_ip_flag": standalone_flag,
    }


__all__ = [
    "ALPHA_NOVELTY",
    "BETA_SHAPE",
    "CHECKLIST_PATH",
    "EGI_AXIS_MAX",
    "GAMMA_SURVIVAL",
    "KILL_SWITCHES",
    "detect_standalone_ip",
    "score_concept",
]
