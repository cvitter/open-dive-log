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
    """Lightweight dive row for the list view. Has only the 6 fields shown
    in the main window's table."""
    id: int
    dive_date: str
    start_time: str | None
    end_time: str | None
    dive_time_minutes: int | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class DiveFull:
    """All 25 user-input fields on a dive, plus the bookkeeping timestamps.

    Used by the add/edit form and the detail dialog. The list view uses
    `Dive` (or the dict-shaped output of `list_recent_with_sites`) to
    avoid the heavier join.
    """
    # when
    id: int
    dive_date: str
    start_time: str | None
    end_time: str | None
    dive_time_minutes: int | None
    time_of_day_id: int | None
    # entry
    entry_type_id: int | None
    entry_notes: str | None
    # surface
    surface_conditions_id: int | None
    surface_conditions_notes: str | None
    run_time_minutes: int | None
    # depth (stored in meters)
    max_depth_m: float | None
    avg_depth_m: float | None
    # conditions (metric)
    air_temp_c: float | None
    water_temp_c: float | None
    visibility_m: float | None
    # tank pressure (stored in BAR)
    start_pressure_bar: float | None
    end_pressure_bar: float | None
    # equipment
    equipment_type_id: int | None
    tank_type_id: int | None
    tank_configuration_id: int | None
    gas_type_id: int | None
    o2_percentage: float | None
    mix_notes: str | None
    gear_notes: str | None
    # purpose
    purpose_id: int | None
    notes: str | None
    # bookkeeping
    created_at: str
    updated_at: str


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
    air_temp_c: float | None = None,
    water_temp_c: float | None = None,
    visibility_m: float | None = None,
    start_pressure_bar: float | None = None,
    end_pressure_bar: float | None = None,
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
            air_temp_c, water_temp_c, visibility_m,
            start_pressure_bar, end_pressure_bar,
            equipment_type_id, tank_type_id, tank_configuration_id, gas_type_id,
            o2_percentage, mix_notes, gear_notes,
            purpose_id, notes
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?,
            ?, ?,
            ?, ?, ?,
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
            air_temp_c, water_temp_c, visibility_m,
            start_pressure_bar, end_pressure_bar,
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


def list_recent_with_sites(
    conn: sqlite3.Connection, limit: int = 500
) -> list[dict]:
    """Return one row per dive, with the comma-joined site names.

    The list view needs (dive_id, date, time, sites, max_depth) without
    a second round-trip per row. The GROUP_CONCAT keeps it to a single
    query. For dives with multiple sites, they're returned in site_order.

    Also returns the new conditions columns (air_temp_c, water_temp_c,
    visibility_m) so the list view can render them when the user is in
    imperial mode. The fields are metric in the DB; the list view does
    the conversion at display time.

    Returned dict shape (stable for the UI layer):
        {
            "id": int,
            "dive_date": str,
            "start_time": str | None,
            "end_time": str | None,
            "dive_time_minutes": int | None,
            "max_depth_m": float | None,
            "avg_depth_m": float | None,
            "air_temp_c": float | None,
            "water_temp_c": float | None,
            "visibility_m": float | None,
            "start_pressure_bar": float | None,
            "end_pressure_bar": float | None,
            "sites": str,         # "Salt Pier, Karpata" or "" if none
        }
    """
    rows = conn.execute(
        """
        SELECT
            d.id, d.dive_date, d.start_time, d.end_time,
            d.dive_time_minutes, d.max_depth_m, d.avg_depth_m,
            d.air_temp_c, d.water_temp_c, d.visibility_m,
            d.start_pressure_bar, d.end_pressure_bar,
            GROUP_CONCAT(s.name, ', ') AS sites
        FROM dive d
        LEFT JOIN dive_site ds ON ds.dive_id = d.id
        LEFT JOIN site s ON s.id = ds.site_id
        GROUP BY d.id
        ORDER BY d.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "dive_date": r["dive_date"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "dive_time_minutes": r["dive_time_minutes"],
            "max_depth_m": r["max_depth_m"],
            "avg_depth_m": r["avg_depth_m"],
            "air_temp_c": r["air_temp_c"],
            "water_temp_c": r["water_temp_c"],
            "visibility_m": r["visibility_m"],
            "start_pressure_bar": r["start_pressure_bar"],
            "end_pressure_bar": r["end_pressure_bar"],
            "sites": r["sites"] or "",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Update + delete + full-row read (used by the add/edit form)
# ---------------------------------------------------------------------------
_FULL_COLS = (
    "id, dive_date, start_time, end_time, dive_time_minutes, time_of_day_id, "
    "entry_type_id, entry_notes, "
    "surface_conditions_id, surface_conditions_notes, run_time_minutes, "
    "max_depth_m, avg_depth_m, "
    "air_temp_c, water_temp_c, visibility_m, "
    "start_pressure_bar, end_pressure_bar, "
    "equipment_type_id, tank_type_id, tank_configuration_id, gas_type_id, "
    "o2_percentage, mix_notes, gear_notes, "
    "purpose_id, notes, "
    "created_at, updated_at"
)


def get_full(conn: sqlite3.Connection, dive_id: int) -> DiveFull | None:
    row = conn.execute(
        f"SELECT {_FULL_COLS} FROM dive WHERE id = ?", (dive_id,)
    ).fetchone()
    if row is None:
        return None
    return DiveFull(
        id=row["id"],
        dive_date=row["dive_date"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        dive_time_minutes=row["dive_time_minutes"],
        time_of_day_id=row["time_of_day_id"],
        entry_type_id=row["entry_type_id"],
        entry_notes=row["entry_notes"],
        surface_conditions_id=row["surface_conditions_id"],
        surface_conditions_notes=row["surface_conditions_notes"],
        run_time_minutes=row["run_time_minutes"],
        max_depth_m=row["max_depth_m"],
        avg_depth_m=row["avg_depth_m"],
        air_temp_c=row["air_temp_c"],
        water_temp_c=row["water_temp_c"],
        visibility_m=row["visibility_m"],
        start_pressure_bar=row["start_pressure_bar"],
        end_pressure_bar=row["end_pressure_bar"],
        equipment_type_id=row["equipment_type_id"],
        tank_type_id=row["tank_type_id"],
        tank_configuration_id=row["tank_configuration_id"],
        gas_type_id=row["gas_type_id"],
        o2_percentage=row["o2_percentage"],
        mix_notes=row["mix_notes"],
        gear_notes=row["gear_notes"],
        purpose_id=row["purpose_id"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def update(
    conn: sqlite3.Connection,
    dive_id: int,
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
    air_temp_c: float | None = None,
    water_temp_c: float | None = None,
    visibility_m: float | None = None,
    start_pressure_bar: float | None = None,
    end_pressure_bar: float | None = None,
    equipment_type_id: int | None = None,
    tank_type_id: int | None = None,
    tank_configuration_id: int | None = None,
    gas_type_id: int | None = None,
    o2_percentage: float | None = None,
    mix_notes: str | None = None,
    gear_notes: str | None = None,
    purpose_id: int | None = None,
    notes: str | None = None,
) -> None:
    """Update an existing dive row. Raises LookupError if not found.

    Does NOT touch dive_site / dive_buddy — those have their own replace
    semantics (`attach_sites`, `attach_buddies`).
    """
    cur = conn.execute(
        """
        UPDATE dive SET
            dive_date = ?, start_time = ?, end_time = ?,
            dive_time_minutes = ?, time_of_day_id = ?,
            entry_type_id = ?, entry_notes = ?,
            surface_conditions_id = ?, surface_conditions_notes = ?,
            run_time_minutes = ?,
            max_depth_m = ?, avg_depth_m = ?,
            air_temp_c = ?, water_temp_c = ?, visibility_m = ?,
            start_pressure_bar = ?, end_pressure_bar = ?,
            equipment_type_id = ?, tank_type_id = ?,
            tank_configuration_id = ?, gas_type_id = ?,
            o2_percentage = ?, mix_notes = ?, gear_notes = ?,
            purpose_id = ?, notes = ?
        WHERE id = ?
        """,
        (
            dive_date, start_time, end_time,
            dive_time_minutes, time_of_day_id,
            entry_type_id, entry_notes,
            surface_conditions_id, surface_conditions_notes,
            run_time_minutes,
            max_depth_m, avg_depth_m,
            air_temp_c, water_temp_c, visibility_m,
            start_pressure_bar, end_pressure_bar,
            equipment_type_id, tank_type_id,
            tank_configuration_id, gas_type_id,
            o2_percentage, mix_notes, gear_notes,
            purpose_id, notes,
            dive_id,
        ),
    )
    if cur.rowcount == 0:
        raise LookupError(f"No dive with id {dive_id}")


def delete(conn: sqlite3.Connection, dive_id: int) -> None:
    """Delete a dive. Cascades to dive_site and dive_buddy via FK rules."""
    cur = conn.execute("DELETE FROM dive WHERE id = ?", (dive_id,))
    if cur.rowcount == 0:
        raise LookupError(f"No dive with id {dive_id}")


# ---------------------------------------------------------------------------
# Picker helpers — used by the add/edit form's site and buddy pickers.
# These return lightweight (id, label) tuples for the form's comboboxes
# and lists. They don't need the full Site / Buddy dataclass because
# the form only needs to display and re-attach ids.
# ---------------------------------------------------------------------------
def list_sites_for_picker(
    conn: sqlite3.Connection, query: str = "", limit: int = 500
) -> list[tuple[int, str]]:
    """Return (id, display_label) for sites matching `query` (substring on
    name and country). Sorted alphabetically. The display label is
    "Name (Country)" or just "Name" if no country is set."""
    if query.strip():
        like = f"%{query.strip()}%"
        rows = conn.execute(
            """
            SELECT s.id, s.name, c.name AS country_name
            FROM site s
            LEFT JOIN country c ON c.code = s.country_code
            WHERE s.name LIKE ? OR c.name LIKE ?
            ORDER BY s.name
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT s.id, s.name, c.name AS country_name
            FROM site s
            LEFT JOIN country c ON c.code = s.country_code
            ORDER BY s.name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        (r["id"], f"{r['name']} ({r['country_name']})" if r["country_name"] else r["name"])
        for r in rows
    ]


def list_buddies_for_picker(
    conn: sqlite3.Connection, query: str = "", limit: int = 500
) -> list[tuple[int, str]]:
    """Return (id, full_name) for buddies matching `query` (substring on
    full_name, case-insensitive). Sorted by full_name."""
    if query.strip():
        like = f"%{query.strip()}%"
        rows = conn.execute(
            """
            SELECT id, full_name FROM buddy
            WHERE full_name LIKE ?
            ORDER BY full_name
            LIMIT ?
            """,
            (like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, full_name FROM buddy ORDER BY full_name LIMIT ?",
            (limit,),
        ).fetchall()
    return [(r["id"], r["full_name"]) for r in rows]


def get_buddies_with_roles(
    conn: sqlite3.Connection, dive_id: int
) -> list[tuple[int, str, int | None]]:
    """For the form: return [(buddy_id, full_name, role_id)] for the dive,
    joined with buddy, sorted by last_name. The role_id may be None if
    the join row was created without a role."""
    rows = conn.execute(
        """
        SELECT b.id, b.full_name, db.role_id
        FROM dive_buddy db
        JOIN buddy b ON b.id = db.buddy_id
        WHERE db.dive_id = ?
        ORDER BY b.last_name, b.first_name
        """,
        (dive_id,),
    ).fetchall()
    return [(r["id"], r["full_name"], r["role_id"]) for r in rows]


def get_sites_ordered(
    conn: sqlite3.Connection, dive_id: int
) -> list[tuple[int, str]]:
    """For the form: return [(site_id, name)] in site_order."""
    rows = conn.execute(
        """
        SELECT s.id, s.name
        FROM dive_site ds
        JOIN site s ON s.id = ds.site_id
        WHERE ds.dive_id = ?
        ORDER BY ds.site_order
        """,
        (dive_id,),
    ).fetchall()
    return [(r["id"], r["name"]) for r in rows]
