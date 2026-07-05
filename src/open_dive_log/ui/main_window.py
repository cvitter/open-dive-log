"""Main application window for Open Dive Log.

Layout:
    QMainWindow
    ├── menu bar:  Dives / Sites / Certifications / View / Lookups / Help
    ├── central:   QTableView bound to DiveTableModel (the dive list)
    └── status bar

Menus:
    Dives:          New Dive, Edit Dive, Delete Dive, List Dives, Quit
    Sites:          List Sites, ---, Import from opendivemap, ---,
                    New/Edit/Delete Site (disabled placeholders)
    Certifications: List Certifications…
    View:           Units → Metric / Imperial (persisted, toggles the
                    dive list and the next opened dive form)
    Lookups:        Manage Lookups (disabled — coming soon)
    Help:           About Open Dive Log

Double-clicking a row in the table opens the dive in the edit form
(same as the menu's Edit Dive). Double-click is the only path that
mutates a dive.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableView,
    QToolBar,
)

from open_dive_log.repositories import dives
from open_dive_log import __version__, import_opendivemap, preferences
from open_dive_log.db import get_default_db_path, get_sqlite_version
from open_dive_log.units import UnitSystem
from open_dive_log.ui.cert_add_edit_dialog import CertAddEditDialog  # noqa: F401
from open_dive_log.ui.cert_list_window import CertListWindow
from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog
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
        # Open at 75% of the available desktop area, centered. The
        # available area excludes the OS menu bar and dock, so the
        # window doesn't accidentally land under the menu bar.
        # We use QScreen.availableGeometry() rather than screenGeometry()
        # for the dock/menubar exclusion. If the app is launched on a
        # multi-monitor setup, the window goes on the primary screen.
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = int(avail.width() * 0.75)
            h = int(avail.height() * 0.75)
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + (avail.height() - h) // 2
            self.setGeometry(x, y, w, h)
        else:
            # Headless test environment: fall back to a sensible default.
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

        # --- Toolbar (Add/Edit/Delete dive — same actions as the menu) --
        toolbar = QToolBar("Dives toolbar", self)
        toolbar.setObjectName("DivesToolbar")
        self.addToolBar(toolbar)
        toolbar.addAction(self._action_new_dive)
        toolbar.addAction(self._action_edit_dive)
        toolbar.addAction(self._action_delete_dive)

        # --- Child windows we keep references to (so they don't get GC'd) -
        self._sites_window: SitesListWindow | None = None
        self._certs_window: CertListWindow | None = None

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
        self._action_new_dive.triggered.connect(self._on_new_dive)
        dives_menu.addAction(self._action_new_dive)

        self._action_edit_dive = QAction("&Edit Dive…", self)
        self._action_edit_dive.setShortcut(QKeySequence("Ctrl+E"))
        self._action_edit_dive.triggered.connect(self._on_edit_dive)
        dives_menu.addAction(self._action_edit_dive)

        self._action_delete_dive = QAction("&Delete Dive", self)
        self._action_delete_dive.setShortcut(QKeySequence.StandardKey.Delete)
        self._action_delete_dive.triggered.connect(self._on_delete_dive)
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
        self._action_new_site.triggered.connect(self._on_new_site)
        sites_menu.addAction(self._action_new_site)
        self._action_edit_site = QAction("&Edit Site…", self)
        self._action_edit_site.triggered.connect(self._on_edit_site)
        sites_menu.addAction(self._action_edit_site)
        self._action_delete_site = QAction("&Delete Site", self)
        self._action_delete_site.triggered.connect(self._on_delete_site)
        sites_menu.addAction(self._action_delete_site)

        # --- Certifications ---
        certs_menu = bar.addMenu("&Certifications")
        action_list_certs = QAction("&List Certifications…", self)
        action_list_certs.setShortcut(QKeySequence("Ctrl+Shift+C"))
        action_list_certs.triggered.connect(self._open_certs_window)
        certs_menu.addAction(action_list_certs)

        # --- Lookups (placeholder) ---
        lookups_menu = bar.addMenu("&Lookups")
        action_manage_lookups = QAction("&Manage Lookups…", self)
        action_manage_lookups.setEnabled(False)
        action_manage_lookups.setToolTip("Coming in a later phase")
        lookups_menu.addAction(action_manage_lookups)

        # --- View (units toggle, persisted across restarts) ---
        view_menu = bar.addMenu("&View")
        units_menu = view_menu.addMenu("&Units")
        # QActionGroup makes the two actions mutually exclusive; the
        # active one shows a check mark. Persisted to
        # ~/.open-dive-log/preferences.json via open_dive_log.preferences.
        self._unit_group = QActionGroup(self)
        self._unit_group.setExclusive(True)
        self._action_units_metric = QAction("&Metric (°C, m)", self)
        self._action_units_metric.setCheckable(True)
        self._action_units_imperial = QAction("&Imperial (°F, ft)", self)
        self._action_units_imperial.setCheckable(True)
        self._unit_group.addAction(self._action_units_metric)
        self._unit_group.addAction(self._action_units_imperial)
        units_menu.addAction(self._action_units_metric)
        units_menu.addAction(self._action_units_imperial)
        # Initialize the active action from the persisted preference,
        # defaulting to metric if the file is missing or malformed.
        initial_units = preferences.get_units()
        if initial_units == UnitSystem.IMPERIAL:
            self._action_units_imperial.setChecked(True)
        else:
            self._action_units_metric.setChecked(True)
        # Set the model's units to match the active preference so the
        # initial list view is rendered in the user's chosen unit.
        self._model.set_unit_system(initial_units)
        self._unit_group.triggered.connect(self._on_units_changed)

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

    def _on_units_changed(self, action: QAction) -> None:
        """Handle the View > Units toggle.

        Persists the choice to ~/.open-dive-log/preferences.json, then
        tells the dive list model to re-render in the new units. The
        next time a DiveAddEditDialog is opened (New Dive / Edit Dive
        / double-click), it picks up the new unit system from
        preferences.get_units() — see the call sites in _on_new_dive
        and _edit_dive_by_id. The SitesListWindow does not display
        dive data so it is unaffected.
        """
        if action is self._action_units_imperial:
            new_units = UnitSystem.IMPERIAL
        elif action is self._action_units_metric:
            new_units = UnitSystem.METRIC
        else:
            # Defensive: should not happen with an exclusive group.
            return
        try:
            preferences.set_units(new_units)
        except OSError as e:
            QMessageBox.warning(
                self,
                "Units preference",
                f"Could not save the units preference: {e}. "
                "The display will update, but the choice won't be "
                "remembered for the next launch.",
            )
        self._model.set_unit_system(new_units)
        label = "Imperial (°F, ft)" if new_units == UnitSystem.IMPERIAL else "Metric (°C, m)"
        self.statusBar().showMessage(f"Units: {label}", 5000)

    def _on_row_double_clicked(self, index) -> None:
        if not index.isValid():
            return
        row = self._model.row_at(index.row())
        if row is None:
            return
        # Double-click edits the dive (same as the menu's Edit Dive).
        self._edit_dive_by_id(row.id)

    def _on_new_dive(self) -> None:
        dlg = DiveAddEditDialog(
            self._conn, dive=None, parent=self,
            unit_system=preferences.get_units(),
        )
        if dlg.exec() != DiveAddEditDialog.DialogCode.Accepted:
            return
        submitted = dlg.result_dive()
        if submitted is None:
            return
        with self._conn:
            new_id = dives.create(self._conn, **submitted.to_kwargs())
            if submitted.site_ids:
                dives.attach_sites(self._conn, new_id, submitted.site_ids)
            if submitted.buddy_entries:
                dives.attach_buddies(self._conn, new_id, submitted.buddy_entries)
        self._refresh_dive_list()
        # Select the new row
        for r in range(self._model.rowCount()):
            if self._model.row_at(r) and self._model.row_at(r).id == new_id:
                self._table.selectRow(r)
                break
        self.statusBar().showMessage(f"Added dive #{new_id}", 5000)

    def _on_edit_dive(self) -> None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "Edit", "Select a dive first.")
            return
        row = self._model.row_at(idx.row())
        if row is None:
            return
        self._edit_dive_by_id(row.id)

    def _edit_dive_by_id(self, dive_id: int) -> None:
        full = dives.get_full(self._conn, dive_id)
        if full is None:
            QMessageBox.warning(self, "Edit", f"Dive #{dive_id} no longer exists.")
            return
        dlg = DiveAddEditDialog(
            self._conn, dive=full, parent=self,
            unit_system=preferences.get_units(),
        )
        if dlg.exec() != DiveAddEditDialog.DialogCode.Accepted:
            return
        submitted = dlg.result_dive()
        if submitted is None:
            return
        with self._conn:
            dives.update(self._conn, dive_id, **submitted.to_kwargs())
            dives.attach_sites(self._conn, dive_id, submitted.site_ids)
            dives.attach_buddies(self._conn, dive_id, submitted.buddy_entries)
        self._refresh_dive_list()
        self.statusBar().showMessage(f"Updated dive #{dive_id}", 5000)

    def _on_delete_dive(self) -> None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "Delete", "Select a dive first.")
            return
        row = self._model.row_at(idx.row())
        if row is None:
            return
        full = dives.get_full(self._conn, row.id)
        if full is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete dive",
            f"Delete the dive from {full.dive_date}? "
            "Attached sites and buddies will be removed via cascade. "
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        dives.delete(self._conn, row.id)
        self._refresh_dive_list()
        self.statusBar().showMessage(f"Deleted dive #{row.id}", 5000)

    def _open_sites_window(self) -> None:
        if self._sites_window is None:
            self._sites_window = SitesListWindow(self._conn, parent=self)
        self._sites_window.show()
        self._sites_window.raise_()
        self._sites_window.activateWindow()

    def _refresh_sites_window(self) -> None:
        """If the sites list window is open, reload it from the DB."""
        if self._sites_window is not None:
            self._sites_window.refresh()

    def _pick_site_for_edit(self) -> int | None:
        """Show a site picker and return the chosen site id, or None.

        Used by _on_edit_site and _on_delete_site so the user has
        a way to pick a site without first opening the list window.
        """
        from PySide6.QtWidgets import QInputDialog
        from open_dive_log.repositories import sites as sites_repo
        rows = sites_repo.list_all(self._conn)
        if not rows:
            QMessageBox.information(
                self, "No sites",
                "There are no sites in the database yet. Create one with "
                "Sites → New Site, or import from opendivemap first.",
            )
            return None
        # Sort alphabetically by name for the picker
        rows.sort(key=lambda s: (s.name or "").lower())
        items = [
            f"{s.name} — {s.country_name or s.country or s.country_code or '?'}"
            for s in rows
        ]
        choice, ok = QInputDialog.getItem(
            self, "Select a site", "Site:", items, 0, False,
        )
        if not ok:
            return None
        return rows[items.index(choice)].id

    def _on_new_site(self) -> None:
        from open_dive_log.ui.site_add_edit_dialog import (
            SiteAddEditDialog, SubmittedSite,
        )
        from open_dive_log.repositories import sites as sites_repo
        dlg = SiteAddEditDialog(self._conn, site=None, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sub: SubmittedSite = dlg.submitted()
        assert sub is not None
        try:
            site = sites_repo.find_or_create(
                self._conn, sub.name,
                region=sub.region,
                country=sub.country,
                country_code=sub.country_code,
                latitude=sub.latitude,
                longitude=sub.longitude,
                environment_id=sub.environment_id,
                entry_id=sub.entry_id,
                max_depth_m=sub.max_depth_m,
                description=sub.description,
                description_wildlife=sub.description_wildlife,
                notes=sub.notes,
            )
        except sqlite3.IntegrityError as e:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not create the site — likely a duplicate "
                f"(name, country) combination.\n\n{e}",
            )
            return
        self._refresh_sites_window()
        self.statusBar().showMessage(f"Created site #{site.id}: {site.name}", 5000)

    def _on_edit_site(self) -> None:
        from open_dive_log.ui.site_add_edit_dialog import (
            SiteAddEditDialog, SubmittedSite,
        )
        from open_dive_log.repositories import sites as sites_repo
        site_id = self._pick_site_for_edit()
        if site_id is None:
            return
        site = sites_repo.get(self._conn, site_id)
        if site is None:
            QMessageBox.warning(self, "Site missing", f"Site #{site_id} no longer exists.")
            return
        dlg = SiteAddEditDialog(self._conn, site=site, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sub: SubmittedSite = dlg.submitted()
        assert sub is not None
        try:
            sites_repo.update(
                self._conn, site_id,
                name=sub.name,
                region=sub.region,
                country=sub.country,
                latitude=sub.latitude,
                longitude=sub.longitude,
                environment_id=sub.environment_id,
                entry_id=sub.entry_id,
                max_depth_m=sub.max_depth_m,
                description=sub.description,
                description_wildlife=sub.description_wildlife,
                notes=sub.notes,
            )
        except sqlite3.IntegrityError as e:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not save the site — likely a duplicate "
                f"(name, country) combination with an existing site.\n\n{e}",
            )
            return
        except LookupError as e:
            QMessageBox.warning(self, "Site missing", str(e))
            return
        self._refresh_sites_window()
        self.statusBar().showMessage(f"Updated site #{site_id}: {sub.name}", 5000)

    def _on_delete_site(self) -> None:
        from open_dive_log.repositories import sites as sites_repo
        site_id = self._pick_site_for_edit()
        if site_id is None:
            return
        site = sites_repo.get(self._conn, site_id)
        if site is None:
            QMessageBox.warning(self, "Site missing", f"Site #{site_id} no longer exists.")
            return
        # Confirm
        answer = QMessageBox.question(
            self, "Delete site?",
            f"Delete site #{site.id} '{site.name}'?\n\n"
            f"This cannot be undone. If any dives reference this site, "
            f"the delete will be blocked.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            sites_repo.delete(self._conn, site_id)
        except sqlite3.IntegrityError:
            blockers = sites_repo.list_blocking_dives(self._conn, site_id)
            lines = "\n".join(f"  • #{d_id} ({d_date})" for d_id, d_date in blockers)
            extra = "" if len(blockers) <= 10 else f"\n  (… and more)"
            QMessageBox.warning(
                self, "Delete blocked",
                f"Cannot delete site #{site.id} '{site.name}' — it's "
                f"referenced by {len(blockers)} dive(s):\n\n{lines}{extra}\n\n"
                f"Edit or delete those dives first, then try again.",
            )
            return
        except LookupError as e:
            QMessageBox.warning(self, "Site missing", str(e))
            return
        self._refresh_sites_window()
        self.statusBar().showMessage(f"Deleted site #{site_id}: {site.name}", 5000)

    def _open_certs_window(self) -> None:
        if self._certs_window is None:
            self._certs_window = CertListWindow(self._conn, parent=self)
        self._certs_window.show()
        self._certs_window.raise_()
        self._certs_window.activateWindow()

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
