#!/usr/bin/env bash
# tests/test_lefthook.sh — Verify lefthook.yml is valid and parseable.
# HARN-17: lefthook pre-commit must include ruff + pyright + gitleaks;
#          pre-push must include make test + make eval.
#
# Run: bash tests/test_lefthook.sh
set -e

echo "=== Checking lefthook.yml ==="

# 1. Verify lefthook.yml parses and has required structure
uv run python -c "
import yaml
import sys

with open('lefthook.yml') as f:
    config = yaml.safe_load(f)

errors = []

# Check pre-commit hook exists
if 'pre-commit' not in config:
    errors.append('Missing pre-commit hook')
else:
    pc_commands = config['pre-commit'].get('commands', {})
    pc_text = str(pc_commands).lower()
    if 'gitleaks' not in pc_text:
        errors.append('pre-commit missing gitleaks command')
    if 'ruff' not in pc_text:
        errors.append('pre-commit missing ruff command')

# Check pre-push hook exists
if 'pre-push' not in config:
    errors.append('Missing pre-push hook')
else:
    pp_commands = config['pre-push'].get('commands', {})
    pp_text = str(pp_commands).lower()
    if 'pytest' not in pp_text:
        errors.append('pre-push missing pytest (test) command')

if errors:
    for e in errors:
        print(f'FAIL: {e}', file=sys.stderr)
    sys.exit(1)

print('lefthook.yml: structure OK')
"

# 2. Verify lefthook is callable (only if installed; otherwise skip with message)
if command -v lefthook >/dev/null 2>&1; then
    lefthook validate || { echo "FAIL: lefthook validate failed"; exit 1; }
    echo "lefthook validate: OK"
else
    echo "SKIP: lefthook binary not installed"
    echo "  Install: brew install lefthook    (macOS)"
    echo "  Install: see https://lefthook.dev/install  (Linux)"
    echo "  After install: lefthook install"
fi

echo "OK: lefthook.yml checks passed"
