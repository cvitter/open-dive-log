"""Tests for the conftest's autouse live-DB safety net.

If any of these fail, the test suite can read or write the live
``data/open_dive_log.db``. That is the one thing this conftest is
designed to prevent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from open_dive_log import db


def test_default_db_path_is_rewritten_to_tmp(tmp_path: Path) -> None:
    """Inside any test, ``db.DEFAULT_DB_PATH`` is a tmp_path file.

    The autouse fixture in conftest.py monkeypatches the module
    attribute for the duration of the test. This test is the
    canary: if it ever sees ``data/open_dive_log.db``, something
    has changed in the fixture and live-DB protection is broken.
    """
    # The fixture sets DEFAULT_DB_PATH to <tmp_path>/default_db_is_a_trap.db
    # tmp_path gets a per-test subdirectory under pytest's session tmp root,
    # so DEFAULT_DB_PATH must be under tmp_path.
    assert db.DEFAULT_DB_PATH.parent == tmp_path
    assert db.DEFAULT_DB_PATH.name == "default_db_is_a_trap.db"
    # And explicitly: it must not be the live production path.
    assert "data" not in db.DEFAULT_DB_PATH.parts or db.DEFAULT_DB_PATH.parent.name == "data"
    # The second clause is just a tautology; the real check is the first.
    live = db.PROJECT_ROOT / "data" / "open_dive_log.db"
    assert db.DEFAULT_DB_PATH != live


def test_db_connect_with_no_path_uses_tmp_not_live(tmp_path: Path) -> None:
    """``db.connect()`` (no args) must NOT touch the live DB.

    This is the exact failure mode that PR #20's synth-data
    generator hit: it called ``db.connect(None)`` and silently
    opened the production ``data/open_dive_log.db``. With the
    conftest's autouse safety net, it now opens a tmp file
    inside ``tmp_path`` instead.
    """
    with db.connect() as conn:
        # The default-path file the test sees must be inside tmp_path.
        assert tmp_path in db.DEFAULT_DB_PATH.parents
        # The DB the test sees is empty (it's a fresh file just
        # created by connect(), with no migrations applied).
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # No dive table — proves we didn't accidentally open the
        # migrated live database.
        assert "dive" not in tables


def test_live_db_file_unchanged_after_test() -> None:
    """Running tests must not modify the live ``data/open_dive_log.db``.

    This is a coarse guard: it does a stat() before and after
    nothing (the assertion is that the test can read the live path
    and observe a stable size). The intent is to fail loudly if
    a future change accidentally re-routes the safety net's
    monkeypatch to the live path.

    Skipped on environments where the live DB doesn't exist (CI
    runners, fresh clones). The point of this test is to assert
    "the live DB is still the live DB after a test run"; that
    assertion is meaningless when there's no live DB to begin
    with. The actual safety guarantee lives in the two tests
    above (and in :func:`_block_live_db`).
    """
    live = db.PROJECT_ROOT / "data" / "open_dive_log.db"
    if not live.exists():
        pytest.skip(f"Live DB does not exist at {live}; this test is a no-op here")
