#!/usr/bin/env bash
# tests/hooks/test_anti_slop_gate.sh — STAB-02 anti-slop gate battery
#
# Tests that .claude/hooks/pre_anti_slop_gate.py:
#   - Blocks Write/Edit to prompts/anti_slop.md (exit 2)
#   - Allows Write/Edit to other files (exit 0)
#
# Usage: bash tests/hooks/test_anti_slop_gate.sh
set -e

HOOK=".claude/hooks/pre_anti_slop_gate.py"
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

echo "=== test_anti_slop_gate.sh — STAB-02 battery ==="
echo ""

# -----------------------------------------------------------------------
# BLOCKED cases — protected anti-slop file (should exit 2)
# -----------------------------------------------------------------------
run_case "block-anti-slop-direct"   "prompts/anti_slop.md"              2
run_case "block-anti-slop-abs-path" "/abs/path/prompts/anti_slop.md"    2

# -----------------------------------------------------------------------
# ALLOWED cases — other prompt files and source files (should exit 0)
# -----------------------------------------------------------------------
run_case "allow-other-prompt"       "prompts/some_other_file.md"        0
run_case "allow-prompts-concept"    "prompts/concept-forger.md"         0
run_case "allow-pipeline"           "pipeline/foo.py"                   0
run_case "allow-tests"              "tests/test_x.py"                   0
run_case "allow-docs"               "docs/stabilization-cycle.md"       0

echo ""
echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed ==="

if [ "$FAIL_COUNT" -ne 0 ]; then
    exit 1
fi

echo "OK"
