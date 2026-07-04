"""Read-only sites list window.

Shows a table of sites from the local DB. Default sort is by name ASC.
For this phase there's no inline filter / search box — the table loads
the first N rows (default 1000) and shows a status bar with the total.

Future phases will add a search box, a country filter, and an "open
detail" action. Keep this file small and the next phase will be a
clean extension.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHeaderView,
    QMainWindow,
    QStatusBar,
    QTableView,
)

from open_dive_log.repositories import sites as sites_repo


HEADERS: tuple[tuple[str, str], ...] = (
    ("Name", "Site name"),
    ("Country", "Country name (ISO 3166-1 alpha-2)"),
    ("Region", "Free-text region / area"),
    ("Max depth (m)", "Maximum depth for this site, in meters"),
    ("Environment", "Where the dive happens (ocean, lake, etc.)"),
    ("Entry", "How divers enter the water (shore, boat, other)"),
)


class SiteTableModel(QAbstractTableModel):
    """Loads sites via `sites_repo.list_all` and exposes them as a table."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[sites_repo.Site] = []

    def set_rows(self, rows: Iterable[sites_repo.Site]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

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
            return section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.name
            if col == 1:
                return row.country_name or row.country_code or ""
            if col == 2:
                return row.region or ""
            if col == 3:
                if row.max_depth_m is None:
                    return ""
                if row.max_depth_m == int(row.max_depth_m):
                    return f"{int(row.max_depth_m)}"
                return f"{row.max_depth_m:.1f}"
            if col == 4:
                return row.environment_name or ""
            if col == 5:
                return row.entry_name or ""

        if role == Qt.ItemDataRole.ToolTipRole:
            if 0 <= col < len(HEADERS):
                return HEADERS[col][1]

        if role == Qt.ItemDataRole.TextAlignmentRole and col == 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None


class SitesListWindow(QMainWindow):
    """Read-only table of sites."""

    DEFAULT_LIMIT = 1000

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn

        self.setWindowTitle("Sites")
        self.resize(900, 600)

        self._model = SiteTableModel(self)
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)  # default order is the SQL one
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.setCentralWidget(self._table)

        self.setStatusBar(QStatusBar(self))
        self.refresh()

    def refresh(self) -> None:
        rows = sites_repo.list_all(self._conn)
        if len(rows) > self.DEFAULT_LIMIT:
            # Cap at DEFAULT_LIMIT for the default view. A search box will
            # come in a later phase; this keeps the table snappy.
            shown = rows[: self.DEFAULT_LIMIT]
        else:
            shown = rows
        self._model.set_rows(shown)
        total = len(rows)
        shown_n = len(shown)
        if total > shown_n:
            self.statusBar().showMessage(f"Showing {shown_n} of {total} sites")
        else:
            self.statusBar().showMessage(f"{total} sites")
