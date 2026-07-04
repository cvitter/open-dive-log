"""Tests for the certifications repository + print rendering."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log.repositories import certifications, lookups
from open_dive_log.ui.cert_list_window import render_cert_html, render_certs_html


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "certs_test.db"
    cm = db.connect(db_path)
    c = cm.__enter__()
    db.apply_migrations(c)
    yield c
    cm.__exit__(None, None, None)


@pytest.fixture()
def padi_id(conn: sqlite3.Connection) -> int:
    return lookups.list_active(conn, "lookup_certifying_agency")[0].id


# ---------------------------------------------------------------------------
# Repository CRUD
# ---------------------------------------------------------------------------
def test_create_returns_rowid_and_persists(conn, padi_id) -> None:
    cid = certifications.create(
        conn,
        cert_date="2026-06-15",
        cert_name="Advanced Open Water",
        cert_number="PADI-12345",
        certifying_agency_id=padi_id,
        certifying_facility="Blue Water Divers",
        instructor="J. Smith",
        notes="Day 1 in Cozumel",
    )
    assert cid > 0
    cert = certifications.get(conn, cid)
    assert cert is not None
    assert cert.cert_name == "Advanced Open Water"
    assert cert.certifying_agency_name == "PADI"
    assert cert.certifying_facility == "Blue Water Divers"
    assert cert.instructor == "J. Smith"
    assert cert.notes == "Day 1 in Cozumel"


def test_create_strips_whitespace_on_text_fields(conn, padi_id) -> None:
    cid = certifications.create(
        conn,
        cert_date="2026-06-15",
        cert_name="  Rescue Diver  ",
        cert_number="  PADI-99  ",
        certifying_agency_id=padi_id,
        certifying_facility="  Blue Water  ",
        instructor="  Smith  ",
        notes="  notes  ",
    )
    cert = certifications.get(conn, cid)
    assert cert.cert_name == "Rescue Diver"
    assert cert.cert_number == "PADI-99"
    assert cert.certifying_facility == "Blue Water"
    assert cert.instructor == "Smith"
    assert cert.notes == "notes"


def test_create_normalizes_empty_to_null(conn, padi_id) -> None:
    """Empty strings on optional fields become NULL, not ''."""
    cid = certifications.create(
        conn,
        cert_date="2026-06-15",
        cert_name="Open Water",
        cert_number="PADI-1",
        certifying_agency_id=padi_id,
        certifying_facility="   ",
        instructor="",
    )
    cert = certifications.get(conn, cid)
    assert cert.certifying_facility is None
    assert cert.instructor is None
    assert cert.notes is None


def test_create_rejects_blank_name_or_number(conn, padi_id) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        certifications.create(
            conn, cert_date="2026-06-15", cert_name="   ",
            cert_number="PADI-1", certifying_agency_id=padi_id,
        )
    with pytest.raises(sqlite3.IntegrityError):
        certifications.create(
            conn, cert_date="2026-06-15", cert_name="Open Water",
            cert_number="", certifying_agency_id=padi_id,
        )


def test_create_rejects_unknown_agency(conn) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        certifications.create(
            conn, cert_date="2026-06-15", cert_name="X",
            cert_number="Y", certifying_agency_id=99999,
        )


def test_list_all_sorts_newest_first(conn, padi_id) -> None:
    certifications.create(conn, cert_date="2025-01-01", cert_name="A",
                          cert_number="1", certifying_agency_id=padi_id)
    certifications.create(conn, cert_date="2026-06-01", cert_name="B",
                          cert_number="2", certifying_agency_id=padi_id)
    certifications.create(conn, cert_date="2026-03-01", cert_name="C",
                          cert_number="3", certifying_agency_id=padi_id)
    rows = certifications.list_all(conn)
    assert [r.cert_date for r in rows] == ["2026-06-01", "2026-03-01", "2025-01-01"]


def test_update_changes_fields(conn, padi_id) -> None:
    ssi_id = next(a.id for a in lookups.list_active(conn, "lookup_certifying_agency") if a.name == "SSI")
    cid = certifications.create(conn, cert_date="2026-06-15", cert_name="AOW",
                                cert_number="PADI-1", certifying_agency_id=padi_id)
    certifications.update(
        conn, cid, cert_date="2026-06-20", cert_name="Advanced Open Water Diver",
        cert_number="PADI-99", certifying_agency_id=ssi_id,
        certifying_facility="New Shop", notes="updated",
    )
    cert = certifications.get(conn, cid)
    assert cert.cert_date == "2026-06-20"
    assert cert.cert_name == "Advanced Open Water Diver"
    assert cert.cert_number == "PADI-99"
    assert cert.certifying_agency_name == "SSI"
    assert cert.certifying_facility == "New Shop"
    assert cert.notes == "updated"


def test_update_raises_for_missing_id(conn, padi_id) -> None:
    with pytest.raises(LookupError):
        certifications.update(
            conn, 99999, cert_date="2026-06-15", cert_name="x",
            cert_number="y", certifying_agency_id=padi_id,
        )


def test_delete_removes_row(conn, padi_id) -> None:
    cid = certifications.create(conn, cert_date="2026-06-15", cert_name="x",
                               cert_number="y", certifying_agency_id=padi_id)
    certifications.delete(conn, cid)
    assert certifications.get(conn, cid) is None


def test_delete_raises_for_missing_id(conn) -> None:
    with pytest.raises(LookupError):
        certifications.delete(conn, 99999)


# ---------------------------------------------------------------------------
# Lookup seeding
# ---------------------------------------------------------------------------
def test_agencies_table_seeded_with_12(conn) -> None:
    agencies = lookups.list_active(conn, "lookup_certifying_agency")
    names = {a.name for a in agencies}
    assert {"PADI", "SSI", "NAUI", "BSAC", "CMAS", "SDI", "TDI",
            "IANTD", "RAID", "GUE", "PSAI", "PSA"} <= names


# ---------------------------------------------------------------------------
# Print rendering (pure HTML, no Qt)
# ---------------------------------------------------------------------------
def test_render_cert_html_escapes_user_text(conn, padi_id) -> None:
    cid = certifications.create(
        conn, cert_date="2026-06-15",
        cert_name="<script>alert(1)</script>",
        cert_number="<b>PADI-1</b>",
        certifying_agency_id=padi_id,
        certifying_facility='evil "injection"',
        notes="line1\nline2",
    )
    cert = certifications.get(conn, cid)
    html = render_cert_html(cert)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>PADI-1</b>" not in html
    assert "&lt;b&gt;PADI-1&lt;/b&gt;" in html
    assert "evil" in html  # content preserved, just escaped


def test_render_certs_html_paginates(conn, padi_id) -> None:
    a = certifications.create(conn, cert_date="2026-06-15", cert_name="A",
                              cert_number="1", certifying_agency_id=padi_id)
    b = certifications.create(conn, cert_date="2026-06-16", cert_name="B",
                              cert_number="2", certifying_agency_id=padi_id)
    ca = certifications.get(conn, a)
    cb = certifications.get(conn, b)
    html = render_certs_html([ca, cb])
    assert "page-break-before" in html
    # Both certs should appear in the output.
    assert ">A<" in html
    assert ">B<" in html


def test_render_certs_html_handles_empty() -> None:
    out = render_certs_html([])
    assert "No certifications" in out


# ---------------------------------------------------------------------------
# Pure-Python tests of the certification module — no Qt required.
# ---------------------------------------------------------------------------
def test_today_iso_returns_iso_date() -> None:
    from open_dive_log.repositories.certifications import today_iso
    from datetime import date
    assert today_iso() == date.today().isoformat()
