"""Tests for the lookups repo (add/update/soft_delete/count_referencing)
and the LookupsListWindow.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import textwrap

import pytest

from open_dive_log.db import apply_migrations, connect
from open_dive_log.repositories import lookups as lk
from open_dive_log.repositories.lookups import LOOKUP_TABLES, LookupValue


# --------------------------------------------------------------------- repo
@pytest.fixture
def conn() -> sqlite3.Connection:
    """A fresh DB with migrations applied."""
    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "lookups_test.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            yield c
        finally:
            cm.__exit__(None, None, None)


def test_add_inserts_active_value(conn: sqlite3.Connection) -> None:
    v = lk.add(conn, "lookup_buddy_role", "photographer", display_order=50)
    assert v.id > 0
    assert v.name == "photographer"
    assert v.display_order == 50
    assert v.is_active is True
    # And it shows up in list_active
    actives = lk.list_active(conn, "lookup_buddy_role")
    assert any(x.id == v.id for x in actives)


def test_add_raises_on_duplicate_name(conn: sqlite3.Connection) -> None:
    lk.add(conn, "lookup_buddy_role", "photographer")
    with pytest.raises(sqlite3.IntegrityError):
        lk.add(conn, "lookup_buddy_role", "photographer")


def test_add_raises_for_unknown_table(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Unknown lookup table"):
        lk.add(conn, "lookup_no_such_table", "x")


def test_update_renames_value(conn: sqlite3.Connection) -> None:
    v = lk.add(conn, "lookup_buddy_role", "photographer")
    lk.update(conn, "lookup_buddy_role", v.id, name="Photographer")
    got = lk.get_by_name(conn, "lookup_buddy_role", "Photographer")
    assert got is not None
    assert got.id == v.id
    # Original lowercase name no longer matches
    assert lk.get_by_name(conn, "lookup_buddy_role", "photographer") is None


def test_update_raises_on_duplicate_name(conn: sqlite3.Connection) -> None:
    lk.add(conn, "lookup_buddy_role", "photographer")
    v2 = lk.add(conn, "lookup_buddy_role", "guide")
    with pytest.raises(sqlite3.IntegrityError):
        lk.update(conn, "lookup_buddy_role", v2.id, name="photographer")


def test_update_raises_for_unknown_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        lk.update(conn, "lookup_buddy_role", 9999, name="x")


def test_soft_delete_hides_from_list_active(conn: sqlite3.Connection) -> None:
    v = lk.add(conn, "lookup_buddy_role", "photographer")
    assert any(x.id == v.id for x in lk.list_active(conn, "lookup_buddy_role"))
    lk.soft_delete(conn, "lookup_buddy_role", v.id)
    assert not any(
        x.id == v.id for x in lk.list_active(conn, "lookup_buddy_role")
    )
    # But still in list_including_inactive
    assert any(
        x.id == v.id and not x.is_active
        for x in lk.list_including_inactive(conn, "lookup_buddy_role")
    )


def test_reactivate_undoes_soft_delete(conn: sqlite3.Connection) -> None:
    v = lk.add(conn, "lookup_buddy_role", "photographer")
    lk.soft_delete(conn, "lookup_buddy_role", v.id)
    lk.reactivate(conn, "lookup_buddy_role", v.id)
    assert any(
        x.id == v.id and x.is_active
        for x in lk.list_active(conn, "lookup_buddy_role")
    )


def test_count_referencing_zero_when_unused(conn: sqlite3.Connection) -> None:
    v = lk.add(conn, "lookup_buddy_role", "photographer")
    assert lk.count_referencing(conn, "lookup_buddy_role", v.id) == 0


def test_count_referencing_counts_dive_buddy_links(
    conn: sqlite3.Connection,
) -> None:
    """A buddy role referenced by a dive_buddy row counts."""
    from open_dive_log.repositories import buddies as b_repo
    from open_dive_log.repositories import dives

    b = b_repo.find_or_create(conn, "Mike", "Smith")
    dive_id = dives.create(conn, dive_date="2026-07-07", dive_time_minutes=45)
    # Get the 'buddy' role id (seeded in 001_init.sql)
    buddy_role = lk.get_by_name(conn, "lookup_buddy_role", "buddy")
    assert buddy_role is not None
    dives.attach_buddies(conn, dive_id, [(b.id, buddy_role.id)])
    assert lk.count_referencing(conn, "lookup_buddy_role", buddy_role.id) == 1


def test_count_referencing_for_table_with_no_refs(
    conn: sqlite3.Connection,
) -> None:
    """A lookup table that nothing references (or that isn't in the
    _REFERENCING_COLUMNS map) returns 0 for any value, no error."""
    v = lk.add(conn, "lookup_purpose", "underwater_photography")
    assert lk.count_referencing(conn, "lookup_purpose", v.id) == 0


# --------------------------------------------------------------- window
def _subprocess_test(source: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a Qt test source in a subprocess. The source should print
    'OK: ...' to indicate success; 'SKIP:' to be skipped.
    """
    bootstrap = (
        "import os, sys\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        "os.environ.setdefault('PYTHONPATH', 'src')\n"
    )
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full = bootstrap + textwrap.dedent(source)
    return subprocess.run(
        [".venv/bin/python", "-c", full],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=timeout,
    )


def test_lookups_window_constructs_with_seeded_data() -> None:
    """The window opens, the left pane lists 12 categories, the
    right pane shows the seeded values for the first one."""
    src = """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.ui.lookups_list_window import (
        LookupsListWindow, LOOKUP_TABLES, CATEGORY_LABELS,
    )
    from open_dive_log.repositories.lookups import (
        list_including_inactive, count_referencing,
    )

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "lookups_window.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            win = LookupsListWindow(c)
            assert win.windowTitle() == "Lookups"
            # 12 categories in the left pane
            assert win._category_list.count() == 12
            # Default selection is row 0
            assert win._model.rowCount() > 0
            # The default table is the first one in LOOKUP_TABLES
            expected = LOOKUP_TABLES[0]
            assert win._model.table() == expected
            # Headers
            for col, expected_label in enumerate(
                ("ID", "Name", "Order", "Active", "Used in")
            ):
                got = win._model.headerData(col, Qt.Orientation.Horizontal)
                assert got == expected_label, f"col {col}: {got!r}"
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: lookups window constructs and lists categories")
    """
    result = _subprocess_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: lookups window constructs and lists categories" in result.stdout


def test_lookups_window_add_edits_soft_delete_reactivate() -> None:
    """Full flow: add a value, edit it, soft-delete it, reactivate it.

    We bypass the modal dialog's exec() loop and drive it directly
    (set the QLineEdit text + call _on_save) so the test doesn't
    need a real event loop or input simulation. The dialog's
    _on_save() does the same work exec() would.
    """
    src = """
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    # Stub QMessageBox.question so the soft-delete confirmation
    # doesn't block the test (auto-confirm "Yes").
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.ui.lookups_list_window import (
        LookupsListWindow, _LookupValueDialog,
    )
    from open_dive_log.repositories.lookups import (
        get_by_name, list_including_inactive,
    )

    # Monkey-patch the dialog class so exec() drives the dialog
    # exactly as a user would: it sets the QLineEdit, calls
    # _on_save() (which validates and accepts), and returns
    # Accepted. We pre-fill the name via a side channel.
    import open_dive_log.ui.lookups_list_window as llw
    next_name = ["cavern"]   # mutable so we can swap before each call
    next_order = [99]
    original_init = llw._LookupValueDialog.__init__
    original_exec = llw._LookupValueDialog.exec
    def fake_init(self, conn, table, *, is_new, existing=None, parent=None):
        original_init(self, conn, table, is_new=is_new, existing=existing, parent=parent)
        # For both add and edit, override the name with next_name[0]
        # so the test can drive the dialog with a known value.
        self._name.setText(next_name[0])
        if is_new:
            self._order.setValue(next_order[0])
    def fake_exec(self):
        # Drive the dialog: validate, accept
        self._on_save()
        return llw.QDialog.DialogCode.Accepted
    llw._LookupValueDialog.__init__ = fake_init
    llw._LookupValueDialog.exec = fake_exec

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "lookups_flow.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            win = LookupsListWindow(c)
            # Select lookup_purpose in the left pane
            for i in range(win._category_list.count()):
                item = win._category_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == "lookup_purpose":
                    win._category_list.setCurrentRow(i)
                    break
            assert win._model.table() == "lookup_purpose"

            # --- Add (next_name="cavern" by default) ---
            pre_count = win._model.rowCount()
            win._on_add()
            assert win._model.rowCount() == pre_count + 1
            assert get_by_name(c, "lookup_purpose", "cavern") is not None

            # --- Edit: swap next_name so the fake_init pre-fills "Cavern dive" ---
            next_name[0] = "Cavern dive"
            # Select the cavern row
            for i in range(win._model.rowCount()):
                if win._model.value_at(i).name == "cavern":
                    win._table.selectRow(i)
                    break
            win._on_edit()
            assert get_by_name(c, "lookup_purpose", "cavern") is None
            assert get_by_name(c, "lookup_purpose", "Cavern dive") is not None

            # --- Soft-delete ---
            for i in range(win._model.rowCount()):
                if win._model.value_at(i).name == "Cavern dive":
                    win._table.selectRow(i)
                    break
            win._on_deactivate()
            found = [v for v in list_including_inactive(c, "lookup_purpose") if v.name == "Cavern dive"]
            assert len(found) == 1
            assert found[0].is_active is False

            # --- Reactivate ---
            for i in range(win._model.rowCount()):
                if win._model.value_at(i).name == "Cavern dive":
                    win._table.selectRow(i)
                    break
            win._on_reactivate()
            found = [v for v in list_including_inactive(c, "lookup_purpose") if v.name == "Cavern dive"]
            assert found[0].is_active is True

            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: add/edit/deactivate/reactivate cycle works")
    """
    result = _subprocess_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: add/edit/deactivate/reactivate cycle works" in result.stdout
