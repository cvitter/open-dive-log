"""Lookups management window — admin view of the 12 lookup tables.

Layout (two-pane):
  * Left pane: a QListWidget of the 12 lookup tables (categories).
  * Right pane: a QTableView of the values in the selected table,
    with a toolbar of Add / Edit / Soft-Delete / Reactivate actions.

The right pane shows BOTH active and inactive values (with an
is_active column) so the user can see and undo soft-deletes. Active
values are listed first; inactive are below in muted styling.

Why soft-delete instead of hard-delete?
  Every referenced table has `ON DELETE RESTRICT` (the default for
  the schema). A lookup value that's referenced by a dive can't be
  hard-deleted without first clearing every reference, and the UI
  has no path to do that. Soft-delete (`is_active = 0`) hides the
  value from dropdowns while leaving FK references intact, so
  historical dive records stay valid.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QSpinBox,
    QStatusBar,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories import lookups as lk
from open_dive_log.repositories.lookups import LOOKUP_TABLES, LookupValue


# Friendlier display names for the left-pane list. The DB column is
# `lookup_<thing>`; users will read "Time of day", "Entry type", etc.
CATEGORY_LABELS: dict[str, str] = {
    "lookup_time_of_day":        "Time of day",
    "lookup_entry_type":         "Entry type",
    "lookup_surface_conditions": "Surface conditions",
    "lookup_equipment_type":     "Equipment type",
    "lookup_tank_type":          "Tank type",
    "lookup_tank_configuration": "Tank configuration",
    "lookup_gas_type":           "Gas type",
    "lookup_purpose":            "Purpose",
    "lookup_buddy_role":         "Buddy role",
    "lookup_site_environment":   "Site environment",
    "lookup_site_topology":      "Site topology",
    "lookup_certifying_agency":  "Certifying agency",
}


class LookupValueModel(QAbstractTableModel):
    """Table model for the right pane — shows all values (active and
    inactive) for the currently-selected lookup table.
    """

    COL_ID = 0
    COL_NAME = 1
    COL_ORDER = 2
    COL_ACTIVE = 3
    COL_REFERENCED = 4
    NUM_COLS = 5

    HEADERS = ("ID", "Name", "Order", "Active", "Used in")

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._table: str | None = None
        self._rows: list[tuple[LookupValue, int]] = []  # (value, referencing_count)

    def set_table(self, table: str | None) -> None:
        """Switch to a different lookup table, or None for empty."""
        self.beginResetModel()
        self._table = table
        if table is None:
            self._rows = []
        else:
            self._rows = [
                (v, lk.count_referencing(self._conn, table, v.id))
                for v in lk.list_including_inactive(self._conn, table)
            ]
        self.endResetModel()

    def table(self) -> str | None:
        return self._table

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid() or self._table is None:
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return self.NUM_COLS

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < self.NUM_COLS:
                return self.HEADERS[section]
        elif orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        value, n_refs = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ID:
                return str(value.id)
            if col == self.COL_NAME:
                return value.name
            if col == self.COL_ORDER:
                return str(value.display_order)
            if col == self.COL_ACTIVE:
                return "yes" if value.is_active else "no"
            if col == self.COL_REFERENCED:
                return str(n_refs)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (self.COL_ID, self.COL_ORDER, self.COL_REFERENCED):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Greyed-out styling for inactive rows so they're visually
        # distinct from active ones.
        if role == Qt.ItemDataRole.ForegroundRole and not value.is_active:
            return QBrush(QColor("#888888"))

        return None

    def value_at(self, row: int) -> LookupValue | None:
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return None


class _LookupValueDialog(QDialog):
    """Add or Edit a single lookup value. Name + display_order.

    `is_new=True` shows "Add" as the button label and requires the
    user to enter a fresh name; `is_new=False` pre-fills the name
    and shows "Save" (and the name is checked only for duplicates
    when changed).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        table: str,
        *,
        is_new: bool,
        existing: LookupValue | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._table = table
        self._is_new = is_new
        self._existing = existing
        self._result: tuple[str, int] | None = None

        self.setWindowTitle(
            f"Add {CATEGORY_LABELS[table]}" if is_new
            else f"Edit {CATEGORY_LABELS[table]}"
        )
        self.setModal(True)

        form = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. cavern")
        if existing is not None:
            self._name.setText(existing.name)
        form.addRow("Name:", self._name)

        self._order = QSpinBox()
        self._order.setRange(0, 9999)
        self._order.setValue(existing.display_order if existing else 100)
        form.addRow("Display order:", self._order)
        form.addRow(QLabel("(Lower numbers appear first in dropdowns.)"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "A value must have a name.")
            return
        # Disallow leading/trailing whitespace silently by re-stripping
        # (already done above). Length sanity:
        if len(name) > 80:
            QMessageBox.warning(self, "Name too long", "Keep the name under 80 characters.")
            return
        self._result = (name, self._order.value())
        self.accept()

    def result_values(self) -> tuple[str, int] | None:
        return self._result


class LookupsListWindow(QMainWindow):
    """Two-pane admin window for all 12 lookup tables."""

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn = conn

        self.setWindowTitle("Lookups")
        self.resize(820, 520)

        # --- Central: a horizontal QSplitter ----------------------------
        central = QWidget(self)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left pane: the 12 categories
        self._category_list = QListWidget(self)
        for table in LOOKUP_TABLES:
            item = QListWidgetItem(CATEGORY_LABELS.get(table, table))
            item.setData(Qt.ItemDataRole.UserRole, table)
            self._category_list.addItem(item)
        self._category_list.currentItemChanged.connect(self._on_category_changed)
        splitter.addWidget(self._category_list)

        # Right pane: a vertical layout with toolbar + table + status
        right_pane = QWidget(self)
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QToolBar("Lookups values", self)
        toolbar.setMovable(False)
        right_layout.addWidget(toolbar)

        self._action_add = QAction("&Add…", self)
        self._action_add.triggered.connect(self._on_add)
        toolbar.addAction(self._action_add)

        self._action_edit = QAction("&Edit…", self)
        self._action_edit.setShortcut("Ctrl+E")
        self._action_edit.triggered.connect(self._on_edit)
        self._action_edit.setEnabled(False)
        toolbar.addAction(self._action_edit)

        self._action_deactivate = QAction("&Deactivate", self)
        self._action_deactivate.triggered.connect(self._on_deactivate)
        self._action_deactivate.setEnabled(False)
        toolbar.addAction(self._action_deactivate)

        self._action_reactivate = QAction("Re&activate", self)
        self._action_reactivate.triggered.connect(self._on_reactivate)
        self._action_reactivate.setEnabled(False)
        toolbar.addAction(self._action_reactivate)

        self._table = QTableView(self)
        self._model = LookupValueModel(conn, self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._on_edit)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        right_layout.addWidget(self._table)

        splitter.addWidget(right_pane)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 600])
        outer.addWidget(splitter)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        # Selection-driven enable/disable
        sel = self._table.selectionModel()
        sel.selectionChanged.connect(self._on_selection_changed)

        # Right-click context menu
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self._table.addAction(self._action_edit)
        self._table.addAction(self._action_deactivate)
        self._table.addAction(self._action_reactivate)

        # Start on the first category
        if self._category_list.count() > 0:
            self._category_list.setCurrentRow(0)

    # ----------------------------------------------------------- selection
    def _on_selection_changed(self, *_args) -> None:
        v = self.selected_value()
        if v is None:
            self._action_edit.setEnabled(False)
            self._action_deactivate.setEnabled(False)
            self._action_reactivate.setEnabled(False)
            return
        self._action_edit.setEnabled(True)
        # Only one of deactivate/reactivate applies at a time
        self._action_deactivate.setEnabled(v.is_active)
        self._action_reactivate.setEnabled(not v.is_active)

    def _on_category_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self._model.set_table(None)
        else:
            self._model.set_table(current.data(Qt.ItemDataRole.UserRole))
        self._update_status()

    # ------------------------------------------------------------- accessors
    def selected_value(self) -> LookupValue | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._model.value_at(rows[0].row())

    def current_table(self) -> str | None:
        item = self._category_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # ------------------------------------------------------------- actions
    def _on_add(self) -> None:
        table = self.current_table()
        if table is None:
            return
        dlg = _LookupValueDialog(self._conn, table, is_new=True, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if vals is None:
            return
        name, order = vals
        try:
            lk.add(self._conn, table, name, display_order=order)
        except sqlite3.IntegrityError as e:
            QMessageBox.critical(
                self, "Add failed",
                f"A value with that name already exists in this lookup.\n\n{e}",
            )
            return
        self._refresh_table()
        self.statusBar().showMessage(f"Added '{name}' to {CATEGORY_LABELS[table]}", 5000)

    def _on_edit(self) -> None:
        v = self.selected_value()
        if v is None:
            return
        table = self.current_table()
        if table is None:
            return
        dlg = _LookupValueDialog(
            self._conn, table, is_new=False, existing=v, parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.result_values()
        if vals is None:
            return
        name, order = vals
        try:
            lk.update(self._conn, table, v.id, name=name, display_order=order)
        except sqlite3.IntegrityError as e:
            QMessageBox.critical(
                self, "Edit failed",
                f"A value with that name already exists in this lookup.\n\n{e}",
            )
            return
        except LookupError as e:
            QMessageBox.warning(self, "Value missing", str(e))
            return
        self._refresh_table()
        self.statusBar().showMessage(
            f"Updated {CATEGORY_LABELS[table]} value: '{name}'", 5000,
        )

    def _on_deactivate(self) -> None:
        v = self.selected_value()
        if v is None or not v.is_active:
            return
        table = self.current_table()
        if table is None:
            return
        # Warn if the value is in use somewhere
        n = lk.count_referencing(self._conn, table, v.id)
        if n:
            extra = (
                f"\n\nThis value is currently used in {n} row(s). "
                f"Deactivating it will hide it from dropdowns but keep "
                f"those existing references intact."
            )
        else:
            extra = ""
        answer = QMessageBox.question(
            self, "Deactivate value?",
            f"Deactivate '{v.name}' from {CATEGORY_LABELS[table]}?{extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            lk.soft_delete(self._conn, table, v.id)
        except LookupError as e:
            QMessageBox.warning(self, "Value missing", str(e))
            return
        self._refresh_table()
        self.statusBar().showMessage(
            f"Deactivated '{v.name}' (use Reactivate to undo)", 5000,
        )

    def _on_reactivate(self) -> None:
        v = self.selected_value()
        if v is None or v.is_active:
            return
        table = self.current_table()
        if table is None:
            return
        try:
            lk.reactivate(self._conn, table, v.id)
        except LookupError as e:
            QMessageBox.warning(self, "Value missing", str(e))
            return
        self._refresh_table()
        self.statusBar().showMessage(f"Reactivated '{v.name}'", 5000)

    # ----------------------------------------------------------- refresh
    def _refresh_table(self) -> None:
        table = self.current_table()
        if table is None:
            return
        self._model.set_table(table)
        # Try to re-select the same row by id (so the user's
        # selection follows the refresh after edit/deactivate)
        self._update_status()

    def _update_status(self) -> None:
        n = self._model.rowCount()
        if n == 0:
            self.statusBar().showMessage("0 values")
        else:
            n_active = sum(1 for (v, _) in self._model._rows if v.is_active)
            self.statusBar().showMessage(
                f"{n} value(s) — {n_active} active, {n - n_active} inactive"
            )
