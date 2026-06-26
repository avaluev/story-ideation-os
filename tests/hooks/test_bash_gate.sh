#!/usr/bin/env bash
# tests/hooks/test_bash_gate.sh — SEC-04, HARN-08 full battery
#
# Tests that .claude/hooks/pre_bash_gate.py blocks banned bash patterns
# and allows safe commands.
#
# Plan 00-01: shipped scaffold with SKIP-then-real pattern.
# Plan 00-03: replaced scaffold with full battery (pre_bash_gate.py now exists).
#
# Usage: bash tests/hooks/test_bash_gate.sh
set -euo pipefail

HOOK=".claude/hooks/pre_bash_gate.py"

if [ ! -f "$HOOK" ]; then
  echo "FAIL: $HOOK missing (plan 00-03 should have created it)"
  exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0

run_case() {
    local desc="$1"
    local cmd="$2"
    local expect_exit="$3"

    # Build JSON payload
    local payload
    payload=$(printf '{"tool_input":{"command":%s}}' \
        "$(printf '%s' "$cmd" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")

    local output exit_code
    exit_code=0
    output=$(echo "$payload" | uv run python "$HOOK" 2>&1) || exit_code=$?

    if [ "$exit_code" != "$expect_exit" ]; then
        echo "FAIL [$desc]: expected exit $expect_exit, got $exit_code"
        echo "  cmd: $cmd"
        if [ -n "$output" ]; then
            echo "  output: $output"
        fi
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo "PASS [$desc]"
        PASS_COUNT=$((PASS_COUNT + 1))
    fi
}

echo "=== test_bash_gate.sh — SEC-04 / HARN-08 battery ==="
echo ""

# -----------------------------------------------------------------------
# ALLOWED commands (should pass through — exit 0)
# -----------------------------------------------------------------------
# NOTE: git push may warn about gitleaks not installed, but exits 0
run_case "allow-push"       "git push origin main"          0
run_case "allow-rm-data"    "rm -rf data/staging"           0
run_case "allow-rm-out"     "rm -rf out/old"                0
run_case "allow-rm-cache"   "rm -rf __pycache__"            0
run_case "allow-make-test"  "make test"                     0
run_case "allow-uv-run"     "uv run pytest tests/"          0
run_case "allow-git-status" "git status"                    0

# -----------------------------------------------------------------------
# BLOCKED commands (should be denied — exit 2)
# -----------------------------------------------------------------------
run_case "block-noverify"   "git commit --no-verify"        2
run_case "block-nogpg"      "git commit --no-gpg-sign"      2
run_case "block-force"      "git push --force origin main"  2
run_case "block-pushf"      "git push -f origin main"       2
run_case "block-rm-root"    "rm -rf /"                      2
run_case "block-rm-home"    "rm -rf ~"                      2
run_case "block-rm-dollar"  'rm -rf $TMP'                   2
run_case "block-chmod777"   "chmod 777 foo"                 2

echo ""
echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed ==="

if [ "$FAIL_COUNT" -ne 0 ]; then
    exit 1
fi

echo "OK"
