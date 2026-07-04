"""User preferences persisted to ~/.open-dive-log/preferences.json.

For now this stores just the unit system (metric/imperial). Add other
preferences here as they come up (window geometry, last-opened file,
default agency, etc.). Each preference gets a typed getter/setter
function so the JSON shape is centralized in one place.

The file is created on first save; on read, missing keys fall back to
sane defaults. The path can be overridden via the `OPEN_DIVE_LOG_HOME`
env var (useful for tests and CI).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .units import UnitSystem


_DEFAULT_HOME = Path.home() / ".open-dive-log"
_DEFAULT_PREFS_PATH = _DEFAULT_HOME / "preferences.json"

_DEFAULTS: dict[str, object] = {
    "units": UnitSystem.METRIC.value,
}


def _home_dir() -> Path:
    """Resolve the preferences directory, honoring the override env var."""
    override = os.environ.get("OPEN_DIVE_LOG_HOME")
    if override:
        return Path(override)
    return _DEFAULT_HOME


def prefs_path() -> Path:
    return _home_dir() / "preferences.json"


def load() -> dict[str, object]:
    """Read the preferences file. Missing file or malformed JSON → defaults.

    Unknown keys are preserved (forward compatibility — the file might
    have been written by a newer version of the app).
    """
    path = prefs_path()
    if not path.is_file():
        return dict(_DEFAULTS)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return dict(_DEFAULTS)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return dict(_DEFAULTS)
    if not isinstance(data, dict):
        return dict(_DEFAULTS)
    # Merge in defaults for any missing keys
    for k, v in _DEFAULTS.items():
        data.setdefault(k, v)
    return data


def save(data: dict[str, object]) -> None:
    """Write the preferences file. Creates the parent dir if needed.

    Atomic-ish: write to a temp file in the same dir, then rename. This
    avoids leaving a half-written file if the process is killed mid-write.
    """
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Typed accessors for the supported preferences
# ---------------------------------------------------------------------------
def get_units() -> UnitSystem:
    raw = load().get("units", UnitSystem.METRIC.value)
    try:
        return UnitSystem(raw)
    except ValueError:
        return UnitSystem.METRIC


def set_units(system: UnitSystem) -> None:
    data = load()
    data["units"] = system.value
    save(data)
