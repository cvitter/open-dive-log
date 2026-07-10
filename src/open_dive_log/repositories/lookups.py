"""Lookup table access. All lookups share the same shape and access pattern
(id, name, display_order, is_active), so this module serves all of them.
"""

from __future__ import annotations

import sqlite3
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
    "lookup_certifying_agency",
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


# Which column in which other table references each lookup. Used by
# `count_referencing` and `is_referenced` below to give the user
# accurate "this value is used in N places" warnings.
_REFERENCING_COLUMNS: dict[str, tuple[str, str, ...]] = {
    "lookup_time_of_day":          ("dive.time_of_day_id",),
    "lookup_entry_type":           ("dive.entry_type_id", "site.entry_id"),
    "lookup_surface_conditions":   ("dive.surface_conditions_id",),
    "lookup_equipment_type":       ("dive.equipment_type_id",),
    "lookup_tank_type":            ("dive.tank_type_id",),
    "lookup_tank_configuration":   ("dive.tank_configuration_id",),
    "lookup_gas_type":             ("dive.gas_type_id",),
    "lookup_purpose":              ("dive.purpose_id",),
    "lookup_buddy_role":           ("dive_buddy.role_id",),
    "lookup_site_environment":     ("site.environment_id",),
    "lookup_site_topology":        ("site_site_topology.topology_id",),
    "lookup_certifying_agency":    ("certification.certifying_agency_id",),
}


def _qualify_col(col: str) -> tuple[str, str]:
    """Split 'table.column' into (table, column) for SQL building."""
    t, c = col.split(".", 1)
    return t, c


def count_referencing(
    conn: sqlite3.Connection, table: str, value_id: int
) -> int:
    """How many rows in any table reference this lookup value.

    Walks all `REFERENCES lookup_X(id)` columns in the schema and
    sums up the rows where the FK equals `value_id`. Returns 0 for
    lookup tables that aren't referenced by anything (so the UI
    always has a number to show).
    """
    cols = _REFERENCING_COLUMNS.get(table, ())
    total = 0
    for col in cols:
        t, c = _qualify_col(col)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {t} WHERE {c} = ?",
            (value_id,),
        ).fetchone()
        total += int(row["n"])
    return total


def update(
    conn: sqlite3.Connection,
    table: str,
    value_id: int,
    *,
    name: str,
    display_order: int | None = None,
) -> None:
    """Update a lookup value's name (and optionally its display_order).

    Raises LookupError if the value doesn't exist. Raises
    sqlite3.IntegrityError if the new name collides with another row
    in the same table (the table has a UNIQUE constraint on name).
    """
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    if display_order is None:
        # Only update the name; leave display_order alone.
        cur = conn.execute(
            f"UPDATE {table} SET name = ? WHERE id = ?",
            (name, value_id),
        )
    else:
        cur = conn.execute(
            f"UPDATE {table} SET name = ?, display_order = ? WHERE id = ?",
            (name, display_order, value_id),
        )
    if cur.rowcount == 0:
        # rowcount can be 0 if the new values match the old ones
        # (SQLite optimization), so check existence separately.
        exists = conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (value_id,),
        ).fetchone()
        if exists is None:
            raise LookupError(f"No {table} row with id {value_id}")


def soft_delete(
    conn: sqlite3.Connection, table: str, value_id: int
) -> None:
    """Set is_active = 0 (soft-delete) so the value disappears from
    dropdowns but historical FK references still resolve.

    We never hard-delete lookup rows because every referenced table
    has `ON DELETE RESTRICT` (the default) and the user has no way
    in the UI to clear every reference. Soft-delete keeps history
    intact and lets the user re-activate later if they want.
    """
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    cur = conn.execute(
        f"UPDATE {table} SET is_active = 0 WHERE id = ?",
        (value_id,),
    )
    if cur.rowcount == 0:
        exists = conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (value_id,),
        ).fetchone()
        if exists is None:
            raise LookupError(f"No {table} row with id {value_id}")


def list_including_inactive(
    conn: sqlite3.Connection, table: str
) -> list[LookupValue]:
    """All values for a table, active and inactive, for the admin view."""
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    rows = conn.execute(
        f"SELECT id, name, display_order, is_active FROM {table} "
        "ORDER BY display_order, name"
    ).fetchall()
    return [LookupValue(r["id"], r["name"], r["display_order"], bool(r["is_active"])) for r in rows]


def reactivate(
    conn: sqlite3.Connection, table: str, value_id: int) -> None:
    """Undo a soft-delete. Resets is_active = 1 so the value
    reappears in dropdowns again."""
    if table not in LOOKUP_TABLES:
        raise ValueError(f"Unknown lookup table: {table!r}")
    cur = conn.execute(
        f"UPDATE {table} SET is_active = 1 WHERE id = ?",
        (value_id,),
    )
    if cur.rowcount == 0:
        exists = conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (value_id,),
        ).fetchone()
        if exists is None:
            raise LookupError(f"No {table} row with id {value_id}")
