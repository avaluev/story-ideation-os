#!/usr/bin/env python3
"""preflight.py - investor-mode environment validator for Anomaly Engine.

Called by `make doctor`. Exits 0 if the environment is ready for `make single`.
Exits non-zero with a single human-readable error line on the first failure.

Checks:
  1. Python >= 3.11
  2. `uv` binary is on PATH and reports a version
  3. .env file exists, has OPENROUTER_API_KEY matching ^sk-or-v1-
  4. The key is live: GET https://openrouter.ai/api/v1/auth/key with the key
     in the Authorization header returns HTTP 200 with a JSON body. This call
     does NOT consume any credits - it is the documented validity endpoint.

Designed to be run by a non-technical user. All output is plain English.
"""

import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
OPENROUTER_VALIDITY_URL = "https://openrouter.ai/api/v1/auth/key"
KEY_PATTERN = re.compile(r"^sk-or-v1-[A-Za-z0-9]{20,}$")

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_PAYMENT_REQUIRED = 402
HTTP_TOO_MANY_REQUESTS = 429
MIN_PYTHON = (3, 11)


def green(msg: str) -> None:
    print(f"  \033[1;32m✓\033[0m {msg}")


def red(msg: str) -> None:
    print(f"  \033[1;31m✗\033[0m {msg}", file=sys.stderr)


def header(msg: str) -> None:
    print(f"\n\033[1;36m▶ {msg}\033[0m")


def fail(msg: str, exit_code: int = 1) -> NoReturn:
    red(msg)
    print(
        "\n  See docs/INVESTOR_TROUBLESHOOTING.md for fixes.",
        file=sys.stderr,
    )
    sys.exit(exit_code)


def check_python() -> None:
    header("Check 1/4 - Python version")
    major, minor = sys.version_info[:2]
    if (major, minor) < MIN_PYTHON:
        fail(f"Python {major}.{minor} detected; need Python >= 3.11")
    green(f"Python {major}.{minor}.{sys.version_info[2]} (>= 3.11)")


def check_uv() -> None:
    header("Check 2/4 - uv package manager")
    uv_path = shutil.which("uv")
    if uv_path is None:
        fail("uv not found on PATH. Install: curl -LsSf https://astral.sh/uv/install.sh | sh")
    try:
        out = subprocess.run(  # noqa: S603
            [uv_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fail("uv --version timed out after 5 seconds")
    except OSError as exc:
        fail(f"could not invoke uv: {exc}")
    if out.returncode != 0:
        fail(f"uv exited {out.returncode}: {out.stderr.strip()}")
    green(out.stdout.strip())


def read_env_key() -> str:
    header("Check 3/4 - .env configuration")
    if not ENV_PATH.exists():
        fail(
            f".env not found at {ENV_PATH}. Run `bash scripts/bootstrap_investor.sh` to create it."
        )
    # Accept either of the two recognized env var names. The pipeline reads
    # OPENROUTER_KEY_PAID first (legacy); OPENROUTER_API_KEY is the investor alias.
    accepted_names = ("OPENROUTER_API_KEY", "OPENROUTER_KEY_PAID")
    found = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        for name in accepted_names:
            if stripped.startswith(f"{name}="):
                value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                if value and "REPLACE-ME" not in value:
                    found[name] = value
    if not found:
        fail(
            ".env does not contain a real OpenRouter key. "
            "Run `bash scripts/bootstrap_investor.sh` and paste your key when prompted."
        )
    # Use whichever was found; prefer the investor alias.
    key = found.get("OPENROUTER_API_KEY") or found.get("OPENROUTER_KEY_PAID")
    assert key is not None
    if not KEY_PATTERN.match(key):
        fail(
            "OpenRouter key does not look right. "
            "Expected format: sk-or-v1-<long alphanumeric string>"
        )
    green(f"OpenRouter key format OK (starts with {key[:12]}...)")
    return key


def check_key_live(key: str) -> None:
    header("Check 4/4 - OpenRouter key validity (1 free API call)")
    req = urllib.request.Request(  # noqa: S310
        OPENROUTER_VALIDITY_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "anomaly-engine-investor-preflight/1.0",
        },
    )
    status = 0
    body_preview = ""
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            status = resp.status
            body_preview = resp.read(512).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == HTTP_UNAUTHORIZED:
            fail(
                "OpenRouter returned 401 Unauthorized. "
                "The key is invalid or was revoked. "
                "Create a new one at https://openrouter.ai/settings/keys"
            )
        if exc.code == HTTP_PAYMENT_REQUIRED:
            fail(
                "OpenRouter returned 402 Payment Required. "
                "Top up credits at https://openrouter.ai/settings/credits"
            )
        if exc.code == HTTP_TOO_MANY_REQUESTS:
            fail(
                "OpenRouter returned 429 Too Many Requests. "
                "Wait 60 seconds and try `make doctor` again."
            )
        fail(f"OpenRouter returned HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        fail(
            f"could not reach openrouter.ai: {exc.reason}. "
            "Check your internet connection and try again."
        )
    except TimeoutError:
        fail("OpenRouter request timed out after 10 seconds")

    if status != HTTP_OK:
        fail(f"OpenRouter returned HTTP {status} (expected 200). Body: {body_preview}")
    green("OpenRouter key is live and authorized")


def main() -> int:
    print("Anomaly Engine - investor preflight check")
    check_python()
    check_uv()
    key = read_env_key()
    check_key_live(key)
    print("\n\033[1;32m════════════════\033[0m")
    print('\033[1;32m  All checks passed. Ready for: make single THEME="..."\033[0m')
    print("\033[1;32m════════════════\033[0m\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
