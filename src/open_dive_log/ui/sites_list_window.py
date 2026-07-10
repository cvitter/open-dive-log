"""Read-only sites list window.

Shows a table of sites from the local DB. Default sort is by name ASC.
For this phase there's no inline filter / search box — the table loads
the first N rows (default 1000) and shows a status bar with the total.

Future phases will add a search box, a country filter, and an "open
detail" action. Keep this file small and the next phase will be a
clean extension.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterable

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableView,
    QToolBar,
    QWidget,
)

from open_dive_log.repositories import sites as sites_repo
from open_dive_log.units import UnitSystem, m_to_ft


# A single filter expression: a name substring and 0-or-1 selection
# on each of the four dimensions. ``None`` or empty string means
# "no filter on this dimension"; the underlying repo call sees
# only the non-None criteria. ``is_empty()`` is used by the UI to
# decide whether the "Clear filters" button is enabled.
@dataclasses.dataclass(frozen=True, slots=True)
class SiteFilter:
    name: str = ""
    country_code: str | None = None
    region: str | None = None
    environment_id: int | None = None
    entry_id: int | None = None

    def is_empty(self) -> bool:
        return not (
            self.name
            or self.country_code
            or self.region
            or self.environment_id is not None
            or self.entry_id is not None
        )


# (column index, header, tooltip, applies_to_max_depth)
# The "Max depth" column is the only unit-bearing column in this table.
# The header is built dynamically from the current unit system, so
# this constant is a placeholder that's overridden at runtime.
HEADERS_METRIC: tuple[tuple[str, str], ...] = (
    ("Name", "Site name"),
    ("Country", "Country name (ISO 3166-1 alpha-2)"),
    ("Region", "Free-text region / area"),
    ("Max depth (m)", "Maximum depth for this site, in meters"),
    ("Environment", "Where the dive happens (ocean, lake, etc.)"),
    ("Entry", "How divers enter the water (shore, boat, other)"),
)
HEADERS_IMPERIAL: tuple[tuple[str, str], ...] = (
    ("Name", "Site name"),
    ("Country", "Country name (ISO 3166-1 alpha-2)"),
    ("Region", "Free-text region / area"),
    ("Max depth (ft)", "Maximum depth for this site, in feet"),
    ("Environment", "Where the dive happens (ocean, lake, etc.)"),
    ("Entry", "How divers enter the water (shore, boat, other)"),
)
COL_MAX_DEPTH = 3


def _build_headers(system: UnitSystem) -> tuple[tuple[str, str], ...]:
    """Return the column headers for the given unit system.

    Only the Max depth column changes between metric and imperial;
    the other columns are unit-less.
    """
    if system == UnitSystem.IMPERIAL:
        return HEADERS_IMPERIAL
    return HEADERS_METRIC


class SiteTableModel(QAbstractTableModel):
    """Loads sites via `sites_repo.list_all` and exposes them as a table.

    Supports a `SiteFilter` (name substring + country / region /
    environment / entry), and a unit system (`set_unit_system`).
    The filter is applied on the in-memory copy of the rows
    (`_all_rows`); `_rows` is the filtered view. The name
    substring is a case-insensitive substring match; the four
    dimension filters are exact matches (None means "no filter").
    `set_rows` resets the filter to "show all".
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_rows: list[sites_repo.Site] = []
        self._rows: list[sites_repo.Site] = []
        self._filter: SiteFilter = SiteFilter()
        self._units: UnitSystem = UnitSystem.METRIC
        self._headers: tuple[tuple[str, str], ...] = _build_headers(self._units)

    def set_rows(self, rows: Iterable[sites_repo.Site]) -> None:
        """Replace the underlying data and reset the filter."""
        self.beginResetModel()
        self._all_rows = list(rows)
        self._filter = SiteFilter()
        self._rows = list(self._all_rows)
        self.endResetModel()

    def set_filter(self, name_substring: str) -> None:
        """Backwards-compatible name-only filter shortcut.

        Equivalent to ``set_filters(SiteFilter(name=name_substring))``.
        Kept so the search box's ``textChanged`` handler doesn't
        have to know about the new filter shape.
        """
        self.set_filters(SiteFilter(name=name_substring))

    def set_filters(self, f: SiteFilter) -> None:
        """Apply a full filter. No-op if the filter is unchanged.

        Name filter: case-insensitive substring on ``name``.
        Dimension filters: exact match on the joined column
        (``country_code`` for country, free-text for region, FK
        id for environment / entry). A dimension value of None
        means "no filter on that dimension".
        """
        if f == self._filter:
            return  # no-op
        self.beginResetModel()
        self._filter = f
        needle = f.name.lower()
        rows: list[sites_repo.Site] = []
        for s in self._all_rows:
            if needle and needle not in (s.name or "").lower():
                continue
            if f.country_code and s.country_code != f.country_code:
                continue
            if f.region and s.region != f.region:
                continue
            if f.environment_id is not None and s.environment_id != f.environment_id:
                continue
            if f.entry_id is not None and s.entry_id != f.entry_id:
                continue
            rows.append(s)
        self._rows = rows
        self.endResetModel()

    def filter(self) -> SiteFilter:
        return self._filter

    def total_count(self) -> int:
        """Number of sites in the underlying data (before filter)."""
        return len(self._all_rows)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return len(self._headers)

    def set_unit_system(self, system: UnitSystem) -> None:
        """Switch the displayed unit for the max-depth column.

        No-op if the system hasn't changed. The headers AND the
        max-depth cell values are both rebuilt under beginResetModel
        so the view repaints cleanly.
        """
        if system == self._units:
            return
        self.beginResetModel()
        self._units = system
        self._headers = _build_headers(system)
        self.endResetModel()

    def unit_system(self) -> UnitSystem:
        return self._units

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section][0]
        elif orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        col = index.column()

        # Expose the site id via UserRole so views can look up
        # the id for a given row (used by the "select newly created
        # site" path in SitesListWindow._on_new_action).
        if role == Qt.ItemDataRole.UserRole:
            return row.id

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.name
            if col == 1:
                return row.country_name or row.country_code or ""
            if col == 2:
                return row.region or ""
            if col == COL_MAX_DEPTH:
                if row.max_depth_m is None:
                    return ""
                # Convert at display time, mirror the dive list's pattern
                value = (
                    m_to_ft(row.max_depth_m)
                    if self._units == UnitSystem.IMPERIAL
                    else row.max_depth_m
                )
                if value == int(value):
                    return f"{int(value)}"
                return f"{value:.1f}"
            if col == 4:
                return row.environment_name or ""
            if col == 5:
                return row.entry_name or ""

        if role == Qt.ItemDataRole.ToolTipRole:
            if 0 <= col < len(self._headers):
                return self._headers[col][1]

        if role == Qt.ItemDataRole.TextAlignmentRole and col == COL_MAX_DEPTH:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None


class SitesListWindow(QMainWindow):
    """Read-only-by-default table of sites, with a search box and
    Edit / Delete actions on the current selection.

    Selection model:
      * The user types into the search box to narrow the visible
        rows (case-insensitive substring on the name field).
      * When a row is selected, the Edit and Delete toolbar /
        context-menu actions become enabled. They act on the
        selected row.
      * Double-click a row to edit it (matches the dive list
        behavior).

    The Edit / Delete actions are also exposed on the main window's
    Sites menu (handled by main_window.py), which dispatches to
    this window's selection when it's open. The actions live here
    because this is where the user actually sees and selects a site.
    """

    DEFAULT_LIMIT = 5000

    # Sentinel "no selection" values for the four filter dropdowns.
    # None would be ambiguous in PySide6 (currentData() returns None
    # for unselected items too), so we use string sentinels and
    # convert to typed values when assembling the SiteFilter.
    _NO_COUNTRY = ""
    _NO_REGION = ""
    _NO_ENV: int = -1
    _NO_ENTRY: int = -1

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
        unit_system: UnitSystem = UnitSystem.METRIC,
    ) -> None:
        super().__init__(parent)
        self._conn = conn

        self.setWindowTitle("Sites")
        self.resize(900, 600)

        self._model = SiteTableModel(self)
        self._model.set_unit_system(unit_system)
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)  # default order is the SQL one
        self._table.verticalHeader().setVisible(False)
        # Double-click to edit — matches the dive list behavior
        self._table.doubleClicked.connect(self._on_edit_action)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # --- Toolbar: 4 filter dropdowns + search + Edit + Delete -------
        toolbar = QToolBar("Sites", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # --- Country filter -------------------------------------------
        toolbar.addWidget(QLabel(" Country: "))
        self._filter_country = QComboBox()
        self._filter_country.setMinimumWidth(140)
        self._filter_country.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_country)

        # --- Region filter --------------------------------------------
        toolbar.addWidget(QLabel("  Region: "))
        self._filter_region = QComboBox()
        self._filter_region.setMinimumWidth(140)
        self._filter_region.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_region)

        # --- Environment filter ---------------------------------------
        toolbar.addWidget(QLabel("  Env: "))
        self._filter_environment = QComboBox()
        self._filter_environment.setMinimumWidth(110)
        self._filter_environment.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_environment)

        # --- Entry filter ---------------------------------------------
        toolbar.addWidget(QLabel("  Entry: "))
        self._filter_entry = QComboBox()
        self._filter_entry.setMinimumWidth(90)
        self._filter_entry.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_entry)

        # --- Clear filters button -------------------------------------
        self._action_clear_filters = QAction("&Clear filters", self)
        self._action_clear_filters.setStatusTip(
            "Reset all four dropdowns and the search box to their defaults"
        )
        self._action_clear_filters.triggered.connect(self._on_clear_filters)
        self._action_clear_filters.setEnabled(False)
        toolbar.addAction(self._action_clear_filters)

        toolbar.addSeparator()

        # --- Search box -----------------------------------------------
        toolbar.addWidget(QLabel(" Search: "))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by site name…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        # Sensible width — the toolbar widget will grow with the window
        self._search.setMinimumWidth(220)
        toolbar.addWidget(self._search)

        toolbar.addSeparator()

        self._action_new = QAction("&New Site…", self)
        self._action_new.setShortcut("Ctrl+N")
        self._action_new.setStatusTip("Add a new site to the database")
        self._action_new.triggered.connect(self._on_new_action)
        toolbar.addAction(self._action_new)

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
        self._table.addAction(self._action_new)
        self._table.addAction(self._action_edit)
        self._table.addAction(self._action_delete)

        # --- Selection-driven enable/disable ----------------------------
        sel_model = self._table.selectionModel()
        sel_model.selectionChanged.connect(self._on_selection_changed)

        # The filter values depend on the data, so they are populated
        # by refresh() rather than in __init__.
        self._filter_values: sites_repo.SiteFilterValues | None = None
        self.refresh()

    # ------------------------------------------------------------------ API
    def set_unit_system(self, system: UnitSystem) -> None:
        """Forward the unit toggle to the model. Called by MainWindow
        when the user picks Metric / Imperial from the View menu.
        """
        self._model.set_unit_system(system)

    def _populate_filter_dropdowns(self) -> None:
        """Read the distinct values from the DB and refill the four
        dropdowns. Preserves the current selection where possible
        (so e.g. picking "USA" and then refreshing doesn't reset
        the dropdown to "All" — it stays on "USA").

        Called from :meth:`refresh` after the data reload.
        """
        values = sites_repo.distinct_filter_values(self._conn)
        self._filter_values = values

        # Capture current selections (by data key) so we can restore
        # them after the refill.
        prev_country = self._current_country_code()
        prev_region = self._current_region()
        prev_env = self._current_environment_id()
        prev_entry = self._current_entry_id()

        # Temporarily disconnect signals so refilling the model
        # doesn't fire a cascade of _on_filter_changed() calls.
        for combo in (
            self._filter_country,
            self._filter_region,
            self._filter_environment,
            self._filter_entry,
        ):
            combo.blockSignals(True)
        try:
            self._refill_combo(
                self._filter_country, values.countries,
                all_label="(All)", sentinel=self._NO_COUNTRY,
            )
            self._refill_combo(
                self._filter_region, values.regions,
                all_label="(All)", sentinel=self._NO_REGION,
            )
            self._refill_combo_int(
                self._filter_environment, values.environments,
                all_label="(All)", sentinel=self._NO_ENV,
            )
            self._refill_combo_int(
                self._filter_entry, values.entries,
                all_label="(All)", sentinel=self._NO_ENTRY,
            )
            # Restore prior selection where the key still exists in
            # the new value list; otherwise fall back to "All".
            self._select_combo_by_data(
                self._filter_country, prev_country, fallback=self._NO_COUNTRY,
            )
            self._select_combo_by_data(
                self._filter_region, prev_region, fallback=self._NO_REGION,
            )
            self._select_combo_by_data(
                self._filter_environment, prev_env, fallback=self._NO_ENV,
            )
            self._select_combo_by_data(
                self._filter_entry, prev_entry, fallback=self._NO_ENTRY,
            )
        finally:
            for combo in (
                self._filter_country,
                self._filter_region,
                self._filter_environment,
                self._filter_entry,
            ):
                combo.blockSignals(False)

    @staticmethod
    def _refill_combo(
        combo: QComboBox,
        items: list[tuple[str, str]],
        *,
        all_label: str,
        sentinel: str,
    ) -> None:
        """Refill a string-keyed dropdown with the "(All)" option
        at index 0 and the items in display order.
        """
        combo.clear()
        combo.addItem(all_label, sentinel)
        for label, key in items:
            combo.addItem(label, key)

    @staticmethod
    def _refill_combo_int(
        combo: QComboBox,
        items: list[tuple[str, int]],
        *,
        all_label: str,
        sentinel: int,
    ) -> None:
        """Refill an int-keyed dropdown with the "(All)" option
        at index 0 and the items in display order.
        """
        combo.clear()
        combo.addItem(all_label, sentinel)
        for label, key in items:
            combo.addItem(label, key)

    @staticmethod
    def _select_combo_by_data(
        combo: QComboBox, key, *, fallback
    ) -> None:
        """Select the dropdown entry whose user-data equals ``key``;
        fall back to the ``fallback`` key (usually the "(All)"
        sentinel) if the key is no longer present.
        """
        target = key if key is not None else fallback
        for i in range(combo.count()):
            if combo.itemData(i) == target:
                combo.setCurrentIndex(i)
                return
        # Key not present: fall back to "(All)" or to whatever the
        # fallback resolves to.
        for i in range(combo.count()):
            if combo.itemData(i) == fallback:
                combo.setCurrentIndex(i)
                return

    def _current_country_code(self) -> str | None:
        data = self._filter_country.currentData()
        if data in (None, self._NO_COUNTRY, ""):
            return None
        return data

    def _current_region(self) -> str | None:
        data = self._filter_region.currentData()
        if data in (None, self._NO_REGION, ""):
            return None
        return data

    def _current_environment_id(self) -> int | None:
        data = self._filter_environment.currentData()
        if data in (None, self._NO_ENV):
            return None
        return int(data)

    def _current_entry_id(self) -> int | None:
        data = self._filter_entry.currentData()
        if data in (None, self._NO_ENTRY):
            return None
        return int(data)

    def _assemble_filter(self) -> SiteFilter:
        """Build a SiteFilter from the current dropdown + search state."""
        return SiteFilter(
            name=self._search.text(),
            country_code=self._current_country_code(),
            region=self._current_region(),
            environment_id=self._current_environment_id(),
            entry_id=self._current_entry_id(),
        )

    def refresh(self) -> None:
        """Reload the sites from the DB. The current filter is preserved
        (so re-importing from opendivemap doesn't lose the user's
        typed search or dropdown selections).
        """
        rows = sites_repo.list_all(self._conn)
        if len(rows) > self.DEFAULT_LIMIT:
            shown = rows[: self.DEFAULT_LIMIT]
        else:
            shown = rows
        # Repopulate the dropdowns BEFORE setting rows so that the
        # dropdowns' restored selections reflect the new data set.
        self._populate_filter_dropdowns()
        self._model.set_rows(shown)
        # Re-apply any active filter
        f = self._assemble_filter()
        if not f.is_empty():
            self._model.set_filters(f)
        self._update_status()

    def _update_status(self) -> None:
        total = self._model.total_count()
        shown = self._model.rowCount()
        f = self._model.filter()
        if f.is_empty():
            msg = f"{shown} of {total} sites"
        else:
            parts = []
            if f.name:
                parts.append(f"name contains '{f.name}'")
            if f.country_code:
                parts.append(f"country = {self._filter_country.currentText()}")
            if f.region:
                parts.append(f"region = {f.region}")
            if f.environment_id is not None:
                parts.append(f"env = {self._filter_environment.currentText()}")
            if f.entry_id is not None:
                parts.append(f"entry = {self._filter_entry.currentText()}")
            criteria = "; ".join(parts) if parts else "(no criteria)"
            msg = f"{shown} of {total} sites — {criteria}"
        self.statusBar().showMessage(msg)
        # Enable the Clear-filters button only when there's something
        # to clear.
        self._action_clear_filters.setEnabled(not f.is_empty())

    def selected_site(self) -> sites_repo.Site | None:
        """Return the currently selected Site, or None if no row is
        selected (or the search filter hid it)."""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0]
        if not (0 <= idx.row() < self._model.rowCount()):
            return None
        return self._model._rows[idx.row()]

    def edit_selected(self) -> bool:
        """Public hook used by main_window.py: open the edit dialog for
        the currently selected row. Returns False if there's no
        selection (so the main window can fall back to opening the
        list window with a status message)."""
        site = self.selected_site()
        if site is None:
            return False
        self._do_edit(site)
        return True

    def delete_selected(self) -> bool:
        """Public hook used by main_window.py: delete the currently
        selected row. Returns False if there's no selection."""
        site = self.selected_site()
        if site is None:
            return False
        self._do_delete(site)
        return True

    # --------------------------------------------------------- selection
    def _on_selection_changed(self, *_args) -> None:
        has_sel = self.selected_site() is not None
        self._action_edit.setEnabled(has_sel)
        self._action_delete.setEnabled(has_sel)

    # ------------------------------------------------------------- search
    def _on_search_changed(self, text: str) -> None:
        self._model.set_filters(self._assemble_filter())
        self._update_status()

    # --------------------------------------------------------- filters
    def _on_filter_changed(self, *_args) -> None:
        """Any of the four dropdowns changed: reassemble the
        composite filter and apply it. Cheap (in-memory scan over
        the already-loaded rows) so it fires synchronously on
        every selection change.
        """
        self._model.set_filters(self._assemble_filter())
        self._update_status()

    def _on_clear_filters(self) -> None:
        """Reset all four dropdowns and the search box to their
        defaults. Disables the action immediately so a second
        click does nothing.
        """
        # Block signals so the four _on_filter_changed() invocations
        # from setCurrentIndex don't fire individually — the explicit
        # set_filters() call at the end will do it once.
        for combo in (
            self._filter_country,
            self._filter_region,
            self._filter_environment,
            self._filter_entry,
        ):
            combo.blockSignals(True)
        try:
            # The "(All)" option is always at index 0 after _refill_combo.
            self._filter_country.setCurrentIndex(0)
            self._filter_region.setCurrentIndex(0)
            self._filter_environment.setCurrentIndex(0)
            self._filter_entry.setCurrentIndex(0)
            self._search.clear()
        finally:
            for combo in (
                self._filter_country,
                self._filter_region,
                self._filter_environment,
                self._filter_entry,
            ):
                combo.blockSignals(False)
        self._model.set_filters(SiteFilter())
        self._update_status()

    # ----------------------------------------------------------- actions
    def _on_new_action(self) -> None:
        """Open the site form in create mode. On Accept, insert a new
        site and select it in the table.
        """
        from open_dive_log.ui.site_add_edit_dialog import (
            SiteAddEditDialog,
        )
        dlg = SiteAddEditDialog(
            self._conn,
            site=None,
            unit_system=self._model.unit_system(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sub = dlg.submitted()
        if sub is None:
            return
        # Convert the frozen dataclass to a dict for the repo call.
        kwargs = dataclasses.asdict(sub)
        # is_new is a UI flag, not a column — strip it before insert.
        kwargs.pop("is_new", None)
        try:
            new_site = sites_repo.create(self._conn, **kwargs)
        except sqlite3.IntegrityError as e:
            # Most likely the (name, country) pair is already taken
            # by an existing site. Show a clear error.
            QMessageBox.critical(
                self, "Could not create site",
                "A site with that name and country already exists. "
                "Use Edit to change the existing site, or pick a "
                "different name/country.\n\n"
                f"Database error: {e}",
            )
            return
        except ValueError as e:
            # Empty name — the form should have caught this, but
            # be defensive in case validation drifts.
            QMessageBox.warning(self, "Could not create site", str(e))
            return
        # Refresh the model and select the new row.
        self.refresh()
        self._select_site_by_id(new_site.id)
        self.statusBar().showMessage(
            f"Created site '{new_site.name}'", 5000,
        )

    def _select_site_by_id(self, site_id: int) -> None:
        """Find the row with the given site id and select it."""
        for row in range(self._model.rowCount()):
            idx = self._model.index(row, 0)
            if self._model.data(idx, Qt.ItemDataRole.UserRole) == site_id:
                self._table.selectRow(row)
                self._table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _on_edit_action(self, *_args) -> None:
        site = self.selected_site()
        if site is not None:
            self._do_edit(site)

    def _on_delete_action(self, *_args) -> None:
        site = self.selected_site()
        if site is not None:
            self._do_delete(site)

    def _do_edit(self, site: sites_repo.Site) -> None:
        from open_dive_log.ui.site_add_edit_dialog import (
            SiteAddEditDialog, SubmittedSite,
        )
        dlg = SiteAddEditDialog(
            self._conn, site=site, parent=self,
            unit_system=self._model.unit_system(),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sub: SubmittedSite = dlg.submitted()
        assert sub is not None
        try:
            sites_repo.update(
                self._conn, site.id,
                name=sub.name,
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
                f"Could not save the site — likely a duplicate "
                f"(name, country) combination with an existing site.\n\n{e}",
            )
            return
        except LookupError as e:
            QMessageBox.warning(self, "Site missing", str(e))
            return
        self.refresh()
        # Re-select the same row so the user can see their edit
        self._reselect_by_id(site.id)
        self.statusBar().showMessage(f"Updated site #{site.id}: {sub.name}", 5000)

    def _do_delete(self, site: sites_repo.Site) -> None:
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
            sites_repo.delete(self._conn, site.id)
        except sqlite3.IntegrityError:
            blockers = sites_repo.list_blocking_dives(self._conn, site.id)
            lines = "\n".join(f"  • #{d_id} ({d_date})" for d_id, d_date in blockers)
            extra = "" if len(blockers) <= 10 else "\n  (… and more)"
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
        self.refresh()
        self.statusBar().showMessage(f"Deleted site #{site.id}: {site.name}", 5000)

    def _reselect_by_id(self, site_id: int) -> None:
        """After refresh, re-select the row whose site id matches.
        The row order may have changed (if the user edited the name
        and the sort is by name), so look it up in the model."""
        for i in range(self._model.rowCount()):
            if self._model._rows[i].id == site_id:
                idx = self._model.index(i, 0)
                self._table.setCurrentIndex(idx)
                return

