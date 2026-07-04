"""QAbstractTableModel for the main dive list.

Reads from `dives.list_recent_with_sites` and exposes 3 columns:
    0  Date        (dive_date, ISO YYYY-MM-DD)
    1  Site        (comma-joined site names, or "" if none)
    2  Max depth   (max_depth_m formatted as "23.0 m", or "" if None)

Sort is fixed (date DESC, then start_time DESC) — it's the default sort
and matches the user's spec for this phase. UI-side reordering can come later.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from open_dive_log.repositories import dives


# (header text, tooltip)
HEADERS: tuple[tuple[str, str], ...] = (
    ("Date", "Dive date (YYYY-MM-DD). Sorted newest first."),
    ("Site", "Dive site(s), comma-separated if more than one."),
    ("Max depth (m)", "Maximum depth reached on this dive, in meters."),
)


@dataclass(frozen=True, slots=True)
class DiveRow:
    """The shape consumed by the QTableView — stable across re-fetches."""
    id: int
    dive_date: str
    sites: str
    max_depth_m: float | None


def _format_depth(value: float | None) -> str:
    if value is None:
        return ""
    # Strip trailing .0 for whole meters; keep one decimal otherwise.
    if value == int(value):
        return f"{int(value)} m"
    return f"{value:.1f} m"


def load_rows(conn: sqlite3.Connection, limit: int = 500) -> list[DiveRow]:
    """Pure-Python row loader — no Qt. Reused by tests."""
    raw = dives.list_recent_with_sites(conn, limit=limit)
    return [
        DiveRow(
            id=r["id"],
            dive_date=r["dive_date"],
            sites=r["sites"],
            max_depth_m=r["max_depth_m"],
        )
        for r in raw
    ]


class DiveTableModel(QAbstractTableModel):
    """Qt model adapter around load_rows().

    Designed to be re-populated by calling `set_rows(rows)` after each
    repository fetch. We don't try to be clever with partial updates —
    re-fetching 500 rows is fast and a real application rarely needs
    per-row diffing.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[DiveRow] = []

    # --- Public API -----------------------------------------------------
    def set_rows(self, rows: Iterable[DiveRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, index: int) -> DiveRow | None:
        """Return the row at `index`, or None if out of range.

        Used by the main window to look up the dive id when the user
        double-clicks a row.
        """
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
        return len(HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(HEADERS):
                return HEADERS[section][0]
        elif orientation == Qt.Orientation.Vertical:
            # Row numbers (1-based) as a familiar affordance.
            return section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if not (0 <= index.row() < len(self._rows)):
            return None
        if not (0 <= index.column() < len(HEADERS)):
            return None

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.dive_date
            if col == 1:
                return row.sites
            if col == 2:
                return _format_depth(row.max_depth_m)

        if role == Qt.ItemDataRole.ToolTipRole:
            return HEADERS[col][1]

        if role == Qt.ItemDataRole.TextAlignmentRole and col == 2:
            # Right-align the depth column for legibility.
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.UserRole:
            # Custom role: return the dive id. Useful for selection models
            # that need to identify the underlying record.
            return row.id

        return None
