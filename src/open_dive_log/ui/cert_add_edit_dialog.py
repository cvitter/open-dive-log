"""Add/Edit certification dialog.

Modal QDialog with a QFormLayout. Used for both create and update:
the same widget opens with a `cert=None` argument for create, and with
an existing Certification for update. The dialog exposes a `result()`
property that returns either:
    - None if the user cancelled
    - a `SubmittedCert` dataclass with the form's values

The main window is responsible for calling `certifications.create()`
or `certifications.update()` based on the result and the original cert.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from open_dive_log.repositories import certifications, lookups


@dataclass(frozen=True, slots=True)
class SubmittedCert:
    """What the dialog hands back to the caller when the user clicks Save."""
    cert_date: str
    cert_name: str
    cert_number: str
    certifying_agency_id: int
    certifying_facility: str | None
    instructor: str | None
    notes: str | None


class CertAddEditDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        cert: certifications.Certification | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._original = cert
        self.setWindowTitle("Edit Certification" if cert else "Add Certification")
        self.setModal(True)
        self.resize(480, 360)

        # Load agency options up front so the combo is populated before show.
        self._agencies = lookups.list_active(conn, "lookup_certifying_agency")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)

        # Date — QDateEdit with a calendar popup.
        self._date = QDateEdit(self)
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        initial_date = cert.cert_date if cert else certifications.today_iso()
        self._date.setDate(QDate.fromString(initial_date, "yyyy-MM-dd"))
        form.addRow("Date:", self._date)

        # Certification name
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("e.g. Advanced Open Water Diver")
        if cert:
            self._name.setText(cert.cert_name)
        form.addRow("Certification name:", self._name)

        # Cert number
        self._number = QLineEdit(self)
        self._number.setPlaceholderText("Agency-issued number")
        if cert:
            self._number.setText(cert.cert_number)
        form.addRow("Certification number:", self._number)

        # Agency (combobox — no "other" needed since the lookup is extensible)
        self._agency = QComboBox(self)
        for a in self._agencies:
            self._agency.addItem(a.name, userData=a.id)
        if cert:
            idx = self._agency.findData(cert.certifying_agency_id)
            if idx >= 0:
                self._agency.setCurrentIndex(idx)
        elif self._agencies:
            # Default to PADI (id of the first item) for new certs.
            self._agency.setCurrentIndex(0)
        form.addRow("Certifying agency:", self._agency)

        # Facility — free text
        self._facility = QLineEdit(self)
        self._facility.setPlaceholderText("Dive shop / training center")
        if cert and cert.certifying_facility:
            self._facility.setText(cert.certifying_facility)
        form.addRow("Certifying facility:", self._facility)

        # Instructor — free text
        self._instructor = QLineEdit(self)
        self._instructor.setPlaceholderText("Instructor's full name")
        if cert and cert.instructor:
            self._instructor.setText(cert.instructor)
        form.addRow("Instructor:", self._instructor)

        # Notes
        self._notes = QPlainTextEdit(self)
        self._notes.setPlaceholderText("Anything worth remembering about this cert")
        self._notes.setFixedHeight(60)
        if cert and cert.notes:
            self._notes.setPlainText(cert.notes)
        form.addRow("Notes:", self._notes)

        layout.addLayout(form)

        # OK / Cancel buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        name = self._name.text().strip()
        number = self._number.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Certification name is required.")
            return
        if not number:
            QMessageBox.warning(self, "Missing number", "Certification number is required.")
            return
        if self._agency.currentIndex() < 0 or self._agency.currentData() is None:
            QMessageBox.warning(self, "Missing agency", "Pick a certifying agency.")
            return

        self._result = SubmittedCert(
            cert_date=self._date.date().toString("yyyy-MM-dd"),
            cert_name=name,
            cert_number=number,
            certifying_agency_id=int(self._agency.currentData()),
            certifying_facility=self._facility.text().strip() or None,
            instructor=self._instructor.text().strip() or None,
            notes=self._notes.toPlainText().strip() or None,
        )
        self.accept()

    def result_cert(self) -> SubmittedCert | None:
        """Return the submitted form data, or None if cancelled."""
        return getattr(self, "_result", None)
