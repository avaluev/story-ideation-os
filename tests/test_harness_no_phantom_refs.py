"""Harness enforcer: every module / hook the harness *references* must resolve.

Why this exists
===============

A phantom reference is a command the harness invokes that points at something
that no longer exists -- e.g. the deleted hook ``post_tool_use_score_apply.py``
shelled ``pipeline.scoring_apply`` whose ``find_spec`` is ``None``. Such a
reference fails silently (the hook errors, the tool call may wedge, or the gate
quietly does nothing). A cleanup with no enforcer re-accumulates that exact debt,
so this test makes the whole class mechanically visible inside ``make test``:

  * every ``uv run python -m <dotted.module>`` in the ``Makefile`` resolves via
    :func:`importlib.util.find_spec`;
  * every ``uv run python <path>.py`` in the ``Makefile`` points at a real file;
  * every hook ``command`` in ``.claude/settings.json`` points at a hook script
    that exists on disk.

This is the runtime half of the ``make dead-code`` reachability sweep (the static
half, vulture, lives in the Makefile per docs/HARNESS_HARDENING_OPERATOR_PATCHES).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
SETTINGS = ROOT / ".claude" / "settings.json"

# `python -m a.b.c` -> capture the dotted module path.
_PY_MODULE_RE = re.compile(r"python3?\s+-m\s+([A-Za-z_][\w.]+)")
# `python path/to/script.py` -> capture the script path (not -m, not -c).
_PY_SCRIPT_RE = re.compile(r"python3?\s+(?!-[mc])((?:\.?/?[\w./-]+)\.py)\b")


def _rel(path: str) -> str:
    """Strip only a leading ``./`` (NOT ``str.lstrip('./')``, which would also
    eat the leading dot of ``.claude/...``)."""
    return path[2:] if path.startswith("./") else path


def _makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8") if MAKEFILE.exists() else ""


def test_makefile_python_m_modules_resolve() -> None:
    """Every ``python -m <module>`` the Makefile invokes must be importable.

    Catches the phantom-module class (a target shelling a module that was
    renamed/removed -- the gate then does nothing while ``make`` exits 0).
    """
    text = _makefile_text()
    modules = sorted(set(_PY_MODULE_RE.findall(text)))
    assert modules, "expected to find at least one `python -m` reference in the Makefile"
    unresolved = [m for m in modules if importlib.util.find_spec(m) is None]
    assert not unresolved, (
        f"Makefile references modules that do not resolve (phantom `python -m`): {unresolved}. "
        "Fix the reference or remove the target."
    )


def test_makefile_python_script_paths_exist() -> None:
    """Every ``python <path>.py`` the Makefile invokes must exist on disk."""
    text = _makefile_text()
    scripts = sorted(set(_PY_SCRIPT_RE.findall(text)))
    missing = [s for s in scripts if not (ROOT / _rel(s)).exists()]
    assert not missing, f"Makefile references script paths that do not exist: {missing}"


def test_settings_hook_scripts_exist() -> None:
    """Every hook ``command`` wired in settings.json must point at a real file.

    This is exactly the failure the three deleted hooks would have re-introduced
    had any been left referenced: a settings.json entry pointing at a missing
    ``.claude/hooks/*.py`` errors on every matching tool call.
    """
    if not SETTINGS.exists():
        return  # settings.json is environment-local; nothing to check
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    commands: list[str] = []
    for _event, groups in data.get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    commands.append(cmd)
    referenced = sorted({m for cmd in commands for m in _PY_SCRIPT_RE.findall(cmd)})
    missing = [s for s in referenced if not (ROOT / _rel(s)).exists()]
    assert not missing, (
        f"settings.json wires hook scripts that do not exist on disk: {missing}. "
        "A missing wired hook errors on every matching tool call."
    )
