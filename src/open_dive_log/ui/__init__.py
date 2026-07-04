"""PySide6 UI layer for Open Dive Log.

Modules here are pure UI; they call into `open_dive_log.repositories` for
data. Each module takes a sqlite3 connection (or a "connection factory")
so test code can wire it up against a temp DB without booting Qt.
"""

from .cert_add_edit_dialog import CertAddEditDialog
from .cert_list_window import CertListWindow
from .dive_add_edit_dialog import DiveAddEditDialog
from .dive_detail_dialog import DiveDetailDialog
from .dive_table_model import DiveTableModel
from .main_window import MainWindow
from .sites_list_window import SitesListWindow

__all__ = [
    "CertAddEditDialog",
    "CertListWindow",
    "DiveAddEditDialog",
    "DiveDetailDialog",
    "DiveTableModel",
    "MainWindow",
    "SitesListWindow",
]
