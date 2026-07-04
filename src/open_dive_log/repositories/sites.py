"""Site repository."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Site:
    id: int
    name: str
    region: str | None
    country: str | None
    latitude: float | None
    longitude: float | None
    notes: str | None


def get(conn: sqlite3.Connection, site_id: int) -> Site | None:
    row = conn.execute(
        "SELECT id, name, region, country, latitude, longitude, notes FROM site WHERE id = ?",
        (site_id,),
    ).fetchone()
    if row is None:
        return None
    return Site(
        row["id"], row["name"], row["region"], row["country"],
        row["latitude"], row["longitude"], row["notes"],
    )


def find_or_create(
    conn: sqlite3.Connection,
    name: str,
    *,
    region: str | None = None,
    country: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    notes: str | None = None,
) -> Site:
    """Find an existing site by (name, country) or create a new one.

    (name, country) is the dedup key from the schema. Country can be None,
    so we treat that as a wildcard — same name, country IS NULL is unique.
    """
    row = conn.execute(
        "SELECT id, name, region, country, latitude, longitude, notes FROM site "
        "WHERE name = ? AND (country IS ? OR country = ?)",
        (name, country, country),
    ).fetchone()
    if row is not None:
        return Site(
            row["id"], row["name"], row["region"], row["country"],
            row["latitude"], row["longitude"], row["notes"],
        )

    cur = conn.execute(
        "INSERT INTO site (name, region, country, latitude, longitude, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, region, country, latitude, longitude, notes),
    )
    return Site(cur.lastrowid, name, region, country, latitude, longitude, notes)


def list_all(conn: sqlite3.Connection) -> list[Site]:
    rows = conn.execute(
        "SELECT id, name, region, country, latitude, longitude, notes FROM site "
        "ORDER BY name"
    ).fetchall()
    return [
        Site(r["id"], r["name"], r["region"], r["country"],
             r["latitude"], r["longitude"], r["notes"])
        for r in rows
    ]
