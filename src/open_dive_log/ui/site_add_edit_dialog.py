"""Add/Edit dialog for sites.

Mirrors the dive add/edit dialog's flow:
  * Pre-loads lookup values (country, environment, entry).
  * Build form sections (Identity, Location, Conditions, Notes).
  * Save → returns the site id (or None if cancelled).
  * Edit mode: pre-populate from an existing Site.

This dialog is independent of `find_or_create`'s dedup behavior on
purpose — when the user clicks "New" we want them to see what they're
creating, and when they click "Edit" we want the change to be exactly
what they typed, not silently merged with an existing site.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories import lookups, sites as sites_repo
from open_dive_log.units import UnitSystem, ft_to_m, m_to_ft


@dataclass(frozen=True, slots=True)
class SubmittedSite:
    """What the form returns to the caller.

    `is_new` tells the caller whether this was a creation or an
    update, so the caller can decide whether to call find_or_create
    (new) or sites_repo.update (edit).
    """
    is_new: bool
    name: str
    region: str | None
    country: str | None
    country_code: str | None
    latitude: float | None
    longitude: float | None
    environment_id: int | None
    entry_id: int | None
    max_depth_m: float | None
    description: str | None
    description_wildlife: str | None
    notes: str | None


class SiteAddEditDialog(QDialog):
    """Modal dialog for creating or editing a Site row.

    Parameters
    ----------
    conn : sqlite3.Connection
        Live connection to the dive log database.
    site : sites_repo.Site | None
        The site to edit. Pass None to create a new site.
    parent : QWidget | None
        Optional parent for modality.
    unit_system : UnitSystem
        Which unit system to display distances in. The max-depth
        spinbox's suffix and range follow the system; the form
        converts back to meters at save time.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        site: sites_repo.Site | None = None,
        parent: QWidget | None = None,
        unit_system: UnitSystem = UnitSystem.METRIC,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._site = site
        self._submitted: SubmittedSite | None = None
        self._units: UnitSystem = unit_system

        self.setWindowTitle("Edit Site" if site else "New Site")
        self.setModal(True)
        self.resize(560, 720)

        # Pre-load lookup values for the comboboxes
        self._environments = lookups.list_active(conn, "lookup_site_environment")
        self._entry_types = lookups.list_active(conn, "lookup_entry_type")
        # Country list — small, just (code, name) ordered by name
        country_rows = conn.execute(
            "SELECT code, name FROM country ORDER BY name ASC"
        ).fetchall()
        self._countries = [(r["code"], r["name"]) for r in country_rows]

        # --- Form sections ------------------------------------------------
        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())

        # ---- Identity ----------------------------------------------------
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. Salt Pier")
        if site:
            self._name.setText(site.name)
        form.addRow("Name *:", self._name)

        self._country_code = QComboBox()
        self._country_code.addItem("(none)", None)
        for code, name in self._countries:
            label = f"{code} — {name}" if name else code
            self._country_code.addItem(label, code)
        if site and site.country_code:
            self._set_combo_data(self._country_code, site.country_code)
        elif site and site.country:
            # Allow free-text country — show a hint and add it as a pseudo-row
            # so the user sees what's there. We don't auto-create the country
            # record here because we don't have an ISO code; the save path
            # just stores the free-text value in site.country.
            pass
        form.addRow("Country (ISO):", self._country_code)

        self._country = QLineEdit()
        self._country.setPlaceholderText("Free-text (legacy sites without an ISO code)")
        if site and site.country:
            self._country.setText(site.country)
        form.addRow("Country (text):", self._country)

        self._region = QLineEdit()
        self._region.setPlaceholderText("e.g. Southern Caribbean")
        if site and site.region:
            self._region.setText(site.region)
        form.addRow("Region:", self._region)

        # ---- Location ----------------------------------------------------
        lat = QDoubleSpinBox()
        lat.setRange(-90.0, 90.0)
        lat.setDecimals(6)
        lat.setSuffix(" °")
        if site and site.latitude is not None:
            lat.setValue(site.latitude)
        self._latitude = lat
        form.addRow("Latitude:", self._latitude)

        lon = QDoubleSpinBox()
        lon.setRange(-180.0, 180.0)
        lon.setDecimals(6)
        lon.setSuffix(" °")
        if site and site.longitude is not None:
            lon.setValue(site.longitude)
        self._longitude = lon
        form.addRow("Longitude:", self._longitude)

        # ---- Conditions --------------------------------------------------
        self._environment = self._make_lookup_combo(
            self._environments,
            site.environment_id if site else None,
        )
        form.addRow("Environment:", self._environment)

        self._entry = self._make_lookup_combo(
            self._entry_types,
            site.entry_id if site else None,
        )
        form.addRow("Entry:", self._entry)

        depth = QDoubleSpinBox()
        if self._units == UnitSystem.IMPERIAL:
            # Up to ~700 ft covers any recreational dive site
            depth.setRange(0.0, 700.0)
            depth.setSuffix(" ft")
        else:
            # Up to 200 m covers any recreational dive site. The DB
            # has no CHECK on site.max_depth_m, but 200 m is a sane
            # upper bound.
            depth.setRange(0.0, 200.0)
            depth.setSuffix(" m")
        depth.setDecimals(1)
        if site and site.max_depth_m is not None:
            # Convert DB meters to the displayed unit
            display = m_to_ft(site.max_depth_m) if self._units == UnitSystem.IMPERIAL else site.max_depth_m
            depth.setValue(display)
        self._max_depth = depth
        form.addRow("Max depth:", self._max_depth)

        # ---- Notes -------------------------------------------------------
        self._description = QPlainTextEdit()
        self._description.setPlaceholderText("What the site is like, conditions, hazards…")
        self._description.setMaximumHeight(80)
        if site and site.description:
            self._description.setPlainText(site.description)
        form.addRow("Description:", self._description)

        self._description_wildlife = QPlainTextEdit()
        self._description_wildlife.setPlaceholderText("Marine life typically seen here…")
        self._description_wildlife.setMaximumHeight(80)
        if site and site.description_wildlife:
            self._description_wildlife.setPlainText(site.description_wildlife)
        form.addRow("Wildlife:", self._description_wildlife)

        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText("Anything else (personal notes, parking, contact…)")
        self._notes.setMaximumHeight(80)
        if site and site.notes:
            self._notes.setPlainText(site.notes)
        form.addRow("Notes:", self._notes)

        outer.addLayout(form)

        # --- Required field hint -----------------------------------------
        hint = QLabel("* required")
        hint.setStyleSheet("color: gray;")
        outer.addWidget(hint)

        # --- Buttons ------------------------------------------------------
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    # ------------------------------------------------------------------ API
    def submitted(self) -> SubmittedSite | None:
        """Return the assembled form data, or None if the user cancelled."""
        return self._submitted

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _make_lookup_combo(
        values: list[lookups.LookupValue],
        current_id: int | None,
    ) -> QComboBox:
        combo = QComboBox()
        combo.addItem("(none)", None)
        for v in values:
            combo.addItem(v.name, v.id)
        if current_id is not None:
            SiteAddEditDialog._set_combo_data(combo, current_id)
        return combo

    @staticmethod
    def _set_combo_data(combo: QComboBox, target: int | str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == target:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _combo_id(combo: QComboBox) -> int | None:
        return combo.currentData()

    @staticmethod
    def _clean(text: str) -> str | None:
        text = text.strip()
        return text or None

    def _read_max_depth_m(self) -> float | None:
        """Read the max-depth spinbox, returning meters regardless of
        the current display unit. Returns None if the value is 0
        (treats 0 as 'unspecified', matching the rest of the form)."""
        raw = self._max_depth.value()
        if not raw:
            return None
        if self._units == UnitSystem.IMPERIAL:
            return ft_to_m(raw)
        return raw

    # --------------------------------------------------------- save handler
    def _on_save(self) -> None:
        name = self._clean(self._name.text())
        if not name:
            QMessageBox.warning(
                self, "Name required",
                "A site must have a name.",
            )
            return

        country_code = self._combo_id(self._country_code)
        country = self._clean(self._country.text())
        if not country_code and not country:
            QMessageBox.warning(
                self, "Country required",
                "Pick a country (ISO code) or enter the country name as text.",
            )
            return

        # If the user picked a code but left the free-text blank, fill
        # it in from the country table so the display name is consistent.
        if country_code and not country:
            for code, cname in self._countries:
                if code == country_code:
                    country = cname
                    break

        self._submitted = SubmittedSite(
            is_new=self._site is None,
            name=name,
            region=self._clean(self._region.text()),
            country=country,
            country_code=country_code,
            latitude=self._latitude.value() or None,
            longitude=self._longitude.value() or None,
            environment_id=self._combo_id(self._environment),
            entry_id=self._combo_id(self._entry),
            # The spinbox displays in the current unit system; convert
            # back to meters (the canonical DB unit) on save.
            max_depth_m=self._read_max_depth_m(),
            description=self._clean(self._description.toPlainText()),
            description_wildlife=self._clean(self._description_wildlife.toPlainText()),
            notes=self._clean(self._notes.toPlainText()),
        )
        self.accept()
