"""Lookup table access. All lookups share the same shape and access pattern
(id, name, display_order, is_active), so this module serves all of them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass


# Names of the lookup_<field> tables in the schema.
LOOKUP_TABLES: tuple[str, ...] = (
    "lookup_time_of_day",
    "lookup_entry_type",
    "lookup_surface_conditions",
    "lookup_equipment_type",
    "lookup_tank_type",
    "lookup_tank_configuration",
    "lookup_gas_type",
    "lookup_purpose",
    "lookup_buddy_role",
    "lookup_site_environment",
    "lookup_site_topology",
)


@dataclass(frozen=True, slots=True)
class LookupValue:
    id: int
    name: str
    display_order: int
    is_active: bool


def list_active(conn: sqlite3.Connection, table: str) -> list[LookupValue]:
    """Return active lookup values for a table, ordered for UI display."""
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    rows = conn.execute(
        f"SELECT id, name, display_order, is_active FROM {table} "
        "WHERE is_active = 1 ORDER BY display_order, name"
    ).fetchall()
    return [LookupValue(r["id"], r["name"], r["display_order"], bool(r["is_active"])) for r in rows]


def get_by_name(conn: sqlite3.Connection, table: str, name: str) -> LookupValue | None:
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    row = conn.execute(
        f"SELECT id, name, display_order, is_active FROM {table} WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    return LookupValue(row["id"], row["name"], row["display_order"], bool(row["is_active"]))


def add(
    conn: sqlite3.Connection,
    table: str,
    name: str,
    display_order: int = 100,
) -> LookupValue:
    """Insert a new lookup value. Raises if the name is already taken."""
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    cur = conn.execute(
        f"INSERT INTO {table} (name, display_order) VALUES (?, ?)",
        (name, display_order),
    )
    return LookupValue(cur.lastrowid, name, display_order, True)
