"""Main application window. Empty placeholder — UI will be built out in later phases."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QStatusBar, QWidget

from open_dive_log import __version__
from open_dive_log.db import (
    get_sqlite_version,
    get_default_db_path,
    init_db,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Open Dive Log")
        self.resize(900, 600)

        # Make sure the DB exists and the schema is current. Safe to call
        # on every launch — migrations are idempotent.
        schema_version = init_db()

        # Placeholder central widget — replaced by real UI in later phases.
        central = QLabel(
            f"Open Dive Log v{__version__}\n\n"
            f"Python bundled SQLite: {get_sqlite_version()}\n"
            f"Schema version: {schema_version}\n"
            f"Default DB path: {get_default_db_path()}\n\n"
            "(UI not yet implemented)",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        central.setWordWrap(True)
        self.setCentralWidget(central)

        # Status bar — also useful as a smoke test that Qt is alive.
        status = QStatusBar()
        status.showMessage(f"SQLite {get_sqlite_version()} ready, schema v{schema_version}")
        self.setStatusBar(status)
