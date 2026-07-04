"""Tests for the dive repository's full-row CRUD + picker helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log.repositories import dives, lookups, sites as sites_repo


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "dives_repo_test.db"
    cm = db.connect(db_path)
    c = cm.__enter__()
    db.apply_migrations(c)
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES ('BQ', 'Bonaire')")
    yield c
    cm.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# get_full / update / delete
# ---------------------------------------------------------------------------
def test_get_full_returns_all_22_fields(conn: sqlite3.Connection) -> None:
    tod = next(t.id for t in lookups.list_active(conn, "lookup_time_of_day") if t.name == "day")
    did = dives.create(
        conn, dive_date="2026-06-15", start_time="14:30", end_time="15:15",
        dive_time_minutes=45, max_depth_m=24.0, avg_depth_m=18.0,
        o2_percentage=32.0, time_of_day_id=tod, gear_notes="BCD-1234",
    )
    full = dives.get_full(conn, did)
    assert full is not None
    assert full.id == did
    assert full.dive_date == "2026-06-15"
    assert full.start_time == "14:30"
    assert full.end_time == "15:15"
    assert full.dive_time_minutes == 45
    assert full.time_of_day_id == tod
    assert full.max_depth_m == 24.0
    assert full.avg_depth_m == 18.0
    assert full.o2_percentage == 32.0
    assert full.gear_notes == "BCD-1234"
    # Bookkeeping fields populated
    assert full.created_at
    assert full.updated_at


def test_get_full_returns_none_for_missing(conn: sqlite3.Connection) -> None:
    assert dives.get_full(conn, 99999) is None


def test_update_replaces_all_fields(conn: sqlite3.Connection) -> None:
    """update() is a full-row setter: any field not in kwargs is set to
    None (its default). This matches what the edit form needs — the
    form loads the dive, then writes all 22 fields back as a single
    atomic update. Calling update() with only some fields is supported
    but means the unspecified fields go to None.
    """
    tod = next(t.id for t in lookups.list_active(conn, "lookup_time_of_day") if t.name == "day")
    did = dives.create(conn, dive_date="2026-06-15", max_depth_m=20.0, time_of_day_id=tod)
    # Update only some fields — others go to None.
    dives.update(
        conn, did, dive_date="2026-07-01", max_depth_m=25.0,
        start_time="09:00", end_time="09:45", dive_time_minutes=45,
    )
    full = dives.get_full(conn, did)
    assert full is not None
    assert full.dive_date == "2026-07-01"
    assert full.max_depth_m == 25.0
    assert full.start_time == "09:00"
    assert full.end_time == "09:45"
    # The unspecified field is reset to None (default for the param).
    assert full.time_of_day_id is None


def test_update_full_round_trip(conn: sqlite3.Connection) -> None:
    """The form's actual use case: get_full, then update with all fields
    populated, then get_full again — values match exactly.
    """
    tod = next(t.id for t in lookups.list_active(conn, "lookup_time_of_day") if t.name == "day")
    did = dives.create(conn, dive_date="2026-06-15", max_depth_m=20.0, time_of_day_id=tod)
    full = dives.get_full(conn, did)
    assert full is not None
    # Mutate one field and write back everything.
    new_kwargs = full.to_kwargs() if hasattr(full, "to_kwargs") else None
    # DiveFull has no to_kwargs() — build the call manually.
    dives.update(
        conn, did,
        dive_date=full.dive_date, start_time=full.start_time, end_time=full.end_time,
        dive_time_minutes=full.dive_time_minutes, time_of_day_id=full.time_of_day_id,
        entry_type_id=full.entry_type_id, entry_notes=full.entry_notes,
        surface_conditions_id=full.surface_conditions_id,
        surface_conditions_notes=full.surface_conditions_notes,
        run_time_minutes=full.run_time_minutes,
        max_depth_m=full.max_depth_m, avg_depth_m=full.avg_depth_m,
        equipment_type_id=full.equipment_type_id, tank_type_id=full.tank_type_id,
        tank_configuration_id=full.tank_configuration_id, gas_type_id=full.gas_type_id,
        o2_percentage=full.o2_percentage, mix_notes=full.mix_notes, gear_notes=full.gear_notes,
        purpose_id=full.purpose_id, notes=full.notes,
    )
    full2 = dives.get_full(conn, did)
    assert full2 is not None
    assert full2.dive_date == full.dive_date
    assert full2.max_depth_m == full.max_depth_m
    assert full2.time_of_day_id == full.time_of_day_id


def test_update_raises_for_missing_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        dives.update(conn, 99999, dive_date="2026-06-15")


def test_delete_removes_row_and_cascades_to_sites_and_buddies(
    conn: sqlite3.Connection,
) -> None:
    s = sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
    did = dives.create(conn, dive_date="2026-06-15", max_depth_m=20.0)
    dives.attach_sites(conn, did, [s.id])
    dives.add_buddy_to_dive(conn, did, "Mike", "Smith")
    # Sanity: joins exist
    assert conn.execute("SELECT COUNT(*) FROM dive_site WHERE dive_id=?", (did,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dive_buddy WHERE dive_id=?", (did,)).fetchone()[0] == 1
    dives.delete(conn, did)
    assert dives.get_full(conn, did) is None
    assert conn.execute("SELECT COUNT(*) FROM dive_site WHERE dive_id=?", (did,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM dive_buddy WHERE dive_id=?", (did,)).fetchone()[0] == 0
    # Site itself is preserved (RESTRICT not CASCADE on site deletes from dive_site)
    assert sites_repo.get(conn, s.id) is not None


def test_delete_raises_for_missing_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        dives.delete(conn, 99999)


# ---------------------------------------------------------------------------
# Picker helpers
# ---------------------------------------------------------------------------
def test_list_sites_for_picker_returns_id_label_tuples(conn: sqlite3.Connection) -> None:
    sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
    sites_repo.find_or_create(conn, "Karpata", country_code="BQ")
    sites_repo.find_or_create(conn, "Atlantis", country_code="US")

    rows = dives.list_sites_for_picker(conn)
    assert len(rows) == 3
    # Sorted alphabetically
    assert [r[1] for r in rows] == [
        "Atlantis (United States)",
        "Karpata (Bonaire)",
        "Salt Pier (Bonaire)",
    ]
    # All are (int, str) tuples
    for sid, label in rows:
        assert isinstance(sid, int)
        assert isinstance(label, str)


def test_list_sites_for_picker_filters_by_name(conn: sqlite3.Connection) -> None:
    sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
    sites_repo.find_or_create(conn, "Karpata", country_code="BQ")
    sites_repo.find_or_create(conn, "Atlantis", country_code="US")
    rows = dives.list_sites_for_picker(conn, query="salt")
    assert [r[1] for r in rows] == ["Salt Pier (Bonaire)"]


def test_list_sites_for_picker_filters_by_country(conn: sqlite3.Connection) -> None:
    sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
    sites_repo.find_or_create(conn, "Atlantis", country_code="US")
    rows = dives.list_sites_for_picker(conn, query="Bonaire")
    assert [r[1] for r in rows] == ["Salt Pier (Bonaire)"]


def test_list_sites_for_picker_respects_limit(conn: sqlite3.Connection) -> None:
    for i in range(10):
        sites_repo.find_or_create(conn, f"Site {i:02d}", country_code="BQ")
    rows = dives.list_sites_for_picker(conn, limit=5)
    assert len(rows) == 5


def test_list_buddies_for_picker_returns_id_name_tuples(conn: sqlite3.Connection) -> None:
    from open_dive_log.repositories import buddies as buddies_repo
    buddies_repo.find_or_create(conn, "Mike", "Smith")
    buddies_repo.find_or_create(conn, "Anna", "Lee")
    rows = dives.list_buddies_for_picker(conn)
    # Sorted by full_name
    assert [r[1] for r in rows] == ["Anna Lee", "Mike Smith"]


def test_list_buddies_for_picker_filters(conn: sqlite3.Connection) -> None:
    from open_dive_log.repositories import buddies as buddies_repo
    buddies_repo.find_or_create(conn, "Mike", "Smith")
    buddies_repo.find_or_create(conn, "Anna", "Lee")
    rows = dives.list_buddies_for_picker(conn, query="mike")
    assert [r[1] for r in rows] == ["Mike Smith"]


# ---------------------------------------------------------------------------
# get_buddies_with_roles / get_sites_ordered (form loaders)
# ---------------------------------------------------------------------------
def test_get_buddies_with_roles_returns_role(conn: sqlite3.Connection) -> None:
    from open_dive_log.repositories import buddies as buddies_repo
    role_id = next(r.id for r in lookups.list_active(conn, "lookup_buddy_role") if r.name == "buddy")
    did = dives.create(conn, dive_date="2026-06-15")
    dives.attach_buddies(conn, did, [(buddies_repo.find_or_create(conn, "Mike", "Smith").id, role_id)])
    rows = dives.get_buddies_with_roles(conn, did)
    assert len(rows) == 1
    buddy_id, name, rid = rows[0]
    assert name == "Mike Smith"
    assert rid == role_id


def test_get_sites_ordered_returns_in_order(conn: sqlite3.Connection) -> None:
    a = sites_repo.find_or_create(conn, "A Site", country_code="BQ")
    b = sites_repo.find_or_create(conn, "B Site", country_code="BQ")
    c = sites_repo.find_or_create(conn, "C Site", country_code="BQ")
    did = dives.create(conn, dive_date="2026-06-15")
    dives.attach_sites(conn, did, [b.id, a.id, c.id])
    rows = dives.get_sites_ordered(conn, did)
    assert [r[1] for r in rows] == ["B Site", "A Site", "C Site"]


# ---------------------------------------------------------------------------
# SubmittedDive.to_kwargs regression (slots=True, no __dict__)
# ---------------------------------------------------------------------------
def test_submitted_dive_to_kwargs_round_trips() -> None:
    """The dive form's SubmittedDive is a frozen+slots dataclass; splat
    into dives.create via to_kwargs() — same pattern as SubmittedCert."""
    from open_dive_log.ui.dive_add_edit_dialog import SubmittedDive
    sub = SubmittedDive(
        dive_date="2026-06-15", start_time="14:30", end_time="15:15",
        dive_time_minutes=45, time_of_day_id=2,
        entry_type_id=None, entry_notes="Slid in from the boat",
        surface_conditions_id=None, surface_conditions_notes=None, run_time_minutes=10,
        max_depth_m=24.0, avg_depth_m=18.0,
        air_temp_c=28.0, water_temp_c=27.0, visibility_m=20.0,
        start_pressure_bar=200.0, end_pressure_bar=80.0,
        equipment_type_id=None, tank_type_id=None, tank_configuration_id=None,
        gas_type_id=None, o2_percentage=32.0, mix_notes=None, gear_notes=None,
        purpose_id=None, notes="Great viz",
        site_ids=[1, 2],
        buddy_entries=[(3, 4)],
    )
    # Slots=True — must use to_kwargs(), not __dict__
    assert not hasattr(sub, "__dict__")
    kw = sub.to_kwargs()
    assert kw["dive_date"] == "2026-06-15"
    assert kw["max_depth_m"] == 24.0
    assert kw["o2_percentage"] == 32.0
    # Conditions fields (migration 005) must round-trip through to_kwargs
    assert kw["air_temp_c"] == 28.0
    assert kw["water_temp_c"] == 27.0
    assert kw["visibility_m"] == 20.0
    # Pressure fields (migration 006) must round-trip through to_kwargs
    assert kw["start_pressure_bar"] == 200.0
    assert kw["end_pressure_bar"] == 80.0
    assert sub.site_ids == [1, 2]
    assert sub.buddy_entries == [(3, 4)]


# ---------------------------------------------------------------------------
# Pressure fields (migration 006)
# ---------------------------------------------------------------------------
def test_create_with_pressure_persists(conn: sqlite3.Connection) -> None:
    did = dives.create(
        conn, dive_date="2026-06-15",
        start_pressure_bar=200.0, end_pressure_bar=80.0,
    )
    full = dives.get_full(conn, did)
    assert full is not None
    assert full.start_pressure_bar == 200.0
    assert full.end_pressure_bar == 80.0


def test_create_with_null_pressure(conn: sqlite3.Connection) -> None:
    """Pressure is optional; passing nothing leaves both columns NULL."""
    did = dives.create(conn, dive_date="2026-06-15")
    full = dives.get_full(conn, did)
    assert full is not None
    assert full.start_pressure_bar is None
    assert full.end_pressure_bar is None


def test_update_pressure_persists(conn: sqlite3.Connection) -> None:
    did = dives.create(conn, dive_date="2026-06-15", start_pressure_bar=200.0)
    dives.update(
        conn, did, dive_date="2026-06-15",
        start_pressure_bar=210.0, end_pressure_bar=90.0,
    )
    full = dives.get_full(conn, did)
    assert full is not None
    assert full.start_pressure_bar == 210.0
    assert full.end_pressure_bar == 90.0


def test_zero_pressure_is_a_real_value(conn: sqlite3.Connection) -> None:
    """0 BAR (empty tank) is a real reading, not 'not entered'.
    The repository must preserve it; only the form-level coercion
    rules differ (and the form does NOT coerce pressure 0 to None).
    """
    did = dives.create(
        conn, dive_date="2026-06-15",
        start_pressure_bar=0.0, end_pressure_bar=0.0,
    )
    full = dives.get_full(conn, did)
    assert full is not None
    assert full.start_pressure_bar == 0.0
    assert full.end_pressure_bar == 0.0


def test_pressure_range_check_rejects_out_of_range(conn: sqlite3.Connection) -> None:
    """Migration 006 added CHECK 0..350 BAR; the form also enforces it."""
    import sqlite3 as _sq
    with pytest.raises(_sq.IntegrityError):
        dives.create(conn, dive_date="2026-06-15", start_pressure_bar=500.0)
    with pytest.raises(_sq.IntegrityError):
        dives.create(conn, dive_date="2026-06-15", end_pressure_bar=-10.0)


def test_list_recent_with_sites_includes_pressure_and_avg_depth(
    conn: sqlite3.Connection,
) -> None:
    did = dives.create(
        conn, dive_date="2026-06-15",
        max_depth_m=24.0, avg_depth_m=18.0,
        start_pressure_bar=200.0, end_pressure_bar=80.0,
    )
    rows = dives.list_recent_with_sites(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == did
    assert rows[0]["max_depth_m"] == 24.0
    assert rows[0]["avg_depth_m"] == 18.0
    assert rows[0]["start_pressure_bar"] == 200.0
    assert rows[0]["end_pressure_bar"] == 80.0
