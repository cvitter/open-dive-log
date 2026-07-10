"""Tests for the units conversion module and the preferences module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_dive_log import preferences
from open_dive_log.units import (
    UnitSystem,
    bar_to_psi,
    c_to_f,
    f_to_c,
    ft_to_m,
    m_to_ft,
    display_distance,
    display_pressure,
    display_temp,
    distance_unit_label,
    pressure_unit_label,
    psi_to_bar,
    temp_unit_label,
)


# ---------------------------------------------------------------------------
# Temperature conversions
# ---------------------------------------------------------------------------
def test_c_to_f_freezing_and_boiling() -> None:
    assert c_to_f(0) == 32.0
    assert c_to_f(100) == 212.0
    assert c_to_f(-40) == -40.0  # the famous "same in C and F" point


def test_f_to_c_freezing_and_boiling() -> None:
    assert f_to_c(32) == pytest.approx(0, abs=1e-9)
    assert f_to_c(212) == pytest.approx(100, abs=1e-9)
    assert f_to_c(-40) == pytest.approx(-40, abs=1e-9)


def test_round_trip_celsius_fahrenheit() -> None:
    """c -> f -> c returns the original (within float precision)."""
    for c in (0, 18, 24, 30, 36.5, -5):
        assert f_to_c(c_to_f(c)) == pytest.approx(c, abs=1e-9)


# ---------------------------------------------------------------------------
# Distance conversions
# ---------------------------------------------------------------------------
def test_m_to_ft_one_meter() -> None:
    assert m_to_ft(1) == pytest.approx(3.28084, abs=1e-4)


def test_ft_to_m_three_feet() -> None:
    # 3 ft = 0.9144 m exactly
    assert ft_to_m(3) == pytest.approx(0.9144, abs=1e-9)


def test_round_trip_meters_feet() -> None:
    for m in (0, 1, 5, 10, 18, 24, 30, 40):
        assert ft_to_m(m_to_ft(m)) == pytest.approx(m, abs=1e-9)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def test_display_temp_metric_returns_celsius() -> None:
    val, unit = display_temp(24.0, UnitSystem.METRIC)
    assert val == 24.0
    assert unit == "°C"


def test_display_temp_imperial_returns_fahrenheit() -> None:
    val, unit = display_temp(24.0, UnitSystem.IMPERIAL)
    assert val == pytest.approx(75.2, abs=1e-9)
    assert unit == "°F"


def test_display_temp_none_preserves_unit_label() -> None:
    val, unit = display_temp(None, UnitSystem.IMPERIAL)
    assert val is None
    assert unit == "°F"


def test_display_distance_imperial() -> None:
    val, unit = display_distance(24.0, UnitSystem.IMPERIAL)
    assert val == pytest.approx(78.74, abs=1e-2)
    assert unit == "ft"


def test_display_distance_metric() -> None:
    val, unit = display_distance(24.0, UnitSystem.METRIC)
    assert val == 24.0
    assert unit == "m"


def test_unit_labels() -> None:
    assert temp_unit_label(UnitSystem.METRIC) == "°C"
    assert temp_unit_label(UnitSystem.IMPERIAL) == "°F"
    assert distance_unit_label(UnitSystem.METRIC) == "m"
    assert distance_unit_label(UnitSystem.IMPERIAL) == "ft"


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
@pytest.fixture()
def isolated_prefs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the preferences module at a temp dir for the duration of the test."""
    monkeypatch.setenv("OPEN_DIVE_LOG_HOME", str(tmp_path))
    return tmp_path / "preferences.json"


def test_prefs_default_is_metric(isolated_prefs: Path) -> None:
    assert preferences.get_units() == UnitSystem.METRIC


def test_prefs_set_and_get_imperial(isolated_prefs: Path) -> None:
    preferences.set_units(UnitSystem.IMPERIAL)
    assert preferences.get_units() == UnitSystem.IMPERIAL
    assert isolated_prefs.is_file()


def test_prefs_persists_across_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPEN_DIVE_LOG_HOME", str(tmp_path))
    preferences.set_units(UnitSystem.IMPERIAL)
    # New "session" — call load() directly to confirm it reads from disk
    data = preferences.load()
    assert data["units"] == "imperial"


def test_prefs_file_format_is_human_readable(isolated_prefs: Path) -> None:
    preferences.set_units(UnitSystem.IMPERIAL)
    text = isolated_prefs.read_text(encoding="utf-8")
    # Should be a JSON object with the units key.
    data = json.loads(text)
    assert "units" in data
    assert data["units"] == "imperial"


def test_prefs_handles_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPEN_DIVE_LOG_HOME", str(tmp_path))
    assert not preferences.prefs_path().is_file()
    data = preferences.load()
    # Defaults filled in
    assert data["units"] == "metric"


def test_prefs_handles_malformed_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPEN_DIVE_LOG_HOME", str(tmp_path))
    preferences.prefs_path().parent.mkdir(parents=True, exist_ok=True)
    preferences.prefs_path().write_text("{ not valid json", encoding="utf-8")
    # Malformed → returns defaults rather than raising.
    assert preferences.get_units() == UnitSystem.METRIC


def test_prefs_handles_unknown_unit_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPEN_DIVE_LOG_HOME", str(tmp_path))
    preferences.prefs_path().parent.mkdir(parents=True, exist_ok=True)
    preferences.prefs_path().write_text(
        json.dumps({"units": "furlongs_per_fortnight"}), encoding="utf-8"
    )
    # Unknown value falls back to metric.
    assert preferences.get_units() == UnitSystem.METRIC


def test_prefs_atomic_write(isolated_prefs: Path) -> None:
    """set_units should not leave a half-written file if the process is
    killed mid-write. We can't easily test the crash mid-write, but we
    can check that no .tmp file lingers after a successful write."""
    preferences.set_units(UnitSystem.IMPERIAL)
    assert not (isolated_prefs.parent / "preferences.json.tmp").exists()


# ---------------------------------------------------------------------------
# Pressure conversions
# ---------------------------------------------------------------------------
def test_bar_to_psi_one_bar() -> None:
    assert bar_to_psi(1.0) == pytest.approx(14.5037738, abs=1e-6)


def test_psi_to_bar_one_psi() -> None:
    assert psi_to_bar(1.0) == pytest.approx(0.0689476, abs=1e-6)


def test_bar_to_psi_typical_fill() -> None:
    # 200 BAR (standard European fill) → ~2900.75 PSI
    assert bar_to_psi(200.0) == pytest.approx(2900.7548, abs=1e-2)


def test_psi_to_bar_typical_fill() -> None:
    # 3000 PSI (standard US fill) → ~206.84 BAR
    assert psi_to_bar(3000.0) == pytest.approx(206.8427, abs=1e-3)


def test_round_trip_pressure_bar_psi() -> None:
    """BAR → PSI → BAR returns the original (within float precision)."""
    for bar in (0, 50, 100, 200, 232, 300, 350):
        assert psi_to_bar(bar_to_psi(bar)) == pytest.approx(bar, abs=1e-9)


def test_round_trip_pressure_psi_bar() -> None:
    for psi in (0, 500, 1500, 2900, 3364, 4351, 5076):
        assert bar_to_psi(psi_to_bar(psi)) == pytest.approx(psi, abs=1e-9)


def test_zero_pressure_round_trips() -> None:
    """0 BAR (empty tank) and 0 PSI (empty tank) are both real values,
    not 'not entered'. Round-trip must preserve 0."""
    assert bar_to_psi(0.0) == 0.0
    assert psi_to_bar(0.0) == 0.0


# ---------------------------------------------------------------------------
# Pressure display helpers
# ---------------------------------------------------------------------------
def test_display_pressure_metric() -> None:
    val, unit = display_pressure(200.0, UnitSystem.METRIC)
    assert val == 200.0
    assert unit == "bar"


def test_display_pressure_imperial() -> None:
    val, unit = display_pressure(200.0, UnitSystem.IMPERIAL)
    assert val == pytest.approx(2900.7548, abs=1e-2)
    assert unit == "psi"


def test_display_pressure_none_preserves_unit_label() -> None:
    val, unit = display_pressure(None, UnitSystem.IMPERIAL)
    assert val is None
    assert unit == "psi"


def test_pressure_unit_label() -> None:
    assert pressure_unit_label(UnitSystem.METRIC) == "bar"
    assert pressure_unit_label(UnitSystem.IMPERIAL) == "psi"
