# Contributing to story-ideation-os

Thanks for your interest. This project has one golden rule that mirrors the
engine's own design: **numbers come from Python, claims come from sources.**
Pull requests that introduce a hard-coded financial figure, an LLM-written
score, or an uncited external number will be declined by the automated gates.

## Development setup

```bash
git clone https://github.com/avaluev/story-ideation-os.git
cd story-ideation-os
uv sync                 # https://docs.astral.sh/uv/
make test               # 2,100+ unit & contract tests (offline, no keys)
make eval               # behavioral eval gates
make lint               # import rules (ANOMALY-001..003)
```

No API keys are required for the test suite or the offline pipeline. Keys are
only needed to exercise the live research and model-dispatch layers; copy
`.env.example` to `.env` and fill in the placeholders.

## Before you open a pull request

Run the full gate locally — CI runs the same checks:

```bash
make lint && make test && make eval
uv run ruff format .          # formatting
uv run pyright pipeline tests # type checking
```

A change is ready when:

- [ ] `make test`, `make eval`, and `make lint` are green.
- [ ] `ruff format --check` and `pyright` pass.
- [ ] New behavior has tests (this project is test-first).
- [ ] No secret, key, or token is added to any tracked file (`gitleaks` runs on commit/push).
- [ ] If you changed a load-bearing invariant, you updated the relevant
      [ADR](docs/adr) and the `CLAUDE.md` enforcer line.

## Architecture & conventions

- Read [`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md) and
  [`docs/adr/`](docs/adr) before non-trivial changes.
- All numeric scoring lives in `pipeline/scoring.py` — never import an LLM
  client there (enforced by `ANOMALY-001`).
- All cross-step state goes through `pipeline/state.py` (atomic writes, ADR-0001).
- Never import from `frameworks/` (read-only doctrine, ADR-0005).
- Keep files focused (≤ ~800 lines) and prefer many small modules.

## Commit messages

Conventional commits: `type(scope): description` where type is one of
`feat | fix | refactor | docs | test | chore | perf | ci`.

## Reporting bugs & ideas

Open a GitHub issue with a minimal reproduction (a failing test is ideal). For
security concerns, see [SECURITY.md](SECURITY.md) — do not open a public issue.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
