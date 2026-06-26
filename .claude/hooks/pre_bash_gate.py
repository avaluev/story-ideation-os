#!/usr/bin/env python3
"""PreToolUse(Bash) hook — bash safety gate with gitleaks integration.

HARN-08, SEC-04: The agent MUST NOT run banned Bash patterns that bypass
the safety harness. This hook blocks banned commands and runs gitleaks
before any git push to prevent secret leaks.

Banned patterns:
  - --no-verify (bypasses pre-commit hooks)
  - --no-gpg-sign (bypasses signing)
  - git push --force / git push -f (destructive)
  - rm -rf / ~ $ (destructive root/home/var deletion)
  - chmod 777 (world-writable permissions)

Exit codes:
  0 → allow
  2 → block (stderr re-injected into agent context)

See: HARN-08, SEC-04, CLAUDE.md MUST NOT §3.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

#: Env override to allow a push when gitleaks is absent. Unset by default, so the
#: gate FAILS CLOSED (no scan == no push) instead of the old fail-open warn-and-allow.
_ALLOW_NO_GITLEAKS_ENV = "ALLOW_PUSH_WITHOUT_GITLEAKS"

_GITLEAKS_MISSING_MSG = f"""\
BLOCKED: gitleaks is not installed and a `git push` was attempted.
  WHY: pushing without a staged-secret scan can leak credentials (SEC-04).
       This gate now fails CLOSED -- a missing scanner no longer silently allows.
  FIX: install gitleaks (e.g. `brew install gitleaks`) and retry the push.
  OVERRIDE (only if you accept the risk): {_ALLOW_NO_GITLEAKS_ENV}=1 git push ...
"""

BANNED = [
    "--no-verify",
    "--no-gpg-sign",
    "rm -rf /",
    "rm -rf ~",
    "rm -rf $",
    "git push --force",
    "git push -f",
]

# Paths that are safe to rm -rf
ALLOWED_RM_PREFIXES = [
    "data/",
    "out/",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
]

BLOCKED_MSG = """\
BLOCKED: command contains banned pattern {pattern!r}.
  WHY: this pattern bypasses the safety harness (CLAUDE.md MUST NOT + HARN-08).
  FIX: investigate the underlying cause; never bypass safety in agent context.
  EXAMPLE: if pre-commit fails, FIX the lint errors — don't `--no-verify`.
"""


def _check_rm_safety(cmd_str: str) -> str | None:
    """Return error string if rm -rf targets a non-allowed path, else None."""
    if "rm -rf" not in cmd_str and "rm -r" not in cmd_str:
        return None

    try:
        parts = shlex.split(cmd_str)
    except ValueError:
        parts = cmd_str.split()

    # Find 'rm' in parts
    rm_idx = None
    for i, p in enumerate(parts):
        if p == "rm":
            rm_idx = i
            break

    if rm_idx is None:
        return None

    # Collect rm targets (args after flags)
    targets = [p for p in parts[rm_idx + 1 :] if not p.startswith("-")]

    for target in targets:
        # Normalise: strip leading ./
        t = target.lstrip("./")
        allowed = any(
            t.startswith(prefix) or target.startswith(prefix) for prefix in ALLOWED_RM_PREFIXES
        )
        if not allowed:
            return (
                f"BLOCKED: rm -rf target {target!r} is not in the allowed list.\n"
                f"  WHY: rm -rf outside data/, out/, cache dirs risks data loss (HARN-08).\n"
                f"  ALLOWED: {', '.join(ALLOWED_RM_PREFIXES)}\n"
                f"  FIX: restrict rm -rf to data/, out/, .pytest_cache, __pycache__.\n"
            )

    return None


def _project_root() -> str:
    """Repo root, cwd-independent. Claude Code exports CLAUDE_PROJECT_DIR; fall
    back to the cwd. Resolving the root here means a stray ``cd`` in an earlier
    Bash step can't point gitleaks at the wrong repo or miss the config."""
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _gitleaks_missing() -> str | None:
    """Fail CLOSED when gitleaks is absent, unless the operator has explicitly
    accepted the risk via the override env var. Returns a BLOCKED message
    (caller exits 2) or None (allow)."""
    if os.environ.get(_ALLOW_NO_GITLEAKS_ENV) == "1":
        print(
            f"WARNING: gitleaks not found — push allowed via {_ALLOW_NO_GITLEAKS_ENV}=1. "
            "No staged-secret scan ran.",
            file=sys.stderr,
        )
        return None
    return _GITLEAKS_MISSING_MSG


def _run_gitleaks(cmd_str: str) -> str | None:
    """Run gitleaks if cmd is a git push. Return error string or None.

    Fails CLOSED: if gitleaks is not installed the push is BLOCKED (unless the
    operator sets the override env var) rather than silently allowed.
    """
    try:
        parts = shlex.split(cmd_str)
    except ValueError:
        parts = cmd_str.split()

    if "git" not in parts or "push" not in parts:
        return None

    root = _project_root()
    config = os.path.join(root, ".gitleaks.toml")
    cmd = ["gitleaks", "protect", "--staged", "--no-banner"]
    if os.path.exists(config):
        cmd += ["--config", config]

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=root,
        )
        _GITLEAKS_NOT_FOUND = 127
        if result.returncode == _GITLEAKS_NOT_FOUND:
            return _gitleaks_missing()
        if result.returncode != 0:
            output_tail = (result.stdout + result.stderr)[-2000:]
            return (
                f"BLOCKED: gitleaks detected potential secrets staged for push.\n"
                f"  WHY: pushing secrets exposes credentials (SEC-04).\n"
                f"  FIX: rotate the leaked credential, then remove it from tracked files.\n"
                f"  EXAMPLE: add the file to .gitignore and use .env for secrets.\n"
                f"  gitleaks output:\n{output_tail}\n"
            )
    except FileNotFoundError:
        return _gitleaks_missing()

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    cmd_str: str = payload.get("tool_input", {}).get("command", "") or ""

    # Check banned substring patterns first
    for banned in BANNED:
        if banned in cmd_str:
            print(BLOCKED_MSG.format(pattern=banned), file=sys.stderr)
            return 2

    # Check chmod 777
    if "chmod 777" in cmd_str:
        print(BLOCKED_MSG.format(pattern="chmod 777"), file=sys.stderr)
        return 2

    # Check rm safety (allow only safe targets)
    if "rm -rf" in cmd_str or "rm -r " in cmd_str:
        error = _check_rm_safety(cmd_str)
        if error:
            print(error, file=sys.stderr)
            return 2

    # Run gitleaks for git push
    gitleaks_error = _run_gitleaks(cmd_str)
    if gitleaks_error:
        print(gitleaks_error, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
