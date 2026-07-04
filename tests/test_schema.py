"""Integration tests: schema migration + repository layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log.repositories import buddies, dives, lookups, sites


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    """A fresh, migrated in-memory-style connection backed by a tmp file."""
    db_path = tmp_path / "test.db"
    with db.connect(db_path) as c:
        db.apply_migrations(c)
        yield c
        c.close()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------
def test_apply_migrations_is_idempotent(conn: sqlite3.Connection) -> None:
    version = db.apply_migrations(conn)
    assert version >= 1
    # Re-apply — should be a no-op (same version).
    version2 = db.apply_migrations(conn)
    assert version2 == version


def test_all_expected_tables_exist(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    expected = {
        "schema_meta", "site", "buddy", "dive", "dive_site", "dive_buddy",
        "lookup_time_of_day", "lookup_entry_type", "lookup_surface_conditions",
        "lookup_equipment_type", "lookup_tank_type", "lookup_tank_configuration",
        "lookup_gas_type", "lookup_purpose", "lookup_buddy_role",
        # migration 002
        "country", "site_source", "site_external_id",
        "lookup_site_environment", "lookup_site_topology", "site_site_topology",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_opendivemap_seed_values(conn: sqlite3.Connection) -> None:
    # country seed
    codes = {r["code"] for r in conn.execute("SELECT code FROM country").fetchall()}
    assert {"MX", "BZ", "ID", "US"}.issubset(codes)

    # site_source seed
    src = conn.execute(
        "SELECT system_name, license FROM site_source WHERE system_name='opendivemap'"
    ).fetchone()
    assert src is not None
    assert src["license"] == "ODbL"

    # topology lookup
    topo = lookups.list_active(conn, "lookup_site_topology")
    names = {v.name for v in topo}
    assert {"reef", "wall", "wreck", "cave", "blue_hole"}.issubset(names)


def test_site_with_external_id_and_topology(conn: sqlite3.Connection) -> None:
    # Get the opendivemap source id (seeded by migration 002)
    src = conn.execute(
        "SELECT id FROM site_source WHERE system_name='opendivemap'"
    ).fetchone()
    env = lookups.get_by_name(conn, "lookup_site_environment", "ocean")
    entry = lookups.get_by_name(conn, "lookup_entry_type", "boat")
    topo = [lookups.get_by_name(conn, "lookup_site_topology", n).id
            for n in ("reef", "wall")]

    # Pre-register the country. The importer handles this on its own via the
    # country_name field from opendivemap; the repository itself enforces FKs.
    conn.execute(
        "INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)",
        ("BQ", "Bonaire"),
    )

    site = sites.find_or_create(
        conn,
        "Salt Pier",
        country_code="BQ",
        latitude=12.15,
        longitude=-68.27,
        sea_mrgid=4287,
        environment_id=env.id,
        entry_id=entry.id,
        max_depth_m=40.0,
        external_id=(src["id"], "abc123", "https://opendivemap.com/site/abc123"),
        topologies=topo,
    )

    assert site.id is not None
    assert site.country_code == "BQ"
    assert site.country_name == "Bonaire"
    assert site.max_depth_m == 40.0

    tops = sites.get_topologies(conn, site.id)
    assert {t.name for t in tops} == {"reef", "wall"}

    ext = sites.get_external_ids(conn, site.id)
    assert len(ext) == 1
    assert ext[0].system_name == "opendivemap"
    assert ext[0].external_id == "abc123"

    # Dedup on re-import
    again = sites.find_or_create(
        conn, "Salt Pier", country_code="BQ",
        external_id=(src["id"], "abc123", None),
    )
    assert again.id == site.id


def test_environment_check_constraint(conn: sqlite3.Connection) -> None:
    # `is_active` is the only check constraint on lookup tables
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO lookup_site_environment (name, is_active) VALUES (?, ?)",
            ("bogus", 2),
        )


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def test_lookup_seed_values_present(conn: sqlite3.Connection) -> None:
    tod = lookups.list_active(conn, "lookup_time_of_day")
    names = [v.name for v in tod]
    assert names == ["dawn", "day", "dusk", "night", "full_moon", "other"]

    equip = lookups.list_active(conn, "lookup_equipment_type")
    assert [v.name for v in equip] == [
        "open_circuit", "semi_closed_circuit_rebreather",
        "closed_circuit_rebreather", "other",
    ]


def test_lookup_add_and_reject_duplicate(conn: sqlite3.Connection) -> None:
    lookups.add(conn, "lookup_entry_type", "cave", display_order=5)
    fetched = lookups.get_by_name(conn, "lookup_entry_type", "cave")
    assert fetched is not None
    assert fetched.name == "cave"

    with pytest.raises(sqlite3.IntegrityError):
        lookups.add(conn, "lookup_entry_type", "cave", display_order=6)


def test_lookup_rejects_unknown_table() -> None:
    with pytest.raises(ValueError, match="Unknown lookup table"):
        lookups.list_active(conn, "lookup_definitely_not_real")


# ---------------------------------------------------------------------------
# Buddy dedup
# ---------------------------------------------------------------------------
def test_buddy_normalize_collapses_case_and_whitespace() -> None:
    assert buddies.normalize_full_name("Mike", "Smith") == "mike smith"
    assert buddies.normalize_full_name("  MIKE  ", "  smith  ") == "mike smith"
    assert buddies.normalize_full_name("Mike", "O'Neill") == "mike o'neill"


def test_buddy_find_or_create_dedups(conn: sqlite3.Connection) -> None:
    a = buddies.find_or_create(conn, "Mike", "Smith")
    b = buddies.find_or_create(conn, "MIKE", "SMITH")
    c = buddies.find_or_create(conn, "mike", "smith")
    assert a.id == b.id == c.id
    # Still one row.
    count = conn.execute("SELECT COUNT(*) AS c FROM buddy").fetchone()["c"]
    assert count == 1


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
def test_site_find_or_create_dedups_on_name_country(conn: sqlite3.Connection) -> None:
    s1 = sites.find_or_create(conn, "Tugboat", country="Bonaire")
    s2 = sites.find_or_create(conn, "Tugboat", country="Bonaire")
    assert s1.id == s2.id

    # Same name, different country -> different row.
    s3 = sites.find_or_create(conn, "Tugboat", country="Curaçao")
    assert s3.id != s1.id


# ---------------------------------------------------------------------------
# Dive with sites + buddies
# ---------------------------------------------------------------------------
def test_dive_attach_sites_in_order(conn: sqlite3.Connection) -> None:
    s1 = sites.find_or_create(conn, "Salt Pier", country="Bonaire")
    s2 = sites.find_or_create(conn, "Karpata", country="Bonaire")
    s3 = sites.find_or_create(conn, "1000 Steps", country="Bonaire")

    dive_id = dives.create(conn, dive_date="2026-07-04", max_depth_m=24.0)
    dives.attach_sites(conn, dive_id, [s2.id, s1.id, s3.id])

    attached = dives.get_sites(conn, dive_id)
    assert [s.id for s in attached] == [s2.id, s1.id, s3.id]
    assert [s.name for s in attached] == ["Karpata", "Salt Pier", "1000 Steps"]


def test_dive_attach_sites_replaces_existing(conn: sqlite3.Connection) -> None:
    s1 = sites.find_or_create(conn, "A", country="X")
    s2 = sites.find_or_create(conn, "B", country="X")
    s3 = sites.find_or_create(conn, "C", country="X")

    dive_id = dives.create(conn, dive_date="2026-07-04")
    dives.attach_sites(conn, dive_id, [s1.id, s2.id])
    dives.attach_sites(conn, dive_id, [s3.id])  # replace

    attached = dives.get_sites(conn, dive_id)
    assert [s.id for s in attached] == [s3.id]


def test_dive_unique_site_per_dive(conn: sqlite3.Connection) -> None:
    s1 = sites.find_or_create(conn, "Reef", country="Bonaire")
    dive_id = dives.create(conn, dive_date="2026-07-04")
    dives.attach_sites(conn, dive_id, [s1.id])
    with pytest.raises(sqlite3.IntegrityError):
        dives.attach_sites(conn, dive_id, [s1.id, s1.id])  # duplicate


def test_dive_attach_buddies_via_add_helper(conn: sqlite3.Connection) -> None:
    role = lookups.get_by_name(conn, "lookup_buddy_role", "buddy").id
    dive_id = dives.create(conn, dive_date="2026-07-04")
    dives.add_buddy_to_dive(conn, dive_id, "Mike", "Smith", role_id=role)
    dives.add_buddy_to_dive(conn, dive_id, "Jane", "Doe", role_id=role)
    # Add Mike again — should be a no-op (PRIMARY KEY + OR IGNORE).
    dives.add_buddy_to_dive(conn, dive_id, "MIKE", "SMITH", role_id=role)

    attached = dives.get_buddies(conn, dive_id)
    assert sorted((b.first_name, b.last_name) for b in attached) == [
        ("Jane", "Doe"), ("Mike", "Smith"),
    ]


def test_dive_o2_percentage_check_constraint(conn: sqlite3.Connection) -> None:
    # Below 0
    with pytest.raises(sqlite3.IntegrityError):
        dives.create(conn, dive_date="2026-07-04", o2_percentage=-1.0)
    # Above 100
    with pytest.raises(sqlite3.IntegrityError):
        dives.create(conn, dive_date="2026-07-04", o2_percentage=100.01)
    # Valid edges
    dives.create(conn, dive_date="2026-07-04", o2_percentage=0.0)
    dives.create(conn, dive_date="2026-07-04", o2_percentage=100.0)


def test_dive_cascade_delete_removes_joins(conn: sqlite3.Connection) -> None:
    s1 = sites.find_or_create(conn, "Cave", country="X")
    dive_id = dives.create(conn, dive_date="2026-07-04")
    dives.attach_sites(conn, dive_id, [s1.id])
    dives.add_buddy_to_dive(conn, dive_id, "Mike", "Smith")

    # dive deletion cascades to joins but not to site/buddy (RESTRICT)
    conn.execute("DELETE FROM dive WHERE id = ?", (dive_id,))
    remaining = conn.execute(
        "SELECT COUNT(*) AS c FROM dive_site WHERE dive_id = ?", (dive_id,)
    ).fetchone()["c"]
    assert remaining == 0
    # Site still exists.
    assert sites.get(conn, s1.id) is not None


def test_list_recent_orders_by_date_desc(conn: sqlite3.Connection) -> None:
    d1 = dives.create(conn, dive_date="2026-07-01")
    d2 = dives.create(conn, dive_date="2026-07-15")
    d3 = dives.create(conn, dive_date="2026-07-08")

    recent = dives.list_recent(conn)
    assert [d.id for d in recent] == [d2, d3, d1]
