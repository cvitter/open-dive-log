"""Import opendivemap.com sites into the local DB.

Idempotent: re-running upserts existing sites (matched by external_id) and
inserts new ones. Lookup tables (environment, topology, entry, country) are
auto-extended when new values appear in the source.

Usage from the app:
    python -m open_dive_log.import_opendivemap

The script:
  1. Fetches /stats for a pre-flight log
  2. Streams sites from /v1/sites (paginated, up to 1000 per page)
  3. Upserts each one in a single transaction per site
  4. Prints a final summary (inserted, updated, skipped, errors)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter

from open_dive_log import db
from open_dive_log.repositories import lookups, sites
from open_dive_log.sources import opendivemap


SYSTEM_NAME = "opendivemap"


def _ensure_source(conn: sqlite3.Connection) -> int:
    """Look up the opendivemap source id, inserting if missing."""
    row = conn.execute(
        "SELECT id FROM site_source WHERE system_name = ?", (SYSTEM_NAME,)
    ).fetchone()
    if row is not None:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO site_source (system_name, base_url, api_url, license, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            SYSTEM_NAME, "https://opendivemap.com",
            "https://api.opendivemap.com/v1", "ODbL",
            "Community-driven open database of dive sites. GeoJSON, 6-char base36 ids.",
        ),
    )
    return cur.lastrowid


def _ensure_country(
    conn: sqlite3.Connection, code: str | None, name: str | None
) -> str | None:
    if not code:
        return None
    row = conn.execute(
        "SELECT code FROM country WHERE code = ?", (code,)
    ).fetchone()
    if row is not None:
        return row["code"]
    conn.execute(
        "INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)",
        (code, name or code),
    )
    return code


def _ensure_topology(conn: sqlite3.Connection, name: str) -> int | None:
    """Look up topology id, auto-inserting unknown values into the lookup table."""
    if not name:
        return None
    existing = lookups.get_by_name(conn, "lookup_site_topology", name)
    if existing is not None:
        return existing.id
    added = lookups.add(conn, "lookup_site_topology", name, display_order=100)
    return added.id


def _ensure_environment(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name:
        return None
    existing = lookups.get_by_name(conn, "lookup_site_environment", name)
    if existing is not None:
        return existing.id
    return lookups.add(conn, "lookup_site_environment", name, display_order=100).id


def _ensure_entry(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name:
        return None
    existing = lookups.get_by_name(conn, "lookup_entry_type", name)
    if existing is not None:
        return existing.id
    return lookups.add(conn, "lookup_entry_type", name, display_order=100).id


def _find_existing(conn: sqlite3.Connection, source_id: int, external_id: str) -> int | None:
    row = conn.execute(
        "SELECT site_id FROM site_external_id WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    ).fetchone()
    return row["site_id"] if row else None


def _upsert_feature(
    conn: sqlite3.Connection, source_id: int, f: opendivemap.ODMFeature
) -> str:
    """Insert or update a single site. Returns the outcome string.

    Outcomes:
        'inserted'  — new site row created, external_id linked
        'updated'   — site row already had this external_id, fields refreshed
        'skipped'   — no usable name or external_id

    For opendivemap imports the dedup key is the `site_external_id` table:
    every opendivemap record becomes its own site row, even if two records
    share (name, country_code). This matches the upstream data model where
    a single physical site can have multiple opendivemap records, and lets
    us preserve the opendivemap 1:1 mapping without (name, country)
    collisions creating ambiguity.
    """
    if not f.external_id or not f.name:
        return "skipped"

    # Lookups first (may auto-insert new values).
    country_code = _ensure_country(conn, f.country_code, f.country_name)
    env_id = _ensure_environment(conn, f.environment)
    entry_id = _ensure_entry(conn, f.entry)
    topo_ids = [t for t in (_ensure_topology(conn, n) for n in f.topologies) if t is not None]

    existing_id = _find_existing(conn, source_id, f.external_id)
    if existing_id is not None:
        # External id already known to us — just refresh the upstream fields.
        conn.execute(
            """
            UPDATE site
            SET country_code = ?,
                latitude = ?,
                longitude = ?,
                sea_mrgid = ?,
                environment_id = ?,
                entry_id = ?,
                max_depth_m = ?
            WHERE id = ?
            """,
            (
                country_code, f.latitude, f.longitude, f.sea_mrgid,
                env_id, entry_id,
                float(f.max_depth) if f.max_depth is not None else None,
                existing_id,
            ),
        )
        sites.attach_topologies(conn, existing_id, topo_ids)
        return "updated"

    # External id is new. Each opendivemap record gets its own site row.
    sites.find_or_create(
        conn,
        f.name,
        country_code=country_code,
        latitude=f.latitude,
        longitude=f.longitude,
        sea_mrgid=f.sea_mrgid,
        environment_id=env_id,
        entry_id=entry_id,
        max_depth_m=float(f.max_depth) if f.max_depth is not None else None,
        external_id=(source_id, f.external_id, f.external_url),
        topologies=topo_ids,
    )
    return "inserted"


def import_all(*, db_path=None, progress_every: int = 100) -> Counter:
    """Stream opendivemap and upsert every site. Returns a Counter of outcomes."""
    counts: Counter = Counter()
    with db.connect(db_path) as conn:
        db.apply_migrations(conn)
        source_id = _ensure_source(conn)

        # Pre-flight log
        try:
            stats = opendivemap.get_stats()
            print(
                f"opendivemap stats: {stats.get('total_sites', '?')} sites "
                f"across {stats.get('total_countries', '?')} countries",
                file=sys.stderr,
            )
        except opendivemap.OpenDiveMapError as e:
            print(f"warning: could not fetch /stats: {e}", file=sys.stderr)

        for f in opendivemap.iter_sites():
            try:
                with conn:  # transaction per feature
                    outcome = _upsert_feature(conn, source_id, f)
                counts[outcome] += 1
            except sqlite3.Error as e:
                counts["errors"] += 1
                print(
                    f"  error on site {f.external_id!r} ({f.name!r}): {e}",
                    file=sys.stderr,
                )
            total = sum(counts.values())
            if total % progress_every == 0:
                print(
                    f"  ... {total} processed: "
                    f"{dict(counts)}",
                    file=sys.stderr,
                )

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import dive sites from opendivemap.com")
    parser.add_argument(
        "--db", type=str, default=None,
        help="Path to the SQLite DB (default: data/open_dive_log.db)",
    )
    parser.add_argument(
        "--progress-every", type=int, default=100,
        help="Print progress every N sites (default: 100)",
    )
    args = parser.parse_args(argv)

    db_path = None if args.db is None else __import__("pathlib").Path(args.db)
    counts = import_all(db_path=db_path, progress_every=args.progress_every)
    print(f"Done: {dict(counts)}")
    return 0 if counts.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
