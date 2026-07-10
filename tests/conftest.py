"""Shared pytest fixtures for open-dive-log.

This conftest is the single source of truth for the test database. The
goal: **no test in this suite can ever read or write the live
``data/open_dive_log.db``.**

Two fixtures, both opt-in:

* :func:`test_db_path` — a path to a fresh, empty SQLite file inside
  ``tmp_path``. Use this when you want to be explicit:

      def test_foo(test_db_path, apply_migrations):
          with db.connect(test_db_path) as conn:
              ...

* :func:`fresh_db` — same as above, plus pre-applies migrations and
  yields a connected ``sqlite3.Connection``. The connection is closed
  and the file deleted automatically. This is the easy-mode default
  for tests that just need a working empty schema:

      def test_foo(fresh_db):
          dives.create(fresh_db, dive_date="2026-07-01", ...)
          assert ...

A safety net is also installed: the autouse :func:`_block_live_db`
fixture monkey-patches :data:`open_dive_log.db.DEFAULT_DB_PATH` to a
non-existent file inside ``tmp_path`` for the duration of the test.
If any code path under test calls ``db.connect()`` with no argument
— the exact mistake the PR #20 synth-data generator made — it opens
the safe fake path, not the real one. The path is restored after
the test.

The autouse fixture is on by default. If a test genuinely needs the
real path (none should), mark it with ``@pytest.mark.allow_live_db``.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from open_dive_log import db


# "Save As" duplicates (foo 2.py, foo 3.py) that text editors drop
# next to tracked files. .gitignore handles the untracked case, but
# pytest 8's gitignore-respecting collector doesn't always skip these
# (literal-space-in-glob edge case). Exclude them by name here so the
# collected test count is the real one.
collect_ignore_glob = ["* 2.py", "* 3.py"]


# Marker: opt out of the live-DB safety net for a single test.
# Usage:  @pytest.mark.allow_live_db
# No tests in the suite should use this. It exists so a future test
# author can explicitly say "I really do want the live path" if that
# ever becomes necessary.
allow_live_db = pytest.mark.allow_live_db


@pytest.fixture(autouse=True)
def _block_live_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """Force :data:`open_dive_log.db.DEFAULT_DB_PATH` to a tmp file.

    Installed as ``autouse`` so every test in the suite benefits.
    Tests that explicitly pass a path to ``db.connect(path)`` are
    unaffected — this only changes the no-argument default.

    Tests marked with ``@pytest.mark.allow_live_db`` opt out. No test
    in the suite should need this; it exists so a future test author
    can explicitly say "I really do want the production path" if that
    ever becomes necessary.
    """
    # Markers live on the node (``request.node``) for both the parent
    # FixtureRequest and the SubRequest that autouse fixtures receive.
    # ``request.keywords`` is the dict pyest populates with marker
    # names, so it's the safe place to read.
    marker_names = set(request.keywords)
    if "allow_live_db" in marker_names:
        # Caller opted out — leave the module-level path alone.
        yield
        return

    fake = tmp_path / "default_db_is_a_trap.db"
    # Never create the file; the point is to make db.connect(None)
    # land somewhere obviously disposable.
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", fake)
    yield
    # monkeypatch undoes the setattr automatically.


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    """A fresh, non-existent path inside tmp_path. Tests create the file
    via ``db.connect(test_db_path)`` themselves.

    Use this when you want to control the connection lifecycle
    (e.g. test cleanup behavior, WAL mode, etc.).
    """
    return tmp_path / "test.db"


@pytest.fixture
def fresh_db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """An empty, migrated SQLite connection.

    The file lives in ``tmp_path`` and is removed automatically when
    the test finishes. Foreign keys are enabled and the row factory
    is set to :class:`sqlite3.Row` (matches what ``db.connect``
    gives you for free).

    Yields
    ------
    sqlite3.Connection
        Ready to use. Caller manages transactions.
    """
    db_path = tmp_path / "fresh.db"
    with db.connect(db_path) as conn:
        db.apply_migrations(conn)
        yield conn
    # The `with` block above has already closed the connection by
    # the time we get here. tmp_path cleanup is automatic.


@pytest.fixture
def live_conn() -> Iterator[sqlite3.Connection]:
    """A connection to the live ``data/open_dive_log.db``.

    Mark the test that uses this with ``@pytest.mark.allow_live_db``;
    otherwise the autouse :func:`_block_live_db` fixture would have
    already monkey-patched ``DEFAULT_DB_PATH`` to a tmp file.

    The path is computed from this file's location and opened with
    an explicit ``db.connect(real_path)`` so the conftest's monkey
    patch of the default path is irrelevant. The connection is in
    SQLite's default mode; tests that use this fixture MUST NOT
    write — the test only proves the live data is well-formed.

    Skips if the live DB doesn't exist (CI runners, fresh clones).
    A test that depends on a real DB can only run where the real
    DB is. The test that uses this fixture should be marked with
    ``@pytest.mark.allow_live_db`` so the skip reason is visible
    in the test report.
    """
    real_path = Path(__file__).resolve().parent.parent / "data" / "open_dive_log.db"
    if not real_path.exists():
        pytest.skip(f"Live DB does not exist at {real_path}; allow_live_db tests are no-ops here")
    with db.connect(real_path) as conn:
        yield conn


# -------------------------------------------------------------------
# Qt subprocess helpers
# -------------------------------------------------------------------
# Several test files run Qt-based UI tests in a subprocess so that a
# crashed Qt plugin (Cocoa on macOS is the recurring offender) doesn't
# take down the whole pytest run. The bootstrap that sets up the
# subprocess environment and starts a QApplication is a single
# source of truth here.

QT_SUBPROCESS_BOOTSTRAP = (
    "import os, sys\n"
    # Drop any inherited PYTHONPATH. The Hermes TUI (and some
    # terminals) sets PYTHONPATH to point at a different Python's
    # site-packages, which contaminates the venv's editable-install
    # .pth file lookup. The bin/run-app.sh launcher does the same.
    "os.environ.pop('PYTHONPATH', None)\n"
    # Force-overwrite (not setdefault) so a parent env that already
    # exports a broken PYTHONPATH doesn't leak into the subprocess.
    "os.environ['PYTHONPATH'] = 'src'\n"
    # Build a QApplication. If it can't init (e.g. a busted plugin
    # dylib in this venv), print SKIP and exit cleanly so the
    # parent test is reported as a skip, not a crash.
    "try:\n"
    "    from PySide6.QtWidgets import QApplication\n"
    "except Exception as e:\n"
    "    print(f'SKIP: PySide6 import failed: {e}')\n"
    "    sys.exit(0)\n"
    "try:\n"
    "    app = QApplication.instance() or QApplication([])\n"
    "except Exception as e:\n"
    "    print(f'SKIP: QApplication init failed: {e}')\n"
    "    sys.exit(0)\n"
    "if app is None:\n"
    "    print('SKIP: QApplication returned None')\n"
    "    sys.exit(0)\n"
    # Probe that Qt actually attached to a plugin. On a fresh venv
    # where libqcocoa.dylib is corrupted (see the README's macOS
    # PySide6 caveat), this raises instead of crashing the runner.
    "try:\n"
    "    _ = app.platformName()\n"
    "except Exception as e:\n"
    "    print(f'SKIP: QApplication.platformName() failed: {e}')\n"
    "    sys.exit(0)\n"
    "print(f'OK: platform = {app.platformName()}')\n"
)


def run_qt_subprocess(
    source: str,
    *,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``source`` as a Python script in a subprocess with the
    Qt-friendly bootstrap applied.

    The subprocess uses the same Python interpreter as the parent
    test process (``sys.executable``), so it works whether the
    parent is a `.venv/bin/python` on a developer's machine or the
    system Python on a CI runner. The project root is the cwd. The
    bootstrap (above) sets up the env and starts a QApplication;
    the ``source`` body runs after that and can call into the
    window classes directly.

    The subprocess is expected to print ``OK: ...`` or ``SKIP: ...``
    on stdout. ``SKIP:`` is treated as a pytest skip by the caller
    (e.g. ``test_lookups.py``); everything else with a non-zero exit
    is a failure.

    The subprocess is given a sanitized environment: the parent's
    ``PYTHONPATH`` is dropped (it often points at a different
    Python's site-packages — e.g. the Hermes TUI sets one to a
    3.11 venv) and replaced with ``src`` so the editable-install
    shim resolves to the project's own source tree. Pass ``env`` to
    override; ``None`` means "use the sanitized default".
    """
    if env is None:
        # Start from the inherited env, then strip and replace
        # PYTHONPATH. Anything else from the parent shell that
        # Python would otherwise pick up (LD_LIBRARY_PATH, etc.) is
        # passed through; this mirrors what `bin/run-app.sh` does.
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONPATH"] = "src"

    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full = QT_SUBPROCESS_BOOTSTRAP + textwrap.dedent(source)
    return subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=timeout,
    )
