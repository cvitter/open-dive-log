"""QAbstractTableModel for the main dive list.

Reads from `dives.list_recent_with_sites` and exposes 10 columns whose
display units follow the user's preference (`UnitSystem.METRIC` or
`IMPERIAL`). The DB always stores metric; the model converts at
`data()` time so toggling units is instant (no DB hit).

Columns (imperial mode shown in parens):
    0  Dive #         the dive's id (1 = first inserted, n = latest)
    1  Date
    2  Air temp       (°C / °F)
    3  Water temp     (°C / °F)
    4  Visibility     (m / ft)
    5  Pressure start (bar / psi)
    6  Pressure end   (bar / psi)
    7  Depth avg      (m / ft)
    8  Depth max      (m / ft)
    9  Site

Dive # is the dive's primary key (1 = first inserted, n = most recent).
The list sorts newest first by `dive_date DESC, start_time DESC`, so
the row at the top has the highest id (the latest dive) and the row
at the bottom has id 1 (the first dive you ever logged). Matches how
divers talk ("what was dive #50?") and how logbook apps typically work.

The column *header* text updates when the unit system changes (via
`set_unit_system`), so the table column captions stay in sync with
the values. We use `beginResetModel` / `endResetModel` to trigger
the view to re-fetch all cells after a unit change.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from open_dive_log.repositories import dives
from open_dive_log.units import (
    UnitSystem,
    bar_to_psi,
    c_to_f,
    m_to_ft,
)


# Column index constants
COL_DIVE_NUM = 0
COL_DATE = 1
COL_AIR_TEMP = 2
COL_WATER_TEMP = 3
COL_VISIBILITY = 4
COL_PRESSURE_START = 5
COL_PRESSURE_END = 6
COL_DEPTH_AVG = 7
COL_DEPTH_MAX = 8
COL_SITE = 9
NUM_COLS = 10


def _build_headers(system: UnitSystem) -> tuple[tuple[str, str], ...]:
    """Return the (label, tooltip) tuple for all columns in the chosen system."""
    if system == UnitSystem.METRIC:
        return (
            ("Dive #", "The dive's id (1 = first inserted, n = latest)."),
            ("Date", "Dive date (YYYY-MM-DD). Sorted newest first."),
            ("Air temp (°C)", "Surface air temperature on the day of the dive, in °C."),
            ("Water temp (°C)", "Water temperature at depth, in °C."),
            ("Visibility (m)", "Horizontal visibility at depth, in meters."),
            ("P start (bar)", "Tank pressure at the start of the dive, in bar."),
            ("P end (bar)", "Tank pressure at the end of the dive, in bar."),
            ("Depth avg (m)", "Average depth across the dive, in meters."),
            ("Depth max (m)", "Maximum depth reached on this dive, in meters."),
            ("Site", "Dive site(s), comma-separated if more than one."),
        )
    return (
        ("Dive #", "The dive's id (1 = first inserted, n = latest)."),
        ("Date", "Dive date (YYYY-MM-DD). Sorted newest first."),
        ("Air temp (°F)", "Surface air temperature on the day of the dive, in °F."),
        ("Water temp (°F)", "Water temperature at depth, in °F."),
        ("Visibility (ft)", "Horizontal visibility at depth, in feet."),
        ("P start (psi)", "Tank pressure at the start of the dive, in psi."),
        ("P end (psi)", "Tank pressure at the end of the dive, in psi."),
        ("Depth avg (ft)", "Average depth across the dive, in feet."),
        ("Depth max (ft)", "Maximum depth reached on this dive, in feet."),
        ("Site", "Dive site(s), comma-separated if more than one."),
    )


@dataclass(frozen=True, slots=True)
class DiveRow:
    """The shape consumed by the QTableView. Stores DB values (metric)."""
    id: int
    dive_date: str
    sites: str
    max_depth_m: float | None
    avg_depth_m: float | None
    air_temp_c: float | None
    water_temp_c: float | None
    visibility_m: float | None
    start_pressure_bar: float | None
    end_pressure_bar: float | None


# ---------------------------------------------------------------------------
# Field formatters
# ---------------------------------------------------------------------------
def _format_depth(value: float | None, system: UnitSystem) -> str:
    """Format a depth for display. None → empty string."""
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


def _format_temp(c: float | None, system: UnitSystem) -> str:
    if c is None:
        return ""
    if system == UnitSystem.METRIC:
        if c == int(c):
            return f"{int(c)} °C"
        return f"{c:.1f} °C"
    f = c_to_f(c)
    if f == int(f):
        return f"{int(f)} °F"
    return f"{f:.1f} °F"


def _format_distance(m: float | None, system: UnitSystem) -> str:
    if m is None:
        return ""
    if system == UnitSystem.METRIC:
        if m == int(m):
            return f"{int(m)} m"
        return f"{m:.1f} m"
    ft = m_to_ft(m)
    if ft == int(ft):
        return f"{int(ft)} ft"
    return f"{ft:.1f} ft"


def _format_pressure(bar: float | None, system: UnitSystem) -> str:
    """Format a tank pressure for display. None → empty string.

    BAR or PSI depending on the unit toggle. Unlike temperature, 0 is
    a valid reading here (an empty tank) so we don't suppress zeros.
    """
    if bar is None:
        return ""
    if system == UnitSystem.METRIC:
        if bar == int(bar):
            return f"{int(bar)} bar"
        return f"{bar:.1f} bar"
    psi = bar_to_psi(bar)
    if psi == int(psi):
        return f"{int(psi)} psi"
    return f"{psi:.1f} psi"


# Columns whose values are numeric and should be right-aligned
_RIGHT_ALIGNED = (
    COL_DIVE_NUM, COL_AIR_TEMP, COL_WATER_TEMP, COL_VISIBILITY,
    COL_PRESSURE_START, COL_PRESSURE_END, COL_DEPTH_AVG, COL_DEPTH_MAX,
)


def load_rows(conn: sqlite3.Connection, limit: int = 500) -> list[DiveRow]:
    """Pure-Python row loader — no Qt. Reused by tests.

    Reads all the dive + conditions + pressure columns and the
    comma-joined site names. The DB always returns them in metric;
    the presentation layer does the unit conversion.
    """
    raw = dives.list_recent_with_sites(conn, limit=limit)
    return [
        DiveRow(
            id=r["id"],
            dive_date=r["dive_date"],
            sites=r["sites"],
            max_depth_m=r.get("max_depth_m"),
            avg_depth_m=r.get("avg_depth_m"),
            air_temp_c=r.get("air_temp_c"),
            water_temp_c=r.get("water_temp_c"),
            visibility_m=r.get("visibility_m"),
            start_pressure_bar=r.get("start_pressure_bar"),
            end_pressure_bar=r.get("end_pressure_bar"),
        )
        for r in raw
    ]


class DiveTableModel(QAbstractTableModel):
    """Qt model adapter around load_rows().

    Holds the unit system as state so `data()` and `headerData()` can
    convert at display time. `set_unit_system()` flips the state and
    emits a full refresh (beginResetModel / endResetModel) so the
    view re-paints all visible cells.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[DiveRow] = []
        self._units: UnitSystem = UnitSystem.METRIC

    # --- Public API -----------------------------------------------------
    def set_rows(self, rows: Iterable[DiveRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_unit_system(self, system: UnitSystem) -> None:
        """Change the displayed units and tell the view to repaint."""
        if system == self._units:
            return
        self.beginResetModel()
        self._units = system
        self.endResetModel()

    def unit_system(self) -> UnitSystem:
        return self._units

    def row_at(self, index: int) -> DiveRow | None:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    # --- QAbstractTableModel -------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return NUM_COLS

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            headers = _build_headers(self._units)
            if 0 <= section < len(headers):
                return headers[section][0]
        elif orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if not (0 <= index.row() < len(self._rows)):
            return None
        if not (0 <= index.column() < NUM_COLS):
            return None

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_DIVE_NUM:
                return str(row.id)
            if col == COL_DATE:
                return row.dive_date
            if col == COL_AIR_TEMP:
                return _format_temp(row.air_temp_c, self._units)
            if col == COL_WATER_TEMP:
                return _format_temp(row.water_temp_c, self._units)
            if col == COL_VISIBILITY:
                return _format_distance(row.visibility_m, self._units)
            if col == COL_PRESSURE_START:
                return _format_pressure(row.start_pressure_bar, self._units)
            if col == COL_PRESSURE_END:
                return _format_pressure(row.end_pressure_bar, self._units)
            if col == COL_DEPTH_AVG:
                return _format_depth(row.avg_depth_m, self._units)
            if col == COL_DEPTH_MAX:
                return _format_depth(row.max_depth_m, self._units)
            if col == COL_SITE:
                return row.sites

        if role == Qt.ItemDataRole.ToolTipRole:
            headers = _build_headers(self._units)
            if 0 <= col < len(headers):
                return headers[col][1]

        if role == Qt.ItemDataRole.TextAlignmentRole and col in _RIGHT_ALIGNED:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.UserRole:
            return row.id

        return None
