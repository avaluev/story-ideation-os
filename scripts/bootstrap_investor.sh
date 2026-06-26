#!/usr/bin/env bash
# bootstrap_investor.sh — non-technical first-run setup for Anomaly Engine.
#
# Called by `make bootstrap`. Idempotent: safe to re-run.
#
# Steps:
#   1. Verify uv is installed (install if not)
#   2. uv sync --dev (install Python dependencies)
#   3. Copy .env.example -> .env if .env is missing
#   4. Prompt for OPENROUTER_API_KEY if it is not already set
#   5. chmod 600 .env
#   6. Run `make doctor` to validate end-to-end

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

say() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
err() { printf "  \033[1;31m✗\033[0m %s\n" "$*" >&2; }

# --- Step 1: uv check -------------------------------------------------------
say "Step 1/6 — checking for the uv package manager"
if ! command -v uv >/dev/null 2>&1; then
  err "uv not found."
  echo "  Install it by running:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  Then restart your terminal and re-run: make bootstrap"
  exit 1
fi
ok "uv $(uv --version | awk '{print $2}') detected"

# --- Step 2: install dependencies -------------------------------------------
say "Step 2/6 — installing Python dependencies (this takes 1-3 minutes)"
uv sync --dev
ok "dependencies installed"

# --- Step 3: create .env if missing -----------------------------------------
say "Step 3/6 — preparing the .env configuration file"
if [ ! -f .env ]; then
  if [ ! -f .env.example ]; then
    err ".env.example is missing from the repository — cannot continue"
    exit 1
  fi
  cp .env.example .env
  ok ".env created from .env.example"
else
  ok ".env already exists — will not overwrite"
fi

# --- Step 4: prompt for OpenRouter key --------------------------------------
say "Step 4/6 — OpenRouter API key"
# Detect whether a real key is already set under EITHER recognized name.
EXISTING_PAID=$(grep -E "^OPENROUTER_KEY_PAID=" .env | head -1 | cut -d= -f2- || true)
EXISTING_ALIAS=$(grep -E "^OPENROUTER_API_KEY=" .env | head -1 | cut -d= -f2- || true)
has_real_key=0
for v in "$EXISTING_PAID" "$EXISTING_ALIAS"; do
  if [ -n "$v" ] && ! echo "$v" | grep -q "REPLACE-ME"; then
    has_real_key=1
  fi
done

if [ "$has_real_key" -eq 0 ]; then
  echo "  Your OpenRouter API key is not yet set."
  echo "  Get one at: https://openrouter.ai/settings/keys"
  echo "  See:        docs/OPENROUTER_GUIDE.md"
  echo
  printf "  Paste your OpenRouter API key (starts with sk-or-v1-): "
  read -r USER_KEY
  if [ -z "$USER_KEY" ]; then
    err "no key entered — aborting"
    exit 1
  fi
  if ! echo "$USER_KEY" | grep -qE "^sk-or-v1-[A-Za-z0-9]{20,}"; then
    err "that does not look like an OpenRouter key (expected format: sk-or-v1-<long string>)"
    exit 1
  fi
  # Write the key under BOTH recognized names so the pipeline AND preflight find it.
  tmp_env=$(mktemp)
  awk -v key="$USER_KEY" '
    /^OPENROUTER_KEY_PAID=/   { print "OPENROUTER_KEY_PAID=" key; seen_paid=1; next }
    /^OPENROUTER_API_KEY=/    { print "OPENROUTER_API_KEY=" key; seen_alias=1; next }
    { print }
    END {
      if (!seen_paid)  { print "OPENROUTER_KEY_PAID=" key }
      if (!seen_alias) { print "OPENROUTER_API_KEY=" key }
    }
  ' .env > "$tmp_env"
  mv "$tmp_env" .env
  ok "key saved to .env under OPENROUTER_API_KEY and OPENROUTER_KEY_PAID"
else
  ok "OpenRouter key already set in .env"
fi

# --- Step 5: lock down permissions ------------------------------------------
say "Step 5/6 — locking down .env file permissions"
chmod 600 .env
ok ".env is now readable only by your user account ($(stat -f '%Sp' .env 2>/dev/null || stat -c '%A' .env 2>/dev/null))"

# --- Step 6: doctor ---------------------------------------------------------
say "Step 6/6 — running the doctor preflight check"
if uv run python scripts/preflight.py; then
  echo
  printf "\033[1;32m═══════════════════════════════════════════════════════════════\033[0m\n"
  printf "\033[1;32m  Bootstrap complete. Anomaly Engine is ready to run.\033[0m\n"
  printf "\033[1;32m═══════════════════════════════════════════════════════════════\033[0m\n"
  echo
  echo "  Next: try a first run with"
  echo "    make single THEME=\"A grief counselor discovers her clients are sharing the same recurring dream.\""
  echo
else
  echo
  err "doctor failed — see message above"
  echo "  See docs/INVESTOR_TROUBLESHOOTING.md for fixes."
  exit 1
fi
