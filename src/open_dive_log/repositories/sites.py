"""Site repository — handles sites, country, topology, and external references.

The site model is the most complex entity in the schema. It joins:
  * site (the row)
  * country (ISO code FK)
  * lookup_site_environment (FK)
  * lookup_entry_type (FK — shared with dive)
  * site_external_id (M:1 to site_source)
  * site_site_topology (M:N to lookup_site_topology)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Site:
    id: int
    name: str
    region: str | None
    country: str | None                  # free text (legacy / unknown)
    country_code: str | None             # ISO 3166-1 alpha-2
    country_name: str | None             # resolved via JOIN
    latitude: float | None
    longitude: float | None
    sea_mrgid: int | None
    sea_name: str | None
    environment_id: int | None
    environment_name: str | None
    entry_id: int | None
    entry_name: str | None
    max_depth_m: float | None
    description: str | None
    description_wildlife: str | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class TopologyRef:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ExternalId:
    system_name: str
    external_id: str
    external_url: str | None


@dataclass(frozen=True, slots=True)
class SiteFilterValues:
    """Distinct values for the four filterable dimensions, restricted
    to values that actually appear in the ``site`` table.

    Each field is a list of ``(label, key)`` pairs in display order.
    ``label`` is what the user sees in the dropdown; ``key`` is what
    the WHERE clause matches on. Country is keyed on the 3-letter
    ISO code (e.g. ``"USA"``); region is keyed on the free-text
    value; environment and entry are keyed on the lookup-table id.

    The lists are alphabetized by label so the dropdown reads
    predictably. Empty list = no sites use that dimension at all
    (the dropdown will show only the blank "All" option).
    """

    countries: list[tuple[str, str]]      # (country_name, country_code)
    regions: list[tuple[str, str]]        # (region, region)  (key == label)
    environments: list[tuple[str, int]]   # (env_name, env_id)
    entries: list[tuple[str, int]]        # (entry_name, entry_id)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
_COLS = (
    "s.id, s.name, s.region, s.country, s.country_code, "
    "c.name AS country_name, "
    "s.latitude, s.longitude, s.sea_mrgid, "
    "s.environment_id, le.name AS environment_name, "
    "s.entry_id, le2.name AS entry_name, "
    "s.max_depth_m, s.description, s.description_wildlife, s.notes"
)


def _row_to_site(row: sqlite3.Row) -> Site:
    return Site(
        id=row["id"],
        name=row["name"],
        region=row["region"],
        country=row["country"],
        country_code=row["country_code"],
        country_name=row["country_name"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        sea_mrgid=row["sea_mrgid"],
        sea_name=None,  # sea lookup table not yet populated; see migration 002 notes
        environment_id=row["environment_id"],
        environment_name=row["environment_name"],
        entry_id=row["entry_id"],
        entry_name=row["entry_name"],
        max_depth_m=row["max_depth_m"],
        description=row["description"],
        description_wildlife=row["description_wildlife"],
        notes=row["notes"],
    )


def get(conn: sqlite3.Connection, site_id: int) -> Site | None:
    row = conn.execute(
        f"SELECT {_COLS} FROM site s "
        "LEFT JOIN country c ON c.code = s.country_code "
        "LEFT JOIN lookup_site_environment le ON le.id = s.environment_id "
        "LEFT JOIN lookup_entry_type le2 ON le2.id = s.entry_id "
        "WHERE s.id = ?",
        (site_id,),
    ).fetchone()
    return _row_to_site(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[Site]:
    rows = conn.execute(
        f"SELECT {_COLS} FROM site s "
        "LEFT JOIN country c ON c.code = s.country_code "
        "LEFT JOIN lookup_site_environment le ON le.id = s.environment_id "
        "LEFT JOIN lookup_entry_type le2 ON le2.id = s.entry_id "
        "ORDER BY s.name"
    ).fetchall()
    return [_row_to_site(r) for r in rows]


def distinct_filter_values(conn: sqlite3.Connection) -> SiteFilterValues:
    """Return the distinct values that actually appear in the site
    table for each of the four filterable dimensions.

    Only values present in the user's data are returned — empty
    list means "no sites use this dimension at all" (the dropdown
    will show only the blank "All" option, which is correct).

    The four queries are independent and cheap. Each runs in
    microseconds against a 3k-row site table.

    Country and region are not deduplicated against the
    ``country`` and region lookup tables in the sense of "if a
    value exists in lookup but not in site, exclude it" — we
    drive the list from the site table itself, not from any
    lookup. This is the contract documented on
    :class:`SiteFilterValues`.
    """
    countries_rows = conn.execute(
        "SELECT c.name, s.country_code "
        "FROM site s JOIN country c ON c.code = s.country_code "
        "WHERE s.country_code IS NOT NULL "
        "GROUP BY s.country_code, c.name "
        "ORDER BY c.name"
    ).fetchall()
    regions_rows = conn.execute(
        "SELECT region FROM site "
        "WHERE region IS NOT NULL AND region != '' "
        "GROUP BY region "
        "ORDER BY region"
    ).fetchall()
    envs_rows = conn.execute(
        "SELECT le.name, s.environment_id "
        "FROM site s JOIN lookup_site_environment le ON le.id = s.environment_id "
        "WHERE s.environment_id IS NOT NULL "
        "GROUP BY s.environment_id, le.name "
        "ORDER BY le.name"
    ).fetchall()
    entries_rows = conn.execute(
        "SELECT le.name, s.entry_id "
        "FROM site s JOIN lookup_entry_type le ON le.id = s.entry_id "
        "WHERE s.entry_id IS NOT NULL "
        "GROUP BY s.entry_id, le.name "
        "ORDER BY le.name"
    ).fetchall()
    return SiteFilterValues(
        countries=[(r[0], r[1]) for r in countries_rows],
        regions=[(r[0], r[0]) for r in regions_rows],
        environments=[(r[0], r[1]) for r in envs_rows],
        entries=[(r[0], r[1]) for r in entries_rows],
    )


def list_filtered(
    conn: sqlite3.Connection,
    *,
    country_code: str | None = None,
    region: str | None = None,
    environment_id: int | None = None,
    entry_id: int | None = None,
) -> list[Site]:
    """Return sites matching the given filter criteria.

    Each criterion is an exact match on the joined column. ``None``
    (or empty string for ``region``) means "don't filter on this
    dimension". Criteria compose with AND: country=US AND
    environment=Reef returns only US reefs.

    The implementation builds a parameterised SQL string — never
    string-interpolates user values, even though the only caller
    is the UI (whose values come from the lookup table).
    """
    clauses: list[str] = []
    params: list[str | int] = []
    if country_code:
        clauses.append("s.country_code = ?")
        params.append(country_code)
    if region:
        clauses.append("s.region = ?")
        params.append(region)
    if environment_id is not None:
        clauses.append("s.environment_id = ?")
        params.append(environment_id)
    if entry_id is not None:
        clauses.append("s.entry_id = ?")
        params.append(entry_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT {_COLS} FROM site s "
        "LEFT JOIN country c ON c.code = s.country_code "
        "LEFT JOIN lookup_site_environment le ON le.id = s.environment_id "
        "LEFT JOIN lookup_entry_type le2 ON le2.id = s.entry_id"
        f"{where} "
        "ORDER BY s.name",
        params,
    ).fetchall()
    return [_row_to_site(r) for r in rows]


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    region: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    sea_mrgid: int | None = None,
    environment_id: int | None = None,
    entry_id: int | None = None,
    max_depth_m: float | None = None,
    description: str | None = None,
    description_wildlife: str | None = None,
    notes: str | None = None,
) -> Site:
    """Create a brand-new site row. Unlike find_or_create, this never
    dedupes — every call inserts a new row.

    The caller is responsible for ensuring the (name, country) pair
    doesn't already exist; the table has a UNIQUE constraint on
    (name, country) and we'll raise sqlite3.IntegrityError if it
    does. The UI catches that and shows a friendly message.

    Returns the inserted Site (re-fetched from the DB so all
    joined fields are populated, not just the inserted ones).
    """
    if not name or not name.strip():
        raise ValueError("Site name is required")
    cur = conn.execute(
        """
        INSERT INTO site (
            name, region, country, country_code,
            latitude, longitude, sea_mrgid,
            environment_id, entry_id, max_depth_m,
            description, description_wildlife, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name.strip(), region, country, country_code,
            latitude, longitude, sea_mrgid,
            environment_id, entry_id, max_depth_m,
            description, description_wildlife, notes,
        ),
    )
    new_id = cur.lastrowid
    assert new_id is not None
    new_site = get(conn, new_id)
    assert new_site is not None
    return new_site


def get_topologies(conn: sqlite3.Connection, site_id: int) -> list[TopologyRef]:
    rows = conn.execute(
        """
        SELECT t.id, t.name
        FROM site_site_topology ss
        JOIN lookup_site_topology t ON t.id = ss.topology_id
        WHERE ss.site_id = ?
        ORDER BY t.display_order, t.name
        """,
        (site_id,),
    ).fetchall()
    return [TopologyRef(r["id"], r["name"]) for r in rows]


def get_external_ids(conn: sqlite3.Connection, site_id: int) -> list[ExternalId]:
    rows = conn.execute(
        """
        SELECT src.system_name, sei.external_id, sei.external_url
        FROM site_external_id sei
        JOIN site_source src ON src.id = sei.source_id
        WHERE sei.site_id = ?
        ORDER BY src.system_name
        """,
        (site_id,),
    ).fetchall()
    return [
        ExternalId(r["system_name"], r["external_id"], r["external_url"])
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def find_or_create(
    conn: sqlite3.Connection,
    name: str,
    *,
    region: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    sea_mrgid: int | None = None,
    environment_id: int | None = None,
    entry_id: int | None = None,
    max_depth_m: float | None = None,
    description: str | None = None,
    description_wildlife: str | None = None,
    notes: str | None = None,
    external_id: tuple[int, str, str | None] | None = None,
    topologies: Sequence[int] | None = None,
) -> Site:
    """Find an existing site by (name, country_code) or create a new one.

    Dedup behavior:
      * If `external_id` is provided, the call is treated as authoritative —
        we always insert a new site row and link the external_id. The
        caller is expected to have already verified the external_id isn't
        already in the site_external_id table. Use this for data imports
        where each upstream record is its own site.
      * If `external_id` is NOT provided (UI / human input), we dedup on
        (name, country_code) — same name + same country = same site. This
        prevents the UI from accidentally creating two "Salt Pier, Bonaire"
        rows when the user just didn't realize it was already there.

    country_code is the modern dedup key (opendivemap-compatible).
    country (free text) is preserved for legacy sites. If country_code is
    given, we match on it; otherwise we fall back to (name, country).

    If external_id is given, it is (source_id, external_id, external_url)
    and is inserted in the same transaction via the new site's id.
    """
    if external_id is not None:
        # External_id path: if this external_id is already linked to a site,
        # return that site (idempotent). Otherwise insert a new site and link.
        source_id, ext_id, ext_url = external_id
        row = conn.execute(
            "SELECT site_id FROM site_external_id WHERE source_id = ? AND external_id = ?",
            (source_id, ext_id),
        ).fetchone()
        if row is not None:
            return get(conn, row["site_id"])  # type: ignore[return-value]
        cur = conn.execute(
            """
            INSERT INTO site (
                name, region, country, country_code,
                latitude, longitude, sea_mrgid,
                environment_id, entry_id, max_depth_m,
                description, description_wildlife, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, region, country, country_code,
                latitude, longitude, sea_mrgid,
                environment_id, entry_id, max_depth_m,
                description, description_wildlife, notes,
            ),
        )
        new_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO site_external_id (site_id, source_id, external_id, external_url)
            VALUES (?, ?, ?, ?)
            """,
            (new_id, source_id, ext_id, ext_url),
        )
        if topologies:
            for t_id in topologies:
                conn.execute(
                    "INSERT OR IGNORE INTO site_site_topology (site_id, topology_id) VALUES (?, ?)",
                    (new_id, t_id),
                )
        site = get(conn, new_id)
        assert site is not None
        return site

    # UI / human path: dedup on (name, country).
    if country_code is not None:
        row = conn.execute(
            "SELECT id FROM site WHERE name = ? AND country_code = ?",
            (name, country_code),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM site WHERE name = ? AND country IS ? AND country_code IS NULL",
            (name, country),
        ).fetchone()

    if row is not None:
        return get(conn, row["id"])  # type: ignore[return-value]

    cur = conn.execute(
        """
        INSERT INTO site (
            name, region, country, country_code,
            latitude, longitude, sea_mrgid,
            environment_id, entry_id, max_depth_m,
            description, description_wildlife, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name, region, country, country_code,
            latitude, longitude, sea_mrgid,
            environment_id, entry_id, max_depth_m,
            description, description_wildlife, notes,
        ),
    )
    new_id = cur.lastrowid

    if topologies:
        for t_id in topologies:
            conn.execute(
                "INSERT OR IGNORE INTO site_site_topology (site_id, topology_id) VALUES (?, ?)",
                (new_id, t_id),
            )

    site = get(conn, new_id)
    assert site is not None
    return site


def attach_topologies(
    conn: sqlite3.Connection, site_id: int, topology_ids: Sequence[int]
) -> None:
    """Replace the topology set on a site with the given ids."""
    conn.execute("DELETE FROM site_site_topology WHERE site_id = ?", (site_id,))
    for t_id in topology_ids:
        conn.execute(
            "INSERT OR IGNORE INTO site_site_topology (site_id, topology_id) VALUES (?, ?)",
            (site_id, t_id),
        )


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------
def update(
    conn: sqlite3.Connection,
    site_id: int,
    *,
    name: str,
    region: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    environment_id: int | None = None,
    entry_id: int | None = None,
    max_depth_m: float | None = None,
    description: str | None = None,
    description_wildlife: str | None = None,
    notes: str | None = None,
) -> None:
    """Update an existing site. Raises LookupError if id not found.

    Performs a direct UPDATE — does NOT go through find_or_create's
    dedup, because renaming a site to match a different (name, country)
    pair would silently collapse two sites into one. We let the
    UNIQUE (name, country) constraint on the table reject illegal
    renames with a clear IntegrityError; the form catches that and
    shows the user what went wrong.

    country_code IS updated here. (Originally I planned to make it
    immutable past the import path, but the form's country picker
    needs to save it, and the field is meant to be user-editable
    just like the free-text country. The FK to country(code) means
    the form must only offer codes that exist; if the user picks a
    code that's not in the country table, the FK will reject it.)
    """
    cur = conn.execute(
        """
        UPDATE site
           SET name = ?, region = ?, country = ?, country_code = ?,
               latitude = ?, longitude = ?,
               environment_id = ?, entry_id = ?,
               max_depth_m = ?,
               description = ?, description_wildlife = ?, notes = ?,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = ?
        """,
        (
            name, region, country, country_code,
            latitude, longitude,
            environment_id, entry_id,
            max_depth_m,
            description, description_wildlife, notes,
            site_id,
        ),
    )
    if cur.rowcount == 0:
        raise LookupError(f"No site with id {site_id}")


def delete(conn: sqlite3.Connection, site_id: int) -> None:
    """Delete a site. Raises LookupError if id not found.

    Note: dive_site has ON DELETE RESTRICT, so if any dive references
    this site the FK will reject the delete with an IntegrityError.
    The UI catches that and tells the user which dives are blocking
    the delete.
    """
    cur = conn.execute("DELETE FROM site WHERE id = ?", (site_id,))
    if cur.rowcount == 0:
        raise LookupError(f"No site with id {site_id}")


def list_blocking_dives(
    conn: sqlite3.Connection, site_id: int
) -> list[tuple[int, str]]:
    """Return (dive_id, dive_date) for every dive that references this
    site. Used to give the user a useful error when a delete is
    blocked by the ON DELETE RESTRICT FK on dive_site."""
    rows = conn.execute(
        """
        SELECT d.id, d.dive_date
          FROM dive_site ds
          JOIN dive d ON d.id = ds.dive_id
         WHERE ds.site_id = ?
         ORDER BY d.dive_date DESC, d.id DESC
         LIMIT 10
        """,
        (site_id,),
    ).fetchall()
    return [(r["id"], r["dive_date"]) for r in rows]
