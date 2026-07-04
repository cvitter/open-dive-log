"""Unit conversion helpers. Pure functions, no Qt.

The DB always stores metric (°C, meters). The form / list view may
display imperial (°F, feet) depending on the user's preference; this
module is the boundary that converts at that edge.

The two extra fields added in migration 005 (air_temp_c, water_temp_c,
visibility_m) join the existing max_depth_m / avg_depth_m in being
subject to the toggle.
"""

from __future__ import annotations

from enum import Enum


class UnitSystem(str, Enum):
    METRIC = "metric"
    IMPERIAL = "imperial"


# Conversion factors (exact)
_M_PER_FT = 0.3048

# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------
def c_to_f(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (fahrenheit - 32.0) * 5.0 / 9.0


# ---------------------------------------------------------------------------
# Distance (length)
# ---------------------------------------------------------------------------
def m_to_ft(meters: float) -> float:
    """Convert meters to feet."""
    return meters / _M_PER_FT


def ft_to_m(feet: float) -> float:
    """Convert feet to meters."""
    return feet * _M_PER_FT


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def temp_unit_label(system: UnitSystem) -> str:
    return "°C" if system == UnitSystem.METRIC else "°F"


def distance_unit_label(system: UnitSystem) -> str:
    return "m" if system == UnitSystem.METRIC else "ft"


def display_temp(celsius: float | None, system: UnitSystem) -> tuple[float | None, str]:
    """Convert a stored °C value to the user's preferred unit for display.

    Returns (display_value, unit_label). If `celsius` is None, returns
    (None, unit_label) so callers can show the unit in the placeholder
    or suffix regardless.
    """
    if celsius is None:
        return None, temp_unit_label(system)
    if system == UnitSystem.METRIC:
        return celsius, "°C"
    return c_to_f(celsius), "°F"


def display_distance(meters: float | None, system: UnitSystem) -> tuple[float | None, str]:
    if meters is None:
        return None, distance_unit_label(system)
    if system == UnitSystem.METRIC:
        return meters, "m"
    return m_to_ft(meters), "ft"
