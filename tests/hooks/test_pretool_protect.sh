#!/usr/bin/env bash
# tests/hooks/test_pretool_protect.sh — HARN-07 full battery
#
# Tests that .claude/hooks/pre_protect.py:
#   - Blocks Write/Edit to all 8 protected config files (exit 2)
#   - Allows Write/Edit to source files, tests, docs (exit 0)
#
# Usage: bash tests/hooks/test_pretool_protect.sh
set -e

HOOK=".claude/hooks/pre_protect.py"
[ -f "$HOOK" ] || { echo "FAIL: $HOOK missing"; exit 1; }

PASS_COUNT=0
FAIL_COUNT=0

run_case() {
    local desc="$1"
    local file_path="$2"
    local expect_exit="$3"

    local payload
    payload=$(printf '{"tool_input":{"file_path":%s}}' \
        "$(printf '%s' "$file_path" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")

    local output exit_code
    output=$(echo "$payload" | uv run python "$HOOK" 2>&1) || true
    # Capture exit code separately since set -e would kill us
    echo "$payload" | uv run python "$HOOK" > /dev/null 2>&1 && exit_code=0 || exit_code=$?

    if [ "$exit_code" != "$expect_exit" ]; then
        echo "FAIL [$desc]: expected exit $expect_exit, got $exit_code"
        echo "  file: $file_path"
        if [ -n "$output" ]; then
            echo "  output: $output"
        fi
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo "PASS [$desc]"
        PASS_COUNT=$((PASS_COUNT + 1))
    fi
}

echo "=== test_pretool_protect.sh — HARN-07 battery ==="
echo ""

# -----------------------------------------------------------------------
# BLOCKED cases — protected config files (should exit 2)
# -----------------------------------------------------------------------
run_case "block-pyproject"       "pyproject.toml"              2
run_case "block-ruff-dot"        ".ruff.toml"                  2
run_case "block-ruff-plain"      "ruff.toml"                   2
run_case "block-lefthook"        "lefthook.yml"                2
run_case "block-pyright"         "pyrightconfig.json"          2
run_case "block-claude-settings" ".claude/settings.json"       2
run_case "block-claude-local"    ".claude/settings.local.json" 2
run_case "block-makefile"        "Makefile"                    2
run_case "block-uvlock"          "uv.lock"                     2

# Nested path variants — should also be blocked
run_case "block-pyproject-path"  "/home/user/project/pyproject.toml" 2
run_case "block-settings-path"   "/abs/path/.claude/settings.json"   2

# -----------------------------------------------------------------------
# ALLOWED cases — source and doc files (should exit 0)
# -----------------------------------------------------------------------
run_case "allow-pipeline"     "pipeline/foo.py"              0
run_case "allow-tests"        "tests/test_x.py"              0
run_case "allow-claude-md"    "CLAUDE.md"                    0
run_case "allow-readme"       "README.md"                    0
run_case "allow-docs-adr"     "docs/adr/0007-future.md"     0
run_case "allow-scripts-py"   "scripts/lint_imports.py"      0
run_case "allow-evals"        "evals/test_resume.py"         0
run_case "allow-hooks-new"    ".claude/hooks/new_hook.py"    0

echo ""
echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed ==="

if [ "$FAIL_COUNT" -ne 0 ]; then
    exit 1
fi

echo "OK"
