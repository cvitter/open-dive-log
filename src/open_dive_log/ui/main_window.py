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

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from open_dive_log.ui.dive_table_model import DiveFilter, DiveTableModel, load_rows
from open_dive_log.ui.sites_list_window import SitesListWindow
from open_dive_log.ui.buddies_list_window import BuddiesListWindow
from open_dive_log.ui.stats_window import StatsWindow
from open_dive_log.ui.lookups_list_window import LookupsListWindow


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
        # Open at 85% of the available desktop area, centered. The
        # available area excludes the OS menu bar and dock, so the
        # window doesn't accidentally land under the menu bar.
        # We use QScreen.availableGeometry() rather than screenGeometry()
        # for the dock/menubar exclusion. If the app is launched on a
        # multi-monitor setup, the window goes on the primary screen.
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = int(avail.width() * 0.85)
            h = int(avail.height() * 0.85)
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

        # --- Filter row (issue #2) -------------------------------------
        # Site-name substring search.
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Site: "))
        self._filter_site_name = QLineEdit()
        self._filter_site_name.setPlaceholderText("Filter by site name…")
        self._filter_site_name.setClearButtonEnabled(True)
        self._filter_site_name.setMinimumWidth(160)
        self._filter_site_name.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_site_name)
        # Esc clears the search box (issue #2 acceptance criterion).
        self._install_esc_clears(self._filter_site_name)

        # Country dropdown (only countries the diver has actually
        # dived in, populated by distinct_dive_filter_values()).
        toolbar.addWidget(QLabel("  Country: "))
        self._filter_country = QComboBox()
        self._filter_country.setMinimumWidth(140)
        self._filter_country.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_country)

        # Date range (from / to).
        toolbar.addWidget(QLabel("  From: "))
        self._filter_date_from = QDateEdit()
        self._filter_date_from.setCalendarPopup(True)
        self._filter_date_from.setDisplayFormat("yyyy-MM-dd")
        self._filter_date_from.setSpecialValueText(" ")  # show blank when cleared
        self._filter_date_from.setDate(self._filter_date_from.minimumDate())
        self._filter_date_from.dateChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_date_from)
        toolbar.addWidget(QLabel("  To: "))
        self._filter_date_to = QDateEdit()
        self._filter_date_to.setCalendarPopup(True)
        self._filter_date_to.setDisplayFormat("yyyy-MM-dd")
        self._filter_date_to.setSpecialValueText(" ")
        self._filter_date_to.setDate(self._filter_date_to.minimumDate())
        self._filter_date_to.dateChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_date_to)

        # Notes substring.
        toolbar.addWidget(QLabel("  Notes: "))
        self._filter_notes = QLineEdit()
        self._filter_notes.setPlaceholderText("Search notes…")
        self._filter_notes.setClearButtonEnabled(True)
        self._filter_notes.setMinimumWidth(160)
        self._filter_notes.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_notes)
        self._install_esc_clears(self._filter_notes)

        # Clear filters action.
        self._action_clear_filters = QAction("&Clear filters", self)
        self._action_clear_filters.setStatusTip(
            "Reset the site search, country, date range, and notes to defaults"
        )
        self._action_clear_filters.triggered.connect(self._on_clear_filters)
        self._action_clear_filters.setEnabled(False)
        toolbar.addAction(self._action_clear_filters)

        # --- Child windows we keep references to (so they don't get GC'd) -
        self._sites_window: SitesListWindow | None = None
        self._buddies_window: BuddiesListWindow | None = None
        self._certs_window: CertListWindow | None = None
        self._stats_window: StatsWindow | None = None
        self._lookups_window: LookupsListWindow | None = None

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

        # Note: New / Edit / Delete site actions were removed from this
        # menu per user spec. They now live only on the Sites List
        # window (toolbar + right-click). The handler methods
        # (_on_new_site / _on_edit_site / _on_delete_site) are also
        # removed; the list window owns those flows now.

        # --- Buddies ---
        buddies_menu = bar.addMenu("&Buddies")
        action_list_buddies = QAction("&List Buddies…", self)
        action_list_buddies.setShortcut(QKeySequence("Ctrl+Shift+B"))
        action_list_buddies.triggered.connect(self._open_buddies_window)
        buddies_menu.addAction(action_list_buddies)

        # --- Certifications ---
        certs_menu = bar.addMenu("&Certifications")
        action_list_certs = QAction("&List Certifications…", self)
        action_list_certs.setShortcut(QKeySequence("Ctrl+Shift+C"))
        action_list_certs.triggered.connect(self._open_certs_window)
        certs_menu.addAction(action_list_certs)

        # --- Lookups ---
        lookups_menu = bar.addMenu("&Lookups")
        action_manage_lookups = QAction("&Manage Lookups…", self)
        action_manage_lookups.setShortcut(QKeySequence("Ctrl+Shift+L"))
        action_manage_lookups.triggered.connect(self._open_lookups_window)
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
        # Stats screen: lives on the View menu, under the units
        # toggle. The dive log's key aggregates — count, time
        # totals, deepest/avg depth, distinct sites/countries.
        view_menu.addSeparator()
        action_show_stats = QAction("Show &Stats…", self)
        action_show_stats.setShortcut(QKeySequence("Ctrl+T"))
        action_show_stats.triggered.connect(self._open_stats_window)
        view_menu.addAction(action_show_stats)

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
        """Reload the dive list, applying the current filter.

        Called on app start, after any add/edit/delete, and from
        the Dives > List Dives menu action. The filter (site
        substring, country, date range, notes) is preserved
        across refreshes — that's the "persists for the session"
        contract from issue #2.
        """
        f = self._current_dive_filter()
        rows = load_rows(self._conn, limit=500, filter=f)
        self._model.set_rows(rows)
        # Populate the country dropdown lazily (the first time the
        # list is rendered). Preserves the user's selection where
        # the country still exists in the data.
        self._populate_country_dropdown()
        self._update_dive_status(f, len(rows))
        # Refresh the Stats window too, so its aggregates stay
        # current with the latest dive add/edit/delete. No-op if
        # the stats window has never been opened.
        self._refresh_stats_window()

    def _current_dive_filter(self) -> DiveFilter:
        """Read the current state of the four filter inputs and
        return a DiveFilter.

        Empty / sentinel values become empty strings; the
        underlying repo call sees None and treats it as "no
        filter on this dimension". The :meth:`DiveFilter.is_empty`
        check is used by the status bar and the Clear action.
        """
        site_name = self._filter_site_name.text()
        country_data = self._filter_country.currentData()
        country_code = "" if country_data in (None, "", self._NO_COUNTRY) else str(country_data)
        date_from = self._date_edit_value(self._filter_date_from)
        date_to = self._date_edit_value(self._filter_date_to)
        notes = self._filter_notes.text()
        return DiveFilter(
            site_name_substring=site_name,
            country_code=country_code,
            date_from=date_from,
            date_to=date_to,
            notes_substring=notes,
        )

    @staticmethod
    def _date_edit_value(edit: QDateEdit) -> str:
        """Return the QDateEdit's date as an ISO string, or "" if
        the widget is at its special "blank" position
        (``minimumDate()`` with ``setSpecialValueText(" ")``).
        """
        if edit.date() == edit.minimumDate():
            return ""
        return edit.date().toString("yyyy-MM-dd")

    @staticmethod
    def _install_esc_clears(line_edit: QLineEdit) -> None:
        """Install Esc-to-clear on a QLineEdit.

        Issue #2's acceptance criteria: "Esc in the search box
        clears the filter". `QLineEdit` has no built-in Esc
        handler (Esc by default dismisses the widget only if
        it has `setClearButtonEnabled`, but the clear button
        requires a click, not a key press). A `QShortcut` with
        ``WidgetShortcut`` context fires only when the widget
        itself has keyboard focus — exactly the "user is in
        the search box" condition the issue describes.
        """
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), line_edit)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(line_edit.clear)

    _NO_COUNTRY = ""  # sentinel "no selection" for the country combo

    def _populate_country_dropdown(self) -> None:
        """Refill the country dropdown from
        :func:`distinct_dive_filter_values`.

        The dropdown is populated lazily (on the first refresh
        that finds a non-empty distinct-values result). The
        "(All)" option is at index 0 with the empty-string
        sentinel; the rest are country names paired with their
        3-letter ISO codes. Preserves the prior selection where
        the code still exists in the data.
        """
        if self._filter_country.count() > 0:
            return  # already populated
        values = dives.distinct_dive_filter_values(self._conn)
        self._filter_country.blockSignals(True)
        try:
            self._filter_country.addItem("(All)", self._NO_COUNTRY)
            for name, code in values.countries:
                self._filter_country.addItem(name, code)
        finally:
            self._filter_country.blockSignals(False)

    def _on_filter_changed(self, *_args) -> None:
        """Any of the four filter inputs changed: re-apply the
        composite filter. Cheap (one SQL query against the
        already-indexed site + dive tables) so it fires
        synchronously on every keystroke.
        """
        f = self._current_dive_filter()
        rows = load_rows(self._conn, limit=500, filter=f)
        self._model.set_rows(rows)
        self._update_dive_status(f, len(rows))

    def _on_clear_filters(self) -> None:
        """Reset all four filter inputs to their defaults.

        Disables the action immediately so a second click does
        nothing. The site-name and notes `QLineEdit`s get their
        ``clear()`` slot called; the date edits go to their
        minimum position (which the ``_date_edit_value`` helper
        treats as "no filter on this dimension"); the country
        dropdown goes back to "(All)" at index 0.

        Signals are blocked during the reset so the four
        ``_on_filter_changed`` invocations from each ``setX``
        don't fire individually — the explicit
        ``_on_filter_changed`` call at the end does it once.
        """
        widgets: list = [
            self._filter_site_name,
            self._filter_country,
            self._filter_date_from,
            self._filter_date_to,
            self._filter_notes,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self._filter_site_name.clear()
            self._filter_country.setCurrentIndex(0)
            self._filter_date_from.setDate(self._filter_date_from.minimumDate())
            self._filter_date_to.setDate(self._filter_date_to.minimumDate())
            self._filter_notes.clear()
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._on_filter_changed()

    def _update_dive_status(self, f: DiveFilter, shown: int) -> None:
        """Update the status bar to reflect the current filter
        state and the row count.

        Format follows the issue's suggestion: ``N dive(s)
        matching '<query>'`` for a single-criterion filter,
        ``N dive(s) from <from> to <to>`` for a date range,
        or a multi-criterion composite description when more
        than one filter is active.
        """
        if f.is_empty():
            msg = (
                f"{shown} dive(s) shown · "
                f"SQLite {get_sqlite_version()} · schema v{self._schema_version}"
            )
        else:
            parts: list[str] = []
            if f.site_name_substring:
                parts.append(f"site contains '{f.site_name_substring}'")
            if f.country_code:
                # Show the country name (the combo's current text),
                # not the code.
                parts.append(f"country = {self._filter_country.currentText()}")
            if f.date_from and f.date_to:
                parts.append(f"from {f.date_from} to {f.date_to}")
            elif f.date_from:
                parts.append(f"from {f.date_from}")
            elif f.date_to:
                parts.append(f"through {f.date_to}")
            if f.notes_substring:
                parts.append(f"notes contains '{f.notes_substring}'")
            if len(parts) == 1 and (f.site_name_substring or f.notes_substring):
                msg = f"{shown} dive(s) matching '{parts[0]}'"
            elif len(parts) == 1 and (f.date_from or f.date_to):
                msg = f"{shown} dive(s) {parts[0]}"
            else:
                msg = f"{shown} dive(s) — " + "; ".join(parts)
        self.statusBar().showMessage(msg)
        self._action_clear_filters.setEnabled(not f.is_empty())

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
        # If the Sites List window is open, propagate the unit toggle
        # to it as well (it shows Max depth in m or ft).
        if self._sites_window is not None:
            self._sites_window.set_unit_system(new_units)
        # Same for the Stats window — its depth rows are in m or ft
        # depending on the toggle.
        if self._stats_window is not None:
            self._stats_window.set_unit_system(new_units)
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
        # Refresh child windows so they show the new buddy
        # (in case the user created a buddy inline in the dive form)
        if self._buddies_window is not None:
            self._buddies_window.refresh()
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
            self._sites_window = SitesListWindow(
                self._conn, parent=self,
                unit_system=preferences.get_units(),
            )
        self._sites_window.show()
        self._sites_window.raise_()
        self._sites_window.activateWindow()

    def _refresh_sites_window(self) -> None:
        """If the sites list window is open, reload it from the DB."""
        if self._sites_window is not None:
            self._sites_window.refresh()

    def _open_certs_window(self) -> None:
        if self._certs_window is None:
            self._certs_window = CertListWindow(self._conn, parent=self)
        self._certs_window.show()
        self._certs_window.raise_()
        self._certs_window.activateWindow()

    def _open_buddies_window(self) -> None:
        if self._buddies_window is None:
            self._buddies_window = BuddiesListWindow(self._conn, parent=self)
        self._buddies_window.show()
        self._buddies_window.raise_()
        self._buddies_window.activateWindow()

    def _open_stats_window(self) -> None:
        if self._stats_window is None:
            self._stats_window = StatsWindow(
                self._conn, parent=self,
                unit_system=preferences.get_units(),
            )
        # Always refresh on open so the numbers reflect any
        # add/edit/delete the user has done since the last open.
        self._stats_window.refresh()
        self._stats_window.show()
        self._stats_window.raise_()
        self._stats_window.activateWindow()

    def _refresh_stats_window(self) -> None:
        """If the stats window is open, re-run the aggregations and
        update the displayed values."""
        if self._stats_window is not None:
            self._stats_window.refresh()

    def _open_lookups_window(self) -> None:
        if self._lookups_window is None:
            self._lookups_window = LookupsListWindow(self._conn, parent=self)
        self._lookups_window.show()
        self._lookups_window.raise_()
        self._lookups_window.activateWindow()

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
            "<a href='https://github.com/cvitter/open-dive-log'>github.com/cvitter/open-dive-log</a></p>",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._owns_connection and self._cm is not None:
            self._cm.__exit__(None, None, None)
        super().closeEvent(event)
