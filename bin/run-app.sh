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

# ----------------------------------------------------------------
# Verify the PySide6 Cocoa plugin is intact.
#
# On macOS, the Qt Cocoa plugin (libqcocoa.dylib) is delivered inside
# the PySide6_Essentials wheel. If it ever becomes corrupted on disk
# (e.g. its codesign identifier no longer matches its filename, or the
# binary grew due to a bad copy), the Qt plugin loader will fail with
# `qt.qpa.plugin: Could not find the Qt platform plugin "cocoa"` on
# the *next* launch, even though the previous launch appeared to
# succeed. macOS sets a `com.apple.provenance` xattr on the freshly-
# extracted dylib automatically; that xattr is harmless and does NOT
# prevent loading. The real failure mode is a broken code signature
# or a size mismatch.
#
# The check below looks at the codesign identifier; if it doesn't
# end with "libqcocoa.dylib", we reinstall PySide6_Essentials (a fast
# re-extract of just the platform-plugin wheel) before launching.
# This makes the "app can only be opened once" symptom self-healing.
# ----------------------------------------------------------------
DYLIB="$PROJECT_ROOT/.venv/lib/python3.13/site-packages/PySide6/Qt/plugins/platforms/libqcocoa.dylib"
NEEDS_REINSTALL=0
if [[ ! -f "$DYLIB" ]]; then
    NEEDS_REINSTALL=1
    echo "open-dive-log: libqcocoa.dylib missing; reinstalling PySide6_Essentials" >&2
else
    # `codesign -dvv` prints "Identifier=<name>" to stderr. We need
    # the `-vv` flag — plain `codesign -d` only prints the Executable
    # line. If the identifier doesn't match "libqcocoa.dylib", the
    # dylib has been corrupted (e.g. by a bad `cp` that broke the
    # signature) and we need a clean reinstall.
    IDENTIFIER="$(codesign -dvv "$DYLIB" 2>&1 1>/dev/null | awk -F= '/^Identifier=/ {print $2; exit}')"
    if [[ "$IDENTIFIER" != "libqcocoa.dylib" ]]; then
        NEEDS_REINSTALL=1
        echo "open-dive-log: libqcocoa.dylib signature is corrupted" >&2
        echo "  (identifier is '$IDENTIFIER', expected 'libqcocoa.dylib')" >&2
        echo "  reinstalling PySide6_Essentials..." >&2
    fi
fi
if [[ "$NEEDS_REINSTALL" -eq 1 ]]; then
    # Reinstall PySide6 (the meta package) along with its version-
    # pinned sub-packages (PySide6_Essentials, PySide6_Addons,
    # shiboken6). We must NOT pull the latest version of any of
    # these, because mixing PySide6 X.Y.Z with PySide6_Essentials
    # X.Y+1.W produces a dylib that the Qt plugin loader refuses
    # (this has happened with the 6.10/6.11 mix on macOS arm64).
    # By reinstalling PySide6 with no version specifier and using
    # its existing constraints, pip will re-resolve the matching
    # 6.10.3 sub-packages.
    PYSIDE_VER="$("$VENV_PY" -c "import PySide6; print(PySide6.__version__)")"
    echo "  reinstalling PySide6==${PYSIDE_VER} (matches the venv's Qt version)..." >&2
    "$PROJECT_ROOT/.venv/bin/pip" install --force-reinstall --no-deps "PySide6==${PYSIDE_VER}" >&2
    # Re-extract the platform-plugin wheel (this is the one that
    # contains libqcocoa.dylib). --no-deps keeps pip from trying to
    # upgrade the meta package to a different version.
    "$PROJECT_ROOT/.venv/bin/pip" install --force-reinstall --no-deps "PySide6_Essentials==${PYSIDE_VER}" >&2
fi

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
