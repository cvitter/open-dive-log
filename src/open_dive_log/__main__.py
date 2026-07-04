"""Entry point for `python -m open_dive_log` and the `open-dive-log` console script."""

import sys

from PySide6.QtWidgets import QApplication

from open_dive_log.app import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Open Dive Log")
    app.setOrganizationName("Open Dive Log")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
