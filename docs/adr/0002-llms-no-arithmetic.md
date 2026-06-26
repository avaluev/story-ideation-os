# ADR-0002: LLMs MUST NOT compute scores

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Operator + Spec (`Inputs/_ANOMALY_ENGINEv3.0.md` Anti-Hallucination Rule 2)

## Context

LLMs are unreliable at arithmetic. The Anomaly Engine's `overall_score`, `sdt_score`, `ajtbd_score`, audience-floor checks, and budget calculations all depend on exact numbers. A single hallucinated digit downstream of the critic could publish a 67-score concept as 87.

## Decision

All numeric scoring lives in `pipeline/scoring.py` as pure Python functions. The module imports zero LLM clients. The Forge agent and Critic agent emit *qualitative* fields only; the orchestrator runs `pipeline.scoring.overall_score(...)` on their outputs. Concept output JSON has `total_score: None` until `scoring.py` populates it.

## Consequences

(+) Scores are deterministic and reproducible.
(+) Score-formula changes are tracked in version control.
(+) Hand-computed test fixtures (Al-Bukhari = 96/100) verify formula correctness.
(−) Forge cannot self-report a score; Critic must score from a fixed rubric.

## Verifies

CLAUDE.md MUST rule "pipeline/scoring.py MUST NOT import openrouter_client or anthropic" (enforced by: `tests/test_scoring.py::test_no_llm_imports`) and "every score in out/concepts/*.md MUST be the output of pipeline.scoring" (enforced by: `evals/test_score_provenance.py`).
