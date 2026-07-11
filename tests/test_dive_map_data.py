"""Tests for the dive map's data layer + tile cache.

The map window itself is covered by a smaller set of tests
in ``test_dive_map_window.py``; this module focuses on the
two pure-Python pieces: the SQL that returns markers and
the on-disk tile cache.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log.repositories import dives as dives_repo
from open_dive_log.ui.map_tile_cache import (
    MapTileCache,
    lat_to_tile_y,
    lon_to_tile_x,
    tile_x_to_lon,
    tile_y_to_lat,
)


@pytest.fixture()
def geo_conn(tmp_path: Path):
    """A migrated test DB with 3 sites (2 with geo, 1 without)
    and 3 dives that exercise every interesting case.
    """
    cm = db.connect(tmp_path / "geo_test.db")
    c = cm.__enter__()
    db.apply_migrations(c)
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES ('US', 'United States')")
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES ('BS', 'Bahamas')")
    c.commit()
    # Salt Pier (US) — has lat/lon.
    salt_pier_id = c.execute(
        "INSERT INTO site (name, country_code, latitude, longitude) "
        "VALUES (?, ?, ?, ?)",
        ("Salt Pier", "US", 24.5, -81.5),
    ).lastrowid
    # Tiger Beach (BS) — has lat/lon.
    tiger_beach_id = c.execute(
        "INSERT INTO site (name, country_code, latitude, longitude) "
        "VALUES (?, ?, ?, ?)",
        ("Tiger Beach", "BS", 26.7, -77.3),
    ).lastrowid
    # No-Country Site — no lat/lon, used for the "excluded" test.
    no_country_id = c.execute(
        "INSERT INTO site (name) VALUES (?)",
        ("No Country",),
    ).lastrowid
    assert salt_pier_id is not None
    assert tiger_beach_id is not None
    assert no_country_id is not None
    did1 = dives_repo.create(
        c, dive_date="2024-01-15", dive_time_minutes=40,
        max_depth_m=18.0, avg_depth_m=12.0, notes="wreck dive",
    )
    did2 = dives_repo.create(
        c, dive_date="2024-03-22", dive_time_minutes=55,
        max_depth_m=25.0, avg_depth_m=15.0, notes="reef exploration",
    )
    did3 = dives_repo.create(
        c, dive_date="2024-07-04", dive_time_minutes=30,
        max_depth_m=10.0, avg_depth_m=8.0, notes=None,
    )
    dives_repo.attach_sites(c, did1, [salt_pier_id])
    dives_repo.attach_sites(c, did2, [tiger_beach_id])
    dives_repo.attach_sites(c, did3, [no_country_id])
    c.commit()
    yield c
    cm.__exit__(None, None, None)


def test_list_for_map_returns_one_point_per_dive_with_geo_site(
    geo_conn: sqlite3.Connection,
) -> None:
    """All three dives are returned; the no-country dive's
    marker is placed at the only site it has (which has
    no lat/lon) so... wait, that's a problem.

    Actually, the third dive is attached to a site with no
    lat/lon, so the join ``first_geo`` excludes it
    entirely. The result should be 2 points, not 3.
    """
    points = dives_repo.list_for_map(geo_conn)
    ids = {p.id for p in points}
    # did1 (Salt Pier) and did2 (Tiger Beach) are in;
    # did3 (No Country) is excluded because its site has
    # no lat/lon.
    assert len(points) == 2
    assert ids == {geo_conn.execute("SELECT id FROM dive ORDER BY id ASC LIMIT 2").fetchall()[0][0],
                   geo_conn.execute("SELECT id FROM dive ORDER BY id ASC LIMIT 2").fetchall()[1][0]}


def test_list_for_map_filter_by_country_excludes_other_dives(
    geo_conn: sqlite3.Connection,
) -> None:
    points = dives_repo.list_for_map(geo_conn, country_code="US")
    assert len(points) == 1
    p = points[0]
    assert p.site_name == "Salt Pier"
    assert p.latitude == 24.5
    assert p.longitude == -81.5


def test_tile_cache_store_and_lookup(tmp_path: Path) -> None:
    """Store → lookup round-trip."""
    cache = MapTileCache(root=tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header
    path = cache.store(3, 4, 5, payload)
    assert path.is_file()
    assert path.read_bytes() == payload
    # Lookup returns the same path.
    assert cache.lookup(3, 4, 5) == path
    # A different tile is a miss.
    assert cache.lookup(3, 4, 6) is None


def test_tile_cache_validates_tile_coordinates(tmp_path: Path) -> None:
    """Out-of-range coordinates raise on store so a bug in
    the map widget can't accidentally write a tile outside
    the zoom-19 world square. ``lookup`` returns None for
    out-of-range (it's a read; no I/O happens; the safe
    answer is "not found").
    """
    cache = MapTileCache(root=tmp_path)
    # Out-of-range zoom: store raises.
    with pytest.raises(ValueError, match="zoom level out of range"):
        cache.store(20, 0, 0, b"x")
    with pytest.raises(ValueError, match="zoom level out of range"):
        cache.store(-1, 0, 0, b"x")
    # Out-of-range x/y at a given z: store raises.
    with pytest.raises(ValueError, match="x out of range"):
        cache.store(3, 8, 0, b"x")  # z=3 has only 8 tiles per side
    with pytest.raises(ValueError, match="y out of range"):
        cache.store(3, 0, 8, b"x")
    # Out-of-range lookup: returns None (not found) rather
    # than raising — reads must never fail loudly.
    assert cache.lookup(20, 0, 0) is None
    assert cache.lookup(3, 8, 0) is None


def test_lon_lat_tile_round_trip() -> None:
    """A (lat, lon) → tile (x, y) → (lat, lon) round-trip is
    identity to within sub-meter precision. Required so the
    marker placement is geographically accurate.
    """
    z = 12
    for lat, lon in [
        (0.0, 0.0),       # equator, prime meridian
        (24.5, -81.5),    # Key West
        (-33.8, 151.2),   # Sydney
        (60.0, 10.0),     # Oslo
    ]:
        x = lon_to_tile_x(lon, z)
        y = lat_to_tile_y(lat, z)
        lon_back = tile_x_to_lon(x, z)
        lat_back = tile_y_to_lat(y, z)
        assert abs(lat - lat_back) < 1e-6, f"lat round-trip failed for {lat}"
        assert abs(lon - lon_back) < 1e-6, f"lon round-trip failed for {lon}"
