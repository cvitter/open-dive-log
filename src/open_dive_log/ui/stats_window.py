"""Dive log statistics screen.

Shows the key aggregate numbers from the diver's logbook:
  * Number of dives
  * Longest / shortest / average / total bottom time
  * Deepest dive (in the user's unit system)
  * Average dive depth (in the user's unit system)
  * Distinct dive sites
  * Distinct countries

A modal-ish QMainWindow so it has its own status bar and lives
independently of the main window's selection. The user opens it
from the main window's View menu ("Show &Stats…") and dismisses
with the close button.

The depth values are stored in meters in the DB; the UI converts
to feet when the user is in imperial mode (the unit toggle is
propagated from the main window via set_unit_system()).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories.dives import DiveStats, compute_stats
from open_dive_log.units import (
    UnitSystem,
    distance_unit_label,
    m_to_ft,
)


def _format_depth(value: float | None, system: UnitSystem) -> str:
    """Format a depth for display. None → empty string.

    Mirrors `dive_table_model._format_depth` so the Stats screen
    and the dive list use the same format (integer when whole,
    one decimal otherwise; ' m' or ' ft' suffix).
    """
    if value is None:
        return ""
    if system == UnitSystem.METRIC:
        if value == int(value):
            return f"{int(value)} m"
        return f"{value:.1f} m"
    ft = m_to_ft(value)
    if ft == int(ft):
        return f"{int(ft)} ft"
    return f"{ft:.1f} ft"


def _format_depth_avg(value: float | None, system: UnitSystem) -> str:
    """Format an average depth (always one decimal place).

    Averages of values like 18, 30, 12 = 20.0 are conceptually
    fractional even when they happen to be integers; showing "20 m"
    obscures that. Use this for the "Average dive depth" stat.
    """
    if value is None:
        return ""
    if system == UnitSystem.METRIC:
        return f"{value:.1f} m"
    return f"{m_to_ft(value):.1f} ft"


@dataclass(frozen=True, slots=True)
class _StatRow:
    """A single (label, value-formatter) pair in the stats grid."""
    label: str
    # The value-formatter takes (stats, system) and returns a string
    # for display, or None if the value isn't available.
    fmt: "callable[[DiveStats, UnitSystem], str | None]"


def _fmt_minutes(stats: DiveStats, _system: UnitSystem) -> str | None:
    if stats.longest_minutes is None:
        return None
    return f"{stats.longest_minutes} min"


def _fmt_shortest(stats: DiveStats, _system: UnitSystem) -> str | None:
    if stats.shortest_minutes is None:
        return None
    return f"{stats.shortest_minutes} min"


def _fmt_average_minutes(stats: DiveStats, _system: UnitSystem) -> str | None:
    if stats.average_minutes is None:
        return None
    # One decimal place; user can see the precision
    return f"{stats.average_minutes:.1f} min"


def _fmt_total_minutes(stats: DiveStats, _system: UnitSystem) -> str | None:
    if stats.total_minutes is None:
        return None
    return f"{stats.total_minutes:,} min"


def _fmt_dive_count(stats: DiveStats, _system: UnitSystem) -> str | None:
    return f"{stats.dive_count:,}"


def _fmt_deepest(stats: DiveStats, system: UnitSystem) -> str | None:
    if stats.deepest_m is None:
        return None
    return _format_depth(stats.deepest_m, system)


def _fmt_average_depth(stats: DiveStats, system: UnitSystem) -> str | None:
    if stats.average_depth_m is None:
        return None
    return _format_depth_avg(stats.average_depth_m, system)


def _fmt_sites(stats: DiveStats, _system: UnitSystem) -> str | None:
    return f"{stats.distinct_sites:,}"


def _fmt_countries(stats: DiveStats, _system: UnitSystem) -> str | None:
    return f"{stats.distinct_countries:,}"


# Build the three groups from the formatters above. Each group has
# its own section header and grid of (label, value) rows.
_TIME_ROWS: list[_StatRow] = [
    _StatRow("Number of dives", _fmt_dive_count),
    _StatRow("Longest dive", _fmt_minutes),
    _StatRow("Shortest dive", _fmt_shortest),
    _StatRow("Average dive length", _fmt_average_minutes),
    _StatRow("Total dive time", _fmt_total_minutes),
]

_DEPTH_ROWS: list[_StatRow] = [
    _StatRow("Deepest dive", _fmt_deepest),
    _StatRow("Average dive depth", _fmt_average_depth),
]

_PLACE_ROWS: list[_StatRow] = [
    _StatRow("Number of dive sites", _fmt_sites),
    _StatRow("Number of countries", _fmt_countries),
]


def _not_recorded() -> str:
    """The displayed placeholder when a stat has no value yet
    (e.g. no dive has a recorded max_depth)."""
    return "—"


def _build_group(title: str, rows: list[_StatRow]) -> tuple[QGroupBox, list[tuple[QLabel, QLabel]]]:
    """Build a QGroupBox with a 2-column grid (label, value).

    Returns the group box and the list of (label, value) widget
    pairs so the caller can re-render the values when the unit
    system changes.
    """
    box = QGroupBox(title)
    grid = QGridLayout(box)
    grid.setColumnStretch(0, 0)
    grid.setColumnStretch(1, 1)
    grid.setHorizontalSpacing(20)
    grid.setVerticalSpacing(6)

    pairs: list[tuple[QLabel, QLabel]] = []
    for i, row in enumerate(rows):
        lbl = QLabel(f"{row.label}:")
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val = QLabel(_not_recorded())
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(lbl, i, 0)
        grid.addWidget(val, i, 1)
        pairs.append((lbl, val))
    return box, pairs


class StatsWindow(QMainWindow):
    """The Stats screen. Lives independently of the main window.

    Call `refresh()` after adding/editing/deleting dives to pull
    fresh aggregates. Call `set_unit_system()` when the user
    toggles metric/imperial in the main window.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
        unit_system: UnitSystem = UnitSystem.METRIC,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._units = unit_system

        self.setWindowTitle("Stats — Open Dive Log")
        # Modality: stay on top of the main window but don't block it
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(520, 480)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Big "log book" header
        self._title = QLabel("Dive log statistics")
        title_font = QFont()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(self._title)

        # Subtitle: shows the depth unit the values are in. Updated
        # on unit toggle.
        self._subtitle = QLabel("")
        outer.addWidget(self._subtitle)

        # Three groups: Time, Depth, Places
        self._time_box, self._time_pairs = _build_group("Bottom time", _TIME_ROWS)
        self._depth_box, self._depth_pairs = _build_group("Depth", _DEPTH_ROWS)
        self._place_box, self._place_pairs = _build_group("Places", _PLACE_ROWS)

        outer.addWidget(self._time_box)
        outer.addWidget(self._depth_box)
        outer.addWidget(self._place_box)
        outer.addStretch(1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self.refresh()

    # ------------------------------------------------------------------ API
    def set_unit_system(self, system: UnitSystem) -> None:
        """Called by the main window when the user toggles units.
        Re-renders the depth values and the subtitle.
        """
        self._units = system
        self._render_depths()
        self._render_subtitle()

    def refresh(self) -> None:
        """Re-run the aggregation queries and re-render all values.
        Cheap; safe to call after every dive add/edit/delete.
        """
        self._stats = compute_stats(self._conn)
        self._render_time()
        self._render_depths()
        self._render_places()
        self._render_subtitle()

    # ------------------------------------------------------------- render
    def _render_subtitle(self) -> None:
        # Show a "depths in feet" hint so the user knows what unit
        # the deepest / average values are in. In metric we keep it
        # generic.
        if self._units == UnitSystem.IMPERIAL:
            self._subtitle.setText(
                f"Depths shown in {distance_unit_label(self._units)} "
                f"(1 m = 3.28084 ft)."
            )
        else:
            self._subtitle.setText(
                f"Depths shown in {distance_unit_label(self._units)}."
            )

    def _render_time(self) -> None:
        s = self._stats
        for row, (_lbl, val) in zip(_TIME_ROWS, self._time_pairs):
            text = row.fmt(s, self._units)
            val.setText(text if text is not None else _not_recorded())

    def _render_depths(self) -> None:
        s = self._stats
        for row, (_lbl, val) in zip(_DEPTH_ROWS, self._depth_pairs):
            text = row.fmt(s, self._units)
            val.setText(text if text is not None else _not_recorded())

    def _render_places(self) -> None:
        s = self._stats
        for row, (_lbl, val) in zip(_PLACE_ROWS, self._place_pairs):
            text = row.fmt(s, self._units)
            val.setText(text if text is not None else _not_recorded())
