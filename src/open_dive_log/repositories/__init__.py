"""Repositories — typed access to the schema for app code.

Each repository takes a `sqlite3.Connection` so the app layer can compose
operations across repos inside a single transaction.
"""

from . import buddies, dives, lookups, sites

__all__ = ["buddies", "dives", "lookups", "sites"]
