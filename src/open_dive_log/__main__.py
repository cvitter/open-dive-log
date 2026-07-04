"""Entry point for `python -m open_dive_log` and the `open-dive-log` console script."""

import sys

from PySide6.QtWidgets import QApplication

from open_dive_log.db import init_db
from open_dive_log.ui import MainWindow


def main() -> int:
    # Apply any pending migrations BEFORE the main window opens. Safe to
    # call on every launch: it's a no-op if the schema is already current.
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("Open Dive Log")
    app.setOrganizationName("Open Dive Log")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
