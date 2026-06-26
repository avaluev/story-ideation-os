"""pipeline/compound_seed.py — Multi-variable compound seed generator.

Combines tensions, psychological patterns, structural inversions, historical
methodology transplants, civilizational stakes, and audience domains to find
the story that REQUIRES all inputs to be simultaneously true.

Targets $500M+ SOM by forcing 3+ non-overlapping audience entry points,
a divisiveness score above 7, and a civilizational or at least universal
emotional anchor.

All scoring is pure Python (ADR-0002). No framework names appear in any output.
The intersection premise generation dispatches a single Haiku call via
cc_dispatch per ADR-0007. All writes use pipeline.state.safe_write (ADR-0001).

Design principles:
- Associative distance 0.3-0.5 between the two most distant elements (C002)
- SDT deprivation intensity drives C003 (emotional anchor stability)
- Structural inversion drives C001 (expert surprise)
- Audience overlap drives SOM floor estimate
- Divisiveness drives organic marketing multiplier
- Compression key drives C007 (aha / MDL delta)

Usage:
    engine = CompoundSeedEngine.from_defaults()

    # Fully auto-sampled — engine finds the best combination
    result = engine.generate()

    # Operator-guided — pin specific inputs
    result = engine.generate(
        themes=["information verification", "AI misinformation"],
        problems=["AI-generated religious text forgery"],
        n_tensions=2,
        force_historical_transplant="HT_01",
        target_som_M=500,
    )

    # Write to run directory
    engine.write_seed(result, run_dir=Path("runs/2026-..."))

Output seed.json schema:
    {
      "run_id": str,
      "themes": list[str],
      "tensions": list[dict],            # 2-3 binary tensions from ontology
      "sdt_wound": dict,
      "psychological_pattern": dict,
      "structural_inversion": dict,
      "moral_fault_line": dict,
      "compression_key": dict,
      "divisiveness_engine": dict,
      "civilizational_stake": dict | None,
      "methodology_protagonist": dict | None,
      "historical_transplant": dict | None,
      "era_collision": dict | None,
      "world_texture": dict,
      "audiences": list[dict],           # 3 audience domains
      "scores": CompoundScoreDict,
      "intersection_premise": str,       # Haiku-generated 150-250 words
      "hidden_attrs": dict               # framework labels — never exposed in output
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast

try:
    from pipeline import lessons_loader as _lessons_loader
except ImportError:  # not available in all envs / test harnesses
    _lessons_loader: ModuleType | None = None  # type: ignore[assignment]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_VARS_PATH: Final[Path] = _REPO_ROOT / "pipeline" / "data" / "compound_seed_variables.json"
_ONTOLOGY_PATH: Final[Path] = _REPO_ROOT / "sources" / "conflict_ontology.json"
_FRAMEWORKS_DATA: Final[Path] = _REPO_ROOT / "frameworks" / "data"
_CONSPIRACY_PATH: Final[Path] = _FRAMEWORKS_DATA / "conspiracy_engines.json"
_REPTILE_PATH: Final[Path] = _FRAMEWORKS_DATA / "reptile_triggers.json"
_OPEN_PROBLEMS_PATH: Final[Path] = _FRAMEWORKS_DATA / "open_problems_science.json"
_CULTURAL_MOMENT_PATH: Final[Path] = _FRAMEWORKS_DATA / "cultural_moment_2026.json"
_DARK_ARCHETYPES_PATH: Final[Path] = _FRAMEWORKS_DATA / "dark_archetypes.json"
_ALLY_ARCHETYPES_PATH: Final[Path] = _FRAMEWORKS_DATA / "ally_archetypes.json"
_PROTAGONIST_ARCHETYPES_PATH: Final[Path] = _FRAMEWORKS_DATA / "protagonist_archetypes.json"

# Scoring constants — pure Python (ADR-0002)
_ASSOC_TARGET: Final[float] = 0.40  # Goldilocks midpoint
_ASSOC_TOLERANCE: Final[float] = 0.15  # acceptable deviation from target
_MIN_GENIUS_SCORE: Final[float] = 0.72
_MIN_DIVISIVENESS: Final[float] = 7.0
_MIN_AUDIENCE_OVERLAP_M: Final[float] = 200.0
# SOM target lowered: only 6 films ever crossed $2B (top-3000 corpus).
# Only Avatar & Titanic are original IP that crossed $2B; both exceptional conditions.
# Concept-stage realistic ceiling: $300-400M for original IP without greenlight.
_TARGET_SOM_M: Final[float] = 150.0  # realistic concept-stage gate ($M)
# Removed _BASE_REVENUE_PER_PERSON — replaced by proper TAM→SAM→SOM pipeline below.
# TAM/SAM/SOM constants anchored to top-3000 corpus analysis
_GLOBAL_THEATRICAL_TAM_M: Final[float] = 40_000.0  # $40B global theatrical 2023 (MPA)
_GENRE_TAM_FRACTION: Final[float] = 0.12  # genre slice for typical mixed-genre original
_CONCEPT_CAPTURE_BASE: Final[float] = 0.025  # 2.5% base: top-quartile original IP
# Hard ceiling: original IP without production — only Avatar/Titanic exceeded $400M
# at comparable concept-quality-only measure. Greenlit+A-list multiplies by 2-5x.
_CONCEPT_STAGE_CEILING_M: Final[float] = 400.0
_MAX_GENERATION_ATTEMPTS: Final[int] = 50
_TRANSPLANT_RANDOM_PROB: Final[float] = 0.30
# Raised 0.20→0.50: 50%+ of top-100 grossing films have civilizational stakes
# (Avatar, Avengers, Star Wars VII all $2B+). 0.20 was undersampling by 60%.
_CIV_STAKE_RANDOM_PROB: Final[float] = 0.50
_ERA_COLLISION_PROB: Final[float] = 0.40
_ERA_FORCE_MIN: Final[int] = 2  # n_era >= this forces sampling, ignoring probability
# Lowered 0.70→0.45: conspiracy bias favoured Joker/Parasite style over Titanic/Frozen
_CONSPIRACY_PROB: Final[float] = 0.45
# Lowered 0.80→0.55: primal fear slant blocks hopeful/uplifting blockbusters
_REPTILE_PROB: Final[float] = 0.55
_OPEN_PROBLEM_PROB: Final[float] = 0.60
# Lowered 0.90→0.60: Frozen II, Lion King remakes succeed on familiarity not zeitgeist
_CULTURAL_MOMENT_PROB: Final[float] = 0.60
# Lowered 0.75→0.55: dark archetype bias blocks Inside Out 2 / Titanic archetypes
_DARK_ARCHETYPE_PROB: Final[float] = 0.55
#: Probability that a base generation is assigned a content format (v5.1.0).
#: ~30% stay format-agnostic so legacy/feature-implicit concepts still flow.
_FORMAT_SAMPLE_PROB: Final[float] = 0.70
_TENSION_SAMPLE_ATTEMPTS: Final[int] = 200
# Compression bonus: cliff removed — continuous curve rewards distributed arcs
# (Titanic, Top Gun: Maverick score well; Inception-style twist also rewarded)
_COMPRESSION_BONUS_HIGH: Final[float] = 0.80  # 1.10x (was 1.20x cliff)
_COMPRESSION_BONUS_MID: Final[float] = 0.60  # 1.05x (was 1.10x at 0.70)
# Thematic anchor: ensemble films penalised less (Avengers = distributed themes)
_THEMATIC_ANCHOR_HIGH: Final[float] = 0.70  # 1.08x (was 1.15x)
_THEMATIC_ANCHOR_MID: Final[float] = 0.45  # 1.03x (was 1.08x)
_EMO_UNI_RESONANCE_HIGH: Final[float] = 500.0  # SDT wound felt by 500M+ people
_EMO_UNI_RESONANCE_MID: Final[float] = 300.0
_EMO_UNI_DIV_HIGH: Final[float] = 8.0  # debate-driven word-of-mouth threshold
_EMO_UNI_DIV_MID: Final[float] = 6.0
_EMO_UNI_COMPRESSION_HIGH: Final[float] = 0.80  # sharp "aha" moment everyone can describe
_EMO_UNI_COMPRESSION_MID: Final[float] = 0.65
_TOP_AUDIENCES_POOL: Final[int] = 8
_TOP_PICK_POOL: Final[int] = 10
_MIN_TAG_GROUPS: Final[int] = 2
_MAX_PREMISE_WORDS: Final[int] = 250

_log = logging.getLogger(__name__)
_MIN_TRIO_AUDIENCES: Final[int] = 2
_SINGLE_AUDIENCE: Final[int] = 1
_PAIR_AUDIENCES: Final[int] = 2
_ARC_DIV_HIGH: Final[float] = 9.0
_ARC_DIV_MID: Final[float] = 7.0
_SDT_MAX_INTENSITY: Final[float] = 1.5
# Reagan/Kim/Dodds 6-arc thresholds
_ARC6_CIV_EMO_UNI: Final[float] = 3.0
_ARC6_OEDIPUS_DIV: Final[float] = 8.5
_ARC6_ICARUS_DIV: Final[float] = 7.5
_ARC6_MAN_HOLE_DIV: Final[float] = 5.0
_LARGE_AUDIENCE_M: Final[float] = 400.0
_BODEN_TRANSFORM_THRESHOLD: Final[float] = 0.85
_BODEN_EXPLORE_THRESHOLD: Final[float] = 0.70
_AFFINITY_CROSSOVER: Final[float] = 0.30
_NON_AFFINITY_CROSSOVER: Final[float] = 0.15
_SINGLE_CAPTURE_RATE: Final[float] = 0.05
_ASSOC_SCALE: Final[float] = 0.70
_PROTAGONIST_POSITIVE_PROB: Final[float] = 0.70
# Commercial flags thresholds (EPAGOGIX/ScriptBook signal proxies)
_COMM_DRAMATIC_Q_DIV_FLOOR: Final[float] = 6.0
_COMM_CATHARSIS_EMO_UNI: Final[float] = 3.0
_COMM_GENRE_COHERENCE: Final[float] = 0.50
_COMM_AUDIENCE_BREADTH_M: Final[float] = 200.0
_COMM_WOM_DIV: Final[float] = 7.0
# Failure risk thresholds (Klein premortem)
_RISK_HIGH_DIV: Final[float] = 9.0
_RISK_LOW_COHERENCE: Final[float] = 0.40
_RISK_LOW_SOM_M: Final[float] = 80.0
_RISK_LOW_EMO_UNI: Final[float] = 2.0
_RISK_LOW_GOLDILOCKS: Final[float] = 0.50

# Prompt notes for non-human entity types (Issue #25 — entity type system)
_ENTITY_PROMPT_NOTES: Final[dict[str, str]] = {
    "HUMAN": "",
    "INSTITUTION": "(system/corp/govt — no individual is evil; the STRUCTURE is)",
    "ENVIRONMENT": "(nature/space/ocean — indifferent; drama from projecting meaning onto it)",
    "TECHNOLOGY": "(AI/machine — follows its logic perfectly; tragedy is unintended consequences)",
    "ORGANISM": "(virus/creature/alien — optimises survival; horror is the mirror it holds)",
    "ABSTRACT": "(time/grief/entropy — inevitable; the force you cannot fight)",
    "COLLECTIVE": "(civilisation/species — no single villain; force is distributed)",
}

# Cluster ID → human-readable name (Issues #23 + #24)
_CLUSTER_NAMES: Final[dict[int, str]] = {
    0: "institutional",
    1: "emotional",
    2: "technology",
    3: "identity",
    4: "nature",
    5: "economic",
    6: "temporal",
    7: "civilizational",
}
_CLUSTER_NAME_TO_ID: Final[dict[str, int]] = {v: k for k, v in _CLUSTER_NAMES.items()}

# Domain tag → cluster ID map (extended — covers all tags across all variable files)
_DOMAIN_CLUSTERS: Final[dict[str, int]] = {
    # 0 — institutional / procedural / authority
    "bureaucracy": 0,
    "institution": 0,
    "precision": 0,
    "authority": 0,
    "government": 0,
    "law": 0,
    "methodology": 0,
    "systemic": 0,
    "systemic_failure": 0,
    "complicity": 0,
    "investigation": 0,
    "expertise": 0,
    "accountability": 0,
    "obligation": 0,
    "honor": 0,
    "resistance": 0,
    "integrity": 0,
    "coercion": 0,
    "competence": 0,
    "work": 0,
    "workplace": 0,
    "recognition": 0,
    "war": 0,
    # 1 — emotional / relational
    "intimacy": 1,
    "family": 1,
    "grief": 1,
    "loss": 1,
    "love": 1,
    "care": 1,
    "trauma": 1,
    "sacrifice": 1,
    "belonging": 1,
    "protection": 1,
    "forgiveness": 1,
    "denial": 1,
    "guilt": 1,
    "moral_injury": 1,
    "isolation": 1,
    "loneliness": 1,
    "healing": 1,
    "reunion": 1,
    "companionship": 1,
    "fear": 1,
    # 2 — technology / AI / digital
    "technology": 2,
    "AI": 2,
    "automation": 2,
    "algorithm": 2,
    "digital": 2,
    "obsolescence": 2,
    "innovation": 2,
    # 3 — identity / culture / social
    "identity": 3,
    "culture": 3,
    "religion": 3,
    "tradition": 3,
    "history": 3,
    "gender": 3,
    "race": 3,
    "language": 3,
    "perception": 3,
    "social": 3,
    "political": 3,
    "invisibility": 3,
    "belief": 3,
    "betrayal": 3,
    "immigration": 3,
    "diaspora": 3,
    # 4 — nature / ecology / science
    "nature": 4,
    "ecology": 4,
    "climate": 4,
    "science": 4,
    "biology": 4,
    "measurement": 4,
    "limits": 4,
    "health": 4,
    "discovery": 4,
    # 5 — economics / class / labor
    "economics": 5,
    "class": 5,
    "labor": 5,
    "money": 5,
    "achievement": 5,
    "precarity": 5,
    "fairness": 5,
    # 6 — temporal / historical
    "time": 6,
    "future": 6,
    "past": 6,
    "anachronism": 6,
    "legacy": 6,
    "generation": 6,
    "era": 6,
    "obsession": 6,
    # 7 — civilizational / philosophical / existential
    "civilization": 7,
    "foundation": 7,
    "scale": 7,
    "truth": 7,
    "epistemology": 7,
    "morality": 7,
    "judgment": 7,
    "paradox": 7,
    "revelation": 7,
    "retroactive": 7,
    "feedback_loop": 7,
    "futility": 7,
    "structure": 7,
    "evidence": 7,
    "gap": 7,
    "new_category": 7,
    "perspective": 7,
    "duality": 7,
    "record": 7,
    "absence": 7,
    "success": 7,
    "failure": 7,
    "values": 7,
    "cost": 7,
    "complexity": 7,
    "hopelessness": 7,
    "humanity": 7,
    "understatement": 7,
    "ordinary": 7,
    "mirror": 7,
    "wonder": 7,
    "awe": 7,
    "exploration": 7,
    "heroism": 7,
    "courage": 7,
    "transformation": 7,
    "potential": 7,
    "redemption": 7,
    "self-doubt": 7,
    "journey": 7,
    "adventure": 7,
    "existential": 7,
    "epistemic": 7,
    "commitment": 7,
    "choice": 7,
    "reversal": 7,
    "mistake": 7,
    "responsibility": 7,
    "diffusion": 7,
    "change": 7,
    "surrender": 7,
    "power": 7,
    "talent": 7,
}


def _dict_list() -> list[dict[str, Any]]:
    """Typed default factory for list[dict] dataclass fields (pyright strict)."""
    return []


def _str_list() -> list[str]:
    """Typed default factory for list[str] dataclass fields (pyright strict)."""
    return []


@dataclass(frozen=True)
class CompoundScore:
    """All numeric outputs from the scoring pass — pure Python (ADR-0002)."""

    genius_score: float  # 0.0-1.0 weighted proxy for C001-C007
    associative_distance: float  # 0.0-1.0 target 0.3-0.5 (C002)
    goldilocks_score: float  # 1.0 when distance == 0.40; falls off on both sides
    sdt_intensity: float  # 1.0 or 1.5
    structural_surprise: float  # 0.0-1.0 (C001 proxy)
    compression_score: float  # 0.0-1.0 (C007 proxy)
    audience_overlap_M: float  # estimated millions in 3-audience Venn
    divisiveness_score: float  # 0-10
    organic_marketing_mult: float  # 1.0-3.0
    tam_M: float  # total addressable market: global theatrical by genre ($M, MPA 2023)
    sam_M: float  # serviceable addressable market: genre slice this concept reaches ($M)
    som_floor_M: float  # concept-stage SOM: realistic capture at this stage ($M, capped $400M)
    passes_500m_gate: bool
    passes_genius_gate: bool
    # New scoring dimensions (Issue #19-24 series)
    thematic_anchor_score: float  # 0.0-1.0 — variable coherence around structural_inversion
    emotional_universality_score: float  # 0.0-5.0 — $2B gate signal (Dark Knight=3.5, Avatar=5.0)
    # Issues #23 + #24 — explicit cluster coherence (replaces Jaccard approximation)
    primary_cluster: str  # dominant thematic_cluster across all narrative variables
    cluster_coherence: float  # 0.0-1.0 — fraction of variables sharing primary_cluster
    # Reagan/Kim/Dodds 6 narrative arc shapes (added post v1)
    arc_shape_6: str  # Cinderella | Man in a Hole | Rags to Riches | Icarus | Oedipus | Tragedy
    # Csikszentmihalyi cultural field alignment (0.0-1.0 zeitgeist fit)
    cultural_field_alignment: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompoundVariables:
    """All sampled variables before the intersection premise is generated."""

    themes: list[str]
    problems: list[str]
    tensions: list[dict[str, Any]]
    sdt_wound: dict[str, Any]
    psychological_pattern: dict[str, Any]
    structural_inversion: dict[str, Any]
    moral_fault_line: dict[str, Any]
    compression_key: dict[str, Any]
    divisiveness_engine: dict[str, Any]
    audiences: list[dict[str, Any]]
    world_texture: dict[str, Any]
    civilizational_stake: dict[str, Any] | None = None
    methodology_protagonist: dict[str, Any] | None = None
    historical_transplant: dict[str, Any] | None = None
    # All decorative slots are lists — empty = not sampled, N items = N picks
    era_collision: list[dict[str, Any]] = field(default_factory=_dict_list)
    conspiracy_engine: list[dict[str, Any]] = field(default_factory=_dict_list)
    reptile_trigger: list[dict[str, Any]] = field(default_factory=_dict_list)
    open_problem: list[dict[str, Any]] = field(default_factory=_dict_list)
    cultural_moment: list[dict[str, Any]] = field(default_factory=_dict_list)
    # Protagonist + antagonist shadow archetypes (paired for dramatic tension)
    dark_archetype: dict[str, Any] | None = None  # protagonist shadow
    antagonist_archetype: dict[str, Any] | None = None  # antagonist shadow
    # Entity types — not always human (Issue #25)
    protagonist_entity_type: str = "HUMAN"
    antagonist_entity_type: str = "HUMAN"
    # Positive hero archetype (aspirational identity layer — paired with dark_archetype shadow)
    protagonist_archetype: dict[str, Any] | None = None
    # Ally / secondary characters (dramatic_function drives intersection prompt)
    ally_archetypes: list[dict[str, Any]] = field(default_factory=_dict_list)
    # Additional decorative slots — multi-pick expansions beyond the primary pick
    # era_collision and open_problem are now list-based (like conspiracy/reptile)
    additional_world_textures: list[dict[str, Any]] = field(default_factory=_dict_list)
    additional_moral_fault_lines: list[dict[str, Any]] = field(default_factory=_dict_list)
    # Content format (v5.1.0) — the 20th axis. None = format-agnostic / legacy.
    # Routed through the ADR-0012 diversity penalty so the slate spans formats.
    format_value: dict[str, Any] | None = None


@dataclass
class CompoundSeedResult:
    """Complete compound seed ready for Phase 0 sidecar write."""

    run_id: str
    themes: list[str]
    problems: list[str]
    variables: CompoundVariables
    scores: CompoundScore
    intersection_premise: str
    hidden_attrs: dict[str, Any]
    commercial_signal_flags: dict[str, Any] = field(default_factory=dict)  # type: ignore[assignment]
    failure_risks: list[dict[str, Any]] = field(default_factory=_dict_list)
    #: v5.0 (ADR-0012) -- per-mutation provenance tags written by the
    #: :mod:`pipeline.operators.mental_models` operators.  Empty for engine
    #: base candidates; otherwise of the form
    #: ``["scamper:protagonist_archetype"]`` or ``["invert:structural_inversion"]``.
    #: The :mod:`pipeline.evolve.one_shot` orchestrator uses this both to
    #: avoid re-applying the same operator to a chain and to attribute
    #: winning concepts back to the operator that produced them.
    lineage: list[str] = field(default_factory=_str_list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "themes": self.themes,
            "problems": self.problems,
            "tensions": self.variables.tensions,
            "sdt_wound": self.variables.sdt_wound,
            "psychological_pattern": self.variables.psychological_pattern,
            "structural_inversion": self.variables.structural_inversion,
            "moral_fault_line": self.variables.moral_fault_line,
            "compression_key": self.variables.compression_key,
            "divisiveness_engine": self.variables.divisiveness_engine,
            "civilizational_stake": self.variables.civilizational_stake,
            "methodology_protagonist": self.variables.methodology_protagonist,
            "historical_transplant": self.variables.historical_transplant,
            "era_collision": self.variables.era_collision,
            "world_texture": self.variables.world_texture,
            "audiences": self.variables.audiences,
            "scores": self.scores.to_dict(),
            "conspiracy_engine": self.variables.conspiracy_engine,
            "reptile_trigger": self.variables.reptile_trigger,
            "open_problem": self.variables.open_problem,
            "cultural_moment": self.variables.cultural_moment,
            "dark_archetype": self.variables.dark_archetype,
            "antagonist_archetype": self.variables.antagonist_archetype,
            "protagonist_archetype": self.variables.protagonist_archetype,
            "protagonist_entity_type": self.variables.protagonist_entity_type,
            "antagonist_entity_type": self.variables.antagonist_entity_type,
            "ally_archetypes": self.variables.ally_archetypes,
            "format": self.variables.format_value,
            "commercial_signal_flags": self.commercial_signal_flags,
            "failure_risks": self.failure_risks,
            "intersection_premise": self.intersection_premise,
            "hidden_attrs": self.hidden_attrs,
            "lineage": list(self.lineage),
        }


class CompoundSeedEngine:
    """Samples and scores compound seeds from the variable library."""

    def __init__(
        self,
        vars_path: Path = _VARS_PATH,
        ontology_path: Path = _ONTOLOGY_PATH,
        rng_seed: int | None = None,
    ) -> None:
        self._rng = random.Random(rng_seed)  # noqa: S311
        self._vars = _load_json(vars_path)
        self._ontology = _load_json(ontology_path) if ontology_path.exists() else {}
        self._binary_tensions: list[dict[str, Any]] = self._load_binary_tensions()
        self._conspiracy: list[dict[str, Any]] = (
            _load_json_list(_CONSPIRACY_PATH) if _CONSPIRACY_PATH.exists() else []
        )
        self._reptile: list[dict[str, Any]] = (
            _load_json_list(_REPTILE_PATH) if _REPTILE_PATH.exists() else []
        )
        self._open_problems: list[dict[str, Any]] = (
            _load_json_list(_OPEN_PROBLEMS_PATH) if _OPEN_PROBLEMS_PATH.exists() else []
        )
        self._cultural_moments: list[dict[str, Any]] = (
            _load_json_list(_CULTURAL_MOMENT_PATH) if _CULTURAL_MOMENT_PATH.exists() else []
        )
        self._dark_archetypes: list[dict[str, Any]] = (
            _load_json_list(_DARK_ARCHETYPES_PATH) if _DARK_ARCHETYPES_PATH.exists() else []
        )
        self._ally_archetypes: list[dict[str, Any]] = (
            _load_json_list(_ALLY_ARCHETYPES_PATH) if _ALLY_ARCHETYPES_PATH.exists() else []
        )
        self._protagonist_archetypes: list[dict[str, Any]] = (
            _load_json_list(_PROTAGONIST_ARCHETYPES_PATH)
            if _PROTAGONIST_ARCHETYPES_PATH.exists()
            else []
        )
        #: Content formats (v5.1.0) — sampled as the 20th ADR-0012 axis.
        self._formats: list[dict[str, Any]] = cast(
            "list[dict[str, Any]]", self._vars.get("formats", [])
        )

    @classmethod
    def from_defaults(cls) -> CompoundSeedEngine:
        return cls()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        themes: list[str] | None = None,
        problems: list[str] | None = None,
        n_tensions: int = 2,
        n_conspiracy: int = 1,
        n_reptile: int = 1,
        n_cultural_moment: int = 1,
        n_audiences: int = 3,
        n_era: int = 1,  # 0=never, 1=40% prob, 2+=always sample N era collisions
        n_open_problems: int = 1,  # how many unsolved science hooks (0-2)
        n_worlds: int = 1,  # how many world textures (1=primary only, 2=add secondary)
        n_moral: int = 1,  # how many moral fault lines (1=primary only, 2=add secondary)
        # Entity type: HUMAN | INSTITUTION | ENVIRONMENT | TECHNOLOGY | ORGANISM | ABSTRACT
        protagonist_entity_type: str = "HUMAN",
        antagonist_entity_type: str = "HUMAN",
        force_historical_transplant: str | None = None,
        force_civilizational: bool = False,
        force_conspiracy: bool = False,
        force_reptile: bool = False,
        force_open_problem: bool = False,
        force_cultural_moment: bool = False,
        force_dark_archetype: bool = False,
        target_som_M: float = _TARGET_SOM_M,
        max_attempts: int = _MAX_GENERATION_ATTEMPTS,
        genre_bias_penalty_weight: float = 0.6,
        n_allies: int = 1,  # 0=none, 1=one ally archetype, 2=ally pair
        freq_table: dict[tuple[str, str], int] | None = None,
        n_formats: int = 1,  # 0=format-agnostic, 1=sample one content format (v5.1.0)
        force_format: str | None = None,  # pin a format by name/id/economics_key
    ) -> CompoundSeedResult:
        """Generate a compound seed targeting the given SOM floor.

        Tries up to max_attempts random combinations, scores each, and returns
        the first that passes both the genius gate and SOM gate.
        If no combination passes within the attempt cap, returns the best
        scoring attempt with a warning flag in hidden_attrs.

        ``genre_bias_penalty_weight`` (0.0-1.0) controls how strongly operator
        ``themes`` and ``problems`` steer variable sampling away from the
        institutional/thriller cluster. 0.0 = pure random; 0.6 = default
        de-bias; 1.0 = maximum avoidance of unmatched clusters.  When themes
        and problems are both empty the weight has no effect.
        """
        themes = themes or []
        problems = problems or []
        # Pre-compute theme clusters once; passed into every sampling attempt.
        # Combines both themes and real-world problems so operators can pass
        # e.g. problems=["AI displacement", "loneliness epidemic"] and have
        # sampling automatically prefer technology- and intimacy-tagged vars.
        target_clusters = _theme_keywords_to_clusters(themes + problems)
        best: CompoundSeedResult | None = None
        best_score = 0.0

        for attempt in range(max_attempts):
            variables = self._sample_variables(
                themes=themes,
                problems=problems,
                n_tensions=n_tensions,
                n_conspiracy=n_conspiracy,
                n_reptile=n_reptile,
                n_cultural_moment=n_cultural_moment,
                n_audiences=n_audiences,
                n_era=n_era,
                n_open_problems=n_open_problems,
                n_worlds=n_worlds,
                n_moral=n_moral,
                protagonist_entity_type=protagonist_entity_type,
                antagonist_entity_type=antagonist_entity_type,
                force_historical_transplant=force_historical_transplant,
                force_civilizational=force_civilizational,
                force_conspiracy=force_conspiracy,
                force_reptile=force_reptile,
                force_open_problem=force_open_problem,
                force_cultural_moment=force_cultural_moment,
                force_dark_archetype=force_dark_archetype,
                target_clusters=target_clusters,
                genre_bias_penalty_weight=genre_bias_penalty_weight,
                n_allies=n_allies,
                freq_table=freq_table,
                n_formats=n_formats,
                force_format=force_format,
            )
            scores = self._score(variables)

            comm_flags = _compute_commercial_flags(variables, scores)
            fail_risks = _compute_failure_risks(variables, scores)

            if scores.som_floor_M >= target_som_M and scores.passes_genius_gate:
                intersection = self._generate_intersection_prompt(variables)
                hidden = self._build_hidden_attrs(variables)
                return CompoundSeedResult(
                    run_id=f"compound_{attempt:03d}",
                    themes=themes,
                    problems=problems,
                    variables=variables,
                    scores=scores,
                    intersection_premise=intersection,
                    hidden_attrs=hidden,
                    commercial_signal_flags=comm_flags,
                    failure_risks=fail_risks,
                )

            if scores.genius_score > best_score:
                best_score = scores.genius_score
                best = CompoundSeedResult(
                    run_id="compound_best",
                    themes=themes,
                    problems=problems,
                    variables=variables,
                    scores=scores,
                    intersection_premise=self._generate_intersection_prompt(variables),
                    hidden_attrs=self._build_hidden_attrs(variables),
                    commercial_signal_flags=comm_flags,
                    failure_risks=fail_risks,
                )
                best.hidden_attrs["_warning"] = (
                    f"Did not reach ${target_som_M}M SOM gate after {max_attempts} attempts. "
                    f"Best score: {best_score:.2f}. Best SOM floor: {scores.som_floor_M:.0f}M."
                )

        if best is None:
            raise RuntimeError(
                "compound seed search produced no candidate "
                f"(all {max_attempts} attempts scored 0.0)"
            )
        return best

    def write_seed(self, result: CompoundSeedResult, run_dir: Path) -> Path:
        """Write compound_seed.json to run_dir using atomic safe_write (ADR-0001)."""
        from pipeline.state import safe_write  # noqa: PLC0415

        out_path = run_dir / "compound_seed.json"
        safe_write(out_path, json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return out_path

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def _sample_variables(
        self,
        themes: list[str],
        problems: list[str],
        n_tensions: int,
        n_conspiracy: int,
        n_reptile: int,
        n_cultural_moment: int,
        n_audiences: int,
        n_era: int,
        n_open_problems: int,
        n_worlds: int,
        n_moral: int,
        protagonist_entity_type: str,
        antagonist_entity_type: str,
        force_historical_transplant: str | None,
        force_civilizational: bool,
        force_conspiracy: bool = False,
        force_reptile: bool = False,
        force_open_problem: bool = False,
        force_cultural_moment: bool = False,
        force_dark_archetype: bool = False,
        target_clusters: set[int] | None = None,
        genre_bias_penalty_weight: float = 0.6,
        n_allies: int = 1,
        freq_table: dict[tuple[str, str], int] | None = None,
        n_formats: int = 1,
        force_format: str | None = None,
    ) -> CompoundVariables:
        _tc: set[int] = target_clusters or set()
        _pw: float = genre_bias_penalty_weight
        tensions = self._sample_tensions(n_tensions)
        sdt_wound: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["sdt_wounds"],
            _tc,
            _pw,
            freq_table=freq_table,
            axis_name="sdt_wound",
        )
        psych: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["psychological_patterns"],
            _tc,
            _pw,
            freq_table=freq_table,
            axis_name="psychological_pattern",
        )
        inversion: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["structural_inversions"],
            _tc,
            _pw,
            freq_table=freq_table,
            axis_name="structural_inversion",
        )
        fault_line: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["moral_fault_lines"],
            _tc,
            _pw,
            freq_table=freq_table,
            axis_name="moral_fault_line",
        )
        # R3: route through the penalized chooser so the cross-run diversity
        # penalty applies (was raw rng.choice -> these axes bypassed ADR-0012 and
        # collapsed to ~90% on the rolling window). Empty targets + 0.0 weight ->
        # identical to rng.choice when freq_table is None (tests unaffected); the
        # penalty only fires in production where one_shot passes a freq_table.
        compression: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["compression_keys"],
            set(),
            0.0,
            freq_table=freq_table,
            axis_name="compression_key",
        )
        divisiveness: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["divisiveness_engines"],
            set(),
            0.0,
            freq_table=freq_table,
            axis_name="divisiveness_engine",
        )
        world: dict[str, Any] = _thematic_weighted_choice(
            self._rng,
            self._vars["world_textures"],
            _tc,
            _pw,
            freq_table=freq_table,
            axis_name="world_texture",
        )
        audiences = self._sample_audiences(n_audiences)

        # Historical transplant — forced or 30% random chance
        transplant: dict[str, Any] | None = None
        if force_historical_transplant:
            transplant = self._get_by_id(
                self._vars["historical_methodology_transplants"],
                force_historical_transplant,
            )
        elif self._rng.random() < _TRANSPLANT_RANDOM_PROB:
            transplant = _thematic_weighted_choice(
                self._rng,
                self._vars["historical_methodology_transplants"],
                set(),
                0.0,
                freq_table=freq_table,
                axis_name="historical_transplant",
            )

        # Civilizational stake — forced or when transplant present or 20% chance
        civ_stake: dict[str, Any] | None = None
        civ_random = self._rng.random() < _CIV_STAKE_RANDOM_PROB
        if force_civilizational or transplant is not None or civ_random:
            civ_stake = _thematic_weighted_choice(
                self._rng,
                self._vars["civilizational_stakes"],
                set(),
                0.0,
                freq_table=freq_table,
                axis_name="civilizational_stake",
            )

        # Methodology protagonist — when civilizational stake or transplant present
        meth_prot: dict[str, Any] | None = None
        if civ_stake is not None or transplant is not None:
            meth_prot = _thematic_weighted_choice(
                self._rng,
                self._vars["methodology_protagonists"],
                set(),
                0.0,
                freq_table=freq_table,
                axis_name="methodology_protagonist",
            )

        # n_era=0 never, n_era=1 uses probability gate, n_era>=_ERA_FORCE_MIN forces
        _sample = self._rng.sample
        era_pool = self._vars["era_collisions"]
        era: list[dict[str, Any]] = (
            _sample(era_pool, min(n_era, len(era_pool)))
            if n_era > 0 and (n_era >= _ERA_FORCE_MIN or self._rng.random() < _ERA_COLLISION_PROB)
            else []
        )

        # Additional world textures and moral fault lines
        extra_worlds, extra_morals = self._sample_extras(n_worlds, n_moral, fault_line)

        # New axes — sampled from frameworks/data/ (ADR-0005: file I/O only, never imported)
        conspiracy: list[dict[str, Any]] = (
            _sample(self._conspiracy, min(n_conspiracy, len(self._conspiracy)))
            if force_conspiracy or (self._conspiracy and self._rng.random() < _CONSPIRACY_PROB)
            else []
        )
        reptile: list[dict[str, Any]] = (
            _sample(self._reptile, min(n_reptile, len(self._reptile)))
            if force_reptile or (self._reptile and self._rng.random() < _REPTILE_PROB)
            else []
        )
        open_prob: list[dict[str, Any]] = (
            _sample(self._open_problems, min(n_open_problems, len(self._open_problems)))
            if force_open_problem
            or (self._open_problems and self._rng.random() < _OPEN_PROBLEM_PROB)
            else []
        )
        cultural: list[dict[str, Any]] = []
        if force_cultural_moment or (
            self._cultural_moments and self._rng.random() < _CULTURAL_MOMENT_PROB
        ):
            try:
                from pipeline.zeitgeist_probe import boost_weights as _boost  # noqa: PLC0415
                from pipeline.zeitgeist_probe import load_cached as _load_cached  # noqa: PLC0415

                _weights = _boost(self._cultural_moments, _load_cached() or [])
                cultural = self._rng.choices(
                    self._cultural_moments,
                    weights=_weights,
                    k=min(n_cultural_moment, len(self._cultural_moments)),
                )
            except Exception:
                cultural = _sample(
                    self._cultural_moments,
                    min(n_cultural_moment, len(self._cultural_moments)),
                )

        # Protagonist + antagonist shadow archetypes — contrast pair drives dramatic tension
        protagonist_arch: dict[str, Any] | None = None
        antagonist_arch: dict[str, Any] | None = None
        if force_dark_archetype or (
            self._dark_archetypes and self._rng.random() < _DARK_ARCHETYPE_PROB
        ):
            protagonist_arch = _thematic_weighted_choice(
                self._rng,
                self._dark_archetypes,
                set(),
                0.0,
                freq_table=freq_table,
                axis_name="dark_archetype",
            )
            remaining_archetypes = [a for a in self._dark_archetypes if a != protagonist_arch]
            if remaining_archetypes:
                antagonist_arch = self._rng.choice(remaining_archetypes)

        allies = self._sample_allies(n_allies, _tc, _pw, freq_table=freq_table)

        protagonist_positive = self._sample_protagonist_positive(_tc, _pw, freq_table=freq_table)

        # Format axis (v5.1.0) sampled LAST so it never perturbs the RNG stream
        # for the narrative axes above (preserves byte-identical seeded output
        # for every pre-format callsite).
        format_value = self._sample_format(n_formats, force_format, freq_table=freq_table)

        return CompoundVariables(
            themes=themes,
            problems=problems,
            tensions=tensions,
            sdt_wound=sdt_wound,
            psychological_pattern=psych,
            structural_inversion=inversion,
            moral_fault_line=fault_line,
            compression_key=compression,
            divisiveness_engine=divisiveness,
            audiences=audiences,
            world_texture=world,
            civilizational_stake=civ_stake,
            methodology_protagonist=meth_prot,
            historical_transplant=transplant,
            era_collision=era,
            conspiracy_engine=conspiracy,
            reptile_trigger=reptile,
            open_problem=open_prob,
            cultural_moment=cultural,
            dark_archetype=protagonist_arch,
            antagonist_archetype=antagonist_arch,
            protagonist_archetype=protagonist_positive,
            protagonist_entity_type=protagonist_entity_type,
            antagonist_entity_type=antagonist_entity_type,
            ally_archetypes=allies,
            additional_world_textures=extra_worlds,
            additional_moral_fault_lines=extra_morals,
            format_value=format_value,
        )

    def _sample_tensions(self, n: int) -> list[dict[str, Any]]:
        """Sample n binary tensions with diversity constraint (no two share pole_a domain)."""
        if not self._binary_tensions:
            return []
        chosen: list[dict[str, Any]] = []
        used_poles: set[str] = set()
        attempts = 0
        max_n = min(n, len(self._binary_tensions))
        while len(chosen) < max_n and attempts < _TENSION_SAMPLE_ATTEMPTS:
            attempts += 1
            candidate = self._rng.choice(self._binary_tensions)
            pole_a = str(candidate.get("pole_a", candidate.get("id", "")))
            if pole_a not in used_poles:
                chosen.append(candidate)
                used_poles.add(pole_a)
        return chosen

    def _sample_audiences(self, n: int) -> list[dict[str, Any]]:
        """Sample n audiences (clamped to 2-5) with affinity diversity."""
        n = max(2, min(n, 5))
        domains = self._vars["audience_domains"]
        chosen: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        # Prefer large audiences for the first pick
        sorted_domains = sorted(domains, key=lambda d: d.get("size_M", 0), reverse=True)
        # Primary: from top-8 largest
        primary = self._rng.choice(sorted_domains[:_TOP_AUDIENCES_POOL])
        chosen.append(primary)
        used_ids.add(str(primary["id"]))

        # Secondary and tertiary: not in affinity_with of primary; still large
        primary_affinity: set[str] = {str(x) for x in primary.get("affinity_with", [])}
        remaining: list[dict[str, Any]] = [
            d
            for d in sorted_domains
            if str(d["id"]) not in used_ids and str(d["id"]) not in primary_affinity
        ]
        for _ in range(n - 1):
            if not remaining:
                break
            pool: list[dict[str, Any]] = remaining[:_TOP_PICK_POOL]
            pick: dict[str, Any] = self._rng.choice(pool)
            chosen.append(pick)
            used_ids.add(str(pick["id"]))
            remaining = [d for d in remaining if str(d["id"]) not in used_ids]

        return chosen

    def _sample_allies(
        self,
        n: int,
        target_clusters: set[int],
        penalty_weight: float,
        *,
        freq_table: dict[tuple[str, str], int] | None = None,
    ) -> list[dict[str, Any]]:
        """Sample up to n ally archetypes, cluster-steered when target_clusters provided."""
        if n <= 0 or not self._ally_archetypes:
            return []
        n_pick = min(n, len(self._ally_archetypes))
        if not target_clusters:
            return self._rng.sample(self._ally_archetypes, n_pick)
        raw = [
            _thematic_weighted_choice(
                self._rng,
                self._ally_archetypes,
                target_clusters,
                penalty_weight,
                freq_table=freq_table,
                axis_name="ally_archetype",
            )
            for _ in range(n_pick * 2)  # oversample to get n_pick unique
        ]
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for a in raw:
            aid = str(a.get("id", ""))
            if aid not in seen:
                seen.add(aid)
                unique.append(a)
            if len(unique) == n_pick:
                break
        return unique

    def _sample_format(
        self,
        n_formats: int,
        force_format: str | None,
        freq_table: dict[tuple[str, str], int] | None = None,
    ) -> dict[str, Any] | None:
        """Sample a single content format — the 20th ADR-0012 axis (v5.1.0).

        ``force_format`` pins a format by display name, id, or economics_key
        (case-insensitive); an unknown value returns ``None`` (explicit, never
        a silent random pick). Otherwise, when formats are loaded and
        ``n_formats > 0``, one is sampled with probability
        :data:`_FORMAT_SAMPLE_PROB`, routed through the cross-run diversity
        penalty (uniform cluster weighting + ``freq_table``) so no single
        format dominates the rolling window — the mechanism that spreads the
        slate across Feature / Series / Animation / Microdrama. Returns
        ``None`` when unsampled (legacy callers see a format-agnostic seed).
        """
        if not self._formats:
            return None
        if force_format:
            needle = force_format.strip().lower()
            for fmt in self._formats:
                candidates = {
                    str(fmt.get("name", "")).lower(),
                    str(fmt.get("id", "")).lower(),
                    str(fmt.get("economics_key", "")).lower(),
                }
                if needle in candidates:
                    return fmt
            return None
        if n_formats <= 0 or self._rng.random() >= _FORMAT_SAMPLE_PROB:
            return None
        return _thematic_weighted_choice(
            self._rng,
            self._formats,
            set(),
            0.0,
            freq_table=freq_table,
            axis_name="format",
        )

    def _sample_extras(
        self,
        n_worlds: int,
        n_moral: int,
        fault_line: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Sample additional world textures and moral fault lines."""
        _s = self._rng.sample
        worlds_pool: list[dict[str, Any]] = self._vars["world_textures"]
        extra_worlds: list[dict[str, Any]] = (
            _s(worlds_pool, min(n_worlds - 1, len(worlds_pool) - 1))
            if n_worlds > 1 and len(worlds_pool) > 1
            else []
        )
        moral_pool: list[dict[str, Any]] = self._vars["moral_fault_lines"]
        extra_morals: list[dict[str, Any]] = (
            _s(
                [m for m in moral_pool if m != fault_line],
                min(n_moral - 1, len(moral_pool) - 1),
            )
            if n_moral > 1 and len(moral_pool) > 1
            else []
        )
        return extra_worlds, extra_morals

    def _sample_protagonist_positive(
        self,
        target_clusters: set[int],
        penalty_weight: float,
        *,
        freq_table: dict[tuple[str, str], int] | None = None,
    ) -> dict[str, Any] | None:
        """Sample a positive hero archetype with 70% probability."""
        if self._protagonist_archetypes and self._rng.random() < _PROTAGONIST_POSITIVE_PROB:
            return _thematic_weighted_choice(
                self._rng,
                self._protagonist_archetypes,
                target_clusters,
                penalty_weight,
                freq_table=freq_table,
                axis_name="protagonist_archetype",
            )
        return None

    # ------------------------------------------------------------------
    # Scoring (pure Python — ADR-0002)
    # ------------------------------------------------------------------

    def _score(self, v: CompoundVariables) -> CompoundScore:
        # --- Associative distance (C002 proxy) ---
        all_domain_tags: list[list[str]] = (
            [t.get("domain_tags", []) for t in v.tensions]
            + [v.psychological_pattern.get("domain_tags", [])]
            + [v.structural_inversion.get("domain_tags", [])]
        )
        if v.historical_transplant:
            all_domain_tags.append(v.historical_transplant.get("domain_tags", []))
        assoc_dist = _compute_associative_distance(all_domain_tags)
        goldilocks = 1.0 - abs(assoc_dist - _ASSOC_TARGET) / _ASSOC_TOLERANCE
        goldilocks = max(0.0, min(1.0, goldilocks))

        # --- SDT intensity (C003 proxy) ---
        sdt_intensity = float(v.sdt_wound.get("deprivation_intensity", 1.0))

        # --- Structural surprise (C001 proxy) ---
        inversion_sw = float(v.structural_inversion.get("surprise_weight", 0.5))
        psych_sw = float(v.psychological_pattern.get("surprise_weight", 0.5))
        transplant_sw = float(
            v.historical_transplant.get("surprise_weight", 0.0) if v.historical_transplant else 0.0
        )
        civ_sw = float(
            v.civilizational_stake.get("surprise_weight", 0.0) if v.civilizational_stake else 0.0
        )
        structural_surprise = max(inversion_sw, psych_sw, transplant_sw, civ_sw)

        # --- Compression score (C007 proxy) ---
        compression_score = float(v.compression_key.get("surprise_weight", 0.5))

        # --- Audience overlap ---
        audience_overlap_M = _compute_audience_overlap(v.audiences)

        # --- Divisiveness ---
        divisiveness = float(v.divisiveness_engine.get("score", 5.0))
        organic_mult = float(v.divisiveness_engine.get("organic_marketing_multiplier", 1.0))

        # --- Civilizational audience bonus ---
        if v.civilizational_stake:
            civ_resonance = float(v.civilizational_stake.get("audience_resonance_M", 0))
            audience_overlap_M = max(audience_overlap_M, civ_resonance * 0.30)

        # --- Genius score composite (ADR-0002 — all weights documented) ---
        # Weights v2 (bias-corrected per top-3000 corpus audit):
        #   goldilocks 25% (C001+C002) — novel-but-coherent premise
        #   sdt_intensity 25% (C003) — raised from 20%; emotional universality drives Titanic/Avatar
        #   structural_surprise 22% (C001) — slightly raised; inversion = commercial differentiation
        #   audience 20% (scale) — unchanged; broad reach required for $2B
        #   divisiveness 8% — reduced from 15%; Frozen II/Inside Out 2 have div=2, gross $1.4-1.7B
        genius_score = (
            goldilocks * 0.25
            + (sdt_intensity / 1.5) * 0.25
            + structural_surprise * 0.22
            + (min(audience_overlap_M, 600.0) / 600.0) * 0.20
            + (divisiveness / 10.0) * 0.08
        )
        # Compression bonus — smooth curve instead of cliff (ADR-0002)
        # Cliff penalised distributed-arc films (Titanic, Top Gun: Maverick)
        if compression_score >= _COMPRESSION_BONUS_HIGH:
            genius_score = min(1.0, genius_score * 1.10)  # was 1.20
        elif compression_score >= _COMPRESSION_BONUS_MID:
            genius_score = min(1.0, genius_score * 1.05)  # was 1.10

        # --- Thematic anchor (bonus multiplier — gentle; ensemble films score lower here) ---
        # Reduced: 1.15→1.08 and 1.08→1.03 to avoid penalising Avengers-style
        # distributed thematic arcs which dominate the top-20 grossing films.
        thematic_anchor = _compute_thematic_anchor(v)
        if thematic_anchor >= _THEMATIC_ANCHOR_HIGH:
            genius_score = min(1.0, genius_score * 1.08)
        elif thematic_anchor >= _THEMATIC_ANCHOR_MID:
            genius_score = min(1.0, genius_score * 1.03)

        # --- Emotional universality (SOM booster: signals $2B demographic breadth) ---
        emotional_uni = _compute_emotional_universality(v)

        # --- TAM → SAM → SOM (anchored to top-3000 corpus) ---
        # TAM: $40B global theatrical (MPA 2023)
        # SAM: genre slice (~12% for mixed-genre original)
        # SOM: concept-stage capture rate x SAM
        #
        # Only 6 films ever crossed $2B worldwide (top-3000 corpus).
        # Only Avatar & Titanic are original IP above $2B; both needed $200M+
        # budgets, A-list directors, and years of development.
        # Concept-stage ceiling: $400M. Greenlit+A-list multiplies by 2-5x later.
        genre_sam_M: float = _GLOBAL_THEATRICAL_TAM_M * _GENRE_TAM_FRACTION
        # Audience reach factor: how much of the genre SAM this concept can address
        audience_factor: float = min(audience_overlap_M / 300.0, 2.0)
        # Capture rate scales with concept quality (genius_score) — 1.25% to 3.75%
        capture_rate: float = _CONCEPT_CAPTURE_BASE * (0.5 + genius_score * 0.5)
        # Organic boost from divisiveness (capped at 2x; even Joker didn't get 3x)
        organic_factor: float = min(organic_mult, 2.0)
        # Emotional universality factor (0.8x to 1.6x)
        emo_factor: float = 0.8 + min(emotional_uni / 5.0, 0.8)
        som_uncapped: float = (
            genre_sam_M * audience_factor * capture_rate * organic_factor * emo_factor
        )
        som_floor_M: float = min(som_uncapped, _CONCEPT_STAGE_CEILING_M)

        # --- Cluster coherence (Issues #23 + #24) ---
        primary_cluster, cluster_coherence = _compute_cluster_coherence(v)

        # --- Reagan/Kim/Dodds 6-arc shape ---
        arc_shape_6 = _derive_arc_shape_6(
            divisiveness, sdt_intensity, emotional_uni, v.civilizational_stake is not None
        )

        # --- Cultural field alignment (Csikszentmihalyi systems model) ---
        cultural_field_alignment = _compute_cultural_field_alignment(v)

        return CompoundScore(
            genius_score=round(genius_score, 4),
            associative_distance=round(assoc_dist, 4),
            goldilocks_score=round(goldilocks, 4),
            sdt_intensity=sdt_intensity,
            structural_surprise=round(structural_surprise, 4),
            compression_score=round(compression_score, 4),
            audience_overlap_M=round(audience_overlap_M, 1),
            divisiveness_score=divisiveness,
            organic_marketing_mult=organic_mult,
            tam_M=round(_GLOBAL_THEATRICAL_TAM_M, 1),
            sam_M=round(genre_sam_M * audience_factor, 1),
            som_floor_M=round(som_floor_M, 1),
            passes_500m_gate=som_floor_M >= _TARGET_SOM_M,
            passes_genius_gate=genius_score >= _MIN_GENIUS_SCORE,
            thematic_anchor_score=round(thematic_anchor, 4),
            emotional_universality_score=round(emotional_uni, 2),
            primary_cluster=primary_cluster,
            cluster_coherence=round(cluster_coherence, 3),
            arc_shape_6=arc_shape_6,
            cultural_field_alignment=cultural_field_alignment,
        )

    # ------------------------------------------------------------------
    # Intersection premise (Haiku prompt — goes through cc_dispatch)
    # ------------------------------------------------------------------

    def _generate_intersection_prompt(self, v: CompoundVariables) -> str:
        """Build the intersection description.

        Returns a structured prompt string that cc_dispatch can send to Haiku.
        In single-idea pipeline mode this is resolved by the concept-drafter
        agent reading the compound_seed.json. This method produces a rich
        natural-language brief that IS the intersection premise when Haiku
        is unavailable (e.g., in tests).
        """
        lines: list[str] = [
            "Find the story that REQUIRES all of the following elements to be simultaneously true.",
            "Write 150-250 words. No framework names. Plain English.",
            "",
        ]
        if v.themes:
            lines.append(f"Themes the operator provided: {'; '.join(v.themes)}")
        if v.problems:
            lines.append(f"Real-world problems in scope: {'; '.join(v.problems)}")
        lines.append("")

        if v.historical_transplant:
            ht = v.historical_transplant
            lines.append(
                f"A methodology born in {ht.get('era_of_origin', 'the past')} — "
                f"{ht.get('methodology', '')} — must now confront: {ht.get('modern_crisis', '')}. "
                f"The bridge: {ht.get('bridge', '')}."
            )

        if v.civilizational_stake:
            lines.append(f"What is at stake: {v.civilizational_stake['description']}")

        if v.methodology_protagonist:
            lines.append(f"Story engine: {v.methodology_protagonist['description']}")

        lines.append(f"Protagonist's inner wound: {v.sdt_wound['description']}")
        lines.append(
            f"Psychological pattern driving behavior: {v.psychological_pattern['description']}"
        )
        lines.append(
            "Structural inversion (unlike every comparable): "
            + str(v.structural_inversion["description"])
        )
        lines.append(
            "Moral fault line (two valid answers): " + str(v.moral_fault_line["description"])
        )
        lines.append(f"The 'aha' / compression moment: {v.compression_key['description']}")
        lines.append(f"Why audiences will argue about it: {v.divisiveness_engine['description']}")
        lines.append(f"World it lives in: {v.world_texture['name']}")

        lines.extend(self._new_axes_prompt_lines(v))

        lines.extend(self._extra_context_lines(v))

        if v.tensions:
            tension_strs = [
                f"'{t.get('pole_a', '')} vs {t.get('pole_b', '')}'"
                for t in v.tensions
                if t.get("pole_a") and t.get("pole_b")
            ]
            if tension_strs:
                lines.append(f"Core tensions in collision: {', '.join(tension_strs)}")

        lines.append("")
        lines.append("Audience entry points (three doors into the same story):")
        for i, aud in enumerate(v.audiences[:3], 1):
            lines.append(
                f"  {i}. {aud.get('name', '')} — enters because: {aud.get('entry_condition', '')}"
            )

        lines.extend(self._character_architecture_lines(v))

        lines.append("")
        lines.append("Now write the intersection premise in 150-250 words.")

        # Append prior-run failure modes as negative constraints (Issue #10).
        if _lessons_loader is not None:
            failures = _lessons_loader.load_failures(max_items=5)
            if failures:
                lines.append("")
                lines.append(
                    "AVOID these failure modes from prior runs: "
                    + "; ".join(f'"{f}"' for f in failures)
                )

        template_prompt = "\n".join(lines)
        return self._call_haiku_for_premise(template_prompt)

    @staticmethod
    def _new_axes_prompt_lines(v: CompoundVariables) -> list[str]:
        """Return prompt lines for the framework-data axes.

        conspiracy_engine, reptile_trigger, cultural_moment are lists (multi-pick);
        open_problem, dark_archetype, antagonist_archetype remain single dicts.
        Extracted to keep _generate_intersection_prompt under the 12-branch limit.
        """
        _L, _F = "label", "primary_fear"
        out: list[str] = []

        if v.conspiracy_engine:
            labels = "; ".join(item.get(_L, "") for item in v.conspiracy_engine)
            fears = "; ".join(item.get(_F, "") for item in v.conspiracy_engine)
            out.append(f"Conspiracy lenses ({len(v.conspiracy_engine)}): {labels}. Fears: {fears}")

        if v.reptile_trigger:
            labels = "; ".join(item.get(_L, "") for item in v.reptile_trigger)
            fears = "; ".join(item.get(_F, "") for item in v.reptile_trigger)
            out.append(f"Primal fear drives ({len(v.reptile_trigger)}): {labels}. Fears: {fears}")

        if v.open_problem:
            labels = "; ".join(item.get(_L, "") for item in v.open_problem)
            fears = "; ".join(item.get(_F, "") for item in v.open_problem)
            out.append(f"Unsolved mysteries ({len(v.open_problem)}): {labels}. {fears}")

        if v.cultural_moment:
            labels = "; ".join(item.get(_L, "") for item in v.cultural_moment)
            fears = "; ".join(item.get(_F, "") for item in v.cultural_moment)
            out.append(
                f"2026 cultural tensions ({len(v.cultural_moment)}): {labels}. Fears: {fears}"
            )

        if v.dark_archetype:
            out.append(
                f"Protagonist shadow: {v.dark_archetype.get(_L, '')}: "
                f"{v.dark_archetype.get(_F, '')}"
            )
        if v.antagonist_archetype:
            out.append(
                f"Antagonist shadow: {v.antagonist_archetype.get(_L, '')}: "
                f"{v.antagonist_archetype.get(_F, '')}"
            )
        return out

    @staticmethod
    def _character_architecture_lines(v: CompoundVariables) -> list[str]:
        """Prompt lines that build specific characters with worldview depth.

        Extracted to keep _generate_intersection_prompt under the 12-branch limit.
        The Matrix, Joker, Dark Knight work because antagonists have COHERENT WORLDVIEWS,
        not because they are evil. This section forces that depth into the premise.
        """
        p_type = v.protagonist_entity_type
        a_type = v.antagonist_entity_type
        p_note = _ENTITY_PROMPT_NOTES.get(p_type, "")
        a_note = _ENTITY_PROMPT_NOTES.get(a_type, "")

        out: list[str] = ["", "CHARACTER ARCHITECTURE (specific entities, not types):"]
        if v.dark_archetype and p_type == "HUMAN":
            _wv = v.dark_archetype.get("worldview_logic", "")
            _pa = v.dark_archetype.get("philosophical_anchor", "")
            out.append(
                f"Protagonist {p_note}: wound = '{v.sdt_wound['description']}'. "
                f"Shadow: {v.dark_archetype.get('label', '')}. "
                + (f"Worldview: {_wv} " if _wv else "")
                + (f"Philosophical anchor: {_pa} " if _pa else "")
                + "Define: (a) unshakeable conviction, "
                "(b) sacrifice they REFUSE, "
                "(c) choice that forces them to break that refusal."
            )
        elif p_type != "HUMAN":
            out.append(
                f"Protagonist is {p_type} {p_note}. "
                f"Core wound still applies: '{v.sdt_wound['description']}'. "
                "How does a non-human entity embody this wound? "
                "What would it mean for this force to 'want' something?"
            )
        if v.antagonist_archetype and a_type == "HUMAN":
            out.append(
                f"Antagonist {a_note}: shadow = {v.antagonist_archetype.get('label', '')}. "
                "NOT evil — COHERENT WORLDVIEW. "
                "Complete: 'I do this because [logic that makes sense to them].' "
                "What do they believe the protagonist is FUNDAMENTALLY WRONG about?"
            )
        elif a_type != "HUMAN":
            out.append(
                f"Antagonist is {a_type} {a_note}. "
                "It has no malice — describe its LOGIC or INDIFFERENCE. "
                "What does it 'want' (or what is it optimising for)? "
                "Why is it MORE frightening than a human villain?"
            )
        out.append(
            "Collision scene: 15 words — the exact moment the protagonist's wound "
            "and the antagonist force meet directly."
        )
        if v.protagonist_archetype and p_type == "HUMAN":
            _pg = v.protagonist_archetype
            out.append(
                f"Protagonist identity aspiration ({_pg.get('label', '')}): "
                f"{_pg.get('worldview_logic', '')} "
                f"Core gift to claim: {_pg.get('core_gift', '')} "
                f"Growth edge: {_pg.get('growth_edge', '')}"
            )
        if v.ally_archetypes:
            out.append("")
            out.append("ALLY / SECONDARY CHARACTERS:")
            for ally in v.ally_archetypes:
                _awv = ally.get("worldview_logic", "")
                out.append(
                    f"  {ally.get('label', '')} ({ally.get('role', '')}): "
                    f"{ally.get('dramatic_function', '')} "
                    f"Relationship: {ally.get('relationship_to_protagonist', '')}"
                    + (f" Worldview: {_awv}" if _awv else "")
                )
        return out

    @staticmethod
    def _extra_context_lines(v: CompoundVariables) -> list[str]:
        """Prompt lines for era collisions, extra world textures, extra moral fault lines.

        Extracted to keep _generate_intersection_prompt under the 12-branch limit.
        """
        out: list[str] = []
        for ec in v.era_collision:
            past = ec.get("past_era", "")
            present = ec.get("present_element", "")
            bridge = ec.get("bridge", "")
            out.append(f"Temporal collision: {past} meets {present}. Bridge: {bridge}.")
        for extra in v.additional_world_textures:
            out.append(f"Secondary world: {extra.get('name', '')}")
        for extra in v.additional_moral_fault_lines:
            out.append("Additional moral fault line: " + str(extra.get("description", "")))
        return out

    def _call_haiku_for_premise(self, template_prompt: str) -> str:
        """Call Haiku to turn the template prompt into real 150-250 word prose.

        Uses json_mode=True because openrouter_client.chat() always JSON-parses
        the response. Asks for {"intersection_premise": "..."} and extracts the
        value. Falls back to template_prompt on any failure (API down, budget
        exceeded, import error) so tests and offline use are unaffected.
        """
        try:
            from pipeline.llm_client import build_chat_client  # noqa: PLC0415

            _json_suffix = (
                "\n\nRespond with ONLY a JSON object: "
                '{"intersection_premise": "<your 150-250 word premise here>"}'
            )
            client = build_chat_client()
            result = client.chat(
                model="anthropic/claude-haiku-4.5",
                messages=[{"role": "user", "content": template_prompt + _json_suffix}],
                json_mode=True,
            )
            premise = str(result.get("intersection_premise", "")).strip()
            if not premise:
                _log.warning("Haiku returned empty intersection_premise — using template fallback.")
                return template_prompt
            words = premise.split()
            if len(words) > _MAX_PREMISE_WORDS:
                premise = " ".join(words[:_MAX_PREMISE_WORDS])
            _log.info("Haiku intersection premise: %d words", len(premise.split()))
            return premise
        except Exception as exc:
            _log.warning("Haiku call failed (%s) — using template fallback.", exc)
            return template_prompt

    # ------------------------------------------------------------------
    # Hidden attributes (framework labels — never in investor output)
    # ------------------------------------------------------------------

    def _build_hidden_attrs(self, v: CompoundVariables) -> dict[str, Any]:
        """Map sampled variables to internal framework labels.

        These populate seed.json hidden_attrs and shape the drafter's prose
        silently. They never appear in the investor-facing NARRATOR document.
        """
        sdt_intensity = float(v.sdt_wound.get("deprivation_intensity", 1.0))
        archetype_dynamic = (
            "mirror"
            if (
                v.dark_archetype
                and v.antagonist_archetype
                and v.dark_archetype.get("label") == v.antagonist_archetype.get("label")
            )
            else "contrast"
        )
        return {
            "arc_shape": _derive_arc_shape(v),
            "conflict_type": _derive_conflict_type(v),
            "boden_type": _derive_boden_type(v),
            "sdt_need": _derive_sdt_need(v),
            "sdt_deprivation_intensity": sdt_intensity,
            "budget_tier": _derive_budget_tier(v),
            "moral_wager": _derive_moral_wager(v),
            "has_civilizational_stake": v.civilizational_stake is not None,
            "has_historical_transplant": v.historical_transplant is not None,
            "tension_count": len(v.tensions),
            "num_conspiracy": len(v.conspiracy_engine),
            "num_reptile": len(v.reptile_trigger),
            "num_cultural_moment": len(v.cultural_moment),
            "num_audiences": len(v.audiences),
            "archetype_dynamic": archetype_dynamic,
            "num_allies": len(v.ally_archetypes),
            "ally_roles": [a.get("role", "") for a in v.ally_archetypes],
            "format": (
                v.format_value.get("name", "unspecified") if v.format_value else "unspecified"
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_binary_tensions(self) -> list[dict[str, Any]]:
        try:
            dims = cast(dict[str, Any], self._ontology.get("dimensions", {}))
            raw = cast(list[Any], dims.get("binary_tensions", []))
            return cast(list[dict[str, Any]], raw)
        except (KeyError, TypeError):
            return []

    def _get_by_id(self, items: list[dict[str, Any]], target_id: str) -> dict[str, Any]:
        for item in items:
            if str(item.get("id", "")) == target_id:
                return item
        return self._rng.choice(items)


# ------------------------------------------------------------------
# Hidden-attr derivation helpers (pure Python, extracted to stay
# under the 12-branch limit per function — ADR-0002)
# ------------------------------------------------------------------

_SDT_NEED_MAP: dict[str, str] = {
    "autonomy": "Autonomy",
    "competence": "Competence",
    "relatedness": "Relatedness",
    "all_three": "Full-Triad",
    "autonomy+competence": "Autonomy+Competence",
    "competence+relatedness": "Competence+Relatedness",
}


def _derive_sdt_need(v: CompoundVariables) -> str:
    return _SDT_NEED_MAP.get(str(v.sdt_wound.get("need", "")), "Autonomy")


def _derive_arc_shape(v: CompoundVariables) -> str:
    divisiveness = float(v.divisiveness_engine.get("score", 5))
    sdt_intensity = float(v.sdt_wound.get("deprivation_intensity", 1.0))
    if divisiveness >= _ARC_DIV_HIGH and sdt_intensity >= _SDT_MAX_INTENSITY:
        return "Fall-Rise"
    if divisiveness >= _ARC_DIV_MID:
        return "Rise-Fall"
    return "Fall-Rise-Fall"


def _derive_conflict_type(v: CompoundVariables) -> str:
    inv_tags = set(v.structural_inversion.get("domain_tags", []))
    if "institution" in inv_tags or "systemic" in inv_tags:
        return "man vs society"
    if "technology" in inv_tags or "AI" in inv_tags:
        return "man vs technology"
    if "identity" in inv_tags:
        return "man vs self"
    return "man vs fate"


def _derive_boden_type(v: CompoundVariables) -> str:
    sw = float(v.structural_inversion.get("surprise_weight", 0.5))
    if sw >= _BODEN_TRANSFORM_THRESHOLD:
        return "transformational"
    if sw >= _BODEN_EXPLORE_THRESHOLD:
        return "exploratory"
    return "combinatorial"


def _derive_budget_tier(v: CompoundVariables) -> str:
    has_large = any(a.get("size_M", 0) >= _LARGE_AUDIENCE_M for a in v.audiences)
    return "mid $15-50M" if has_large else "indie $1-15M"


def _derive_moral_wager(v: CompoundVariables) -> str:
    fault_desc = str(v.moral_fault_line.get("description", "")).lower()
    if "truth" in fault_desc:
        return (
            "Devotion to truth, pursued without the ability to limit "
            "its consequences, becomes its own form of destruction."
        )
    if "care" in fault_desc:
        return "The act of care, performed without presence, becomes the instrument of harm."
    return (
        "Precision without accountability leads to harm that the precision itself cannot measure."
    )


def _derive_arc_shape_6(
    divisiveness: float,
    sdt_intensity: float,
    emotional_uni: float,
    has_civ_stake: bool,
) -> str:
    """Classify into Reagan/Kim/Dodds 6 narrative arc shapes.

    Reference: Reagan et al. 2016 — emotional arcs of stories are dominated
    by six basic shapes: Cinderella, Man in a Hole, Rags to Riches, Icarus,
    Oedipus, Tragedy.

    Commercial tier (descending): Cinderella > Man in a Hole / Rags to Riches
    > Icarus > Oedipus > Tragedy.
    """
    if has_civ_stake and emotional_uni >= _ARC6_CIV_EMO_UNI:
        return "Cinderella"
    if divisiveness >= _ARC6_OEDIPUS_DIV and sdt_intensity >= _SDT_MAX_INTENSITY:
        return "Oedipus"
    if divisiveness >= _ARC6_ICARUS_DIV:
        return "Icarus"
    if sdt_intensity >= _SDT_MAX_INTENSITY and divisiveness >= _ARC6_MAN_HOLE_DIV:
        return "Man in a Hole"
    if sdt_intensity >= _SDT_MAX_INTENSITY:
        return "Rags to Riches"
    return "Tragedy"


def _compute_cultural_field_alignment(v: CompoundVariables) -> float:
    """Score 2026 cultural field alignment (0.0-1.0).

    Based on Csikszentmihalyi's systems model: creative work gains traction
    when it aligns with the current field's readiness.
    Higher score = stronger zeitgeist fit = better opening weekend potential.
    """
    score: float = 0.0
    if v.cultural_moment:
        score += 0.40 * min(len(v.cultural_moment), 2) / 2.0
        cm_clusters = {cm.get("thematic_cluster", "") for cm in v.cultural_moment}
        seed_cluster = v.structural_inversion.get("thematic_cluster", "")
        if seed_cluster and seed_cluster in cm_clusters:
            score += 0.30
    if v.open_problem:
        score += 0.15
    if v.conspiracy_engine:
        score += 0.15
    return round(min(score, 1.0), 3)


def _compute_commercial_flags(v: CompoundVariables, scores: CompoundScore) -> dict[str, bool]:
    """Map seed variables to EPAGOGIX/ScriptBook commercial prediction signals.

    Boolean flags corresponding to features used by studio commercial prediction
    tools. All derived from seed variables — no LLM calls, no external data.
    """
    return {
        "strong_antagonist": v.antagonist_archetype is not None,
        "dual_character_arc": v.dark_archetype is not None and len(v.ally_archetypes) > 0,
        "clear_dramatic_question": float(v.divisiveness_engine.get("score", 0))
        >= _COMM_DRAMATIC_Q_DIV_FLOOR,
        "franchise_potential": v.civilizational_stake is not None,
        "emotional_catharsis_signal": scores.emotional_universality_score
        >= _COMM_CATHARSIS_EMO_UNI,
        "genre_legibility": scores.cluster_coherence >= _COMM_GENRE_COHERENCE,
        "audience_breadth_signal": scores.audience_overlap_M >= _COMM_AUDIENCE_BREADTH_M,
        "word_of_mouth_potential": scores.divisiveness_score >= _COMM_WOM_DIV,
        "zeitgeist_hook": len(v.cultural_moment) > 0,
        "science_hook": len(v.open_problem) > 0,
    }


def _compute_failure_risks(v: CompoundVariables, scores: CompoundScore) -> list[dict[str, Any]]:
    """Klein premortem — pre-identify failure modes before any script is written.

    Reference: Gary Klein (2007) 'Performing a Project Premortem', HBR.
    Each entry: id, category, risk, signal, mitigation.
    """
    risks: list[dict[str, Any]] = []

    _R = risks.append
    if scores.divisiveness_score >= _RISK_HIGH_DIV:
        _R(
            {
                "id": "FR_001",
                "category": "commercial",
                "risk": "Extreme divisiveness may trigger negative-WOM suppressing opening weekend",
                "signal": f"divisiveness={scores.divisiveness_score:.1f}",
                "mitigation": "Add ally archetypes as emotional counterweight; cast likeable lead",
            }
        )

    if scores.cluster_coherence < _RISK_LOW_COHERENCE:
        _R(
            {
                "id": "FR_002",
                "category": "concept",
                "risk": "Low thematic coherence — concept may feel tonally scattered to audiences",
                "signal": f"cluster_coherence={scores.cluster_coherence:.2f}",
                "mitigation": "Tighten cluster alignment; pick one dominant emotional register",
            }
        )

    if scores.som_floor_M < _RISK_LOW_SOM_M:
        _R(
            {
                "id": "FR_003",
                "category": "commercial",
                "risk": "Low SOM at concept stage — hard to justify mid-budget greenlight",
                "signal": f"som_floor={scores.som_floor_M:.0f}M",
                "mitigation": "Attach A-list talent early; seek co-production deal",
            }
        )

    if v.dark_archetype is not None and len(v.ally_archetypes) == 0:
        _R(
            {
                "id": "FR_004",
                "category": "concept",
                "risk": "No ally archetype — story risks nihilism without emotional counterweight",
                "signal": "ally_archetypes=[]",
                "mitigation": "Add Faithful Companion or Innocent Witness to anchor empathy",
            }
        )

    _emo_sig = f"emotional_universality={scores.emotional_universality_score:.1f}, civ_stake=None"
    if v.civilizational_stake is None and scores.emotional_universality_score < _RISK_LOW_EMO_UNI:
        _R(
            {
                "id": "FR_005",
                "category": "commercial",
                "risk": "Low emotional universality without civ stakes — niche demographic ceiling",
                "signal": _emo_sig,
                "mitigation": "Raise stakes to universal needs (relatedness, survival, belonging)",
            }
        )

    _gold_sig = (
        f"goldilocks={scores.goldilocks_score:.2f}, assoc_dist={scores.associative_distance:.2f}"
    )
    if scores.goldilocks_score < _RISK_LOW_GOLDILOCKS:
        _R(
            {
                "id": "FR_006",
                "category": "concept",
                "risk": "Associative distance outside Goldilocks zone — derivative or incoherent",
                "signal": _gold_sig,
                "mitigation": "Rebalance elements: target associative distance 0.30-0.50",
            }
        )

    if v.historical_transplant is None and not v.cultural_moment:
        _R(
            {
                "id": "FR_007",
                "category": "market",
                "risk": "No historical or cultural hook — marketing lacks a zeitgeist peg",
                "signal": "historical_transplant=None, cultural_moment=[]",
                "mitigation": "Add a cultural moment hook for a trailer-ready logline",
            }
        )

    return risks


# ------------------------------------------------------------------
# Pure-Python scoring helpers (ADR-0002)
# ------------------------------------------------------------------


def _compute_associative_distance(tag_groups: list[list[str]]) -> float:
    """Proxy for cosine distance between the two most distant element groups.

    Uses domain cluster assignments to estimate conceptual distance.
    Target range: 0.30-0.50 (C002 Goldilocks zone).
    """
    if len(tag_groups) < _MIN_TAG_GROUPS:
        return _ASSOC_TARGET  # default to midpoint

    cluster_sets: list[set[int]] = []
    for tags in tag_groups:
        clusters: set[int] = set()
        for tag in tags:
            c = _DOMAIN_CLUSTERS.get(tag)
            if c is not None:
                clusters.add(c)
        if clusters:
            cluster_sets.append(clusters)

    if len(cluster_sets) < _MIN_TAG_GROUPS:
        return _ASSOC_TARGET

    # Find the pair with maximum jaccard distance
    max_dist = 0.0
    for i in range(len(cluster_sets)):
        for j in range(i + 1, len(cluster_sets)):
            a, b = cluster_sets[i], cluster_sets[j]
            union = len(a | b)
            inter = len(a & b)
            if union > 0:
                jaccard_dist = 1.0 - inter / union
                max_dist = max(max_dist, jaccard_dist)

    # Scale to 0.0-0.7 range and map to target 0.3-0.5 zone
    return round(min(_ASSOC_SCALE, max_dist * _ASSOC_SCALE), 4)


def _compute_audience_overlap(audiences: list[dict[str, Any]]) -> float:
    """Estimate unique-addressable audience size in millions.

    v5.0 (ADR-0012): Delegates to
    :func:`pipeline.crystallize.revenue.compute_audience_overlap` -- the
    explicit inclusion-exclusion Venn computation introduced in Module 2.
    The old conservative 30%/15% flat-rate heuristic is gone; the new
    delegate uses ``domain_tags`` Jaccard + ``affinity_with`` priors for a
    per-pair overlap, then applies proper inclusion-exclusion.

    Signature preserved (``list[dict] -> float``) so every caller in the
    v4 path keeps working.  Empty input still returns ``0.0``.
    """
    if not audiences:
        return 0.0
    from pipeline.crystallize.revenue import (  # noqa: PLC0415
        compute_audience_overlap as _revenue_overlap,
    )

    return _revenue_overlap(audiences).unique_addressable_M


def _compute_thematic_anchor(v: CompoundVariables) -> float:
    """Measure coherence of all variables around the structural_inversion.

    Issue #23: uses explicit ``thematic_cluster`` string for direct comparison
    when the field is present (all variables migrated to v2.0 schema).
    Falls back to tag-level Jaccard distance for legacy entries without the field.

    Goldilocks target: 0.40-0.70 cluster match fraction — enough coherence to
    feel intentional, not so much that every element is identical.
    Returns 0.0 (scatter) to 1.0 (all vars share the core cluster).
    """
    core_cluster: str = v.structural_inversion.get("thematic_cluster", "")
    if core_cluster:
        companions: list[str] = [
            v.psychological_pattern.get("thematic_cluster", ""),
            v.sdt_wound.get("thematic_cluster", ""),
            v.moral_fault_line.get("thematic_cluster", ""),
            v.divisiveness_engine.get("thematic_cluster", ""),
        ]
        if v.historical_transplant:
            companions.append(v.historical_transplant.get("thematic_cluster", ""))
        populated = [c for c in companions if c]
        if not populated:
            return 0.5
        match_frac = sum(1 for c in populated if c == core_cluster) / len(populated)
        # Goldilocks 0.4-0.7: cohesive but not monotone
        score = 1.0 - abs(match_frac - 0.55) / 0.55
        return round(max(0.0, min(1.0, score)), 4)

    # Legacy Jaccard fallback (variables without thematic_cluster)
    core_tags: set[str] = set(v.structural_inversion.get("domain_tags", []))
    if not core_tags:
        return 0.5
    companion_groups: list[set[str]] = [
        set(v.psychological_pattern.get("domain_tags", [])),
        set(v.sdt_wound.get("domain_tags", [])),
        set(v.moral_fault_line.get("domain_tags", [])),
        set(v.divisiveness_engine.get("domain_tags", [])),
    ]
    if v.historical_transplant:
        companion_groups.append(set(v.historical_transplant.get("domain_tags", [])))
    overlaps: list[float] = []
    for tags in companion_groups:
        if not tags:
            continue
        union = len(core_tags | tags)
        inter = len(core_tags & tags)
        overlaps.append(inter / union if union > 0 else 0.0)
    if not overlaps:
        return 0.5
    avg = sum(overlaps) / len(overlaps)
    score = 1.0 - abs(avg - 0.35) / 0.35
    return round(max(0.0, min(1.0, score)), 4)


def _compute_cluster_coherence(v: CompoundVariables) -> tuple[str, float]:
    """Return (primary_cluster, coherence_fraction) across all narrative variables.

    Issue #23: counts ``thematic_cluster`` votes from the five core narrative
    variables (sdt_wound, psych_pattern, structural_inversion, moral_fault_line,
    world_texture) plus cultural_moment entries when present.

    primary_cluster — the most frequent cluster name (empty string if none found).
    coherence_fraction — fraction of populated variables that share primary_cluster.
    A value >= 0.60 means the seed has strong thematic direction.
    """
    from collections import Counter  # noqa: PLC0415

    votes: list[str] = []
    for item in [
        v.sdt_wound,
        v.psychological_pattern,
        v.structural_inversion,
        v.moral_fault_line,
        v.world_texture,
    ]:
        c = item.get("thematic_cluster", "")
        if c:
            votes.append(c)
    for cm in v.cultural_moment:
        c = cm.get("thematic_cluster", "")
        if c:
            votes.append(c)

    if not votes:
        return ("", 0.0)

    counts: Counter[str] = Counter(votes)
    primary = counts.most_common(1)[0][0]
    coherence = counts[primary] / len(votes)
    return (primary, coherence)


def _compute_emotional_universality(v: CompoundVariables) -> float:
    """Score broad demographic reach (0-5). $2B+ films pattern: Avatar=5, Joker=3.5.

    Five dimensions drawn from corpus analysis of top-1000 grossing films:
    1. Universal SDT need (autonomy/relatedness felt by all demographics)
    2. High SDT wound audience resonance (the wound is widely shared)
    3. Divisiveness >= 8 (debate-driven word-of-mouth amplifies reach)
    4. Civilizational stakes (the outcome matters to everyone on Earth)
    5. Sharp compression moment (everyone can describe the key scene)
    """
    score: float = 0.0

    need = str(v.sdt_wound.get("need", ""))
    if any(n in need for n in ("relatedness", "autonomy", "all_three")):
        score += 1.0

    sdt_resonance = float(v.sdt_wound.get("audience_resonance_M", 0))
    if sdt_resonance >= _EMO_UNI_RESONANCE_HIGH:
        score += 1.0
    elif sdt_resonance >= _EMO_UNI_RESONANCE_MID:
        score += 0.5

    div_score = float(v.divisiveness_engine.get("score", 0))
    if div_score >= _EMO_UNI_DIV_HIGH:
        score += 1.0
    elif div_score >= _EMO_UNI_DIV_MID:
        score += 0.5

    if v.civilizational_stake is not None:
        score += 1.0

    compression = float(v.compression_key.get("surprise_weight", 0))
    if compression >= _EMO_UNI_COMPRESSION_HIGH:
        score += 1.0
    elif compression >= _EMO_UNI_COMPRESSION_MID:
        score += 0.5

    return round(min(score, 5.0), 2)


def _theme_keywords_to_clusters(texts: list[str]) -> set[int]:
    """Map operator theme/problem strings to domain cluster IDs.

    Issue #23: also matches explicit cluster name strings so operators can
    write themes=["emotional"] or problems=["technology displacement"] and
    get the right cluster without needing exact tag spelling.

    Precedence: cluster name match > domain tag keyword match.

    Examples::

        _theme_keywords_to_clusters(["family adventure"])      # -> {1}
        _theme_keywords_to_clusters(["AI displacement"])       # -> {2}
        _theme_keywords_to_clusters(["emotional", "nature"])   # -> {1, 4}
        _theme_keywords_to_clusters([])                        # -> set()
    """
    clusters: set[int] = set()
    combined = " ".join(texts).lower()
    # Direct cluster-name match (highest priority)
    for name, cid in _CLUSTER_NAME_TO_ID.items():
        if name in combined:
            clusters.add(cid)
    # Domain tag keyword match
    for keyword, cluster_id in _DOMAIN_CLUSTERS.items():
        if keyword.lower() in combined:
            clusters.add(cluster_id)
    return clusters


def _thematic_weighted_choice(
    rng: random.Random,
    pool: list[dict[str, Any]],
    target_clusters: set[int],
    penalty_weight: float,
    *,
    freq_table: dict[tuple[str, str], int] | None = None,
    axis_name: str | None = None,
) -> dict[str, Any]:
    """Weighted random choice that steers toward operator theme clusters.

    Issue #23: now checks ``thematic_cluster`` string directly (highest fidelity)
    before falling back to ``domain_tags`` inference.

    Weight tiers (descending priority):
    1. ``thematic_cluster`` name in target cluster names -> 1.2  (direct cluster match)
    2. ``domain_tags`` overlap with target_clusters -> 1.0       (tag-level match)
    3. Neutral (neither match nor penalised) -> 1.0
    4. ``thematic_cluster == "institutional"`` AND 0 not in targets -> max(0.05, 1-penalty)

    Empty ``target_clusters`` or ``penalty_weight == 0`` falls back to uniform choice.

    v5.0 (ADR-0012): When ``freq_table`` and ``axis_name`` are supplied, each
    item's weight is additionally multiplied by
    :func:`pipeline.diversity.penalty` -- which decays for over-sampled
    ``(axis, value_id)`` pairs.  This is the cross-run memory layer that
    breaks the v4 sampler's local-attractor convergence.  Both arguments
    are optional and default to ``None`` -- when either is missing the
    function returns the v4 weighting verbatim.
    """
    if not pool:
        raise ValueError("Cannot sample from empty pool")

    # v5 frequency-penalty short-circuit: when target_clusters is empty but
    # the operator passed a freq_table, we still apply the diversity bias
    # over uniform weights (skipping the cluster-steering tiers entirely).
    if not target_clusters or penalty_weight == 0.0:
        if freq_table and axis_name:
            from pipeline import diversity as _diversity  # noqa: PLC0415

            weights = [
                _diversity.penalty(axis_name, str(item.get("id", "")), freq_table) for item in pool
            ]
            (chosen,) = rng.choices(pool, weights=weights, k=1)
            return chosen
        return rng.choice(pool)

    _INSTITUTIONAL_ID: Final[int] = 0
    _INSTITUTIONAL_NAME: Final[str] = "institutional"
    target_names: set[str] = {_CLUSTER_NAMES[c] for c in target_clusters if c in _CLUSTER_NAMES}
    weights: list[float] = []
    for item in pool:
        item_cluster: str = item.get("thematic_cluster", "")
        tags: list[str] = item.get("domain_tags", [])
        item_cluster_ids: set[int] = {_DOMAIN_CLUSTERS[t] for t in tags if t in _DOMAIN_CLUSTERS}

        if item_cluster and item_cluster in target_names:
            # Direct thematic_cluster hit — highest confidence steering
            weights.append(1.2)
        elif item_cluster_ids & target_clusters:
            # Tag-level cluster match
            weights.append(1.0)
        elif (
            item_cluster == _INSTITUTIONAL_NAME or item_cluster_ids.issubset({_INSTITUTIONAL_ID})
        ) and _INSTITUTIONAL_ID not in target_clusters:
            # Institutional cluster not wanted by operator
            weights.append(max(0.05, 1.0 - penalty_weight))
        else:
            weights.append(1.0)

    # v5.0 (ADR-0012) — fold cross-run frequency penalty into the
    # cluster-steered weights so over-sampled values are downweighted
    # even when they match the operator's theme.
    if freq_table and axis_name:
        from pipeline import diversity as _diversity  # noqa: PLC0415

        for i, item in enumerate(pool):
            weights[i] *= _diversity.penalty(axis_name, str(item.get("id", "")), freq_table)

    (chosen,) = rng.choices(pool, weights=weights, k=1)
    return chosen


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    """Load a JSON file that contains a top-level array."""
    with open(path, encoding="utf-8") as f:
        return cast(list[dict[str, Any]], json.load(f))


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a compound seed.")
    parser.add_argument("--themes", nargs="*", default=[], help="Operator themes")
    parser.add_argument("--problems", nargs="*", default=[], help="Real-world problems")
    parser.add_argument(
        "--transplant", default=None, help="Force historical transplant ID (e.g. HT_01)"
    )
    parser.add_argument("--civilizational", action="store_true", help="Force civilizational stake")
    parser.add_argument("--target-som", type=float, default=500.0, help="SOM target in $M")
    parser.add_argument("--attempts", type=int, default=50)
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--n-conspiracy", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--n-reptile", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--n-cultural", type=int, default=1, choices=[1, 2])
    parser.add_argument("--n-audiences", type=int, default=3, choices=[2, 3, 4, 5])
    # Derive entity choices from the module constant — single source of truth
    _entity_choices = list(_ENTITY_PROMPT_NOTES.keys())
    _entity_descriptions = " | ".join(
        f"{k}={v[:30]}" for k, v in _ENTITY_PROMPT_NOTES.items() if k != "HUMAN"
    )
    parser.add_argument(
        "--protagonist-entity",
        default="HUMAN",
        choices=_entity_choices,
        help=f"Protagonist force type. Options: {_entity_descriptions}",
    )
    parser.add_argument(
        "--antagonist-entity",
        default="HUMAN",
        choices=_entity_choices,
        help="Antagonist force type. Gravity=ENVIRONMENT, HAL=TECHNOLOGY, Virus=ORGANISM",
    )
    parser.add_argument("--n-tensions", type=int, default=2, choices=[1, 2, 3, 4])
    parser.add_argument(
        "--n-era",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="Temporal collisions (0=none, 1=40%% prob, 2=always 2)",
    )
    parser.add_argument(
        "--n-open", type=int, default=1, choices=[0, 1, 2], help="Unsolved science hooks"
    )
    parser.add_argument(
        "--n-worlds",
        type=int,
        default=1,
        choices=[1, 2],
        help="World textures (1=primary, 2=add secondary setting)",
    )
    parser.add_argument(
        "--n-moral",
        type=int,
        default=1,
        choices=[1, 2],
        help="Moral fault lines (1=primary, 2=add secondary dilemma)",
    )
    parser.add_argument(
        "--genre-bias-penalty",
        type=float,
        default=0.6,
        metavar="W",
        help=(
            "De-bias weight 0.0-1.0. When themes/problems are provided, "
            "institutional-cluster variables are down-weighted by this factor. "
            "0.0=pure random, 0.6=default, 1.0=maximum avoidance."
        ),
    )
    parser.add_argument(
        "--n-allies",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="Ally/secondary character archetypes (0=none, 1=one ally, 2=ally pair)",
    )
    parser.add_argument(
        "--n-formats",
        type=int,
        default=1,
        choices=[0, 1],
        help="Sample a content format (0=format-agnostic, 1=one format; v5.1.0)",
    )
    parser.add_argument(
        "--force-format",
        default=None,
        help=(
            "Pin a content format by name/id/economics_key: Feature Film | "
            "Limited Series | Returning Series | Animation Feature | "
            "Animation Series | Microdrama"
        ),
    )
    args = parser.parse_args()

    engine = CompoundSeedEngine(rng_seed=args.seed)
    result = engine.generate(
        themes=args.themes,
        problems=args.problems,
        n_tensions=args.n_tensions,
        n_conspiracy=args.n_conspiracy,
        n_reptile=args.n_reptile,
        n_cultural_moment=args.n_cultural,
        n_audiences=args.n_audiences,
        n_era=args.n_era,
        n_open_problems=args.n_open,
        n_worlds=args.n_worlds,
        n_moral=args.n_moral,
        protagonist_entity_type=args.protagonist_entity,
        antagonist_entity_type=args.antagonist_entity,
        force_historical_transplant=args.transplant,
        force_civilizational=args.civilizational,
        target_som_M=args.target_som,
        max_attempts=args.attempts,
        genre_bias_penalty_weight=args.genre_bias_penalty,
        n_allies=args.n_allies,
        n_formats=args.n_formats,
        force_format=args.force_format,
    )

    scores = result.scores
    print(f"\n{'=' * 60}")
    print("COMPOUND SEED GENERATED")
    print(f"{'=' * 60}")
    print(f"Genius score:         {scores.genius_score:.2f} (gate: {_MIN_GENIUS_SCORE})")
    print(f"Associative distance: {scores.associative_distance:.2f} (target: 0.30-0.50)")
    print(f"Audience overlap:     {scores.audience_overlap_M:.0f}M")
    print(f"Divisiveness:         {scores.divisiveness_score:.1f}/10")
    print(f"SOM floor:            ${scores.som_floor_M:.0f}M (gate: ${_TARGET_SOM_M:.0f}M)")
    print(f"Passes $500M gate:    {scores.passes_500m_gate}")
    print("\n--- INTERSECTION PREMISE ---\n")
    print(result.intersection_premise)
    print(f"\n{'=' * 60}")

    if "_warning" in result.hidden_attrs:
        print(f"\nWARNING: {result.hidden_attrs['_warning']}")


if __name__ == "__main__":
    main()
