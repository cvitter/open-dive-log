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


def test_init_db_creates_db_with_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: init_db() on a fresh path produces a usable, migrated DB."""
    target = tmp_path / "fresh.db"
    assert not target.exists()
    version = db.init_db(target)
    assert version >= 1
    assert target.exists()
    with db.connect(target) as c:
        tables = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert {"dive", "site", "buddy", "dive_site", "dive_buddy", "schema_meta",
                "country", "site_source", "site_external_id",
                "lookup_site_environment", "lookup_site_topology", "site_site_topology"
               }.issubset(tables)
    v2 = db.init_db(target)
    assert v2 == version
