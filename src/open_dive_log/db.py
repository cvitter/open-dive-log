"""SQLite access layer.

The application database lives at <project>/data/open_dive_log.db.
This module is the only place that should open a sqlite3 connection — UI and
business-logic layers call helpers here so we can centralize PRAGMAs,
connection settings, and the WAL journal mode in one spot.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Project root: src/open_dive_log/db.py -> parents[2] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "open_dive_log.db"

REQUIRED_SQLITE_VERSION = (3, 53, 0)


def get_sqlite_version() -> str:
    """Return the SQLite version compiled into this Python build."""
    return sqlite3.sqlite_version


def assert_sqlite_version() -> None:
    """Raise if the bundled SQLite is older than the required minimum."""
    current = tuple(int(p) for p in sqlite3.sqlite_version.split("."))
    if current < REQUIRED_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite {REQUIRED_SQLITE_VERSION[0]}.{REQUIRED_SQLITE_VERSION[1]}.x required, "
            f"got {sqlite3.sqlite_version}"
        )


def get_default_db_path() -> Path:
    return DEFAULT_DB_PATH


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a sqlite3 connection with sensible defaults.

    Enables WAL journal mode and foreign keys. Caller is responsible for
    transactions (use `with conn:` blocks).
    """
    if db_path is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = DEFAULT_DB_PATH

    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # autocommit; we manage txns explicitly
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()
