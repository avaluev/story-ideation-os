# Security Policy

## Reporting a vulnerability

Please report security issues privately. Use GitHub's
[private vulnerability reporting](https://github.com/avaluev/story-ideation-os/security/advisories/new)
or contact the maintainer directly. **Do not open a public issue** for a
security vulnerability.

You can expect an acknowledgement within a few business days.

## Secret handling

This repository contains **no credentials**. Its design treats secrets as a
first-class hazard:

- The only secret-bearing file is `.env`, which is git-ignored. The repo ships
  a placeholder [`.env.example`](.env.example) only.
- `gitleaks` runs as a pre-commit and pre-push gate, and a test
  (`tests/test_secret_leak.py`) fails the build if any API-key prefix appears in
  a tracked file.
- API-key prefixes are masked in all logs and stack traces (ADR-0003).
- Model dispatch is quota-gated and fails closed at the configured budget cap
  (ADR-0008), limiting the blast radius of a leaked key.

If you find a credential committed anywhere in the history, please report it
privately so it can be rotated.

## Supported versions

This is an actively developed research project; security fixes target the
`main` branch.
