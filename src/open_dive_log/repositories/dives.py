"""Dive repository — create dives, attach sites and buddies, query.

This is the entry point the UI calls. The repositories for site/buddy are
composed in so the caller only deals with one module.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from . import buddies, sites


@dataclass(frozen=True, slots=True)
class Dive:
    id: int
    dive_date: str
    start_time: str | None
    end_time: str | None
    dive_time_minutes: int | None
    notes: str | None


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create(
    conn: sqlite3.Connection,
    *,
    dive_date: str,
    start_time: str | None = None,
    end_time: str | None = None,
    dive_time_minutes: int | None = None,
    time_of_day_id: int | None = None,
    entry_type_id: int | None = None,
    entry_notes: str | None = None,
    surface_conditions_id: int | None = None,
    surface_conditions_notes: str | None = None,
    run_time_minutes: int | None = None,
    max_depth_m: float | None = None,
    avg_depth_m: float | None = None,
    equipment_type_id: int | None = None,
    tank_type_id: int | None = None,
    tank_configuration_id: int | None = None,
    gas_type_id: int | None = None,
    o2_percentage: float | None = None,
    mix_notes: str | None = None,
    gear_notes: str | None = None,
    purpose_id: int | None = None,
    notes: str | None = None,
) -> int:
    """Insert a new dive row. Returns the new id. Caller manages transaction."""
    cur = conn.execute(
        """
        INSERT INTO dive (
            dive_date, start_time, end_time, dive_time_minutes, time_of_day_id,
            entry_type_id, entry_notes,
            surface_conditions_id, surface_conditions_notes,
            run_time_minutes,
            max_depth_m, avg_depth_m,
            equipment_type_id, tank_type_id, tank_configuration_id, gas_type_id,
            o2_percentage, mix_notes, gear_notes,
            purpose_id, notes
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?
        )
        """,
        (
            dive_date, start_time, end_time, dive_time_minutes, time_of_day_id,
            entry_type_id, entry_notes,
            surface_conditions_id, surface_conditions_notes,
            run_time_minutes,
            max_depth_m, avg_depth_m,
            equipment_type_id, tank_type_id, tank_configuration_id, gas_type_id,
            o2_percentage, mix_notes, gear_notes,
            purpose_id, notes,
        ),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Attach sites (ordered)
# ---------------------------------------------------------------------------
def attach_sites(
    conn: sqlite3.Connection, dive_id: int, site_ids: Sequence[int]
) -> None:
    """Attach a sequence of site_ids to a dive in the given order.

    site_ids[0] -> site_order=1, site_ids[1] -> site_order=2, etc.
    Replaces any existing dive_site rows for this dive.
    """
    conn.execute("DELETE FROM dive_site WHERE dive_id = ?", (dive_id,))
    for order, site_id in enumerate(site_ids, start=1):
        conn.execute(
            "INSERT INTO dive_site (dive_id, site_id, site_order) VALUES (?, ?, ?)",
            (dive_id, site_id, order),
        )


def get_sites(conn: sqlite3.Connection, dive_id: int) -> list[Site]:
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.region, s.country, s.country_code,
               s.latitude, s.longitude, s.sea_mrgid, s.max_depth_m,
               s.environment_id, s.entry_id,
               s.description, s.description_wildlife, s.notes
        FROM dive_site ds
        JOIN site s ON s.id = ds.site_id
        WHERE ds.dive_id = ?
        ORDER BY ds.site_order
        """,
        (dive_id,),
    ).fetchall()
    return [
        sites.Site(
            r["id"], r["name"], r["region"], r["country"],
            r["country_code"], None,        # country_name (no JOIN in this query)
            r["latitude"], r["longitude"],
            r["sea_mrgid"], None,           # sea_name
            r["environment_id"], None,      # environment_name
            r["entry_id"], None,            # entry_name
            r["max_depth_m"],
            r["description"] if "description" in r.keys() else None,
            r["description_wildlife"] if "description_wildlife" in r.keys() else None,
            r["notes"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Attach buddies
# ---------------------------------------------------------------------------
def attach_buddies(
    conn: sqlite3.Connection,
    dive_id: int,
    buddy_inputs: Sequence[tuple[int, int | None]],
) -> None:
    """Attach (buddy_id, role_id) pairs to a dive. Replaces existing rows."""
    conn.execute("DELETE FROM dive_buddy WHERE dive_id = ?", (dive_id,))
    for buddy_id, role_id in buddy_inputs:
        conn.execute(
            "INSERT INTO dive_buddy (dive_id, buddy_id, role_id) VALUES (?, ?, ?)",
            (dive_id, buddy_id, role_id),
        )


def add_buddy_to_dive(
    conn: sqlite3.Connection,
    dive_id: int,
    first_name: str,
    last_name: str,
    *,
    role_id: int | None = None,
) -> int:
    """Convenience: find-or-create the buddy, then attach. Returns buddy_id."""
    buddy = buddies.find_or_create(conn, first_name, last_name)
    conn.execute(
        "INSERT OR IGNORE INTO dive_buddy (dive_id, buddy_id, role_id) VALUES (?, ?, ?)",
        (dive_id, buddy.id, role_id),
    )
    return buddy.id


def get_buddies(conn: sqlite3.Connection, dive_id: int) -> list[Buddy]:
    rows = conn.execute(
        """
        SELECT b.id, b.first_name, b.last_name, b.full_name, db.role_id
        FROM dive_buddy db
        JOIN buddy b ON b.id = db.buddy_id
        WHERE db.dive_id = ?
        ORDER BY b.last_name, b.first_name
        """,
        (dive_id,),
    ).fetchall()
    return [
        buddies.Buddy(r["id"], r["first_name"], r["last_name"], r["full_name"])
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
def get(conn: sqlite3.Connection, dive_id: int) -> Dive | None:
    row = conn.execute(
        "SELECT id, dive_date, start_time, end_time, dive_time_minutes, notes "
        "FROM dive WHERE id = ?",
        (dive_id,),
    ).fetchone()
    if row is None:
        return None
    return Dive(
        row["id"], row["dive_date"], row["start_time"], row["end_time"],
        row["dive_time_minutes"], row["notes"],
    )


def list_recent(conn: sqlite3.Connection, limit: int = 50) -> list[Dive]:
    rows = conn.execute(
        "SELECT id, dive_date, start_time, end_time, dive_time_minutes, notes "
        "FROM dive ORDER BY dive_date DESC, start_time DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        Dive(r["id"], r["dive_date"], r["start_time"], r["end_time"],
             r["dive_time_minutes"], r["notes"])
        for r in rows
    ]
