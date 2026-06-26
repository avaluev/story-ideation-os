#!/usr/bin/env bash
# scripts/build-tarball.sh — OPS-04: Package the Anomaly Engine for distribution.
#
# Creates: dist/anomaly-engine-<git-short-sha>.tar.gz
# Excludes: Inputs/ .env .env.* data/ out/ __pycache__/ .venv/ dist/
#
# After creating the tarball:
#   - Extracts to a tmpdir
#   - Runs `uv sync --dev` inside to verify the package is installable
#
# Exit 0 on success; exit 1 on any failure.
#
# Usage:
#   bash scripts/build-tarball.sh           # full build + verify
#   bash scripts/build-tarball.sh --dry-run # print what would be excluded, skip tar

set -euo pipefail

DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=1
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--dry-run]" >&2
            exit 1
            ;;
    esac
done

# ── Git short SHA ─────────────────────────────────────────────────────────────

if ! command -v git &>/dev/null; then
    echo "FAIL: git not found." >&2
    exit 1
fi

GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
OUTPUT_NAME="anomaly-engine-${GIT_SHA}.tar.gz"
OUTPUT_PATH="dist/${OUTPUT_NAME}"

# ── Exclusion list ────────────────────────────────────────────────────────────

EXCLUDES=(
    "--exclude=./Inputs"
    "--exclude=./.env"
    "--exclude=./.env.*"
    "--exclude=./data"
    "--exclude=./out"
    "--exclude=./__pycache__"
    "--exclude=./.venv"
    "--exclude=./dist"
    "--exclude=./.git"
    "--exclude=./.mypy_cache"
    "--exclude=./.ruff_cache"
    "--exclude=./.pytest_cache"
    "--exclude=*.pyc"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "build-tarball: DRY RUN"
    echo "Output would be: $OUTPUT_PATH"
    echo "Excluded paths:"
    for excl in "${EXCLUDES[@]}"; do
        echo "  $excl"
    done
    echo "build-tarball: OK (dry-run)"
    exit 0
fi

# ── Create dist/ directory ────────────────────────────────────────────────────

mkdir -p dist

# ── Create tarball ────────────────────────────────────────────────────────────

echo "Creating $OUTPUT_PATH ..."
tar -czf "$OUTPUT_PATH" "${EXCLUDES[@]}" .

if [[ ! -f "$OUTPUT_PATH" ]]; then
    echo "FAIL: tarball not created at $OUTPUT_PATH" >&2
    exit 1
fi

TARBALL_SIZE=$(du -sh "$OUTPUT_PATH" | cut -f1)
echo "Tarball created: $OUTPUT_PATH ($TARBALL_SIZE)"

# ── Verify: extract + uv sync --dev ──────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    echo "WARN: uv not found — skipping install verification"
else
    TMPDIR=$(mktemp -d)
    trap 'rm -rf "$TMPDIR"' EXIT

    echo "Verifying in $TMPDIR ..."
    tar -xzf "$OUTPUT_PATH" -C "$TMPDIR"

    if ! (cd "$TMPDIR" && uv sync --dev --quiet); then
        echo "FAIL: uv sync --dev failed inside extracted tarball." >&2
        exit 1
    fi
    echo "Verification: uv sync --dev passed inside extracted tarball"
fi

echo "build-tarball: OK — $OUTPUT_PATH"
