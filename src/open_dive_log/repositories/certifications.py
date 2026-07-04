"""Repository for the `certification` table.

A cert is about the diver, not a specific dive, so it has no FK to
`dive`. The agency is a FK to `lookup_certifying_agency`; facility and
instructor are free text (per design decision in this phase).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Certification:
    id: int
    cert_date: str                       # ISO-8601 YYYY-MM-DD
    cert_name: str
    cert_number: str
    certifying_agency_id: int
    certifying_agency_name: str         # joined for display
    certifying_facility: str | None
    instructor: str | None
    notes: str | None
    created_at: str
    updated_at: str


_SELECT = """
    SELECT
        c.id, c.cert_date, c.cert_name, c.cert_number,
        c.certifying_agency_id, la.name AS certifying_agency_name,
        c.certifying_facility, c.instructor, c.notes,
        c.created_at, c.updated_at
    FROM certification c
    LEFT JOIN lookup_certifying_agency la ON la.id = c.certifying_agency_id
"""


def create(
    conn: sqlite3.Connection,
    *,
    cert_date: str,
    cert_name: str,
    cert_number: str,
    certifying_agency_id: int,
    certifying_facility: str | None = None,
    instructor: str | None = None,
    notes: str | None = None,
) -> int:
    """Insert a new certification and return its row id."""
    cur = conn.execute(
        """
        INSERT INTO certification
            (cert_date, cert_name, cert_number,
             certifying_agency_id, certifying_facility, instructor, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cert_date,
            cert_name.strip(),
            cert_number.strip(),
            certifying_agency_id,
            _clean(certifying_facility),
            _clean(instructor),
            _clean(notes),
        ),
    )
    return cur.lastrowid


def update(
    conn: sqlite3.Connection,
    cert_id: int,
    *,
    cert_date: str,
    cert_name: str,
    cert_number: str,
    certifying_agency_id: int,
    certifying_facility: str | None = None,
    instructor: str | None = None,
    notes: str | None = None,
) -> None:
    """Update an existing certification. Raises if id not found."""
    cur = conn.execute(
        """
        UPDATE certification
           SET cert_date = ?, cert_name = ?, cert_number = ?,
               certifying_agency_id = ?,
               certifying_facility = ?, instructor = ?, notes = ?
         WHERE id = ?
        """,
        (
            cert_date,
            cert_name.strip(),
            cert_number.strip(),
            certifying_agency_id,
            _clean(certifying_facility),
            _clean(instructor),
            _clean(notes),
            cert_id,
        ),
    )
    if cur.rowcount == 0:
        raise LookupError(f"No certification with id {cert_id}")


def delete(conn: sqlite3.Connection, cert_id: int) -> None:
    cur = conn.execute("DELETE FROM certification WHERE id = ?", (cert_id,))
    if cur.rowcount == 0:
        raise LookupError(f"No certification with id {cert_id}")


def get(conn: sqlite3.Connection, cert_id: int) -> Certification | None:
    row = conn.execute(_SELECT + " WHERE c.id = ?", (cert_id,)).fetchone()
    return _row_to_cert(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[Certification]:
    """All certs, newest first (by cert_date DESC, then id DESC for ties)."""
    rows = conn.execute(
        _SELECT + " ORDER BY c.cert_date DESC, c.id DESC"
    ).fetchall()
    return [_row_to_cert(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_cert(row: sqlite3.Row) -> Certification:
    return Certification(
        id=row["id"],
        cert_date=row["cert_date"],
        cert_name=row["cert_name"],
        cert_number=row["cert_number"],
        certifying_agency_id=row["certifying_agency_id"],
        certifying_agency_name=row["certifying_agency_name"] or "",
        certifying_facility=row["certifying_facility"],
        instructor=row["instructor"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _clean(value: str | None) -> str | None:
    """Strip whitespace; treat empty string as None so columns stay NULL."""
    if value is None:
        return None
    v = value.strip()
    return v or None


def today_iso() -> str:
    """Convenience for defaulting the cert_date field in the form."""
    return date.today().isoformat()
