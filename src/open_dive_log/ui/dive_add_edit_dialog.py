"""Add / Edit dive dialog.

A single scrollable QFormLayout holding all 22 user-input fields on a
dive, plus an inline section for picking sites (with order) and
buddies (with roles). Used for both create and update; the dialog
exposes `to_kwargs()` and `selected_sites` / `selected_buddies`
attributes that the caller passes to `dives.create()` /
`dives.update()` / `dives.attach_sites()` / `dives.attach_buddies()`.

The dialog is intentionally long — 30+ fields is what diving logbooks
actually look like — but grouped by section header labels in the form
so the user can scan it quickly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories import (
    buddies,
    dives,
    lookups,
    sites as sites_repo,
)


# Tables that need to be loaded into comboboxes. (id, name) ordering
# matches the lookup table's display_order column.
_LOOKUP_TABLES_FOR_FORM: tuple[str, ...] = (
    "lookup_time_of_day",
    "lookup_entry_type",
    "lookup_surface_conditions",
    "lookup_equipment_type",
    "lookup_tank_type",
    "lookup_tank_configuration",
    "lookup_gas_type",
    "lookup_purpose",
    "lookup_buddy_role",
)


@dataclass(frozen=True, slots=True)
class SubmittedDive:
    """Form result. The dialog hands this back on Save; the main window
    calls `dives.create(**to_kwargs())` or `dives.update(dive_id, **to_kwargs())`,
    then `dives.attach_sites(...)` and `dives.attach_buddies(...)`.

    `slots=True` means no __dict__; use `to_kwargs()` for the splat.
    """
    # when
    dive_date: str
    start_time: str | None
    end_time: str | None
    dive_time_minutes: int | None
    time_of_day_id: int | None
    # entry
    entry_type_id: int | None
    entry_notes: str | None
    # surface
    surface_conditions_id: int | None
    surface_conditions_notes: str | None
    run_time_minutes: int | None
    # depth
    max_depth_m: float | None
    avg_depth_m: float | None
    # equipment
    equipment_type_id: int | None
    tank_type_id: int | None
    tank_configuration_id: int | None
    gas_type_id: int | None
    o2_percentage: float | None
    mix_notes: str | None
    gear_notes: str | None
    # purpose
    purpose_id: int | None
    notes: str | None
    # sites (in order) and buddies (with role)
    site_ids: list[int] = field(default_factory=list)
    buddy_entries: list[tuple[int, int | None]] = field(default_factory=list)

    def to_kwargs(self) -> dict:
        return {
            "dive_date": self.dive_date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "dive_time_minutes": self.dive_time_minutes,
            "time_of_day_id": self.time_of_day_id,
            "entry_type_id": self.entry_type_id,
            "entry_notes": self.entry_notes,
            "surface_conditions_id": self.surface_conditions_id,
            "surface_conditions_notes": self.surface_conditions_notes,
            "run_time_minutes": self.run_time_minutes,
            "max_depth_m": self.max_depth_m,
            "avg_depth_m": self.avg_depth_m,
            "equipment_type_id": self.equipment_type_id,
            "tank_type_id": self.tank_type_id,
            "tank_configuration_id": self.tank_configuration_id,
            "gas_type_id": self.gas_type_id,
            "o2_percentage": self.o2_percentage,
            "mix_notes": self.mix_notes,
            "gear_notes": self.gear_notes,
            "purpose_id": self.purpose_id,
            "notes": self.notes,
        }


class DiveAddEditDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        dive: dives.DiveFull | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._original = dive
        self.setWindowTitle("Edit Dive" if dive else "Add Dive")
        self.setModal(True)
        self.resize(720, 820)

        # Pre-load lookup values for the comboboxes.
        self._lookups: dict[str, list[lookups.LookupValue]] = {
            t: lookups.list_active(conn, t) for t in _LOOKUP_TABLES_FOR_FORM
        }
        # Buddy roles need id->value lookups for the buddies table.
        self._buddy_roles_by_id: dict[int, str] = {
            r.id: r.name for r in self._lookups["lookup_buddy_role"]
        }
        self._buddy_roles_by_name: dict[str, int] = {
            r.name: r.id for r in self._lookups["lookup_buddy_role"]
        }

        # -- Scroll area containing the form --
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)

        body = QWidget()
        scroll.setWidget(body)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)

        body_layout.addWidget(self._build_when_section(dive))
        body_layout.addWidget(self._build_entry_section(dive))
        body_layout.addWidget(self._build_surface_section(dive))
        body_layout.addWidget(self._build_depth_section(dive))
        body_layout.addWidget(self._build_equipment_section(dive))
        body_layout.addWidget(self._build_sites_section(dive))
        body_layout.addWidget(self._build_buddies_section(dive))
        body_layout.addWidget(self._build_notes_section(dive))

        # OK / Cancel buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    # Section builders — each returns a QWidget with a header + form.
    # ------------------------------------------------------------------
    def _build_when_section(self, dive: dives.DiveFull | None) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("When"))
        form = QFormLayout()

        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setDate(
            QDate.fromString(dive.dive_date, "yyyy-MM-dd") if dive
            else QDate.currentDate()
        )
        form.addRow("Date:", self._date)

        self._start_time = QTimeEdit()
        self._start_time.setDisplayFormat("HH:mm")
        if dive and dive.start_time:
            from PySide6.QtCore import QTime
            t = QTime.fromString(dive.start_time, "HH:mm")
            if t.isValid():
                self._start_time.setTime(t)
        form.addRow("Start time (24h):", self._start_time)

        self._end_time = QTimeEdit()
        self._end_time.setDisplayFormat("HH:mm")
        if dive and dive.end_time:
            from PySide6.QtCore import QTime
            t = QTime.fromString(dive.end_time, "HH:mm")
            if t.isValid():
                self._end_time.setTime(t)
        form.addRow("End time (24h):", self._end_time)

        self._duration = QSpinBox()
        self._duration.setRange(0, 999)
        self._duration.setSuffix(" min")
        if dive and dive.dive_time_minutes is not None:
            self._duration.setValue(dive.dive_time_minutes)
        form.addRow("Duration:", self._duration)

        self._time_of_day = self._make_lookup_combo("lookup_time_of_day", dive.time_of_day_id if dive else None)
        form.addRow("Time of day:", self._time_of_day)

        v.addLayout(form)
        return container

    def _build_entry_section(self, dive: dives.DiveFull | None) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Entry"))
        form = QFormLayout()

        self._entry_type = self._make_lookup_combo("lookup_entry_type", dive.entry_type_id if dive else None)
        form.addRow("Entry type:", self._entry_type)

        self._entry_notes = QPlainTextEdit()
        self._entry_notes.setFixedHeight(50)
        if dive and dive.entry_notes:
            self._entry_notes.setPlainText(dive.entry_notes)
        form.addRow("Entry notes:", self._entry_notes)

        v.addLayout(form)
        return container

    def _build_surface_section(self, dive: dives.DiveFull | None) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Surface"))
        form = QFormLayout()

        self._surface_conditions = self._make_lookup_combo("lookup_surface_conditions", dive.surface_conditions_id if dive else None)
        form.addRow("Surface conditions:", self._surface_conditions)

        self._run_time = QSpinBox()
        self._run_time.setRange(0, 9999)
        self._run_time.setSuffix(" min")
        if dive and dive.run_time_minutes is not None:
            self._run_time.setValue(dive.run_time_minutes)
        form.addRow("Surface run time:", self._run_time)

        self._surface_notes = QPlainTextEdit()
        self._surface_notes.setFixedHeight(50)
        if dive and dive.surface_conditions_notes:
            self._surface_notes.setPlainText(dive.surface_conditions_notes)
        form.addRow("Surface notes:", self._surface_notes)

        v.addLayout(form)
        return container

    def _build_depth_section(self, dive: dives.DiveFull | None) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Depth (m)"))
        form = QFormLayout()

        self._max_depth = self._make_depth_spin()
        if dive and dive.max_depth_m is not None:
            self._max_depth.setValue(dive.max_depth_m)
        form.addRow("Max depth:", self._max_depth)

        self._avg_depth = self._make_depth_spin()
        if dive and dive.avg_depth_m is not None:
            self._avg_depth.setValue(dive.avg_depth_m)
        form.addRow("Avg depth:", self._avg_depth)

        v.addLayout(form)
        return container

    def _build_equipment_section(self, dive: dives.DiveFull | None) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Equipment & gas"))
        form = QFormLayout()

        self._equipment_type = self._make_lookup_combo("lookup_equipment_type", dive.equipment_type_id if dive else None)
        form.addRow("Equipment type:", self._equipment_type)

        self._tank_type = self._make_lookup_combo("lookup_tank_type", dive.tank_type_id if dive else None)
        form.addRow("Tank type:", self._tank_type)

        self._tank_config = self._make_lookup_combo("lookup_tank_configuration", dive.tank_configuration_id if dive else None)
        form.addRow("Tank configuration:", self._tank_config)

        self._gas_type = self._make_lookup_combo("lookup_gas_type", dive.gas_type_id if dive else None)
        form.addRow("Gas type:", self._gas_type)

        self._o2 = QDoubleSpinBox()
        self._o2.setRange(0.0, 100.0)
        self._o2.setDecimals(1)
        self._o2.setSuffix(" %")
        if dive and dive.o2_percentage is not None:
            self._o2.setValue(dive.o2_percentage)
        form.addRow("O2 percentage:", self._o2)

        self._mix_notes = QPlainTextEdit()
        self._mix_notes.setFixedHeight(50)
        if dive and dive.mix_notes:
            self._mix_notes.setPlainText(dive.mix_notes)
        form.addRow("Mix notes:", self._mix_notes)

        self._gear_notes = QPlainTextEdit()
        self._gear_notes.setFixedHeight(50)
        if dive and dive.gear_notes:
            self._gear_notes.setPlainText(dive.gear_notes)
        form.addRow("Gear notes:", self._gear_notes)

        v.addLayout(form)
        return container

    def _build_sites_section(self, dive: dives.DiveFull | None) -> QWidget:
        """Sites picker: a listbox with up/down ordering, an 'Add' button
        that opens an add-site dialog, and a 'Create new site inline'
        button that pops a small create form."""
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Sites (in dive order)"))

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: available sites (searchable list)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Available sites:"))
        self._sites_search = QLineEdit()
        self._sites_search.setPlaceholderText("Type to filter…")
        self._sites_search.textChanged.connect(self._refresh_sites_picker)
        ll.addWidget(self._sites_search)
        self._sites_picker = QListWidget()
        self._sites_picker.itemDoubleClicked.connect(self._on_site_add_clicked)
        ll.addWidget(self._sites_picker, 1)
        self._refresh_sites_picker()
        splitter.addWidget(left)

        # Middle: add/remove buttons
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addStretch(1)
        btn_add = QPushButton("→")
        btn_add.setToolTip("Add selected site to dive")
        btn_add.clicked.connect(self._on_site_add_clicked)
        ml.addWidget(btn_add)
        btn_remove = QPushButton("←")
        btn_remove.setToolTip("Remove selected site from dive")
        btn_remove.clicked.connect(self._on_site_remove_clicked)
        ml.addWidget(btn_remove)
        ml.addStretch(1)
        splitter.addWidget(mid)

        # Right: attached sites (ordered)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Attached to this dive:"))
        self._sites_attached = QListWidget()
        rl.addWidget(self._sites_attached, 1)

        reorder_row = QHBoxLayout()
        btn_up = QToolButton(); btn_up.setText("▲")
        btn_up.setToolTip("Move up")
        btn_up.clicked.connect(lambda: self._move_site(-1))
        btn_down = QToolButton(); btn_down.setText("▼")
        btn_down.setToolTip("Move down")
        btn_down.clicked.connect(lambda: self._move_site(1))
        reorder_row.addWidget(btn_up)
        reorder_row.addWidget(btn_down)
        reorder_row.addStretch(1)
        rl.addLayout(reorder_row)
        splitter.addWidget(right)
        splitter.setSizes([250, 40, 200])
        v.addWidget(splitter)

        btn_create = QPushButton("Create new site inline…")
        btn_create.clicked.connect(self._on_site_create_clicked)
        v.addWidget(btn_create)

        # Pre-populate for edit mode.
        if dive is not None:
            for site_id, name in dives.get_sites_ordered(self._conn, dive.id):
                self._add_attached_site(site_id, name)
        return container

    def _build_buddies_section(self, dive: dives.DiveFull | None) -> QWidget:
        """Buddies picker: a listbox with a role combobox per row, an
        'Add' button that opens a small pick dialog, and a 'Create new
        buddy inline' button that prompts for first/last name."""
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Buddies"))

        # Top: search + pick existing
        top_row = QHBoxLayout()
        self._buddies_search = QLineEdit()
        self._buddies_search.setPlaceholderText("Type to filter existing buddies…")
        self._buddies_search.textChanged.connect(self._refresh_buddies_picker)
        top_row.addWidget(self._buddies_search, 1)
        self._buddies_picker = QComboBox()
        self._buddies_picker.setMinimumWidth(220)
        self._refresh_buddies_picker()
        top_row.addWidget(self._buddies_picker)
        btn_add_buddy = QPushButton("Add")
        btn_add_buddy.clicked.connect(self._on_buddy_add_clicked)
        top_row.addWidget(btn_add_buddy)
        v.addLayout(top_row)

        # Bottom: attached buddies with per-row role combobox
        v.addWidget(QLabel("Attached to this dive:"))
        self._buddies_attached = QListWidget()
        self._buddies_attached.setMinimumHeight(110)
        v.addWidget(self._buddies_attached, 1)

        # Per-row widget: full name + role combobox + remove button
        # (Using a QListWidget with custom items would be heavier; we
        # use a QListWidget of formatted strings and a side panel for
        # role editing instead. Simpler and good enough for a list
        # that almost always has <5 entries.)
        controls = QHBoxLayout()
        self._attached_role_combo = QComboBox()
        self._attached_role_combo.addItem("(no role)", userData=None)
        for r in self._lookups["lookup_buddy_role"]:
            self._attached_role_combo.addItem(r.name, userData=r.id)
        controls.addWidget(QLabel("Role for selected:"))
        controls.addWidget(self._attached_role_combo, 1)
        btn_remove_buddy = QPushButton("Remove selected")
        btn_remove_buddy.clicked.connect(self._on_buddy_remove_clicked)
        controls.addWidget(btn_remove_buddy)
        v.addLayout(controls)

        btn_create_buddy = QPushButton("Create new buddy inline…")
        btn_create_buddy.clicked.connect(self._on_buddy_create_clicked)
        v.addWidget(btn_create_buddy)

        # Pre-populate for edit mode.
        if dive is not None:
            for buddy_id, full_name, role_id in dives.get_buddies_with_roles(self._conn, dive.id):
                self._add_attached_buddy(buddy_id, full_name, role_id)
        return container

    def _build_notes_section(self, dive: dives.DiveFull | None) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._header("Purpose & notes"))

        form = QFormLayout()
        self._purpose = self._make_lookup_combo("lookup_purpose", dive.purpose_id if dive else None)
        form.addRow("Purpose:", self._purpose)

        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(80)
        if dive and dive.notes:
            self._notes.setPlainText(dive.notes)
        form.addRow("General notes:", self._notes)
        v.addLayout(form)
        return container

    # ------------------------------------------------------------------
    # Helpers for the form widgets themselves.
    # ------------------------------------------------------------------
    def _header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font(); f.setBold(True); f.setPointSize(f.pointSize() + 1)
        lbl.setFont(f)
        return lbl

    def _make_lookup_combo(self, table: str, current_id: int | None) -> QComboBox:
        c = QComboBox()
        c.addItem("(none)", userData=None)
        for v in self._lookups[table]:
            c.addItem(v.name, userData=v.id)
        if current_id is not None:
            idx = c.findData(current_id)
            if idx >= 0:
                c.setCurrentIndex(idx)
        return c

    def _make_depth_spin(self) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(0.0, 999.0)
        s.setDecimals(1)
        s.setSuffix(" m")
        return s

    # ------------------------------------------------------------------
    # Sites picker: refresh, add, remove, reorder, create inline
    # ------------------------------------------------------------------
    def _refresh_sites_picker(self) -> None:
        query = self._sites_search.text()
        self._sites_picker.clear()
        for site_id, label in dives.list_sites_for_picker(self._conn, query=query, limit=500):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, site_id)
            self._sites_picker.addItem(item)

    def _on_site_add_clicked(self, *_args) -> None:
        item = self._sites_picker.currentItem()
        if item is None:
            return
        site_id = item.data(Qt.ItemDataRole.UserRole)
        # Don't add twice
        for i in range(self._sites_attached.count()):
            if self._sites_attached.item(i).data(Qt.ItemDataRole.UserRole) == site_id:
                return
        self._add_attached_site(site_id, item.text())

    def _on_site_remove_clicked(self) -> None:
        row = self._sites_attached.currentRow()
        if row >= 0:
            self._sites_attached.takeItem(row)

    def _add_attached_site(self, site_id: int, label: str) -> None:
        item = QListWidgetItem(f"{self._sites_attached.count() + 1}. {label}")
        item.setData(Qt.ItemDataRole.UserRole, site_id)
        self._sites_attached.addItem(item)

    def _move_site(self, delta: int) -> None:
        row = self._sites_attached.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if not (0 <= new_row < self._sites_attached.count()):
            return
        item = self._sites_attached.takeItem(row)
        self._sites_attached.insertItem(new_row, item)
        self._sites_attached.setCurrentRow(new_row)
        # Renumber the visible labels
        for i in range(self._sites_attached.count()):
            it = self._sites_attached.item(i)
            label = it.text()
            if ". " in label:
                rest = label.split(". ", 1)[1]
                it.setText(f"{i + 1}. {rest}")

    def _on_site_create_clicked(self) -> None:
        # Small prompt: ask for a name, then create a new site.
        name, ok = QInputDialog.getText(self, "New site", "Site name:")
        if not ok or not name.strip():
            return
        s = sites_repo.find_or_create(self._conn, name.strip())
        self._refresh_sites_picker()
        # Auto-add to attached list
        self._add_attached_site(s.id, s.name)

    # ------------------------------------------------------------------
    # Buddies picker: refresh, add, remove, create inline
    # ------------------------------------------------------------------
    def _refresh_buddies_picker(self) -> None:
        query = self._buddies_search.text()
        self._buddies_picker.clear()
        for buddy_id, full_name in dives.list_buddies_for_picker(self._conn, query=query, limit=500):
            self._buddies_picker.addItem(full_name, userData=buddy_id)

    def _on_buddy_add_clicked(self) -> None:
        buddy_id = self._buddies_picker.currentData()
        if buddy_id is None:
            return
        full_name = self._buddies_picker.currentText()
        # Don't add twice
        for i in range(self._buddies_attached.count()):
            if self._buddies_attached.item(i).data(Qt.ItemDataRole.UserRole) == buddy_id:
                return
        # Default role to "Dive Buddy" if it exists
        default_role = self._buddy_roles_by_name.get("Dive Buddy") or self._buddy_roles_by_name.get("Dive buddy") or self._buddy_roles_by_name.get("buddy")
        self._add_attached_buddy(buddy_id, full_name, default_role)

    def _on_buddy_remove_clicked(self) -> None:
        row = self._buddies_attached.currentRow()
        if row >= 0:
            self._buddies_attached.takeItem(row)

    def _add_attached_buddy(self, buddy_id: int, full_name: str, role_id: int | None) -> None:
        role_name = self._buddy_roles_by_id.get(role_id, "(no role)") if role_id else "(no role)"
        item = QListWidgetItem(f"{full_name}  —  {role_name}")
        item.setData(Qt.ItemDataRole.UserRole, buddy_id)
        item.setData(Qt.ItemDataRole.UserRole + 1, role_id)
        self._buddies_attached.addItem(item)
        # Auto-select the new row so the role combobox applies
        self._buddies_attached.setCurrentRow(self._buddies_attached.count() - 1)
        if role_id is not None:
            idx = self._attached_role_combo.findData(role_id)
            if idx >= 0:
                self._attached_role_combo.setCurrentIndex(idx)
        # Wire role combo to update the currently selected row's role
        # (signal connected once via first add — see __init__)
        if not self._role_combo_wired:
            self._attached_role_combo.currentIndexChanged.connect(self._on_role_changed)
            self._role_combo_wired = True

    _role_combo_wired: bool = False  # class-level flag set on instance

    def _on_role_changed(self, _index: int) -> None:
        row = self._buddies_attached.currentRow()
        if row < 0:
            return
        item = self._buddies_attached.item(row)
        if item is None:
            return
        role_id = self._attached_role_combo.currentData()
        # Recover the full_name from the existing text "Full Name — Role"
        text = item.text()
        full_name = text.split("  —  ")[0] if "  —  " in text else text
        role_name = self._buddy_roles_by_id.get(role_id, "(no role)") if role_id else "(no role)"
        item.setText(f"{full_name}  —  {role_name}")
        item.setData(Qt.ItemDataRole.UserRole + 1, role_id)

    def _on_buddy_create_clicked(self) -> None:
        first, ok = QInputDialog.getText(self, "New buddy", "First name:")
        if not ok or not first.strip():
            return
        last, ok = QInputDialog.getText(self, "New buddy", "Last name:")
        if not ok or not last.strip():
            return
        b = buddies.find_or_create(self._conn, first.strip(), last.strip())
        self._refresh_buddies_picker()
        # Auto-add to attached list with default role
        default_role = self._buddy_roles_by_name.get("Dive Buddy") or self._buddy_roles_by_name.get("Dive buddy")
        self._add_attached_buddy(b.id, b.full_name, default_role)

    # ------------------------------------------------------------------
    # Save: build a SubmittedDive from the form state.
    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        # date / time fields
        dive_date = self._date.date().toString("yyyy-MM-dd")
        start = self._start_time.time().toString("HH:mm")
        end = self._end_time.time().toString("HH:mm")
        # QTimeEdit default 00:00 — treat as "not entered" so we don't
        # write 00:00 to a nullable column.
        start_time = start if (start and start != "00:00") else None
        end_time = end if (end and end != "00:00") else None
        duration = self._duration.value() or None
        # Lookup combos: only set the FK if the user picked a real value
        def _lookup_id(combo: QComboBox) -> int | None:
            return combo.currentData()

        # Optional integer / float fields: treat 0 as "not entered" for
        # spinboxes that allow it. (Depth 0 is technically valid, but
        # unlikely; if you want 0 stored, you can set it later.)
        max_depth = self._max_depth.value() or None
        avg_depth = self._avg_depth.value() or None
        run_time = self._run_time.value() or None
        o2 = self._o2.value() or None

        # Sites (in order)
        site_ids: list[int] = []
        for i in range(self._sites_attached.count()):
            site_ids.append(self._sites_attached.item(i).data(Qt.ItemDataRole.UserRole))

        # Buddies (with role)
        buddy_entries: list[tuple[int, int | None]] = []
        for i in range(self._buddies_attached.count()):
            it = self._buddies_attached.item(i)
            bid = it.data(Qt.ItemDataRole.UserRole)
            rid = it.data(Qt.ItemDataRole.UserRole + 1)
            buddy_entries.append((bid, rid))

        result = SubmittedDive(
            dive_date=dive_date,
            start_time=start_time,
            end_time=end_time,
            dive_time_minutes=duration,
            time_of_day_id=_lookup_id(self._time_of_day),
            entry_type_id=_lookup_id(self._entry_type),
            entry_notes=self._entry_notes.toPlainText().strip() or None,
            surface_conditions_id=_lookup_id(self._surface_conditions),
            surface_conditions_notes=self._surface_notes.toPlainText().strip() or None,
            run_time_minutes=run_time,
            max_depth_m=max_depth,
            avg_depth_m=avg_depth,
            equipment_type_id=_lookup_id(self._equipment_type),
            tank_type_id=_lookup_id(self._tank_type),
            tank_configuration_id=_lookup_id(self._tank_config),
            gas_type_id=_lookup_id(self._gas_type),
            o2_percentage=o2,
            mix_notes=self._mix_notes.toPlainText().strip() or None,
            gear_notes=self._gear_notes.toPlainText().strip() or None,
            purpose_id=_lookup_id(self._purpose),
            notes=self._notes.toPlainText().strip() or None,
            site_ids=site_ids,
            buddy_entries=buddy_entries,
        )
        self._result = result
        self.accept()

    def result_dive(self) -> SubmittedDive | None:
        return getattr(self, "_result", None)
