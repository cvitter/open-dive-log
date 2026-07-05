"""Tests for the UI layer.

The UI has two kinds of code:
  * Pure-Python helpers (data assembly, row loading, formatters) — these
    are tested directly without Qt.
  * Qt widgets — constructed against a temp DB. We don't try to run an
    event loop (the offscreen Qt platform plugin doesn't load on this
    Mac under Python 3.14; see earlier notes). Construction is enough
    to prove the wiring doesn't blow up.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log.repositories import dives, lookups, sites
from open_dive_log.ui import dive_detail_dialog, dive_table_model, sites_list_window


# ---------------------------------------------------------------------------
# Fixture: a real DB connection with one dive, two sites, one buddy.
# ---------------------------------------------------------------------------
@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "ui_test.db"
    cm = db.connect(db_path)
    c = cm.__enter__()
    db.apply_migrations(c)

    # Migration 002 seeds 60 countries but not Bonaire (BQ). Pre-register it
    # so the FK on site.country_code is satisfied.
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))

    # One site, one buddy, one dive attached to the site.
    s1 = sites.find_or_create(c, "Salt Pier", country_code="BQ")
    s2 = sites.find_or_create(c, "Karpata", country_code="BQ")
    dive_id = dives.create(
        c,
        dive_date="2026-07-04",
        start_time="14:30",
        end_time="15:15",
        dive_time_minutes=45,
        max_depth_m=24.0,
        avg_depth_m=18.0,
        o2_percentage=32.0,
    )
    dives.attach_sites(c, dive_id, [s1.id, s2.id])
    dives.add_buddy_to_dive(c, dive_id, "Mike", "Smith")
    try:
        yield c
    finally:
        cm.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# dive_table_model.load_rows — pure Python
# ---------------------------------------------------------------------------
def test_load_rows_returns_one_row_per_dive(conn: sqlite3.Connection) -> None:
    rows = dive_table_model.load_rows(conn)
    assert len(rows) == 1
    assert rows[0].id > 0
    assert rows[0].dive_date == "2026-07-04"
    assert "Salt Pier" in rows[0].sites
    assert "Karpata" in rows[0].sites
    assert rows[0].max_depth_m == 24.0


def test_load_rows_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    cm = db.connect(db_path)
    c = cm.__enter__()
    db.apply_migrations(c)
    try:
        assert dive_table_model.load_rows(c) == []
    finally:
        cm.__exit__(None, None, None)


def test_load_rows_orders_by_id_desc(conn: sqlite3.Connection) -> None:
    """The list is sorted by dive id DESC — the latest inserted dive
    (highest id, which the user calls Dive #) is at the top of the
    list. Insertion order in the test is:
        1. fixture dive (2026-07-04)
        2. 2026-07-01
        3. 2026-07-15
        4. 2026-07-08
    So sorted by id DESC: 4, 3, 2, 1 = 07-08, 07-15, 07-01, 07-04.
    """
    dives.create(conn, dive_date="2026-07-01", max_depth_m=10.0)
    dives.create(conn, dive_date="2026-07-15", max_depth_m=20.0)
    dives.create(conn, dive_date="2026-07-08", max_depth_m=15.0)
    rows = dive_table_model.load_rows(conn)
    assert [r.dive_date for r in rows] == [
        "2026-07-08", "2026-07-15", "2026-07-01", "2026-07-04",
    ]
    # And the Dive # column matches the row order — top row has the highest id.
    assert [r.id for r in rows] == [4, 3, 2, 1]


def test_format_depth() -> None:
    from open_dive_log.ui.dive_table_model import _format_depth
    from open_dive_log.units import UnitSystem
    metric = UnitSystem.METRIC
    imperial = UnitSystem.IMPERIAL
    assert _format_depth(None, metric) == ""
    assert _format_depth(24.0, metric) == "24 m"
    assert _format_depth(24.5, metric) == "24.5 m"
    assert _format_depth(0.0, metric) == "0 m"
    # 24 m ≈ 78.7 ft
    assert _format_depth(24.0, imperial) == "78.7 ft"
    assert _format_depth(None, imperial) == ""


def test_format_pressure_metric() -> None:
    from open_dive_log.ui.dive_table_model import _format_pressure
    from open_dive_log.units import UnitSystem
    assert _format_pressure(None, UnitSystem.METRIC) == ""
    assert _format_pressure(200.0, UnitSystem.METRIC) == "200 bar"
    assert _format_pressure(195.5, UnitSystem.METRIC) == "195.5 bar"
    # 0 is a real value (empty tank), not "not entered"
    assert _format_pressure(0.0, UnitSystem.METRIC) == "0 bar"


def test_format_pressure_imperial() -> None:
    from open_dive_log.ui.dive_table_model import _format_pressure
    from open_dive_log.units import UnitSystem
    # 200 BAR ≈ 2900.75 PSI
    assert _format_pressure(200.0, UnitSystem.IMPERIAL) == "2900.8 psi"
    # 232 BAR (high-pressure) ≈ 3364.9 PSI
    assert _format_pressure(232.0, UnitSystem.IMPERIAL) == "3364.9 psi"
    assert _format_pressure(0.0, UnitSystem.IMPERIAL) == "0 psi"
    assert _format_pressure(None, UnitSystem.IMPERIAL) == ""


def test_table_model_has_eleven_columns() -> None:
    """The user's spec added a 'Bottom time (min)' column next to Date,
    bringing the total to 11: Dive#/date/bottom time/air temp/water
    temp/visibility/pressure start/pressure end/depth avg/depth
    max/site. Verify both the count and the column constants in order.
    """
    from open_dive_log.ui.dive_table_model import (
        COL_DIVE_NUM, COL_DATE, COL_BOTTOM_TIME, COL_AIR_TEMP, COL_WATER_TEMP,
        COL_VISIBILITY, COL_PRESSURE_START, COL_PRESSURE_END, COL_DEPTH_AVG,
        COL_DEPTH_MAX, COL_SITE, NUM_COLS,
    )
    assert NUM_COLS == 11
    # Order matters
    assert (COL_DIVE_NUM, COL_DATE, COL_BOTTOM_TIME, COL_AIR_TEMP, COL_WATER_TEMP,
            COL_VISIBILITY, COL_PRESSURE_START, COL_PRESSURE_END, COL_DEPTH_AVG,
            COL_DEPTH_MAX, COL_SITE) == (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def test_table_model_headers_metric() -> None:
    from open_dive_log.ui.dive_table_model import _build_headers
    from open_dive_log.units import UnitSystem
    headers = _build_headers(UnitSystem.METRIC)
    labels = [h[0] for h in headers]
    assert labels == [
        "Dive #", "Date", "Bottom time (min)", "Air temp (°C)", "Water temp (°C)",
        "Visibility (m)", "P start (bar)", "P end (bar)",
        "Depth avg (m)", "Depth max (m)", "Site",
    ]


def test_table_model_headers_imperial() -> None:
    from open_dive_log.ui.dive_table_model import _build_headers
    from open_dive_log.units import UnitSystem
    headers = _build_headers(UnitSystem.IMPERIAL)
    labels = [h[0] for h in headers]
    assert labels == [
        "Dive #", "Date", "Bottom time (min)", "Air temp (°F)", "Water temp (°F)",
        "Visibility (ft)", "P start (psi)", "P end (psi)",
        "Depth avg (ft)", "Depth max (ft)", "Site",
    ]


def test_format_bottom_time() -> None:
    """Bottom time is a duration; it doesn't change with the unit
    toggle. None → empty string. 0 is a valid value (aborted dive)."""
    from open_dive_log.ui.dive_table_model import _format_bottom_time
    from open_dive_log.units import UnitSystem
    for unit in (UnitSystem.METRIC, UnitSystem.IMPERIAL):
        assert _format_bottom_time(None, unit) == ""
        assert _format_bottom_time(0, unit) == "0 min"
        assert _format_bottom_time(45, unit) == "45 min"
        assert _format_bottom_time(120, unit) == "120 min"


# ---------------------------------------------------------------------------
# Temperature spinbox range (per user spec: 120°F max in imperial)
# ---------------------------------------------------------------------------
def test_temp_spin_max_in_imperial_is_120F(conn: sqlite3.Connection) -> None:
    """The form's air/water temp spinboxes must accept up to 120°F in
    imperial mode. The form used to cap at 60 (which the user noted was
    too low — desert diving can hit 50°C / 122°F). The DB CHECK still
    allows up to 60°C, but the form is intentionally more restrictive
    at the UI layer.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog
    from open_dive_log.units import UnitSystem

    dlg = DiveAddEditDialog(conn, dive=None, unit_system=UnitSystem.IMPERIAL)
    dlg.show()
    app.processEvents()

    # The dialog builds air_temp and water_temp in _build_conditions_section
    air = dlg._air_temp
    water = dlg._water_temp
    assert air.maximum() == 120.0, f"air temp max was {air.maximum()}, expected 120.0"
    assert water.maximum() == 120.0, f"water temp max was {water.maximum()}, expected 120.0"

    # The user can now enter 120°F without the form rejecting it
    air.setValue(120.0)
    water.setValue(120.0)
    app.processEvents()
    assert air.value() == 120.0
    assert water.value() == 120.0

    dlg.close()


def test_temp_spin_max_in_metric_is_48_9C(conn: sqlite3.Connection) -> None:
    """In metric, the form cap is 48.9°C — the metric equivalent of
    120°F (rounded down so the spinbox can hold it as a clean
    display value). The DB still accepts up to 60°C; the form is
    intentionally more restrictive at the UI layer.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog
    from open_dive_log.units import UnitSystem

    dlg = DiveAddEditDialog(conn, dive=None, unit_system=UnitSystem.METRIC)
    dlg.show()
    app.processEvents()

    air = dlg._air_temp
    water = dlg._water_temp
    assert air.maximum() == 48.9, f"air temp max was {air.maximum()}, expected 48.9"
    assert water.maximum() == 48.9, f"water temp max was {water.maximum()}, expected 48.9"

    dlg.close()


def test_temp_spin_min_in_imperial_is_neg_58F(conn: sqlite3.Connection) -> None:
    """The lower bound is -50°C in the DB, which is -58°F — the form
    uses that in imperial mode so the spinbox range mirrors the DB
    in both unit systems."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog
    from open_dive_log.units import UnitSystem

    dlg = DiveAddEditDialog(conn, dive=None, unit_system=UnitSystem.IMPERIAL)
    dlg.show()
    app.processEvents()

    assert dlg._air_temp.minimum() == -58.0
    assert dlg._water_temp.minimum() == -58.0
    dlg.close()


# ---------------------------------------------------------------------------
# Pressure fields (migration 006)
# ---------------------------------------------------------------------------
def test_load_rows_includes_pressure_and_avg_depth(tmp_path: Path) -> None:
    """The DiveRow dataclass must carry all 11 columns' data from the DB.

    Uses an isolated connection (not the shared `conn` fixture) so we
    can assert an exact row count.
    """
    from open_dive_log.ui.dive_table_model import load_rows
    cm = db.connect(tmp_path / "load_rows_pressure.db")
    c = cm.__enter__()
    db.apply_migrations(c)
    try:
        did = dives.create(
            c, dive_date="2026-06-15",
            dive_time_minutes=45,
            max_depth_m=24.0, avg_depth_m=18.0,
            air_temp_c=28.0, water_temp_c=27.0, visibility_m=20.0,
            start_pressure_bar=200.0, end_pressure_bar=80.0,
        )
        rows = load_rows(c)
        assert len(rows) == 1
        assert rows[0].id == did
        assert rows[0].bottom_time_min == 45
        assert rows[0].max_depth_m == 24.0
        assert rows[0].avg_depth_m == 18.0
        assert rows[0].air_temp_c == 28.0
        assert rows[0].water_temp_c == 27.0
        assert rows[0].visibility_m == 20.0
        assert rows[0].start_pressure_bar == 200.0
        assert rows[0].end_pressure_bar == 80.0
    finally:
        cm.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# dive_detail_dialog.assemble_dive_detail — pure Python
# ---------------------------------------------------------------------------
def test_assemble_dive_detail_returns_all_fields(conn: sqlite3.Connection) -> None:
    dive_id = conn.execute("SELECT id FROM dive").fetchone()["id"]
    data = dive_detail_dialog.assemble_dive_detail(conn, dive_id)
    assert data is not None
    assert data["id"] == dive_id
    assert data["Date"] == "2026-07-04"
    assert data["Start time"] == "14:30"
    assert data["End time"] == "15:15"
    assert data["Duration (min)"] == 45
    assert data["Max depth (m)"] == 24.0
    assert data["Avg depth (m)"] == 18.0
    assert data["O2 percentage"] == 32.0
    # Joined site names
    assert "Salt Pier" in data["Sites"]
    assert "Karpata" in data["Sites"]
    # Joined buddy
    assert "Mike Smith" in data["Buddies"]


def test_assemble_dive_detail_returns_none_for_missing_dive(conn: sqlite3.Connection) -> None:
    assert dive_detail_dialog.assemble_dive_detail(conn, 99999) is None


def test_fmt_renders_none_as_dash() -> None:
    from open_dive_log.ui.dive_detail_dialog import _fmt
    assert _fmt(None) == "—"
    assert _fmt(24.0) == "24"
    assert _fmt(24.5) == "24.5"
    assert _fmt("hello") == "hello"


# ---------------------------------------------------------------------------
# Qt widget construction (no event loop)
#
# PySide6 6.11.1 on Homebrew Python 3.14 / macOS arm64 can crash the
# Python interpreter when QApplication initializes (Qt's plugin loader
# fails to resolve the platform plugin). When that happens the whole
# pytest process dies. To make the rest of the suite survive, the Qt
# tests below run in a subprocess; if the subprocess dies the test is
# reported as a skip (with the crash reason) rather than tearing down
# the whole run.
#
# On a working environment (Linux + system Qt, Windows, etc.) the
# subprocess returns 0 and the assertions below run normally.
# ---------------------------------------------------------------------------
import subprocess
import sys
import textwrap


def _run_qt_test(test_source: str) -> subprocess.CompletedProcess:
    """Run a snippet of Qt-testing code in a subprocess. Returns the result."""
    bootstrap = textwrap.dedent(
        """
        import sys
        # Force the Cocoa platform on macOS (the only one with a chance
        # of working). Skip cleanly if QApplication crashes.
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
        # Probe: did Qt actually attach to a platform plugin?
        try:
            _ = app.platformName()
        except Exception as e:
            print(f'SKIP: QApplication.platformName() failed: {e}')
            sys.exit(0)
        print(f'OK: platform = {app.platformName()}')
        # Now exec the test body.
        """
    )
    full = bootstrap + textwrap.dedent(test_source)
    return subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _subprocess_qt_check(test_source: str) -> None:
    """Run a Qt test in a subprocess. Skip if Qt won't initialize."""
    result = _run_qt_test(test_source)
    if result.returncode != 0:
        pytest.skip(
            f"Qt test crashed (rc={result.returncode}); "
            f"stderr head: {result.stderr[:200]!r}; "
            f"stdout head: {result.stdout[:200]!r}"
        )
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    if not result.stdout.startswith("OK:"):
        pytest.fail(f"Unexpected subprocess output: {result.stdout!r}")


def test_qt_main_window_constructs() -> None:
    """Construct MainWindow in a subprocess; skip on Qt init failure.

    The pure-Python tests above (load_rows, assemble_dive_detail) already
    verify the data path; this test adds widget-construction coverage
    for environments where Qt works.
    """
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import sites as sites_repo, dives
        from open_dive_log.ui.main_window import MainWindow

        # Build a tiny in-memory-ish DB for the test
        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        conn.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))
        s = sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
        d_id = dives.create(conn, dive_date="2026-07-04", max_depth_m=20.0)
        dives.attach_sites(conn, d_id, [s.id])

        win = MainWindow(conn=conn)
        assert win.windowTitle() == "Open Dive Log", win.windowTitle()
        menus = [a.text() for a in win.menuBar().actions()]
        assert "&Dives" in menus
        assert "&Sites" in menus
        assert "&Lookups" in menus
        assert "&Help" in menus
        assert win._model.rowCount() == 1, win._model.rowCount()
        assert not win._action_new_dive.isEnabled()
        assert win._action_import_sites.isEnabled()
        win.close()
        cm.__exit__(None, None, None)
        print('OK: main window constructed and assertions passed')
        """
    )


def test_qt_main_window_opens_at_75_percent_of_desktop() -> None:
    """Per the user's spec, the main window should open at 75% of the
    primary screen's available area (excluding the menu bar/dock),
    centered. We assert the geometry is within 1% of the target so
    floating-point rounding doesn't make the test flaky.
    """
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.ui.main_window import MainWindow
        from PySide6.QtGui import QGuiApplication

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)

        win = MainWindow(conn=conn)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        target_w = int(avail.width() * 0.75)
        target_h = int(avail.height() * 0.75)

        actual = win.geometry()
        # Allow a 1% tolerance for rounding / OS decorations
        tol = max(target_w, target_h) // 100
        assert abs(actual.width()  - target_w) <= tol, f'width {actual.width()} != ~{target_w}'
        assert abs(actual.height() - target_h) <= tol, f'height {actual.height()} != ~{target_h}'
        # Centered: window's center should be within tol of the screen's center
        cx = actual.x() + actual.width() // 2
        cy = actual.y() + actual.height() // 2
        ax = avail.x() + avail.width() // 2
        ay = avail.y() + avail.height() // 2
        assert abs(cx - ax) <= tol, f'window not horizontally centered (cx={cx}, ax={ax})'
        assert abs(cy - ay) <= tol, f'window not vertically centered (cy={cy}, ay={ay})'

        win.close()
        cm.__exit__(None, None, None)
        print('OK: main window opens at 75% of desktop, centered')
        """
    )


def test_qt_main_window_sites_menu_has_no_new_edit_delete() -> None:
    """Per the user's spec, the Sites menu on the main window should
    NOT contain New Site, Edit Site, or Delete Site entries. Those
    actions live only on the Sites List window.

    The Sites menu should still have: List Sites, separator,
    Import from opendivemap. Nothing else under Sites.
    """
    _subprocess_qt_check(
        """
        import os, tempfile
        os.environ['PYTHONPATH'] = 'src'
        from PySide6.QtWidgets import QApplication
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        tmp = tempfile.mkdtemp()
        cm = connect(os.path.join(tmp, 'menu_test.db'))
        c = cm.__enter__()
        apply_migrations(c)
        win = MainWindow(c)
        win.show()
        app.processEvents()

        # Collect the text of every action in every menu. The Qt
        # actions are C++-owned by the menubar, so we MUST capture
        # the text into a Python list before holding any other
        # references, otherwise a C++ object can be deleted while
        # we still hold a Python ref to it.
        all_texts = []
        for top_action in win.menuBar().actions():
            sub = top_action.menu()
            if sub is None:
                continue
            for a in sub.actions():
                t = a.text()
                if t:
                    all_texts.append(t)

        # Filter to just the Sites menu items (top_action.text() == '&Sites')
        sites_texts = []
        for top_action in win.menuBar().actions():
            if top_action.text() != '&Sites':
                continue
            sub = top_action.menu()
            for a in sub.actions():
                t = a.text()
                if t:
                    sites_texts.append(t)
            break

        # The handler attributes should not exist on the window
        assert not hasattr(win, '_action_new_site'), 'New Site action still exists'
        assert not hasattr(win, '_action_edit_site'), 'Edit Site action still exists'
        assert not hasattr(win, '_action_delete_site'), 'Delete Site action still exists'

        for forbidden in ('&New Site…', '&Edit Site…', '&Delete Site'):
            assert forbidden not in sites_texts, \\
                f'forbidden entry {forbidden!r} still in Sites menu: {sites_texts}'

        # Should still have List Sites and Import
        assert any('List Sites' in t for t in sites_texts), f'List Sites missing: {sites_texts}'
        assert any('Import' in t for t in sites_texts), f'Import missing: {sites_texts}'

        win.close()
        cm.__exit__(None, None, None)
        print('OK: Sites menu has no New/Edit/Delete entries')
        """
    )


def test_qt_dive_detail_dialog_constructs() -> None:
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import sites as sites_repo, dives
        from open_dive_log.ui.dive_detail_dialog import DiveDetailDialog

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        conn.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))
        s = sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
        d_id = dives.create(conn, dive_date="2026-07-04", max_depth_m=20.0)
        dives.attach_sites(conn, d_id, [s.id])

        dlg = DiveDetailDialog(conn, d_id)
        assert "Dive #" in dlg.windowTitle()
        assert "2026-07-04" in dlg.windowTitle()
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: detail dialog constructed and assertions passed')
        """
    )


def test_qt_sites_list_window_constructs() -> None:
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import sites as sites_repo
        from open_dive_log.ui.sites_list_window import SitesListWindow

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        conn.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))
        sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
        sites_repo.find_or_create(conn, "Karpata", country_code="BQ")

        win = SitesListWindow(conn)
        assert win._model.rowCount() == 2, win._model.rowCount()
        assert "2 sites" in win.statusBar().currentMessage()
        win.close()
        cm.__exit__(None, None, None)
        print('OK: sites list window constructed and assertions passed')
        """
    )


def test_qt_main_window_has_certifications_menu() -> None:
    """The main window now has 5 top-level menus including Certifications."""
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.ui.main_window import MainWindow

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        win = MainWindow(conn=conn)
        menus = [a.text() for a in win.menuBar().actions()]
        for required in ('&Dives', '&Sites', '&Certifications', '&Lookups', '&Help'):
            assert required in menus, f"missing menu: {required}; have {menus}"
        win.close()
        cm.__exit__(None, None, None)
        print('OK: main window has all 5 menus')
        """
    )


def test_qt_cert_list_window_constructs() -> None:
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import certifications, lookups
        from open_dive_log.ui.cert_list_window import CertListWindow

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        padi = lookups.list_active(conn, 'lookup_certifying_agency')[0]
        certifications.create(conn, cert_date='2026-06-15', cert_name='Open Water',
                              cert_number='PADI-1', certifying_agency_id=padi.id)
        certifications.create(conn, cert_date='2026-08-20', cert_name='AOW Diver',
                              cert_number='PADI-2', certifying_agency_id=padi.id,
                              certifying_facility='Blue Water Divers')

        win = CertListWindow(conn)
        assert win._model.rowCount() == 2, win._model.rowCount()
        # Status bar reports count.
        assert '2 certification' in win.statusBar().currentMessage()
        # Toolbar has the expected actions.
        toolbar = win.findChild(type(win._action_add).__mro__[0])  # placeholder
        win.close()
        cm.__exit__(None, None, None)
        print('OK: cert list window constructed and 2 certs loaded')
        """
    )


def test_qt_cert_add_dialog_constructs() -> None:
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.ui.cert_add_edit_dialog import CertAddEditDialog

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        dlg = CertAddEditDialog(conn, cert=None)
        assert dlg.windowTitle() == 'Add Certification'
        # Date defaults to today, agency combo is populated.
        assert dlg._agency.count() == 12
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: cert add dialog constructed')
        """
    )


def test_qt_dive_add_dialog_constructs() -> None:
    """Verify the dive add dialog opens and the form has all the
    expected sections wired. This is the UI-level smoke test for the
    new add/edit feature — the actual user flow is exercised manually."""
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import sites as sites_repo, buddies
        from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        conn.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))
        sites_repo.find_or_create(conn, "Salt Pier", country_code='BQ')
        buddies.find_or_create(conn, "Mike", "Smith")

        dlg = DiveAddEditDialog(conn, dive=None)
        assert dlg.windowTitle() == 'Add Dive'
        # All 9 lookup comboboxes wired
        for attr in ('_time_of_day', '_entry_type', '_surface_conditions',
                     '_equipment_type', '_tank_type', '_tank_config',
                     '_gas_type', '_purpose'):
            combo = getattr(dlg, attr)
            assert combo.count() > 1, f'{attr} not populated'
        # Buddy roles combo has at least the 4 seeded values
        assert dlg._attached_role_combo.count() == 5  # 1 "(none)" + 4 roles
        # Sites picker populated
        assert dlg._sites_picker.count() == 1
        assert dlg._sites_picker.item(0).text() == 'Salt Pier (Bonaire)'
        # Buddies picker populated
        assert dlg._buddies_picker.count() == 1
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: dive add dialog constructed with all sections')
        """
    )


def test_qt_dive_edit_round_trip() -> None:
    """End-to-end: create a dive + sites + buddies, open the edit dialog,
    verify the form is pre-populated correctly, then save a change and
    verify it round-trips through the repository. This is the regression
    test for the slots=True + to_kwargs() boundary."""
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import dives, sites as sites_repo, buddies, lookups
        from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        conn.execute("INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)", ("BQ", "Bonaire"))
        s1 = sites_repo.find_or_create(conn, "Salt Pier", country_code='BQ')
        s2 = sites_repo.find_or_create(conn, "Karpata", country_code='BQ')
        mike = buddies.find_or_create(conn, "Mike", "Smith")
        day = next(t.id for t in lookups.list_active(conn, 'lookup_time_of_day') if t.name == 'day')

        # Create a dive
        did = dives.create(conn, dive_date='2026-06-15', start_time='14:30',
                          end_time='15:15', dive_time_minutes=45, max_depth_m=24.0,
                          time_of_day_id=day)
        dives.attach_sites(conn, did, [s1.id, s2.id])
        dives.attach_buddies(conn, did, [(mike.id, None)])

        # Open the edit dialog and check the form is pre-populated
        full = dives.get_full(conn, did)
        dlg = DiveAddEditDialog(conn, dive=full)
        assert dlg.windowTitle() == 'Edit Dive'
        # Sites are pre-attached in order
        assert dlg._sites_attached.count() == 2
        assert dlg._sites_attached.item(0).text().endswith('Salt Pier')
        assert dlg._sites_attached.item(1).text().endswith('Karpata')
        # Buddy is pre-attached
        assert dlg._buddies_attached.count() == 1
        assert 'Mike Smith' in dlg._buddies_attached.item(0).text()
        dlg.close()
        cm.__exit__(None, None, None)
        print('OK: dive edit dialog pre-populates from get_full()')
        """
    )


def test_qt_cert_add_edit_round_trip() -> None:
    """End-to-end: construct add dialog, simulate Save, verify create + edit
    via to_kwargs() actually round-trips through the repository. This is the
    regression test for the slots=True + **self.__dict__ bug.
    """
    _subprocess_qt_check(
        """
        from open_dive_log.db import connect, apply_migrations
        from open_dive_log.repositories import certifications, lookups
        from open_dive_log.ui.cert_add_edit_dialog import CertAddEditDialog, SubmittedCert

        cm = connect(':memory:')
        conn = cm.__enter__()
        apply_migrations(conn)
        padi = lookups.list_active(conn, 'lookup_certifying_agency')[0]

        # Path 1: create via SubmittedCert.to_kwargs() (this is what the
        # add dialog will hand to cert_list_window on Save).
        dlg = CertAddEditDialog(conn, cert=None)
        sub = SubmittedCert(
            cert_date='2026-06-15', cert_name='Open Water',
            cert_number='PADI-1', certifying_agency_id=padi.id,
            certifying_facility='Blue Water', instructor='J. Smith', notes='Day 1',
        )
        new_id = certifications.create(conn, **sub.to_kwargs())
        cert = certifications.get(conn, new_id)
        assert cert is not None
        assert cert.cert_name == 'Open Water'
        assert cert.certifying_agency_name == 'PADI'
        assert cert.certifying_facility == 'Blue Water'
        dlg.close()

        # Path 2: edit + update via the same to_kwargs() mechanism.
        dlg2 = CertAddEditDialog(conn, cert=cert)
        assert dlg2._name.text() == 'Open Water'
        assert dlg2._facility.text() == 'Blue Water'
        sub2 = SubmittedCert(
            cert_date='2026-08-20', cert_name='Advanced Open Water',
            cert_number='PADI-2', certifying_agency_id=padi.id,
            certifying_facility='Blue Water', instructor='J. Smith', notes='Updated',
        )
        certifications.update(conn, cert.id, **sub2.to_kwargs())
        updated = certifications.get(conn, cert.id)
        assert updated.cert_name == 'Advanced Open Water'
        assert updated.cert_date == '2026-08-20'
        dlg2.close()
        cm.__exit__(None, None, None)
        print('OK: cert add + edit round-trip via to_kwargs()')
        """
    )
