"""Main application window for Open Dive Log.

Layout:
    QMainWindow
    ├── menu bar:  Dives / Sites / Lookups / Help
    ├── central:   QTableView bound to DiveTableModel (the dive list)
    └── status bar

Menus:
    Dives:    New Dive (disabled), Edit Dive (disabled), Delete Dive (disabled),
              List Dives, ---, Quit
    Sites:    List Sites, ---, Import from opendivemap, ---,
              New Site (disabled), Edit Site (disabled), Delete Site (disabled)
    Lookups:  Manage Lookups (disabled — coming soon)
    Help:     About Open Dive Log

Double-clicking a row in the table opens a read-only DiveDetailDialog.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableView,
)

from open_dive_log import __version__, import_opendivemap
from open_dive_log.db import get_default_db_path, get_sqlite_version
from open_dive_log.ui.dive_detail_dialog import DiveDetailDialog
from open_dive_log.ui.dive_table_model import DiveTableModel, load_rows
from open_dive_log.ui.sites_list_window import SitesListWindow


class _ImportWorker(QObject):
    """Runs `import_opendivemap.import_all` off the UI thread.

    QThread takes ownership of the QObject. Signals are the only safe
    way to communicate with the UI thread.
    """

    finished = Signal(dict)        # counts dict from import_all
    failed = Signal(str)           # error message

    def __init__(self, db_path) -> None:
        super().__init__()
        self._db_path = db_path

    def run(self) -> None:
        try:
            counts = import_opendivemap.import_all(db_path=self._db_path)
        except Exception as e:  # noqa: BLE001 — we want to surface any error
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.finished.emit(dict(counts))


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        super().__init__()
        # Lazily connect if the caller didn't pass one in. We accept a
        # connection (not a factory) for testability — tests pass a
        # tmp_path-backed connection, the real app calls get_default.
        if conn is None:
            from open_dive_log.db import connect
            self._cm = connect()
            self._conn = self._cm.__enter__()
            self._owns_connection = True
        else:
            self._cm = None
            self._owns_connection = False
            self._conn = conn

        # Schema version banner so we can show a useful "About" without
        # re-querying every time.
        from open_dive_log.db import get_schema_version
        try:
            self._schema_version = get_schema_version(self._conn)
        except Exception:
            self._schema_version = "?"

        self.setWindowTitle("Open Dive Log")
        self.resize(900, 600)

        # --- Central widget: the dive list --------------------------------
        self._model = DiveTableModel(self)
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self.setCentralWidget(self._table)

        # --- Status bar ---------------------------------------------------
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage(
            f"SQLite {get_sqlite_version()} · schema v{self._schema_version} · "
            f"DB: {get_default_db_path()}"
        )

        # --- Menu bar -----------------------------------------------------
        self._build_menus()

        # --- Child windows we keep references to (so they don't get GC'd) -
        self._sites_window: SitesListWindow | None = None

        # Initial population.
        self._refresh_dive_list()

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------
    def _build_menus(self) -> None:
        bar = self.menuBar()

        # --- Dives ---
        dives_menu = bar.addMenu("&Dives")

        self._action_new_dive = QAction("&New Dive…", self)
        self._action_new_dive.setShortcut(QKeySequence.StandardKey.New)
        self._action_new_dive.setEnabled(False)  # future phase
        dives_menu.addAction(self._action_new_dive)

        self._action_edit_dive = QAction("&Edit Dive…", self)
        self._action_edit_dive.setShortcut(QKeySequence("Ctrl+E"))
        self._action_edit_dive.setEnabled(False)  # future phase
        dives_menu.addAction(self._action_edit_dive)

        self._action_delete_dive = QAction("&Delete Dive", self)
        self._action_delete_dive.setShortcut(QKeySequence.StandardKey.Delete)
        self._action_delete_dive.setEnabled(False)  # future phase
        dives_menu.addAction(self._action_delete_dive)

        dives_menu.addSeparator()
        action_list_dives = QAction("&List Dives", self)
        action_list_dives.setShortcut(QKeySequence("Ctrl+L"))
        action_list_dives.triggered.connect(self._refresh_dive_list)
        dives_menu.addAction(action_list_dives)

        dives_menu.addSeparator()
        action_quit = QAction("&Quit", self)
        action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        action_quit.setMenuRole(QAction.MenuRole.QuitRole)
        action_quit.triggered.connect(self.close)
        dives_menu.addAction(action_quit)

        # --- Sites ---
        sites_menu = bar.addMenu("&Sites")

        action_list_sites = QAction("&List Sites…", self)
        action_list_sites.triggered.connect(self._open_sites_window)
        sites_menu.addAction(action_list_sites)

        sites_menu.addSeparator()
        self._action_import_sites = QAction("&Import from opendivemap…", self)
        self._action_import_sites.triggered.connect(self._start_opendivemap_import)
        sites_menu.addAction(self._action_import_sites)

        sites_menu.addSeparator()
        self._action_new_site = QAction("&New Site…", self)
        self._action_new_site.setEnabled(False)
        sites_menu.addAction(self._action_new_site)
        self._action_edit_site = QAction("&Edit Site…", self)
        self._action_edit_site.setEnabled(False)
        sites_menu.addAction(self._action_edit_site)
        self._action_delete_site = QAction("&Delete Site", self)
        self._action_delete_site.setEnabled(False)
        sites_menu.addAction(self._action_delete_site)

        # --- Lookups (placeholder) ---
        lookups_menu = bar.addMenu("&Lookups")
        action_manage_lookups = QAction("&Manage Lookups…", self)
        action_manage_lookups.setEnabled(False)
        action_manage_lookups.setToolTip("Coming in a later phase")
        lookups_menu.addAction(action_manage_lookups)

        # --- Help ---
        help_menu = bar.addMenu("&Help")
        action_about = QAction("&About Open Dive Log", self)
        action_about.setMenuRole(QAction.MenuRole.AboutRole)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _refresh_dive_list(self) -> None:
        rows = load_rows(self._conn, limit=500)
        self._model.set_rows(rows)
        self.statusBar().showMessage(
            f"{len(rows)} dive(s) shown · SQLite {get_sqlite_version()} · "
            f"schema v{self._schema_version}",
            5000,
        )

    def _on_row_double_clicked(self, index) -> None:
        if not index.isValid():
            return
        row = self._model.row_at(index.row())
        if row is None:
            return
        dlg = DiveDetailDialog(self._conn, row.id, parent=self)
        dlg.exec()

    def _open_sites_window(self) -> None:
        if self._sites_window is None:
            self._sites_window = SitesListWindow(self._conn, parent=self)
        self._sites_window.show()
        self._sites_window.raise_()
        self._sites_window.activateWindow()

    def _start_opendivemap_import(self) -> None:
        # Confirm first — the import takes a couple of minutes.
        answer = QMessageBox.question(
            self,
            "Import from opendivemap",
            "Download all 3,123 dive sites from opendivemap.com and add them "
            "to the local database? This takes about 1–2 minutes and writes to "
            f"{get_default_db_path()}.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # Disable the action while the import is running.
        self._action_import_sites.setEnabled(False)
        self.statusBar().showMessage("Importing from opendivemap…")

        self._import_thread = QThread(self)
        worker = _ImportWorker(get_default_db_path())
        worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(worker.run)
        worker.finished.connect(self._import_thread.quit)
        worker.failed.connect(self._import_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(self._on_import_finished)
        worker.failed.connect(self._on_import_failed)
        self._import_thread.finished.connect(self._import_thread.deleteLater)
        self._import_thread.start()

    def _on_import_finished(self, counts: dict) -> None:
        self._action_import_sites.setEnabled(True)
        self.statusBar().showMessage(f"Import complete: {counts}", 10000)
        QMessageBox.information(
            self,
            "Import complete",
            "Import from opendivemap finished.\n\n"
            + "\n".join(f"{k}: {v}" for k, v in counts.items()),
        )

    def _on_import_failed(self, message: str) -> None:
        self._action_import_sites.setEnabled(True)
        self.statusBar().showMessage("Import failed", 5000)
        QMessageBox.critical(self, "Import failed", message)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Open Dive Log",
            "<h3>Open Dive Log</h3>"
            f"<p>Version {__version__}</p>"
            f"<p>Python bundled SQLite: {get_sqlite_version()}</p>"
            f"<p>Schema version: {self._schema_version}</p>"
            f"<p>DB path: <code>{get_default_db_path()}</code></p>"
            "<p>Open source under Apache 2.0. "
            "<a href='https://github.com/craigvitter/open-dive-log'>github.com/craigvitter/open-dive-log</a></p>",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._owns_connection and self._cm is not None:
            self._cm.__exit__(None, None, None)
        super().closeEvent(event)
