---
schema_version: "1.0"
last_updated: "2026-06-26T12:00:00Z"
current_phase: "PUBLIC-RELEASE — story-ideation-os open-sourced under Apache 2.0 (2026-06-26)."
current_plan: "Public open-source release of the story-ideation pipeline. Entry points: README.md, docs/REPOSITORY_STRUCTURE.md, docs/adr/. Planning history is reset for the public mirror; the live engine writes real run state here at runtime."
last_session_id: "public-release-2026-06-26"
open_questions: []
blockers: []
next_agent: "none — community contributions are routed via CONTRIBUTING.md."
next_action: "Run `make test && make eval` to confirm a green baseline, then read docs/ and browse showcase/."
---

# Resume — story-ideation-os

This file is the recovery pointer for the engine's state-durability layer
(ADR-0001): cross-session state lives on disk, never only in an agent's context.

For this public release the internal planning/campaign history has been reset.
At runtime the engine rewrites its real run state, handoffs, and checkpoints under
`.planning/state/`. See [`CLAUDE.md`](../../CLAUDE.md) for the recovery protocol and
[`docs/REPOSITORY_STRUCTURE.md`](../../docs/REPOSITORY_STRUCTURE.md) for the full
state substrate.
