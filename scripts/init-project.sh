#!/usr/bin/env bash
# scripts/init-project.sh — OPS-03: Bootstrap the Anomaly Engine development environment.
#
# Checks:
#   1. Python >= 3.11
#   2. uv sync --dev (skipped with --check-only)
#   3. .env has all required keys from .env.example
#
# Exit 0 on success; exit 1 with descriptive message on any failure.
#
# Usage:
#   bash scripts/init-project.sh            # full bootstrap
#   bash scripts/init-project.sh --check-only  # skip uv sync (CI dry-run)

set -euo pipefail

CHECK_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --check-only)
            CHECK_ONLY=1
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--check-only]" >&2
            exit 1
            ;;
    esac
done

# ── 1. Python version check ───────────────────────────────────────────────────

PYTHON_BIN=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)

if [[ -z "$PYTHON_BIN" ]]; then
    echo "FAIL: python3 not found. Install Python >= 3.11." >&2
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 11 ]]; }; then
    echo "FAIL: Python $PYTHON_VERSION found but >= 3.11 is required." >&2
    exit 1
fi

echo "python: $PYTHON_VERSION OK"

# ── 2. uv sync --dev ─────────────────────────────────────────────────────────

if [[ "$CHECK_ONLY" -eq 0 ]]; then
    if ! command -v uv &>/dev/null; then
        echo "FAIL: uv not found. Install via: curl -Lsf https://astral.sh/uv/install.sh | sh" >&2
        exit 1
    fi

    echo "Running uv sync --dev ..."
    if ! uv sync --dev; then
        echo "FAIL: uv sync failed." >&2
        exit 1
    fi
    echo "uv sync: OK"
else
    echo "uv sync: SKIPPED (--check-only)"
fi

# ── 3. .env key validation ────────────────────────────────────────────────────

ENV_EXAMPLE=".env.example"
ENV_FILE=".env"

if [[ ! -f "$ENV_EXAMPLE" ]]; then
    echo "WARN: $ENV_EXAMPLE not found — skipping key validation"
elif [[ "$CHECK_ONLY" -eq 1 ]]; then
    echo ".env keys: SKIPPED (--check-only)"
else
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "FAIL: $ENV_FILE is missing. Copy $ENV_EXAMPLE and fill in real values." >&2
        exit 1
    fi

    MISSING_KEYS=()
    while IFS= read -r line; do
        # Match lines like KEY= or KEY=value (uppercase keys only)
        if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]]; then
            key="${BASH_REMATCH[1]}"
            # Check .env has a non-empty value for this key
            if ! grep -qE "^${key}=.+" "$ENV_FILE" 2>/dev/null; then
                MISSING_KEYS+=("$key")
            fi
        fi
    done < "$ENV_EXAMPLE"

    if [[ "${#MISSING_KEYS[@]}" -gt 0 ]]; then
        for key in "${MISSING_KEYS[@]}"; do
            echo "FAIL: MISSING env key: $key" >&2
        done
        exit 1
    fi

    echo ".env keys: OK"
fi

echo "init-project: OK"
