"""Read-only dive detail dialog (QDialog).

Shows every field for one dive, plus the joined site names, the joined
buddies, and the joined lookup values. Built with QFormLayout + grouped
sections so it scales as we add more fields.

This is read-only by design for this phase. Edit support is the next
phase — the plan is to keep the same layout and turn each QLabel into
a QLineEdit / QComboBox without restructuring.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories import dives
from open_dive_log.units import UnitSystem, display_distance, display_pressure, display_temp


# ---------------------------------------------------------------------------
# Pure-Python row assembly — testable without Qt
# ---------------------------------------------------------------------------
def assemble_dive_detail(conn: sqlite3.Connection, dive_id: int) -> dict[str, Any] | None:
    """Pull every field for one dive and its joins.

    Returns a flat dict so the QFormLayout binding is one line per row.
    Returns None if the dive id doesn't exist.
    """
    row = conn.execute(
        """
        SELECT
            d.id, d.dive_date, d.start_time, d.end_time, d.dive_time_minutes,
            d.run_time_minutes,
            d.entry_notes, d.surface_conditions_notes, d.notes,
            d.max_depth_m, d.avg_depth_m,
            d.air_temp_c, d.water_temp_c, d.visibility_m,
            d.start_pressure_bar, d.end_pressure_bar,
            d.o2_percentage, d.mix_notes, d.gear_notes,
            d.created_at, d.updated_at,
            tod.name        AS time_of_day,
            et.name         AS entry_type,
            sc.name         AS surface_conditions,
            etype.name      AS equipment_type,
            tt.name         AS tank_type,
            tcfg.name       AS tank_configuration,
            gt.name         AS gas_type,
            p.name          AS purpose
        FROM dive d
        LEFT JOIN lookup_time_of_day         tod  ON tod.id  = d.time_of_day_id
        LEFT JOIN lookup_entry_type          et   ON et.id   = d.entry_type_id
        LEFT JOIN lookup_surface_conditions  sc   ON sc.id   = d.surface_conditions_id
        LEFT JOIN lookup_equipment_type      etype ON etype.id = d.equipment_type_id
        LEFT JOIN lookup_tank_type           tt   ON tt.id   = d.tank_type_id
        LEFT JOIN lookup_tank_configuration  tcfg ON tcfg.id = d.tank_configuration_id
        LEFT JOIN lookup_gas_type            gt   ON gt.id   = d.gas_type_id
        LEFT JOIN lookup_purpose             p    ON p.id    = d.purpose_id
        WHERE d.id = ?
        """,
        (dive_id,),
    ).fetchone()
    if row is None:
        return None

    site_list = dives.get_sites(conn, dive_id)
    buddy_list = dives.get_buddies(conn, dive_id)

    return {
        # identity
        "id": row["id"],
        # when
        "Date": row["dive_date"],
        "Start time": row["start_time"],
        "End time": row["end_time"],
        "Duration (min)": row["dive_time_minutes"],
        "Time of day": row["time_of_day"],
        # entry
        "Entry type": row["entry_type"],
        "Entry notes": row["entry_notes"],
        # surface
        "Surface conditions": row["surface_conditions"],
        "Surface notes": row["surface_conditions_notes"],
        "Surface run time (min)": row["run_time_minutes"],
        # depth (meters in DB — formatted by caller based on unit toggle)
        "Max depth (m)": row["max_depth_m"],
        "Avg depth (m)": row["avg_depth_m"],
        # conditions (metric in DB — formatted by caller)
        "Air temp (C)": row["air_temp_c"],
        "Water temp (C)": row["water_temp_c"],
        "Visibility (m)": row["visibility_m"],
        # tank pressure (metric in DB — formatted by caller)
        "Start pressure (bar)": row["start_pressure_bar"],
        "End pressure (bar)": row["end_pressure_bar"],
        # gas
        "Equipment": row["equipment_type"],
        "Tank type": row["tank_type"],
        "Tank configuration": row["tank_configuration"],
        "Gas type": row["gas_type"],
        "O2 percentage": row["o2_percentage"],
        "Mix notes": row["mix_notes"],
        "Gear notes": row["gear_notes"],
        # people / place
        "Purpose": row["purpose"],
        "Sites": ", ".join(s.name for s in site_list) or "(none)",
        "Buddies": ", ".join(f"{b.full_name}" for b in buddy_list) or "(none)",
        # free text
        "Notes": row["notes"],
        # bookkeeping
        "Created": row["created_at"],
        "Updated": row["updated_at"],
    }


def _fmt(value: Any) -> str:
    """Render a field value for display. None -> '—', floats -> '23.0 m', etc."""
    if value is None:
        return "—"
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value)}"
        return f"{value:.1f}"
    return str(value)


def _fmt_temp(c: float | None, system: UnitSystem) -> str:
    """Format a stored °C temperature for the user's chosen unit system."""
    val, unit = display_temp(c, system)
    if val is None:
        return "—"
    if isinstance(val, float) and val == int(val):
        return f"{int(val)} {unit}"
    return f"{val:.1f} {unit}"


def _fmt_pressure(bar: float | None, system: UnitSystem) -> str:
    val, unit = display_pressure(bar, system)
    if val is None:
        return "—"
    if isinstance(val, float) and val == int(val):
        return f"{int(val)} {unit}"
    return f"{val:.1f} {unit}"


def _fmt_distance(m: float | None, system: UnitSystem) -> str:
    val, unit = display_distance(m, system)
    if val is None:
        return "—"
    if isinstance(val, float) and val == int(val):
        return f"{int(val)} {unit}"
    return f"{val:.1f} {unit}"


# ---------------------------------------------------------------------------
# Qt widget
# ---------------------------------------------------------------------------
class DiveDetailDialog(QDialog):
    """Modal dialog showing every field for one dive, read-only."""

    def __init__(self, conn: sqlite3.Connection, dive_id: int, parent=None, unit_system: UnitSystem = UnitSystem.METRIC) -> None:
        super().__init__(parent)
        self._conn = conn
        self._dive_id = dive_id
        self._units = unit_system

        data = assemble_dive_detail(conn, dive_id)
        if data is None:
            self.setWindowTitle(f"Dive #{dive_id} (not found)")
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(f"No dive with id {dive_id}."))
            return

        self.setWindowTitle(f"Dive #{dive_id} — {data['Date']}")
        self.resize(560, 720)

        # Scroll area so a long detail doesn't get clipped on small screens.
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)

        body = QWidget()
        scroll.setWidget(body)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)

        body_layout.addWidget(self._build_section("When", [
            "Date", "Start time", "End time", "Duration (min)", "Time of day",
        ], data))
        body_layout.addWidget(self._build_section("Entry & surface", [
            "Entry type", "Entry notes",
            "Surface conditions", "Surface notes", "Surface run time (min)",
        ], data))
        body_layout.addWidget(self._build_section("Depth", [
            "Max depth (m)", "Avg depth (m)",
        ], data))
        body_layout.addWidget(self._build_section("Conditions", [
            "Air temp (C)", "Water temp (C)", "Visibility (m)",
        ], data))
        body_layout.addWidget(self._build_section("Tank pressure", [
            "Start pressure (bar)", "End pressure (bar)",
        ], data))
        body_layout.addWidget(self._build_section("Equipment & gas", [
            "Equipment", "Tank type", "Tank configuration", "Gas type",
            "O2 percentage", "Mix notes", "Gear notes",
        ], data))
        body_layout.addWidget(self._build_section("People & place", [
            "Purpose", "Sites", "Buddies",
        ], data))
        body_layout.addWidget(self._build_section("Notes", ["Notes"], data))
        body_layout.addWidget(self._build_section("Bookkeeping", [
            "Created", "Updated",
        ], data, small=True))

        body_layout.addStretch(1)

        # Standard OK button (closes the dialog).
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, parent=self)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    def _build_section(
        self,
        title: str,
        keys: list[str],
        data: dict[str, Any],
        *,
        small: bool = False,
    ) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        heading = QLabel(title)
        font = heading.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        heading.setFont(font)
        v.addWidget(heading)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        v.addWidget(line)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(4)
        for key in keys:
            label = QLabel(_label_for(key) + ":")
            # Use unit-aware formatter for temp/distance keys
            value_text = _format_key(key, data, self._units)
            value = QLabel(value_text)
            if small:
                vlabel_font = value.font()
                vlabel_font.setPointSize(max(vlabel_font.pointSize() - 1, 7))
                value.setFont(vlabel_font)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, value)
        v.addLayout(form)
        return container


def _format_key(key: str, data: dict[str, Any], units: UnitSystem) -> str:
    """Format a detail dialog field value, applying unit conversion for
    depth / temp / visibility keys."""
    if key == "Max depth (m)":
        return _fmt_distance(data.get("Max depth (m)"), units)
    if key == "Avg depth (m)":
        return _fmt_distance(data.get("Avg depth (m)"), units)
    if key == "Air temp (C)":
        return _fmt_temp(data.get("Air temp (C)"), units)
    if key == "Water temp (C)":
        return _fmt_temp(data.get("Water temp (C)"), units)
    if key == "Visibility (m)":
        return _fmt_distance(data.get("Visibility (m)"), units)
    if key == "Start pressure (bar)":
        return _fmt_pressure(data.get("Start pressure (bar)"), units)
    if key == "End pressure (bar)":
        return _fmt_pressure(data.get("End pressure (bar)"), units)
    return _fmt(data.get(key))


def _label_for(key: str) -> str:
    """Trim a 'Max depth (m)' style key for the form label."""
    return key.split(" (")[0]
