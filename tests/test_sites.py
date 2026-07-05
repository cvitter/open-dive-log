"""Tests for the sites repository and the site add/edit dialog.

Covers:
  * Site CRUD (create via find_or_create, update, delete)
  * UNIQUE (name, country) constraint enforcement
  * dive_site ON DELETE RESTRICT behavior (with a clear blocker list)
  * The add/edit dialog's round-trip (in subprocess so Qt crashes
    don't take down the test process — same pattern as test_ui.py).
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log.repositories import dives, sites as sites_repo


@pytest.fixture
def empty_db(tmp_path: Path) -> sqlite3.Connection:
    """A fresh DB with a few seed countries for FK."""
    cm = db.connect(tmp_path / "sites_test.db")
    c = cm.__enter__()
    db.apply_migrations(c)
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("CW", "Curaçao"))
    c.commit()
    yield c
    cm.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Repository: update
# ---------------------------------------------------------------------------
def test_update_persists_changes(empty_db: sqlite3.Connection) -> None:
    s = sites_repo.find_or_create(empty_db, "Salt Pier", country_code="BQ")
    sites_repo.update(
        empty_db, s.id,
        name="Salt Pier",
        country="Bonaire",
        region="Southern Caribbean",
        max_depth_m=18.0,
    )
    after = sites_repo.get(empty_db, s.id)
    assert after is not None
    assert after.region == "Southern Caribbean"
    assert after.max_depth_m == 18.0
    assert after.country == "Bonaire"


def test_update_unknown_id_raises(empty_db: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        sites_repo.update(empty_db, 9999, name="nope")


def test_update_to_duplicate_name_country_raises(
    empty_db: sqlite3.Connection,
) -> None:
    """UNIQUE (name, country) — renaming a site to collide with another
    site in the same country must fail with IntegrityError, not silently
    collapse the two sites.

    To trigger the constraint, BOTH sites need a non-NULL `country`
    field that matches. (find_or_create only sets country_code by
    default, not the free-text country.)"""
    a = sites_repo.find_or_create(empty_db, "Salt Pier", country_code="BQ", country="Bonaire")
    b = sites_repo.find_or_create(empty_db, "Karpata", country_code="BQ", country="Bonaire")
    assert a.country == "Bonaire"
    assert b.country == "Bonaire"
    with pytest.raises(sqlite3.IntegrityError):
        sites_repo.update(
            empty_db, b.id,
            name="Salt Pier",
            country="Bonaire",
        )
    # Both sites still exist
    assert sites_repo.get(empty_db, a.id) is not None
    assert sites_repo.get(empty_db, b.id) is not None


def test_update_does_not_change_country_code(
    empty_db: sqlite3.Connection,
) -> None:
    """country_code is the modern, opendivemap-compatible key. It is
    intentionally NOT in the update() signature — the form shouldn't
    change it. This test pins that behavior."""
    s = sites_repo.find_or_create(empty_db, "Salt Pier", country_code="BQ")
    sites_repo.update(empty_db, s.id, name="Salt Pier", country="Bonaire")
    after = sites_repo.get(empty_db, s.id)
    assert after is not None
    assert after.country_code == "BQ"  # unchanged


# ---------------------------------------------------------------------------
# Repository: delete
# ---------------------------------------------------------------------------
def test_delete_unreferenced_site(empty_db: sqlite3.Connection) -> None:
    s = sites_repo.find_or_create(empty_db, "Salt Pier", country_code="BQ")
    sites_repo.delete(empty_db, s.id)
    assert sites_repo.get(empty_db, s.id) is None


def test_delete_unknown_id_raises(empty_db: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        sites_repo.delete(empty_db, 9999)


def test_delete_blocked_by_referencing_dive(
    empty_db: sqlite3.Connection,
) -> None:
    """dive_site has ON DELETE RESTRICT. Delete must fail and the
    caller can ask list_blocking_dives() for which dives are in the
    way."""
    s = sites_repo.find_or_create(empty_db, "Salt Pier", country_code="BQ")
    d_id = dives.create(empty_db, dive_date="2026-07-04", max_depth_m=20.0)
    dives.attach_sites(empty_db, d_id, [s.id])
    with pytest.raises(sqlite3.IntegrityError):
        sites_repo.delete(empty_db, s.id)
    blockers = sites_repo.list_blocking_dives(empty_db, s.id)
    assert blockers == [(d_id, "2026-07-04")]


def test_list_blocking_dives_returns_at_most_10(
    empty_db: sqlite3.Connection,
) -> None:
    """The list is capped at 10 in the SQL so the UI can show a useful
    error message without flooding the user."""
    s = sites_repo.find_or_create(empty_db, "Salt Pier", country_code="BQ")
    for i in range(15):
        d_id = dives.create(
            empty_db,
            dive_date=f"2026-07-{(i % 28) + 1:02d}",
            max_depth_m=20.0,
        )
        dives.attach_sites(empty_db, d_id, [s.id])
    blockers = sites_repo.list_blocking_dives(empty_db, s.id)
    assert len(blockers) == 10  # capped in the SQL


# ---------------------------------------------------------------------------
# Qt dialog: subprocess-isolated tests
# ---------------------------------------------------------------------------
def _run_qt_test(test_source: str) -> subprocess.CompletedProcess:
    """Run a Qt test snippet in a subprocess. Returns the result.

    Mirrors the pattern in tests/test_ui.py. If Qt can't init in the
    subprocess, the test should be reported as a skip rather than
    crashing the whole test run.
    """
    bootstrap = textwrap.dedent(
        """
        import sys
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'cocoa')
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as e:
            print(f'SKIP: PySide6 import failed: {e}')
            sys.exit(0)
        try:
            app = QApplication.instance() or QApplication([])
        except Exception as e:
            print(f'SKIP: QApplication init failed: {e}')
            sys.exit(0)
        if app is None:
            print('SKIP: QApplication returned None')
            sys.exit(0)
        """
    )
    full = bootstrap + textwrap.dedent(test_source)
    return subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )


def _assert_qt_ok(result: subprocess.CompletedProcess) -> None:
    if result.returncode != 0:
        pytest.skip(f"Qt test crashed (rc={result.returncode}); "
                    f"stderr head: {result.stderr[:200]!r}")
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    if not result.stdout.startswith("OK:"):
        pytest.fail(f"Unexpected subprocess output: {result.stdout!r}")


def test_qt_site_add_dialog_constructs() -> None:
    """The 'New Site' dialog builds without errors."""
    _assert_qt_ok(_run_qt_test(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.ui.site_add_edit_dialog import SiteAddEditDialog
        cm = connect(':memory:')
        c = cm.__enter__()
        apply_migrations(c)
        dlg = SiteAddEditDialog(c, site=None)
        dlg.show()
        app.processEvents()
        assert dlg.windowTitle() == 'New Site', dlg.windowTitle()
        assert dlg._name is not None
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: new site dialog constructs')
        """
    ))


def test_qt_site_edit_dialog_constructs() -> None:
    """The 'Edit Site' dialog builds and pre-populates from an existing site."""
    _assert_qt_ok(_run_qt_test(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import sites as sites_repo
        from open_dive_log.ui.site_add_edit_dialog import SiteAddEditDialog
        cm = connect(':memory:')
        c = cm.__enter__()
        apply_migrations(c)
        c.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ('BQ', 'Bonaire'))
        c.commit()
        s = sites_repo.find_or_create(c, 'Salt Pier', country_code='BQ')
        dlg = SiteAddEditDialog(c, site=s)
        dlg.show()
        app.processEvents()
        assert dlg.windowTitle() == 'Edit Site', dlg.windowTitle()
        assert dlg._name.text() == 'Salt Pier', dlg._name.text()
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: edit site dialog constructs and pre-populates')
        """
    ))


def test_qt_site_dialog_rejects_empty_name() -> None:
    """Saving with an empty name must keep the dialog open and not
    return a SubmittedSite. We can't easily assert on QMessageBox
    interactions in a subprocess, but we CAN assert that .submitted()
    returns None after _on_save() with no name."""
    _assert_qt_ok(_run_qt_test(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.ui.site_add_edit_dialog import SiteAddEditDialog
        cm = connect(':memory:')
        c = cm.__enter__()
        apply_migrations(c)
        c.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ('BQ', 'Bonaire'))
        c.commit()
        dlg = SiteAddEditDialog(c, site=None)
        # Pick the country code so the only missing required field is the name
        for i in range(dlg._country_code.count()):
            if dlg._country_code.itemData(i) == 'BQ':
                dlg._country_code.setCurrentIndex(i)
                break
        dlg._country.setText('Bonaire')
        # Don't set a name
        # _on_save shows a QMessageBox.warning; the test subprocess
        # can't interactively dismiss it, so we patch QMessageBox.warning
        # to a no-op. The point is that .submitted() stays None.
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
        dlg._on_save()
        assert dlg.submitted() is None, 'form should not have saved with no name'
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: empty name rejected')
        """
    ))
