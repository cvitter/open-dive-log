"""Buddies list window — read-only-by-default table of buddies, with a
search box and Edit / Delete actions on the current selection.

Mirrors the sites list window's UX:
  * Search box (case-insensitive substring on full_name) at the top.
  * Toolbar with Edit and Delete actions; both are disabled when
    no row is selected.
  * Double-click a row to edit.
  * Right-click context menu with Edit / Delete.
  * Edits open a small dialog (first/last name fields).
  * Deletes show a confirmation, then run; if the buddy is
    referenced by any dives, the user is warned and shown how
    many.

Selection model:
  * The main window's "List Buddies…" menu opens this window.
  * Edit and Delete live in this window's toolbar/context menu.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories import buddies as buddies_repo


HEADERS: tuple[tuple[str, str], ...] = (
    ("First name", "Buddy's first name"),
    ("Last name", "Buddy's last name"),
    ("# Dives", "Number of dives this buddy is on"),
)
COL_FIRST = 0
COL_LAST = 1
COL_DIVE_COUNT = 2
NUM_COLS = 3


class BuddyTableModel(QAbstractTableModel):
    """Loads buddies via `buddies_repo.list_all` and exposes them as a
    table. Supports a name-substring filter.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_rows: list[tuple[buddies_repo.Buddy, int]] = []
        self._rows: list[tuple[buddies_repo.Buddy, int]] = []
        self._filter: str = ""

    def set_rows(self, rows: Iterable[tuple[buddies_repo.Buddy, int]]) -> None:
        """Replace the underlying data and reset the filter.

        `rows` is a sequence of (Buddy, dive_count) tuples — the
        dive_count is computed by the caller (typically the window
        populating it after a refresh).
        """
        self.beginResetModel()
        self._all_rows = list(rows)
        self._filter = ""
        self._rows = list(self._all_rows)
        self.endResetModel()

    def set_filter(self, name_substring: str) -> None:
        """Filter visible rows by case-insensitive substring on
        full_name. Empty string shows all rows.
        """
        needle = name_substring.lower().strip()
        if needle == self._filter:
            return
        self.beginResetModel()
        self._filter = needle
        if not needle:
            self._rows = list(self._all_rows)
        else:
            self._rows = [
                (b, n) for (b, n) in self._all_rows
                if needle in (b.full_name or "").lower()
            ]
        self.endResetModel()

    def filter(self) -> str:
        return self._filter

    def total_count(self) -> int:
        return len(self._all_rows)

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
            if 0 <= section < NUM_COLS:
                return HEADERS[section][0]
        elif orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        buddy, dive_count = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_FIRST:
                return buddy.first_name
            if col == COL_LAST:
                return buddy.last_name
            if col == COL_DIVE_COUNT:
                return str(dive_count)

        if role == Qt.ItemDataRole.ToolTipRole:
            if 0 <= col < NUM_COLS:
                return HEADERS[col][1]

        if role == Qt.ItemDataRole.TextAlignmentRole and col == COL_DIVE_COUNT:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None


class _EditBuddyDialog(QDialog):
    """Small modal dialog to edit a buddy's first/last name.

    Returns a (first, last) tuple via `result_names()` after accept.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        buddy: buddies_repo.Buddy,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._buddy = buddy
        self.setWindowTitle(f"Edit buddy #{buddy.id}")
        self.setModal(True)

        form = QFormLayout()
        self._first = QLineEdit()
        self._first.setText(buddy.first_name)
        form.addRow("First name:", self._first)
        self._last = QLineEdit()
        self._last.setText(buddy.last_name)
        form.addRow("Last name:", self._last)

        # Warn about uniqueness — the buddy has a normalized-name
        # UNIQUE constraint, so a rename can collide.
        form.addRow(QLabel(
            "(Renaming may collide with another buddy's normalized name.)"
        ))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        first = self._first.text().strip()
        last = self._last.text().strip()
        if not first or not last:
            QMessageBox.warning(
                self, "Buddy",
                "Both first and last name are required.",
            )
            return
        self._result = (first, last)
        self.accept()

    def result_names(self) -> tuple[str, str] | None:
        return getattr(self, "_result", None)


class BuddiesListWindow(QMainWindow):
    """Read-only-by-default table of buddies, with a search box and
    Edit / Delete actions on the current selection.
    """

    DEFAULT_LIMIT = 5000

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn = conn

        self.setWindowTitle("Buddies")
        self.resize(700, 500)

        self._model = BuddyTableModel(self)
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.verticalHeader().setVisible(False)
        # Double-click to edit — matches sites/dives behavior
        self._table.doubleClicked.connect(self._on_edit_action)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # --- Toolbar: search + Edit + Delete ----------------------------
        toolbar = QToolBar("Buddies", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel(" Search: "))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by buddy name…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.setMinimumWidth(220)
        toolbar.addWidget(self._search)

        toolbar.addSeparator()

        self._action_edit = QAction("&Edit…", self)
        self._action_edit.setShortcut("Ctrl+E")
        self._action_edit.triggered.connect(self._on_edit_action)
        self._action_edit.setEnabled(False)
        toolbar.addAction(self._action_edit)

        self._action_delete = QAction("&Delete", self)
        self._action_delete.setShortcut("Delete")
        self._action_delete.triggered.connect(self._on_delete_action)
        self._action_delete.setEnabled(False)
        toolbar.addAction(self._action_delete)

        # --- Central widget ---------------------------------------------
        self.setCentralWidget(self._table)

        # --- Status bar --------------------------------------------------
        self.setStatusBar(QStatusBar(self))

        # --- Context menu on the table (right-click) --------------------
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self._table.addAction(self._action_edit)
        self._table.addAction(self._action_delete)

        # --- Selection-driven enable/disable ----------------------------
        sel_model = self._table.selectionModel()
        sel_model.selectionChanged.connect(self._on_selection_changed)

        self.refresh()

    # ------------------------------------------------------------------ API
    def refresh(self) -> None:
        """Reload the buddies from the DB, including each one's dive
        count. The current search filter is preserved.
        """
        rows: list[tuple[buddies_repo.Buddy, int]] = []
        for b in buddies_repo.list_all(self._conn):
            if len(rows) >= self.DEFAULT_LIMIT:
                break
            count = buddies_repo.count_referencing_dives(self._conn, b.id)
            rows.append((b, count))
        self._model.set_rows(rows)
        if self._search.text():
            self._model.set_filter(self._search.text())
        self._update_status()

    def selected_buddy(self) -> buddies_repo.Buddy | None:
        """Return the currently selected Buddy, or None if no row is
        selected (or the search filter hid it)."""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0]
        if not (0 <= idx.row() < self._model.rowCount()):
            return None
        return self._model._rows[idx.row()][0]

    # --------------------------------------------------------- selection
    def _on_selection_changed(self, *_args) -> None:
        has_sel = self.selected_buddy() is not None
        self._action_edit.setEnabled(has_sel)
        self._action_delete.setEnabled(has_sel)

    # ------------------------------------------------------------- search
    def _on_search_changed(self, text: str) -> None:
        self._model.set_filter(text)
        self._update_status()

    # ----------------------------------------------------------- actions
    def _on_edit_action(self, *_args) -> None:
        buddy = self.selected_buddy()
        if buddy is not None:
            self._do_edit(buddy)

    def _on_delete_action(self, *_args) -> None:
        buddy = self.selected_buddy()
        if buddy is not None:
            self._do_delete(buddy)

    def _do_edit(self, buddy: buddies_repo.Buddy) -> None:
        dlg = _EditBuddyDialog(self._conn, buddy, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        names = dlg.result_names()
        if names is None:
            return
        first, last = names
        try:
            buddies_repo.update(self._conn, buddy.id, first_name=first, last_name=last)
        except sqlite3.IntegrityError as e:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save the buddy — likely a duplicate "
                f"normalized name (case/whitespace-insensitive) with "
                f"another buddy.\n\n{e}",
            )
            return
        except LookupError as e:
            QMessageBox.warning(self, "Buddy missing", str(e))
            return
        self.refresh()
        self._reselect_by_id(buddy.id)
        self.statusBar().showMessage(
            f"Updated buddy #{buddy.id}: {first} {last}", 5000,
        )

    def _do_delete(self, buddy: buddies_repo.Buddy) -> None:
        # If the buddy is on any dives, tell the user how many will be
        # affected. CASCADE on dive_buddy will remove those rows.
        n_dives = buddies_repo.count_referencing_dives(self._conn, buddy.id)
        if n_dives:
            extra = (
                f"\n\nThis buddy is on {n_dives} dive(s). The dive_buddy "
                f"links will be removed automatically (ON DELETE CASCADE)."
            )
        else:
            extra = ""
        answer = QMessageBox.question(
            self, "Delete buddy?",
            f"Delete buddy #{buddy.id} '{buddy.full_name}'?{extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            buddies_repo.delete(self._conn, buddy.id)
        except LookupError as e:
            QMessageBox.warning(self, "Buddy missing", str(e))
            return
        self.refresh()
        self.statusBar().showMessage(
            f"Deleted buddy #{buddy.id}: {buddy.full_name}", 5000,
        )

    def _reselect_by_id(self, buddy_id: int) -> None:
        """After refresh, re-select the row whose buddy id matches.
        The row order may have changed (renamed → different sort
        position), so look it up in the model."""
        for i in range(self._model.rowCount()):
            if self._model._rows[i][0].id == buddy_id:
                idx = self._model.index(i, 0)
                self._table.setCurrentIndex(idx)
                return

    # ---------------------------------------------------------- status bar
    def _update_status(self) -> None:
        shown = self._model.rowCount()
        total = self._model.total_count()
        needle = self._search.text().strip()
        if needle and shown != total:
            self.statusBar().showMessage(
                f"Showing {shown} of {total} buddies matching “{needle}”"
            )
        elif shown != total:
            self.statusBar().showMessage(f"Showing {shown} of {total} buddies")
        else:
            self.statusBar().showMessage(f"{total} buddies")
