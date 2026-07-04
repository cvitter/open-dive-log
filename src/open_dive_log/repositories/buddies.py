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
