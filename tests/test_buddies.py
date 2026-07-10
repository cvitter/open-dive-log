"""Tests for the buddies repository + the BuddiesListWindow.

The repo functions are tested directly against a temp DB. The window
is exercised via a Qt subprocess test (the same pattern used in
test_sites.py and test_ui.py) because the window uses QMessageBox and
other modal dialogs that don't play well in-process.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from open_dive_log.db import apply_migrations, connect
from open_dive_log.repositories import buddies as b_repo


# --------------------------------------------------------------------- repo
@pytest.fixture
def conn() -> sqlite3.Connection:
    """A fresh DB with migrations applied, autocommit (matches prod)."""
    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "buddies_test.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            yield c
        finally:
            cm.__exit__(None, None, None)


def test_list_all_empty(conn: sqlite3.Connection) -> None:
    assert b_repo.list_all(conn) == []


def test_list_all_sorted_by_full_name(conn: sqlite3.Connection) -> None:
    b_repo.find_or_create(conn, "Zoe", "Zebra")
    b_repo.find_or_create(conn, "Alice", "Adams")
    b_repo.find_or_create(conn, "Bob", "Brown")
    names = [b.full_name for b in b_repo.list_all(conn)]
    assert names == ["Alice Adams", "Bob Brown", "Zoe Zebra"]


def test_update_changes_names_and_recomputes_full_name(
    conn: sqlite3.Connection,
) -> None:
    b = b_repo.find_or_create(conn, "Mike", "Smith")
    b_repo.update(conn, b.id, first_name="Michael", last_name="Smith")
    got = b_repo.get(conn, b.id)
    assert got is not None
    assert got.first_name == "Michael"
    assert got.full_name == "Michael Smith"


def test_update_collapses_case_and_whitespace_for_dedup(
    conn: sqlite3.Connection,
) -> None:
    """If a rename would collide with another buddy's normalized name,
    the UNIQUE constraint rejects it — caller catches IntegrityError."""
    b_repo.find_or_create(conn, "Mike", "Smith")
    b = b_repo.find_or_create(conn, "Jane", "Doe")
    with pytest.raises(sqlite3.IntegrityError):
        b_repo.update(conn, b.id, first_name="MIKE", last_name="SMITH")


def test_update_unknown_id_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        b_repo.update(conn, 9999, first_name="No", last_name="One")


def test_delete_removes_row(conn: sqlite3.Connection) -> None:
    b = b_repo.find_or_create(conn, "Mike", "Smith")
    b_repo.delete(conn, b.id)
    assert b_repo.get(conn, b.id) is None


def test_delete_unknown_id_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        b_repo.delete(conn, 9999)


def test_count_referencing_dives_zero_for_unused_buddy(
    conn: sqlite3.Connection,
) -> None:
    b = b_repo.find_or_create(conn, "Mike", "Smith")
    assert b_repo.count_referencing_dives(conn, b.id) == 0


def test_count_referencing_dives_counts_links(
    conn: sqlite3.Connection,
) -> None:
    """When a dive is linked to a buddy, the count goes up."""
    from open_dive_log.repositories import dives

    b = b_repo.find_or_create(conn, "Mike", "Smith")
    assert b_repo.count_referencing_dives(conn, b.id) == 0

    dive_id = dives.create(
        conn,
        dive_date="2026-07-07",
        dive_time_minutes=45,
    )
    dives.attach_buddies(conn, dive_id, [(b.id, None)])
    assert b_repo.count_referencing_dives(conn, b.id) == 1


# ------------------------------------------------------------ BuddiesListWindow
# These are subprocess tests — they construct a real QApplication and a
# real BuddiesListWindow. The subprocess bootstrap lives in
# tests/conftest.py as `run_qt_subprocess` so the env-setup pattern
# stays in one place.


def _run_qt_test(source: str) -> "subprocess.CompletedProcess[str]":  # type: ignore[name-defined]
    """Deprecated: call the conftest's ``run_qt_subprocess`` directly.
    Kept as a thin wrapper so existing tests don't have to change.
    """
    from tests.conftest import run_qt_subprocess
    return run_qt_subprocess(source)


def test_buddies_list_window_constructs_empty_db() -> None:
    """A fresh DB with no buddies should produce an empty window."""
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.ui.buddies_list_window import BuddiesListWindow

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "empty.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            win = BuddiesListWindow(c)
            assert win.windowTitle() == "Buddies", f"got {win.windowTitle()!r}"
            assert win._model.rowCount() == 0
            assert not win._action_edit.isEnabled()
            assert not win._action_delete.isEnabled()
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: empty db shows 0 rows")
    """
    result = _run_qt_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: empty db shows 0 rows" in result.stdout


def test_buddies_list_window_loads_existing_buddies() -> None:
    """A window on a DB with 2 buddies should show 2 rows, with the
    correct first/last names and a # Dives column of 0 (no dives yet)."""
    src = """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import buddies as b_repo
    from open_dive_log.ui.buddies_list_window import BuddiesListWindow

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "two.db"))
        c = cm.__enter__()
        apply_migrations(c)
        b_repo.find_or_create(c, "Mike", "Smith")
        b_repo.find_or_create(c, "Jane", "Doe")
        try:
            win = BuddiesListWindow(c)
            assert win._model.rowCount() == 2, f"got {win._model.rowCount()}"
            # Header order: First, Last, # Dives
            assert win._model.headerData(0, Qt.Orientation.Horizontal) == "First name"
            assert win._model.headerData(1, Qt.Orientation.Horizontal) == "Last name"
            assert win._model.headerData(2, Qt.Orientation.Horizontal) == "# Dives"
            # Find Mike Smith's row by scanning
            mike_idx = jane_idx = -1
            for r in range(2):
                first = win._model.data(win._model.index(r, 0))
                if first == "Mike":
                    mike_idx = r
                elif first == "Jane":
                    jane_idx = r
            assert mike_idx >= 0 and jane_idx >= 0
            assert win._model.data(win._model.index(mike_idx, 1)) == "Smith"
            assert win._model.data(win._model.index(jane_idx, 1)) == "Doe"
            assert win._model.data(win._model.index(mike_idx, 2)) == "0"
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: window loads 2 buddies with correct columns")
    """
    result = _run_qt_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: window loads 2 buddies with correct columns" in result.stdout


def test_buddies_list_window_filter_substring() -> None:
    """Searching 'mike' should filter the table to 1 row."""
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import buddies as b_repo
    from open_dive_log.ui.buddies_list_window import BuddiesListWindow

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "filter.db"))
        c = cm.__enter__()
        apply_migrations(c)
        b_repo.find_or_create(c, "Mike", "Smith")
        b_repo.find_or_create(c, "Jane", "Doe")
        try:
            win = BuddiesListWindow(c)
            assert win._model.rowCount() == 2
            win._search.setText("mike")
            assert win._model.rowCount() == 1, f"got {win._model.rowCount()}"
            win._search.setText("")
            assert win._model.rowCount() == 2
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: search filter narrows results")
    """
    result = _run_qt_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: search filter narrows results" in result.stdout


def test_buddy_add_button_with_empty_picker_triggers_inline_create() -> None:
    """Regression: when the buddies picker is empty (no buddies in DB),
    clicking 'Add' should auto-launch the inline-create flow rather
    than silently do nothing. Pre-fix bug: currentData() was None, the
    handler returned early, and the user got no feedback.
    """
    src = """
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    app = QApplication.instance() or QApplication([])

    # Stub QMessageBox.warning (called by _on_save validators if any)
    QMessageBox.warning = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    # Stub QInputDialog.getText to return a name when prompted. The
    # inline-create flow asks for "First name:" and "Last name:" — we
    # return "John" and "Smith" respectively.
    responses = iter([("John", True), ("Smith", True)])
    QInputDialog.getText = staticmethod(
        lambda *a, **k: next(responses)
    )

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import buddies as b_repo
    from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog
    from open_dive_log.units import UnitSystem

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "add_empty.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            dlg = DiveAddEditDialog(c, dive=None, unit_system=UnitSystem.METRIC)
            # Pre-condition: picker is empty (no buddies in DB)
            assert dlg._buddies_picker.count() == 0
            assert dlg._buddies_attached.count() == 0

            # Click Add — should auto-create the buddy
            dlg._on_buddy_add_clicked()

            # Post-conditions: buddy in DB, attached to dive
            buddies = b_repo.list_all(c)
            assert len(buddies) == 1, f"expected 1 buddy, got {len(buddies)}"
            assert buddies[0].full_name == "John Smith"
            assert dlg._buddies_attached.count() == 1
            dlg.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: empty picker Add button creates and attaches a buddy")
    """
    result = _run_qt_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: empty picker Add button creates and attaches a buddy" in result.stdout


def test_buddy_add_button_with_existing_buddy_adds_to_attached() -> None:
    """When the picker has a buddy and the user clicks Add (no
    selection), the first buddy in the picker should be added to the
    attached list. This is the original flow — preserved by the fix.
    """
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import buddies as b_repo
    from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog
    from open_dive_log.units import UnitSystem

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "add_existing.db"))
        c = cm.__enter__()
        apply_migrations(c)
        b_repo.find_or_create(c, "Mike", "Smith")
        try:
            dlg = DiveAddEditDialog(c, dive=None, unit_system=UnitSystem.METRIC)
            # Picker has 1 buddy
            assert dlg._buddies_picker.count() == 1
            # Simulate the user selecting the buddy in the combo
            dlg._buddies_picker.setCurrentIndex(0)
            assert dlg._buddies_attached.count() == 0

            dlg._on_buddy_add_clicked()

            # Buddy added to attached list
            assert dlg._buddies_attached.count() == 1
            dlg.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: existing buddy Add button attaches to dive")
    """
    result = _run_qt_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: existing buddy Add button attaches to dive" in result.stdout
