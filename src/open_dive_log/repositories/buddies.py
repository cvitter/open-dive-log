"""Buddy repository — find-or-create by normalized name.

Normalization: lower(trim(full_name)) with internal whitespace collapsed.
So "Mike Smith", "  mike  smith  ", and "MIKE   SMITH" all collapse to the
same row.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


def normalize_full_name(first: str, last: str) -> str:
    """Build the dedup key: lower(trim(first||' '||last)) with whitespace collapsed."""
    raw = f"{first.strip()} {last.strip()}"
    return re.sub(r"\s+", " ", raw.strip().lower())


def display_full_name(first: str, last: str) -> str:
    return re.sub(r"\s+", " ", f"{first.strip()} {last.strip()}").strip()


@dataclass(frozen=True, slots=True)
class Buddy:
    id: int
    first_name: str
    last_name: str
    full_name: str


def find_by_normalized(
    conn: sqlite3.Connection, normalized: str
) -> Buddy | None:
    row = conn.execute(
        "SELECT id, first_name, last_name, full_name FROM buddy "
        "WHERE full_name_normalized = ?",
        (normalized,),
    ).fetchone()
    if row is None:
        return None
    return Buddy(row["id"], row["first_name"], row["last_name"], row["full_name"])


def get(conn: sqlite3.Connection, buddy_id: int) -> Buddy | None:
    row = conn.execute(
        "SELECT id, first_name, last_name, full_name FROM buddy WHERE id = ?",
        (buddy_id,),
    ).fetchone()
    if row is None:
        return None
    return Buddy(row["id"], row["first_name"], row["last_name"], row["full_name"])


def find_or_create(
    conn: sqlite3.Connection, first_name: str, last_name: str
) -> Buddy:
    """Return the existing buddy if a row matches the normalized name, else insert.

    Caller is expected to manage the transaction (use `with conn:`).
    """
    normalized = normalize_full_name(first_name, last_name)
    existing = find_by_normalized(conn, normalized)
    if existing is not None:
        return existing

    full_name = display_full_name(first_name, last_name)
    cur = conn.execute(
        "INSERT INTO buddy (first_name, last_name, full_name, full_name_normalized) "
        "VALUES (?, ?, ?, ?)",
        (first_name.strip(), last_name.strip(), full_name, normalized),
    )
    return Buddy(cur.lastrowid, first_name.strip(), last_name.strip(), full_name)


def list_all(conn: sqlite3.Connection) -> list[Buddy]:
    """Return all buddies, sorted by full_name."""
    rows = conn.execute(
        "SELECT id, first_name, last_name, full_name FROM buddy "
        "ORDER BY full_name ASC"
    ).fetchall()
    return [Buddy(r["id"], r["first_name"], r["last_name"], r["full_name"]) for r in rows]


def update(
    conn: sqlite3.Connection,
    buddy_id: int,
    *,
    first_name: str,
    last_name: str,
) -> None:
    """Update an existing buddy. Re-normalizes the full_name.

    Note: changing first/last name may produce a `full_name_normalized`
    that collides with another buddy — the UNIQUE constraint on the
    normalized column will reject that with an IntegrityError. The
    UI catches and reports.
    """
    full_name = display_full_name(first_name, last_name)
    normalized = normalize_full_name(first_name, last_name)
    cur = conn.execute(
        "UPDATE buddy "
        "SET first_name = ?, last_name = ?, full_name = ?, "
        "    full_name_normalized = ? "
        "WHERE id = ?",
        (first_name.strip(), last_name.strip(), full_name, normalized, buddy_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"No buddy with id {buddy_id}")


def delete(conn: sqlite3.Connection, buddy_id: int) -> None:
    """Delete a buddy. Raises LookupError if id is missing.

    Note: dive_buddy has ON DELETE CASCADE per the schema, so any
    dive-buddy links to this buddy are removed automatically. The
    caller may want to warn the user before deletion if there are
    linked dives — see `count_referencing_dives` below.
    """
    cur = conn.execute("DELETE FROM buddy WHERE id = ?", (buddy_id,))
    if cur.rowcount == 0:
        raise LookupError(f"No buddy with id {buddy_id}")


def count_referencing_dives(conn: sqlite3.Connection, buddy_id: int) -> int:
    """How many dives reference this buddy via dive_buddy. Used to
    warn the user before deleting a buddy that has linked dives."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM dive_buddy WHERE buddy_id = ?",
        (buddy_id,),
    ).fetchone()
    return int(row["c"])

