#!/bin/bash
# Launcher for the open-dive-log GUI.
#
# Why this script exists: Python 3.14 doesn't process the venv's
# editable-install .pth file when PYTHONPATH is set in the env (Hermes
# injects PYTHONPATH=/Users/craigvitter/.hermes/hermes-agent into every
# shell). So `python3.14 -m open_dive_log` fails with ModuleNotFoundError
# when launched from a Hermes terminal.
#
# This wrapper sets PYTHONPATH=src explicitly, which sidesteps the bug
# without modifying the venv or fighting pip's console-script template.
#
# Usage: bin/run-app.sh          (from the project root)
#        bash bin/run-app.sh     (from anywhere)
set -euo pipefail

# Find the project root: this script lives at <project>/bin/run-app.sh
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"

VENV_PY="$PROJECT_ROOT/.venv/bin/python3.13"
if [[ ! -x "$VENV_PY" ]]; then
    echo "open-dive-log: venv python not found at $VENV_PY" >&2
    echo "open-dive-log: run: brew install python@3.13 && python3.13 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'" >&2
    exit 1
fi

cd "$PROJECT_ROOT"
# Strip the Hermes-injected PYTHONPATH. Two reasons:
#   1. PYTHONPATH-set envs skip .pth processing on Python 3.14, which
#      breaks the editable install (we set PYTHONPATH=src ourselves below
#      to work around that).
#   2. The Hermes injection includes `~/.hermes/hermes-agent/venv/lib/python3.11/site-packages`
#      on the path. On a fresh project venv (Python 3.13) this can cause
#      pip to "see" packages that aren't actually installed locally
#      (e.g. Pygments), and runtime imports can land on Python 3.11
#      bytecode when the running interpreter is 3.13. Both manifest as
#      confusing ModuleNotFoundError or AttributeError on a clean
#      `pip install -e ".[dev]"`. Stripping the inherited PYTHONPATH
#      before the explicit `PYTHONPATH=src` makes the launcher
#      deterministic.
exec env -u PYTHONPATH PYTHONPATH="$PROJECT_ROOT/src" "$VENV_PY" -m open_dive_log "$@"
