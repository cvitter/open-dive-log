"""Smoke tests for the SQLite access layer."""

import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db


def test_bundled_sqlite_meets_minimum() -> None:
    db.assert_sqlite_version()
    version = tuple(int(p) for p in db.get_sqlite_version().split("."))
    assert version >= db.REQUIRED_SQLITE_VERSION


def test_connect_creates_db_and_enables_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    with db.connect(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert mode.lower() == "wal"
    assert fk == 1
    assert db_path.exists()


def test_default_db_path_under_data_dir() -> None:
    default = db.get_default_db_path()
    assert default.parent.name == "data"
    assert default.name == "open_dive_log.db"
