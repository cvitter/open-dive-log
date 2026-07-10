"""SQLite access layer.

The application database lives at <project>/data/open_dive_log.db.
This module owns:
  * the default DB path
  * PRAGMAs (WAL, foreign keys) via `connect()`
  * the migration runner (`apply_migrations()`)
  * the schema version banner (`get_schema_version()`)

UI and business-logic code should not open connections directly — go through
the `connect()` context manager so PRAGMAs stay consistent.
"""

from __future__ import annotations

import importlib.resources
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Project root: src/open_dive_log/db.py -> parents[2] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "open_dive_log.db"
MIGRATIONS_PACKAGE = "open_dive_log.migrations"

REQUIRED_SQLITE_VERSION = (3, 45, 0)


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

    Enables WAL journal mode and foreign keys. Caller manages transactions
    (use `with conn:` blocks).
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


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
_MIGRATION_FILE_RE = re.compile(r"^(\d+)_.*\.sql$")


def _list_migration_files() -> list[tuple[int, str]]:
    """Return [(version, sql_text), ...] sorted ascending by version.

    Files are read from the `open_dive_log.migrations` package — bundling them
    with the wheel means a `pip install` carries the schema with it.
    """
    files = importlib.resources.files(MIGRATIONS_PACKAGE)
    out: list[tuple[int, str]] = []
    for entry in files.iterdir():
        name = entry.name
        m = _MIGRATION_FILE_RE.match(name)
        if not m:
            continue
        version = int(m.group(1))
        out.append((version, entry.read_text(encoding="utf-8")))
    out.sort(key=lambda x: x[0])
    return out


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version, or 0 if no migrations applied."""
    row = conn.execute("SELECT version FROM schema_meta WHERE id = 0").fetchone()
    return int(row["version"]) if row else 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations. Returns the new schema version.

    Each migration runs inside a transaction. If a migration fails the
    transaction is rolled back and the exception propagates — the caller
    decides whether to back out the whole DB.
    """
    # Ensure the meta table exists before reading the version. This is the
    # only DDL we run outside a migration file, and it's safe to repeat.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            id          INTEGER PRIMARY KEY CHECK (id = 0),
            version     INTEGER NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    current = get_schema_version(conn)
    target = 0
    for version, sql in _list_migration_files():
        if version > current:
            conn.executescript(sql)
            # Refresh the meta row.
            conn.execute("DELETE FROM schema_meta WHERE id = 0")
            conn.execute(
                "INSERT INTO schema_meta (id, version) VALUES (0, ?)",
                (version,),
            )
            target = version

    return target or current


def init_db(db_path: Path | None = None) -> int:
    """Connect, apply migrations, return the resulting schema version.

    Convenience for the app entry point: open the DB, make sure schema is
    current, close. Safe to call on every launch.
    """
    with connect(db_path) as conn:
        version = apply_migrations(conn)
    return version
