"""Dive repository — create dives, attach sites and buddies, query.

This is the entry point the UI calls. The repositories for site/buddy are
composed in so the caller only deals with one module.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import buddies, sites

if TYPE_CHECKING:
    from .buddies import Buddy
    from .sites import Site


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


def is_empty(conn: sqlite3.Connection) -> bool:
    """Return True if the `dive` table contains no rows.

    Uses a lightweight `SELECT 1 ... LIMIT 1` for minimal overhead.
    """
    row = conn.execute("SELECT 1 FROM dive LIMIT 1").fetchone()
    return row is None


@dataclass(frozen=True, slots=True)
class DiveStats:
    """Aggregated dive-book statistics for the Stats screen.

    All time fields are minutes. All depth fields are meters — the
    UI converts to the user's unit system on display. Distinct-sites
    and distinct-countries count dives with a site attached (sites
    without a country_code or in a country with no name still count
    toward the site total but not toward the country total).

    `dive_count` is the total number of dive rows; `dive_time_count`
    is how many have a non-NULL `dive_time_minutes` (so avg/total/min/
    max ignore dives with no time recorded).
    """
    dive_count: int
    dive_time_count: int
    longest_minutes: int | None
    shortest_minutes: int | None
    average_minutes: float | None
    total_minutes: int | None
    deepest_m: float | None
    average_depth_m: float | None
    distinct_sites: int
    distinct_countries: int


def compute_stats(conn: sqlite3.Connection) -> DiveStats:
    """Run the aggregation queries for the Stats screen.

    Each subquery is independent; we don't try to fold them into a
    single SELECT (SQLite supports that, but the result is harder to
    read and the per-statement cost is tiny at this scale).
    """
    # Time aggregates (only dives with a recorded time)
    time_row = conn.execute(
        "SELECT COUNT(*) AS c, MIN(dive_time_minutes) AS lo, "
        "       MAX(dive_time_minutes) AS hi, AVG(dive_time_minutes) AS avg, "
        "       SUM(dive_time_minutes) AS total "
        "FROM dive WHERE dive_time_minutes IS NOT NULL"
    ).fetchone()

    # Depth aggregates — max is "deepest"; avg is "average dive depth"
    depth_row = conn.execute(
        "SELECT MAX(max_depth_m) AS deepest, AVG(max_depth_m) AS avg_depth "
        "FROM dive WHERE max_depth_m IS NOT NULL"
    ).fetchone()

    # Total dive count (including dives with no time recorded)
    dive_count = int(conn.execute("SELECT COUNT(*) AS c FROM dive").fetchone()["c"])

    # Distinct sites and distinct countries the diver has been to.
    # "Countries" counts dive-site links where the site has a
    # country_code (NULL country_code sites don't count as a country
    # but do count toward the site total).
    site_row = conn.execute(
        "SELECT COUNT(DISTINCT ds.site_id) AS sites, "
        "       COUNT(DISTINCT CASE WHEN s.country_code IS NOT NULL "
        "                          THEN s.country_code END) AS countries "
        "FROM dive_site ds JOIN site s ON s.id = ds.site_id"
    ).fetchone()

    return DiveStats(
        dive_count=dive_count,
        dive_time_count=int(time_row["c"]) if time_row["c"] is not None else 0,
        longest_minutes=int(time_row["hi"]) if time_row["hi"] is not None else None,
        shortest_minutes=int(time_row["lo"]) if time_row["lo"] is not None else None,
        average_minutes=float(time_row["avg"]) if time_row["avg"] is not None else None,
        total_minutes=int(time_row["total"]) if time_row["total"] is not None else None,
        deepest_m=float(depth_row["deepest"]) if depth_row["deepest"] is not None else None,
        average_depth_m=float(depth_row["avg_depth"]) if depth_row["avg_depth"] is not None else None,
        distinct_sites=int(site_row["sites"]) if site_row["sites"] is not None else 0,
        distinct_countries=int(site_row["countries"]) if site_row["countries"] is not None else 0,
    )


def list_recent_with_sites(
    conn: sqlite3.Connection,
    limit: int = 500,
    *,
    site_name_substring: str | None = None,
    country_code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    notes_substring: str | None = None,
) -> list[dict]:
    """Return one row per dive, with the comma-joined site names.

    The list view needs (dive_id, date, time, sites, max_depth) without
    a second round-trip per row. The GROUP_CONCAT keeps it to a single
    query. For dives with multiple sites, they're returned in site_order.

    Also returns the new conditions columns (air_temp_c, water_temp_c,
    visibility_m) so the list view can render them when the user is in
    imperial mode. The fields are metric in the DB; the list view does
    the conversion at display time.

    Each row also carries ``display_dive_number`` — the dive's
    chronological position in the logbook, 1 = the earliest dive in
    time, n = the most recent. This is computed by a window
    function over the entire ``dive`` table (not just the rows
    in this result set) so the number is stable as the user
    scrolls or filters, and so adding a new backdated dive
    renumbers everything above it the way a diver would expect.

    The list is sorted by ``d.id DESC`` (newest inserted at the
    top) for display order; the *number* the UI shows in column 0
    is the chronological ``display_dive_number``, not the row id.
    Callers that need the stable internal key (selection, lookup
    by primary key, double-click → detail) should use ``id``,
    not ``display_dive_number``.

    Returned dict shape (stable for the UI layer):
        {
            "id": int,                          # stable PK
            "display_dive_number": int,         # 1 = earliest, n = latest
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

    Filter arguments (all optional, all compose with AND):

    * ``site_name_substring``: case-insensitive substring match
      against any of the dive's joined site names. A dive with
      no site is excluded when this filter is set.
    * ``country_code``: exact match on the 3-letter ISO code of
      any of the dive's joined sites. A dive with no site is
      excluded.
    * ``date_from`` / ``date_to``: inclusive ISO date strings
      (``"YYYY-MM-DD"``). A None bound means "no bound on that
      side". The match is on the dive's own ``dive_date`` column.
    * ``notes_substring``: case-insensitive substring match on
      ``dive.notes``. NULLs are excluded when this filter is set.

    All filters are None by default, so the no-filter case
    (which is the common case) is one extra branch of parameter
    passing.
    """
    # Build the WHERE clause incrementally. The numbered CTE stays
    # over the entire dive table so display_dive_number is stable
    # across filters; the WHERE filters the joined result.
    clauses: list[str] = []
    params: list[str | int] = []
    if site_name_substring:
        clauses.append("(s.name IS NOT NULL AND LOWER(s.name) LIKE ?)")
        params.append(f"%{site_name_substring.lower()}%")
    if country_code:
        clauses.append("s.country_code = ?")
        params.append(country_code)
    if date_from:
        clauses.append("n.dive_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("n.dive_date <= ?")
        params.append(date_to)
    if notes_substring:
        clauses.append("(n.notes IS NOT NULL AND LOWER(n.notes) LIKE ?)")
        params.append(f"%{notes_substring.lower()}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = conn.execute(
        f"""
        WITH numbered AS (
            SELECT
                d.*,
                ROW_NUMBER() OVER (
                    ORDER BY d.dive_date ASC,
                             d.start_time ASC NULLS LAST,
                             d.id ASC
                ) AS display_dive_number
            FROM dive d
        )
        SELECT
            n.id, n.display_dive_number,
            n.dive_date, n.start_time, n.end_time,
            n.dive_time_minutes, n.max_depth_m, n.avg_depth_m,
            n.air_temp_c, n.water_temp_c, n.visibility_m,
            n.start_pressure_bar, n.end_pressure_bar,
            GROUP_CONCAT(s.name, ', ') AS sites
        FROM numbered n
        LEFT JOIN dive_site ds ON ds.dive_id = n.id
        LEFT JOIN site s ON s.id = ds.site_id
        {where}
        GROUP BY n.id
        ORDER BY n.id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "display_dive_number": r["display_dive_number"],
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


@dataclass(frozen=True, slots=True)
class DiveFilterValues:
    """Distinct values for the dive-list filter dimensions.

    Only the country dimension needs a precomputed list (the dropdown).
    Date range is two `QDateEdit` widgets that don't need a list.
    Site-name and notes are free-text, no list.

    `countries` is the list of distinct country codes the diver has
    actually dived in (via a joined site). The dropdown shows the
    country **name** in display order; the SQL key is the 3-letter
    ISO code. Dives with no site are not in this list (the user
    can still see them by leaving the dropdown at "(All)").
    """

    countries: list[tuple[str, str]]   # (country_name, country_code)


def distinct_dive_filter_values(conn: sqlite3.Connection) -> DiveFilterValues:
    """Return the distinct country values present in the dive's
    joined sites.

    One independent query. Returns the country **name** (resolved
    via JOIN to the `country` table) in display order, with the
    3-letter ISO code as the matching key for the WHERE clause.

    Dives with no site are excluded — the user can still see them
    by leaving the dropdown at "(All)". The function is the
    "only values that exist" mirror of
    :func:`sites_repo.distinct_filter_values`: the dropdown
    shows only countries the diver has actually visited.
    """
    rows = conn.execute(
        "SELECT c.name, s.country_code "
        "FROM dive d "
        "JOIN dive_site ds ON ds.dive_id = d.id "
        "JOIN site s ON s.id = ds.site_id "
        "JOIN country c ON c.code = s.country_code "
        "WHERE s.country_code IS NOT NULL "
        "GROUP BY s.country_code, c.name "
        "ORDER BY c.name"
    ).fetchall()
    return DiveFilterValues(countries=[(r[0], r[1]) for r in rows])


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


@dataclass(frozen=True, slots=True)
class DiveMapPoint:
    """A single marker on the dive map.

    One row per dive. The coordinates come from the dive's
    *first* site (in ``dive_site`` order) that has a
    non-null ``latitude`` / ``longitude``. Dives with no such
    site are excluded — the map's value is the spatial view,
    so a dive that can't be placed isn't useful here.

    `display_dive_number` is the chronological position from
    the same window function that powers the list view, so
    the hover tooltip reads "Dive #N" matching the table.
    """

    id: int
    display_dive_number: int
    dive_date: str
    site_name: str
    latitude: float
    longitude: float
    max_depth_m: float | None


def list_for_map(
    conn: sqlite3.Connection,
    *,
    site_name_substring: str | None = None,
    country_code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    notes_substring: str | None = None,
) -> list[DiveMapPoint]:
    """Return one marker per dive for the map view.

    A dive appears if it has at least one site with
    non-null ``latitude`` and ``longitude``. The marker is
    placed at the dive's *first* such site (in
    ``dive_site.site_order``, then ``dive_site.id ASC`` as a
    tiebreaker for the first-inserted site).

    All five filter dimensions from :func:`list_recent_with_sites`
    are supported. ``country_code`` matches against the joined
    site's country (same semantics).

    The chronological display number is computed over the
    entire ``dive`` table (the same window function the list
    view uses) so the hover tooltip reads consistent with
    the list view.
    """
    clauses: list[str] = []
    params: list[str | int] = []
    if site_name_substring:
        clauses.append("(s.name IS NOT NULL AND LOWER(s.name) LIKE ?)")
        params.append(f"%{site_name_substring.lower()}%")
    if country_code:
        clauses.append("s.country_code = ?")
        params.append(country_code)
    if date_from:
        clauses.append("n.dive_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("n.dive_date <= ?")
        params.append(date_to)
    if notes_substring:
        clauses.append("(n.notes IS NOT NULL AND LOWER(n.notes) LIKE ?)")
        params.append(f"%{notes_substring.lower()}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    # The subquery picks the lowest site_order (or first
    # inserted as a tiebreaker) for each dive. We only join
    # to sites that have a non-null lat/lon. The
    # ``WHERE ds.site_id IN (...)`` filter is the "has at
    # least one geo site" guard.
    rows = conn.execute(
        f"""
        WITH numbered AS (
            SELECT
                d.*,
                ROW_NUMBER() OVER (
                    ORDER BY d.dive_date ASC,
                             d.start_time ASC NULLS LAST,
                             d.id ASC
                ) AS display_dive_number
            FROM dive d
        ),
        first_geo AS (
            SELECT
                ds.dive_id,
                ds.site_id,
                ROW_NUMBER() OVER (
                    PARTITION BY ds.dive_id
                    ORDER BY ds.site_order ASC, ds.site_id ASC
                ) AS rn
            FROM dive_site ds
            JOIN site s ON s.id = ds.site_id
            WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL
        )
        SELECT
            n.id, n.display_dive_number, n.dive_date,
            s.name AS site_name, s.latitude, s.longitude,
            n.max_depth_m
        FROM numbered n
        JOIN first_geo fg ON fg.dive_id = n.id AND fg.rn = 1
        JOIN site s ON s.id = fg.site_id
        {where}
        ORDER BY n.id DESC
        """,
        params,
    ).fetchall()
    return [
        DiveMapPoint(
            id=r["id"],
            display_dive_number=r["display_dive_number"],
            dive_date=r["dive_date"],
            site_name=r["site_name"],
            latitude=float(r["latitude"]),
            longitude=float(r["longitude"]),
            max_depth_m=r["max_depth_m"],
        )
        for r in rows
    ]


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
